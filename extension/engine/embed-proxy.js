/**
 * The service worker's handle on the neural encoder living in the offscreen
 * document, plus the policy for when to use it.
 *
 * The contract is the same one `HashingEmbedder` implements, so `LocalEngine`
 * cannot tell them apart. What this adds is the decision about *which* one is
 * in play, and the guarantee that a model which is missing, still loading, or
 * broken never takes retrieval down with it.
 */

const OFFSCREEN_PATH = "offscreen.html";
const MODEL_SIGNATURE = "multilingual-e5-small:384";

let creating = null;

/**
 * Chrome allows exactly one offscreen document per extension, and calling
 * `createDocument` twice — or racing two calls — throws. Both guards matter:
 * the service worker restarts constantly, so this runs far more often than it
 * looks like it should.
 */
async function ensureOffscreen() {
  if (!chrome.offscreen) throw new Error("offscreen API unavailable");
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (existing && existing.length) return;
  if (creating) {
    await creating;
    return;
  }
  creating = chrome.offscreen.createDocument({
    url: OFFSCREEN_PATH,
    reasons: ["WORKERS"],
    justification: "Runs the on-device sentence encoder that ranks your saves.",
  });
  try {
    await creating;
  } finally {
    creating = null;
  }
}

function sendToOffscreen(message, timeoutMs = 60_000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("encoder timed out")), timeoutMs);
    chrome.runtime.sendMessage({ ...message, target: "offscreen" }, (response) => {
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response || !response.ok) {
        reject(new Error((response && response.error) || "encoder failed"));
        return;
      }
      resolve(response);
    });
  });
}

export class ModelEmbedder {
  constructor(signature = MODEL_SIGNATURE) {
    this.signature = signature;
    this.name = "multilingual-e5-small";
  }

  async _embed(texts, kind) {
    if (!texts.length) return [];
    await ensureOffscreen();
    const { vectors } = await sendToOffscreen({ type: "embed", texts, kind });
    return vectors.map((v) => Float32Array.from(v));
  }

  /** Indexed passages. */
  async embed(texts) {
    return this._embed(texts, "passage");
  }

  /** The thing the user is looking at, or typed. */
  async embedOne(text) {
    const [vector] = await this._embed([text], "query");
    return vector;
  }

  /** Is the model actually present and loadable? Never throws. */
  static async probe() {
    try {
      await ensureOffscreen();
      const response = await sendToOffscreen({ type: "warmup" }, 120_000);
      return response.status && response.status.state === "ready";
    } catch {
      return false;
    }
  }
}

/**
 * Wraps the neural encoder so that a failure at query time falls back to the
 * hashing embedder for that call instead of failing the query.
 *
 * The signature reported is the *fallback's* whenever the model is not
 * currently usable, because the signature is what decides which stored vectors
 * retrieval is allowed to compare against. Reporting the model's signature
 * while actually returning hashed vectors would silently mix two vector spaces
 * in one ranking — the one failure mode that produces confidently wrong results
 * rather than merely worse ones.
 */
export class FallbackEmbedder {
  constructor(model, hash) {
    this.model = model;
    this.hash = hash;
    this.usingModel = false;
    this.lastError = "";
  }

  get signature() {
    return this.usingModel ? this.model.signature : this.hash.signature;
  }

  /** Called once the model has been confirmed loadable. */
  promote() {
    this.usingModel = true;
    this.lastError = "";
  }

  demote(error) {
    this.usingModel = false;
    this.lastError = String(error && error.message ? error.message : error || "");
  }

  async embedWithSignature(texts, { query = false } = {}) {
    const encoder = this.usingModel ? this.model : this.hash;
    const run = async (backend) => ({
      vectors: query ? [await backend.embedOne(texts[0])] : await backend.embed(texts),
      signature: backend.signature,
    });
    try {
      return await run(encoder);
    } catch (error) {
      if (encoder === this.hash) throw error;
      this.demote(error);
      return run(this.hash);
    }
  }

  async embed(texts) {
    return (await this.embedWithSignature(texts)).vectors;
  }

  async embedOne(text) {
    return (await this.embedWithSignature([text], { query: true })).vectors[0];
  }
}
