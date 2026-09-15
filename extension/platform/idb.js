/**
 * The IndexedDB implementation of the storage port.
 *
 * This is the one file that knows how the library is physically stored. `core/`
 * never imports it; it receives plain rows. When the Android app arrives it
 * supplies its own module with this same shape over SQLite, and the retrieval
 * engine moves across unchanged.
 *
 * The schema mirrors the SQLite tables in `chekhovsgun/rag/store.py` so an item
 * captured here and the same item synced by the Python adapters collide on one
 * id instead of appearing twice.
 */

const DB_NAME = "chekhovsgun";
const DB_VERSION = 1;

export const STORE_ITEMS = "items";
export const STORE_CHUNKS = "chunks";
export const STORE_META = "meta";
export const STORE_EVENTS = "events";

function promisify(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("transaction aborted"));
  });
}

export class IdbStore {
  /**
   * @param {IDBFactory} factory injectable so tests can run on fake-indexeddb
   */
  constructor(factory = globalThis.indexedDB, name = DB_NAME) {
    this.factory = factory;
    this.name = name;
    this._db = null;
    // Bumped on every write. The in-memory index is rebuilt only when this
    // moves, which is the same cache-invalidation strategy the Python Store
    // uses — rebuilding the BM25 postings on every query is not affordable.
    this.revision = 0;
  }

  async open() {
    if (this._db) return this._db;
    const request = this.factory.open(this.name, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_ITEMS)) {
        const items = db.createObjectStore(STORE_ITEMS, { keyPath: "id" });
        items.createIndex("source", "source");
        items.createIndex("savedAt", "savedAt");
        items.createIndex("status", "status");
        items.createIndex("url", "url");
      }
      if (!db.objectStoreNames.contains(STORE_CHUNKS)) {
        const chunks = db.createObjectStore(STORE_CHUNKS, { keyPath: "id" });
        chunks.createIndex("itemId", "itemId");
        chunks.createIndex("embedder", "embedder");
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains(STORE_EVENTS)) {
        const events = db.createObjectStore(STORE_EVENTS, {
          keyPath: "id",
          autoIncrement: true,
        });
        events.createIndex("ts", "ts");
      }
      void event;
    };
    this._db = await promisify(request);
    return this._db;
  }

  async _tx(stores, mode) {
    const db = await this.open();
    return db.transaction(stores, mode);
  }

  // ------------------------------------------------------------------ items

  async putItem(item) {
    const tx = await this._tx([STORE_ITEMS], "readwrite");
    tx.objectStore(STORE_ITEMS).put(normalizeItem(item));
    await txDone(tx);
    this.revision += 1;
  }

  async getItem(id) {
    const tx = await this._tx([STORE_ITEMS], "readonly");
    return promisify(tx.objectStore(STORE_ITEMS).get(id));
  }

  async allItems() {
    const tx = await this._tx([STORE_ITEMS], "readonly");
    return promisify(tx.objectStore(STORE_ITEMS).getAll());
  }

  async findItemByUrl(url) {
    if (!url) return null;
    const tx = await this._tx([STORE_ITEMS], "readonly");
    const found = await promisify(tx.objectStore(STORE_ITEMS).index("url").get(url));
    return found || null;
  }

  async countItems() {
    const tx = await this._tx([STORE_ITEMS], "readonly");
    return promisify(tx.objectStore(STORE_ITEMS).count());
  }

  /**
   * Replace an item and its chunks in one transaction.
   *
   * Re-capturing a page must not leave the previous chunk set behind: the ids
   * are content-derived, so edited text produces new ids and the stale rows
   * would otherwise linger forever and keep matching.
   */
  async replaceItem(item, chunks) {
    const tx = await this._tx([STORE_ITEMS, STORE_CHUNKS], "readwrite");
    const itemStore = tx.objectStore(STORE_ITEMS);
    const chunkStore = tx.objectStore(STORE_CHUNKS);

    const existing = await promisify(itemStore.get(item.id));
    // Ingest never owns the user's lifecycle columns, so a re-capture must not
    // resurrect something the user already marked 学完了.
    const merged = normalizeItem(
      existing ? { ...item, status: existing.status, digestedAt: existing.digestedAt } : item
    );
    itemStore.put(merged);

    const stale = await promisify(chunkStore.index("itemId").getAllKeys(item.id));
    for (const key of stale) chunkStore.delete(key);
    for (const chunk of chunks) chunkStore.put(normalizeChunk(chunk));

    await txDone(tx);
    this.revision += 1;
    return merged;
  }

  async deleteItem(id) {
    const tx = await this._tx([STORE_ITEMS, STORE_CHUNKS], "readwrite");
    tx.objectStore(STORE_ITEMS).delete(id);
    const chunkStore = tx.objectStore(STORE_CHUNKS);
    for (const key of await promisify(chunkStore.index("itemId").getAllKeys(id))) {
      chunkStore.delete(key);
    }
    await txDone(tx);
    this.revision += 1;
  }

  async setStatus(id, status) {
    const tx = await this._tx([STORE_ITEMS], "readwrite");
    const store = tx.objectStore(STORE_ITEMS);
    const item = await promisify(store.get(id));
    if (!item) {
      await txDone(tx);
      return null;
    }
    item.status = status;
    item.digestedAt = status === "digested" ? Date.now() / 1000 : 0;
    store.put(item);
    await txDone(tx);
    this.revision += 1;
    return item;
  }

  // ----------------------------------------------------------------- chunks

  async allChunks() {
    const tx = await this._tx([STORE_CHUNKS], "readonly");
    const rows = await promisify(tx.objectStore(STORE_CHUNKS).getAll());
    return rows.map(hydrateChunk);
  }

  /** Chunks whose vector was produced by something other than `signature`. */
  async chunksNeedingEmbedding(signature, limit = 200) {
    const tx = await this._tx([STORE_CHUNKS], "readonly");
    const rows = await promisify(tx.objectStore(STORE_CHUNKS).getAll());
    const stale = [];
    for (const row of rows) {
      if (row.embedder === signature && row.vector && row.vector.length) continue;
      stale.push(hydrateChunk(row));
      if (stale.length >= limit) break;
    }
    return stale;
  }

  /** Write vectors back after a re-embed pass. */
  async putVectors(updates, signature) {
    if (!updates.length) return;
    const tx = await this._tx([STORE_CHUNKS], "readwrite");
    const store = tx.objectStore(STORE_CHUNKS);
    for (const { id, vector } of updates) {
      const row = await promisify(store.get(id));
      if (!row) continue;
      row.vector = toStorable(vector);
      row.dim = vector.length;
      row.embedder = signature;
      store.put(row);
    }
    await txDone(tx);
    this.revision += 1;
  }

  // ------------------------------------------------------------ meta/events

  async getMeta(key, fallback = null) {
    const tx = await this._tx([STORE_META], "readonly");
    const row = await promisify(tx.objectStore(STORE_META).get(key));
    return row ? row.value : fallback;
  }

  async setMeta(key, value) {
    const tx = await this._tx([STORE_META], "readwrite");
    tx.objectStore(STORE_META).put({ key, value });
    await txDone(tx);
  }

  async logEvent(kind, detail = {}) {
    const tx = await this._tx([STORE_EVENTS], "readwrite");
    tx.objectStore(STORE_EVENTS).add({ ts: Date.now() / 1000, kind, ...detail });
    await txDone(tx);
  }

  async recentEvents(limit = 50) {
    const tx = await this._tx([STORE_EVENTS], "readonly");
    const rows = await promisify(tx.objectStore(STORE_EVENTS).getAll());
    return rows.sort((a, b) => b.ts - a.ts).slice(0, limit);
  }

  async stats() {
    const [items, chunks] = await Promise.all([this.allItems(), this.allChunks()]);
    const bySource = {};
    let digested = 0;
    for (const item of items) {
      bySource[item.source] = (bySource[item.source] || 0) + 1;
      if (item.status === "digested") digested += 1;
    }
    return { items: items.length, chunks: chunks.length, digested, bySource };
  }

  async clear() {
    const tx = await this._tx(
      [STORE_ITEMS, STORE_CHUNKS, STORE_META, STORE_EVENTS],
      "readwrite"
    );
    for (const name of [STORE_ITEMS, STORE_CHUNKS, STORE_META, STORE_EVENTS]) {
      tx.objectStore(name).clear();
    }
    await txDone(tx);
    this.revision += 1;
  }
}

function normalizeItem(item) {
  return {
    id: item.id,
    source: item.source || "",
    sourceId: item.sourceId || "",
    title: item.title || "",
    url: item.url || "",
    author: item.author || "",
    description: item.description || "",
    thumbnail: item.thumbnail || "",
    duration: item.duration || 0,
    publishedAt: item.publishedAt || 0,
    savedAt: item.savedAt || Date.now() / 1000,
    folder: item.folder || "",
    lang: item.lang || "",
    tags: item.tags || [],
    mediaKind: item.mediaKind || "video",
    status: item.status || "active",
    digestedAt: item.digestedAt || 0,
    hasTranscript: item.hasTranscript ? 1 : 0,
    indexedAt: item.indexedAt || Date.now() / 1000,
  };
}

function normalizeChunk(chunk) {
  return {
    id: chunk.id,
    itemId: chunk.itemId,
    ordinal: chunk.ordinal || 0,
    text: chunk.text,
    start: chunk.start || 0,
    end: chunk.end || 0,
    kind: chunk.kind || "transcript",
    tokens: chunk.tokens || [],
    vector: chunk.vector ? toStorable(chunk.vector) : null,
    dim: chunk.vector ? chunk.vector.length : 0,
    embedder: chunk.embedder || "",
  };
}

/**
 * Structured clone handles typed arrays, but a plain array round-trips through
 * every backend (including a future SQLite one) without special-casing, and the
 * size difference is not material next to the text we store beside it.
 */
function toStorable(vector) {
  return Array.from(vector);
}

function hydrateChunk(row) {
  return {
    ...row,
    vector: row.vector && row.vector.length ? Float32Array.from(row.vector) : null,
  };
}
