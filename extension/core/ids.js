/**
 * Identity helpers. These must match `chekhovsgun/models.py` exactly: an item
 * captured by the extension and the same item later synced by the Python
 * adapters have to collide on the same id, or the user sees it twice.
 */

export const STATUS_ACTIVE = "active";
export const STATUS_DIGESTED = "digested";
export const STATUS_MUTED = "muted";

export const MEDIA_POST = "post";
export const MEDIA_VIDEO = "video";

/** Stable, human-debuggable primary key for a saved item. */
export function makeItemId(source, sourceId) {
  return `${source}:${sourceId}`;
}

/**
 * `sha1(item_id|ordinal|text)[:20]`, matching `make_chunk_id`.
 *
 * SubtleCrypto is async and this is called in tight loops while chunking, so
 * we use a synchronous SHA-1. The digest is an identity, never a security
 * boundary — it exists so that re-indexing the same text is idempotent.
 */
export function makeChunkId(itemId, ordinal, text) {
  return sha1Hex(`${itemId}|${ordinal}|${text}`).slice(0, 20);
}

function sha1Hex(message) {
  const bytes = new TextEncoder().encode(message);
  const bitLen = bytes.length * 8;
  // Pad to a multiple of 64 bytes: 0x80, zeros, then the 64-bit bit length.
  const withPad = new Uint8Array(((bytes.length + 8) >> 6 << 6) + 64);
  withPad.set(bytes);
  withPad[bytes.length] = 0x80;
  const view = new DataView(withPad.buffer);
  view.setUint32(withPad.length - 8, Math.floor(bitLen / 0x100000000));
  view.setUint32(withPad.length - 4, bitLen >>> 0);

  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Int32Array(80);

  for (let offset = 0; offset < withPad.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) w[i] = view.getInt32(offset + i * 4);
    for (let i = 16; i < 80; i += 1) {
      const n = w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16];
      w[i] = (n << 1) | (n >>> 31);
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let i = 0; i < 80; i += 1) {
      let f, k;
      if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const temp = (((a << 5) | (a >>> 27)) + f + e + k + w[i]) | 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = temp;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
  }
  return [h0, h1, h2, h3, h4]
    .map((n) => (n >>> 0).toString(16).padStart(8, "0"))
    .join("");
}
