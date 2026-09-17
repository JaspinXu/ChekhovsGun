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

import { copyFile, mkdir, mkdtemp, readdir, readFile, rm, stat } from "node:fs/promises";
import { execFile } from "node:child_process";
import { join, dirname, relative } from "node:path";
import { tmpdir } from "node:os";
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
  for await (const file of walk(SOURCE)) {
    files.push(relative(SOURCE, file).replace(/\\/g, "/"));
  }

  await mkdir(OUT_DIR, { recursive: true });
  const suffix = hasModel && hasVendor ? "with-model" : "lite";
  const name = `chekhovsgun-${manifest.version}-${suffix}.zip`;
  const target = join(OUT_DIR, name);

  // Both platforms package the exact filtered file set. Build a fresh archive
  // so zip's update semantics cannot retain files removed since the last run.
  const stage = await mkdtemp(join(tmpdir(), "chekhovsgun-package-"));
  try {
    const payload = join(stage, "payload");
    for (const file of files) {
      const destination = join(payload, file);
      await mkdir(dirname(destination), { recursive: true });
      await copyFile(join(SOURCE, file), destination);
    }
    const archive = join(stage, "extension.zip");
    if (process.platform === "win32") {
      const quote = (value) => `'${value.replaceAll("'", "''")}'`;
      await run("powershell", ["-NoProfile", "-Command",
        `Compress-Archive -Path ${quote(join(payload, "*"))} -DestinationPath ${quote(archive)}`]);
    } else {
      await run("zip", ["-r", "-q", archive, "."], { cwd: payload });
    }
    await copyFile(archive, target);
  } finally {
    if (!stage.startsWith(join(tmpdir(), "chekhovsgun-package-"))) throw new Error("unexpected staging directory");
    await rm(stage, { recursive: true, force: true });
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
}

main().catch((error) => {
  console.error(`build failed: ${error.message}`);
  process.exitCode = 1;
});
