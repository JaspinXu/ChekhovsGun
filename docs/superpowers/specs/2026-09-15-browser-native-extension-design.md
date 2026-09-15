# Browser-native ChekhovsGun — design

Date: 2026-09-15
Status: approved (brainstorming), pending implementation

## Problem

Today the extension is a thin HTTP client. Every useful thing it does —
retrieval, storage, chunking — happens in a Python process the user has to
install and keep running on `127.0.0.1:8700`. "Install the extension" is
therefore not a thing anyone can actually do: it is step 3 of a five-step
setup, and if the server is not up the extension is inert.

The goal is an extension you install and use. The Python backend does not go
away — it keeps the capabilities a browser genuinely cannot have (Whisper
transcription, bulk platform-API sync) — but it stops being required.

Android is planned next. That is a constraint on this design, not a later
problem: the retrieval core must not be written against `chrome.*`.

## Decisions taken during brainstorming

1. **Standalone-first, backend as an upgrade.** The extension carries a
   complete engine. If a backend is reachable it is used *as well*, not
   instead.
2. **Federated retrieval, not synced storage.** Both sides run their own full
   retrieval; only the ranked result lists are merged (RRF + dedupe by URL).
   Consequence: the two sides need not share a vector space, and a backend
   that is down or slow degrades to "fewer results", never to an error.
3. **Bundled model with layered fallback (plan B).** Semantic quality comes
   from a real multilingual encoder running in the browser, but the extension
   is useful from the first second without it.

## Architecture

```
extension/
  core/            pure ES modules — no chrome.*, no DOM, no network
    text.js          normalize / tokenize / script_of / sentences / snippet
    embed-hash.js    HashingEmbedder            (port of rag/embeddings.py)
    bm25.js          inverted index + IDF       (port of store._LexicalIndex)
    chunker.js       chunk_item and friends     (port of rag/chunker.py)
    retrieve.js      RRF, per-item cap, coverage, confidence
                                                (port of rag/retriever.py)
    config.js        RetrievalConfig defaults, kept in step with config.py
    ports.js         StoragePort / EmbedderPort interfaces
  platform/
    idb.js           StoragePort over IndexedDB     ← Android swaps this file
  engine/
    local.js         wires core + platform into a query-in/hits-out engine
    remote.js        the same shape, backed by the Python API
    federate.js      merges two ranked lists
  offscreen.html/.js transformers.js host (see "Why offscreen")
  background.js      message router and orchestration only — holds no state
  content.js         page recipes, capture, card rendering (largely unchanged)
  popup / options
```

`core/` is the deliverable that outlives this change. It imports nothing from
the platform and is tested with plain `node:test`, so the Android app can take
it verbatim and supply its own `StoragePort`.

### Why offscreen

An MV3 service worker is killed after ~30s idle. A 120MB encoder cannot be
reloaded on every wake, so the model lives in an offscreen document, whose
lifetime is independent of the worker that created it. The service worker
keeps no state at all: it routes messages, and everything durable is in
IndexedDB. onnxruntime's `.wasm` ships in the package and CSP gains
`wasm-unsafe-eval`; no remote code is ever loaded.

### Model delivery and the two embedders

| | signature | when |
|---|---|---|
| `local-hash:512` | ported `HashingEmbedder` | always available, zero download |
| `e5-small:384` | `multilingual-e5-small`, int8 (~118MB) | once fetched |

On install the extension indexes and retrieves with `local-hash` + BM25 —
identical behaviour to the Python default path, so it works offline and
immediately. In the background it looks for the model: first in
`extension/models/` (present in release zips, written by `npm run fetch-model`),
otherwise from the CDN into the Cache API. When the model becomes available a
background job re-embeds existing chunks.

**Vector-space safety.** Every stored vector carries its embedder signature.
Dense retrieval only considers vectors whose signature matches the embedder
currently in use. BM25 always covers 100% of chunks, so during a re-embed no
saved item is invisible — the not-yet-upgraded part simply falls back to
lexical matching. This mirrors the existing `Embedder.signature` contract.

## Data model (IndexedDB, db `chekhovsgun`)

- `items` — keyPath `id` (`source:source_id`); indexes on `source`, `saved_at`,
  `status`, `url`. Mirrors the `items` table including the user-owned
  `status` / lifecycle columns.
- `chunks` — keyPath `id`; indexes on `item_id`, `embedder`. Fields as in
  SQLite plus `embedder`; `vector` stored as `Float32Array`, `tokens` as a
  string array computed once at write time (same reasoning as the Python
  comment: re-tokenising on every query was the hot path).
- `meta`, `events` — as today.

The BM25 index and the vector matrix are rebuilt in memory on first query after
a write, guarded by a revision counter — the same caching strategy `Store`
already uses.

## Retrieval, end to end

1. `content.js` extracts the page context (existing recipes) and asks
   background to `relate`.
2. Background runs `engine/local.js` and, in parallel, `engine/remote.js` if a
   backend answered `/healthz` recently. `remote` failing is not an error.
3. `federate.js` fuses the two ranked item lists with RRF and dedupes by
   normalised URL, preferring the record with more chunks.
4. The `min_library_items` gate (15) and the confidence floor (0.30) apply to
   the merged list, so the card stays silent until the library can support it.

Scoring constants — `dense_weight` 0.6, `lexical_weight` 0.4, `rrf_k` 60,
`min_confidence` 0.30, `min_score_ratio` 0.45, `max_chunks_per_item` 4, BM25
`k1` 1.4 / `b` 0.72 — are ported unchanged. They were tuned against a golden
set; changing them is out of scope here.

## Testing

`core/` is pure, so it tests without a browser. `node --test` over
`extension/core/*.test.js`:

- tokenizer parity: a fixture of Chinese/English/mixed strings checked against
  output captured from the Python `tokenize`, so the port cannot silently drift
- BM25 ranking on a small corpus, including the `max_df` cutoff
- RRF fusion, per-item cap, coverage saturation, `confidence_of`
- chunker boundaries: char limit, seconds limit, overlap carry, dedupe
- federation: dedupe by URL, backend-absent degradation

`platform/idb.js` is tested with `fake-indexeddb`. The existing pytest suite
must keep passing untouched — the Python side is not being modified beyond
CORS additions.

## Out of scope

- Any change to Python retrieval logic.
- Bidirectional sync (explicitly rejected: conflict resolution is not a v1
  problem).
- The Android app itself — this design only ensures `core/` is portable.
- Chrome Web Store submission.
