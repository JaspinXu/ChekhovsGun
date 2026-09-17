import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, copyFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);

// Read the central directory, independent of the platform's ZIP command.
function entries(zip) {
  const names = [];
  const end = zip.length - 22;
  assert.equal(zip.readUInt32LE(end), 0x06054b50);
  let offset = zip.readUInt32LE(end + 16);
  while (zip.readUInt32LE(offset) === 0x02014b50) {
    const length = zip.readUInt16LE(offset + 28);
    names.push(zip.subarray(offset + 46, offset + 46 + length).toString().replaceAll("\\", "/"));
    offset += 46 + length + zip.readUInt16LE(offset + 30) + zip.readUInt16LE(offset + 32);
  }
  return names.filter((name) => !name.endsWith("/"));
}

test("the built ZIP excludes tests and removes files deleted since the previous build", async () => {
  const root = await mkdtemp(join(tmpdir(), "chekhovsgun-build-test-"));
  try {
    await mkdir(join(root, "scripts"));
    await mkdir(join(root, "extension", "test"), { recursive: true });
    await mkdir(join(root, "extension", "core"));
    await copyFile(new URL("../../scripts/build-extension.mjs", import.meta.url), join(root, "scripts", "build-extension.mjs"));
    await writeFile(join(root, "extension", "manifest.json"), JSON.stringify({ version: "test" }));
    await writeFile(join(root, "extension", "core", "main.js"), "export const ready = true;");
    await writeFile(join(root, "extension", "obsolete.js"), "old");
    await writeFile(join(root, "extension", "test", "private-fixture.json"), "{}");
    const script = join(root, "scripts", "build-extension.mjs");
    await run(process.execPath, [script]);
    await rm(join(root, "extension", "obsolete.js"));
    await run(process.execPath, [script]);
    const names = entries(await readFile(join(root, "dist", "chekhovsgun-test-lite.zip")));
    assert.deepEqual(names.sort(), ["core/main.js", "manifest.json"]);
  } finally {
    if (!root.startsWith(join(tmpdir(), "chekhovsgun-build-test-"))) throw new Error("unexpected test directory");
    await rm(root, { recursive: true, force: true });
  }
});
