/**
 * Merge ranked results from the local engine and the optional Python backend.
 *
 * The two sides index different things and deliberately use different vector
 * spaces, so their scores are not comparable — only their *orderings* are. That
 * is the same reason retrieval fuses dense and lexical with RRF rather than a
 * weighted sum, and the same fusion works here: it needs no calibration and
 * cannot be destabilised by one side reporting scores on a different scale.
 *
 * The backend is strictly an upgrade. If it is absent, slow or broken, the
 * merge degrades to "the local list", never to an error.
 */

const RRF_K = 60;

/**
 * Normalise a URL for identity comparison.
 *
 * The same save reached through the backend's adapter and through a browser
 * capture rarely has a byte-identical URL: one carries `?spm_id_from=...`, the
 * other a trailing slash or a tracking parameter appended by the site. Without
 * this the user sees the same item twice in one card.
 */
export function canonicalUrl(url) {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    const drop = [];
    parsed.searchParams.forEach((_, key) => {
      if (/^(utm_|spm|spm_id_from|share_|from_|vd_source|ref|ref_src|_r$)/i.test(key)) {
        drop.push(key);
      }
    });
    for (const key of drop) parsed.searchParams.delete(key);
    parsed.hash = "";
    parsed.hostname = parsed.hostname.replace(/^(www|m)\./i, "");
    let path = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.protocol}//${parsed.hostname}${path}${parsed.search}`.toLowerCase();
  } catch {
    return String(url).trim().toLowerCase();
  }
}

/** The key two records must share to be considered the same save. */
function identityOf(hit) {
  const id = hit.item && hit.item.id;
  const url = canonicalUrl(hit.item && hit.item.url);
  // Prefer the item id: it is `source:source_id` on both sides, so an item the
  // adapters synced and the same item captured in the browser collide on it.
  return url || id || JSON.stringify(hit.item);
}

/**
 * Pick which of two records for the same save to keep.
 *
 * More matching passages means more evidence to show the user, so that record
 * wins; confidence breaks the tie.
 */
function preferred(a, b) {
  const aChunks = (a.chunks || []).length;
  const bChunks = (b.chunks || []).length;
  if (aChunks !== bChunks) return aChunks > bChunks ? a : b;
  return (a.confidence || 0) >= (b.confidence || 0) ? a : b;
}

/**
 * @param {object[]} local ranked item hits from the in-browser engine
 * @param {object[]} remote ranked item hits from the Python backend (may be [])
 * @param {{limit?: number}} options
 */
export function federate(local, remote, { limit = 5 } = {}) {
  const lists = [local || [], remote || []].filter((l) => l.length);
  if (!lists.length) return [];
  if (lists.length === 1) return lists[0].slice(0, limit);

  const fused = new Map();
  const byKey = new Map();
  const origins = new Map();

  lists.forEach((list, listIndex) => {
    list.forEach((hit, rank) => {
      const key = identityOf(hit);
      fused.set(key, (fused.get(key) || 0) + 1 / (RRF_K + rank + 1));
      const existing = byKey.get(key);
      byKey.set(key, existing ? preferred(existing, hit) : hit);
      const seen = origins.get(key) || new Set();
      seen.add(listIndex === 0 ? "local" : "remote");
      origins.set(key, seen);
    });
  });

  return [...byKey.keys()]
    .sort((a, b) => fused.get(b) - fused.get(a))
    .slice(0, limit)
    .map((key) => ({ ...byKey.get(key), origins: [...origins.get(key)].sort() }));
}
