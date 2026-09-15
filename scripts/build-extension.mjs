#!/usr/bin/env node
/**
 * Package `extension/` into a zip that can be dropped into Chrome or uploaded
 * to a store listing.
 *
 * Deliberately not a bundler. The extension is plain ES modules loaded directly
 * by the browser, which means what you debug at chrome://extensions is exactly
 * what is in this file — worth more here than the few kilobytes minification
 * would save.
 *
 * The encoder is included when `npm run fetch-model` has been run and left out
 * otherwise; the build prints which of the two it produced, because the
 * difference is ~120MB and a real difference in retrieval quality.
 */

import { createWriteStream } from "node:fs";
import { mkdir, readdir, readFile, stat } from "node:fs/promises";
import { execFile } from "node:child_process";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE = join(ROOT, "extension");
const OUT_DIR = join(ROOT, "dist");

/** Never shipped: tests and their fixtures are development-only. */
const EXCLUDE = new Set(["test"]);

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (EXCLUDE.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else yield full;
  }
}

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function main() {
  const manifest = JSON.parse(await readFile(join(SOURCE, "manifest.json"), "utf-8"));
  const hasModel = await exists(join(SOURCE, "models"));
  const hasVendor = await exists(join(SOURCE, "vendor"));

  const files = [];
  let bytes = 0;
  for await (const file of walk(SOURCE)) {
    files.push(relative(SOURCE, file).replace(/\\/g, "/"));
    bytes += (await stat(file)).size;
  }

  await mkdir(OUT_DIR, { recursive: true });
  const suffix = hasModel && hasVendor ? "with-model" : "lite";
  const name = `chekhovsgun-${manifest.version}-${suffix}.zip`;
  const target = join(OUT_DIR, name);

  // PowerShell's Compress-Archive is present on every supported Windows box and
  // `zip` on every Unix one, so neither platform needs a dependency here.
  if (process.platform === "win32") {
    await run("powershell", [
      "-NoProfile",
      "-Command",
      `Compress-Archive -Path '${SOURCE}\\*' -DestinationPath '${target}' -Force`,
    ]);
  } else {
    await run("zip", ["-r", "-q", target, "."], { cwd: SOURCE });
  }

  const { size } = await stat(target);
  console.log(`\n  ${name}`);
  console.log(`  ${files.length} files, ${(size / (1 << 20)).toFixed(1)} MB packed`);
  console.log(
    hasModel && hasVendor
      ? "  includes the on-device encoder — installs ready for semantic search"
      : "  no encoder included — runs on keyword retrieval; `npm run fetch-model` adds it"
  );
  console.log(`\n  dist/${name}\n`);
  void bytes;
}

main().catch((error) => {
  console.error(`build failed: ${error.message}`);
  process.exitCode = 1;
});
