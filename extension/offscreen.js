/**
 * The neural encoder's home.
 *
 * An MV3 service worker is killed after roughly 30 seconds idle. Loading a
 * ~120MB encoder on every wake-up would be far slower than the retrieval it is
 * meant to improve, so the model lives here instead: an offscreen document's
 * lifetime is independent of the worker that created it, so the model is loaded
 * once and stays resident.
 *
 * Everything is loaded from inside the extension package. MV3's CSP forbids
 * remote code, and the whole point of an on-device encoder is that queries
 * never leave the machine — so `allowRemoteModels` is off and the ONNX runtime
 * is pointed at the bundled `.wasm`.
 *
 * If the model was never fetched, this reports `unavailable` and the service
 * worker keeps using the hashing embedder. That is not an error path; it is the
 * documented default state of a fresh install.
 */

const MODEL_ID = "multilingual-e5-small";
const VENDOR = "vendor/";
const MODEL_ROOT = "models/";

let pipelinePromise = null;
let status = { state: "idle", detail: "" };

/**
 * e5 models are trained with asymmetric prefixes and score noticeably worse
 * without them: the query side and the indexed side must be marked differently
 * or the two embeddings sit in slightly different regions of the space.
 */
function withPrefix(text, kind) {
  return `${kind === "query" ? "query" : "passage"}: ${text}`;
}

async function loadPipeline() {
  if (pipelinePromise) return pipelinePromise;
  pipelinePromise = (async () => {
    status = { state: "loading", detail: "" };
    const transformers = await import(chrome.runtime.getURL(VENDOR + "transformers.min.js"));
    const { env, pipeline } = transformers;

    env.allowRemoteModels = false;
    env.allowLocalModels = true;
    env.localModelPath = chrome.runtime.getURL(MODEL_ROOT);
    env.backends.onnx.wasm.wasmPaths = chrome.runtime.getURL(VENDOR);
    // Threads need SharedArrayBuffer and cross-origin isolation, which an
    // extension page does not have; asking for them fails the load outright.
    env.backends.onnx.wasm.numThreads = 1;

    const extractor = await pipeline("feature-extraction", MODEL_ID, {
      dtype: "q8",
      device: "wasm",
    });
    status = { state: "ready", detail: MODEL_ID };
    return extractor;
  })().catch((error) => {
    pipelinePromise = null;
    status = { state: "unavailable", detail: String(error && error.message ? error.message : error) };
    throw error;
  });
  return pipelinePromise;
}

async function embed(texts, kind) {
  const extractor = await loadPipeline();
  const output = await extractor(
    texts.map((t) => withPrefix(t, kind)),
    { pooling: "mean", normalize: true }
  );
  // `output` is a [n, dim] tensor; slice it back into one array per input.
  const dim = output.dims[output.dims.length - 1];
  const flat = output.data;
  const vectors = [];
  for (let i = 0; i < texts.length; i += 1) {
    vectors.push(Array.from(flat.slice(i * dim, (i + 1) * dim)));
  }
  return { vectors, dim };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.target !== "offscreen") return false;

  if (message.type === "embed") {
    embed(message.texts || [], message.kind || "passage")
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true; // keep the channel open for the async reply
  }

  if (message.type === "warmup") {
    loadPipeline().then(
      () => sendResponse({ ok: true, status }),
      () => sendResponse({ ok: false, status })
    );
    return true;
  }

  if (message.type === "status") {
    sendResponse({ ok: true, status });
    return false;
  }

  return false;
});
