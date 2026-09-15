#!/usr/bin/env node
/**
 * Put the on-device encoder into `extension/`.
 *
 * Two things are needed and neither belongs in git: the transformers.js runtime
 * (~1MB) which is vendored out of node_modules, and the quantised encoder
 * (~120MB) which is downloaded once. Both land in gitignored directories and
 * are picked up by `scripts/build-extension.mjs` when packaging a release.
 *
 * Skipping this step is a supported state, not a broken one: the extension runs
 * on its hashed embedder plus BM25 and says so in the popup. What you lose is
 * cross-language matching — a Chinese query finding an English save — which is
 * the capability the encoder is here for.
 */

import { createWriteStream } from "node:fs";
import { mkdir, copyFile, stat, rm } from "node:fs/promises";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const VENDOR = join(ROOT, "extension", "vendor");
const MODEL_DIR = join(ROOT, "extension", "models", "multilingual-e5-small");

const REPO = "Xenova/multilingual-e5-small";
const REVISION = "main";

/** Everything transformers.js needs to load this model with `dtype: "q8"`. */
const MODEL_FILES = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "onnx/model_quantized.onnx",
];

/** Vendored from node_modules so no CDN is involved at runtime. */
const VENDOR_FILES = [
  ["dist/transformers.web.min.js", "transformers.min.js"],
  ["dist/ort-wasm-simd-threaded.jsep.mjs", "ort-wasm-simd-threaded.jsep.mjs"],
  ["dist/ort-wasm-simd-threaded.jsep.wasm", "ort-wasm-simd-threaded.jsep.wasm"],
];

function human(bytes) {
  if (bytes > 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function vendorRuntime() {
  const pkg = join(ROOT, "node_modules", "@huggingface", "transformers");
  if (!(await exists(pkg))) {
    throw new Error(
      "@huggingface/transformers is not installed.\n" +
        "  Run:  npm install --no-save @huggingface/transformers@3.7.2"
    );
  }
  await mkdir(VENDOR, { recursive: true });
  for (const [from, to] of VENDOR_FILES) {
    const source = join(pkg, from);
    if (!(await exists(source))) throw new Error(`missing ${from} in the installed package`);
    await copyFile(source, join(VENDOR, to));
    const { size } = await stat(join(VENDOR, to));
    console.log(`  vendored  ${to.padEnd(36)} ${human(size)}`);
  }
}

async function download(file) {
  const target = join(MODEL_DIR, file);
  if (await exists(target)) {
    const { size } = await stat(target);
    console.log(`  have      ${file.padEnd(36)} ${human(size)}`);
    return;
  }
  await mkdir(dirname(target), { recursive: true });
  const url = `https://huggingface.co/${REPO}/resolve/${REVISION}/${file}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${file}`);

  // Write to a temporary name first: a half-downloaded .onnx that looks
  // complete would fail at load time with a confusing error, and the popup
  // would report a broken model rather than a missing one.
  const partial = `${target}.part`;
  await pipeline(Readable.fromWeb(response.body), createWriteStream(partial));
  const { size } = await stat(partial);
  await rm(target, { force: true });
  await (await import("node:fs/promises")).rename(partial, target);
  console.log(`  fetched   ${file.padEnd(36)} ${human(size)}`);
}

async function main() {
  console.log(`\nVendoring the transformers.js runtime into extension/vendor/`);
  await vendorRuntime();

  console.log(`\nFetching ${REPO} into extension/models/ (about 120 MB, once)`);
  for (const file of MODEL_FILES) await download(file);

  console.log(
    "\nDone. Reload the extension at chrome://extensions and it will pick the\n" +
      "encoder up on its next start, then re-index your library in the background.\n"
  );
}

main().catch((error) => {
  console.error(`\nCould not install the encoder: ${error.message}`);
  console.error(
    "The extension still works without it — keyword retrieval stays on and the\n" +
      "popup will say so. Re-run `npm run fetch-model` whenever you like.\n"
  );
  process.exitCode = 1;
});
