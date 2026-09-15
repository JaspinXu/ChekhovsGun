/**
 * The optional Python backend, behind the same shape as `LocalEngine`.
 *
 * Every method here is allowed to fail. The backend is an upgrade — it adds
 * Whisper transcripts and bulk platform-API syncs the browser cannot do — and
 * the extension is required to work without it, so a failure returns an empty
 * result and records that the backend is down rather than propagating an error
 * into the card path.
 */

const DEFAULT_URL = "http://127.0.0.1:8700";
const PROBE_TTL_MS = 30_000;
const RELATE_TIMEOUT_MS = 2_500;

export class RemoteEngine {
  constructor(baseUrl = DEFAULT_URL) {
    this.baseUrl = (baseUrl || DEFAULT_URL).replace(/\/+$/, "");
    this._available = false;
    this._probedAt = 0;
    this.lastError = "";
  }

  setBaseUrl(url) {
    const next = (url || DEFAULT_URL).replace(/\/+$/, "");
    if (next !== this.baseUrl) {
      this.baseUrl = next;
      this._probedAt = 0; // force a re-probe against the new address
      this._available = false;
    }
  }

  async _request(path, { method = "GET", body = null, timeout = 5000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(this.baseUrl + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Is the backend up? Cached briefly so that scrolling a feed does not issue a
   * health check per page, and so that a backend the user never runs costs one
   * failed connection every 30 seconds rather than one per query.
   */
  async available({ force = false } = {}) {
    const now = Date.now();
    if (!force && now - this._probedAt < PROBE_TTL_MS) return this._available;
    this._probedAt = now;
    try {
      await this._request("/healthz", { timeout: 1200 });
      this._available = true;
      this.lastError = "";
    } catch (error) {
      this._available = false;
      this.lastError = String(error && error.message ? error.message : error);
    }
    return this._available;
  }

  /** Ranked item hits, or `[]` for any failure at all. */
  async relate(context, { limit = 5 } = {}) {
    if (!(await this.available())) return [];
    try {
      const payload = await this._request("/api/relate", {
        method: "POST",
        body: { ...context, limit },
        timeout: RELATE_TIMEOUT_MS,
      });
      return normalizeHits(payload);
    } catch (error) {
      // A backend that answers /healthz but fails a query is still "down" for
      // our purposes; re-probe rather than retrying this call.
      this._available = false;
      this._probedAt = 0;
      this.lastError = String(error && error.message ? error.message : error);
      return [];
    }
  }

  async search(query, { limit = 5 } = {}) {
    if (!(await this.available())) return [];
    try {
      const payload = await this._request(
        `/api/search?q=${encodeURIComponent(query)}&limit=${limit}`,
        { timeout: RELATE_TIMEOUT_MS }
      );
      return normalizeHits(payload);
    } catch {
      return [];
    }
  }

  /**
   * Forward a capture so the backend's library stays in step with what the
   * browser sees. Best-effort: the local copy is already written by the time
   * this runs, so a failure costs nothing.
   */
  async forwardCapture(capture) {
    if (!(await this.available())) return false;
    try {
      await this._request("/api/capture", { method: "POST", body: capture, timeout: 8000 });
      return true;
    } catch {
      return false;
    }
  }

  async mark(itemId, status) {
    if (!(await this.available())) return false;
    try {
      await this._request(`/api/items/${encodeURIComponent(itemId)}/mark`, {
        method: "POST",
        body: { status },
      });
      return true;
    } catch {
      return false;
    }
  }

  async stats() {
    if (!(await this.available())) return null;
    try {
      return await this._request("/api/status", { timeout: 3000 });
    } catch {
      return null;
    }
  }
}

/**
 * The backend speaks snake_case over the wire; the core speaks camelCase.
 * Converting here keeps the difference from leaking into the merge or the card.
 */
function normalizeHits(payload) {
  const rows = (payload && (payload.results || payload.hits || payload.items)) || [];
  return rows.map((row) => {
    const item = row.item || row;
    return {
      item: {
        id: item.id,
        source: item.source || "",
        sourceId: item.source_id || item.sourceId || "",
        title: item.title || "",
        url: item.url || "",
        author: item.author || "",
        thumbnail: item.thumbnail || "",
        duration: item.duration || 0,
        folder: item.folder || "",
        status: item.status || "active",
        mediaKind: item.media_kind || item.mediaKind || "video",
      },
      chunks: (row.chunks || []).map((chunk) => ({
        id: chunk.id,
        text: chunk.text || "",
        start: chunk.start || 0,
        end: chunk.end || 0,
        kind: chunk.kind || "transcript",
      })),
      timestamps: row.timestamps || [],
      score: row.score || 0,
      confidence: row.confidence || 0,
    };
  });
}
