/**
 * Package integrity.
 *
 * These are the failures that only show up when Chrome loads the unpacked
 * directory, where the feedback is a red error on chrome://extensions rather
 * than a failing test: a manifest pointing at a file that was renamed, an
 * import path that resolves in Node's resolution but not the browser's, a
 * module that parses here but not under the extension's CSP.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const EXT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === "test" || entry.name === "node_modules") continue;
    if (entry.name === "models" || entry.name === "vendor") continue; // third-party
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.name.endsWith(".js")) yield full;
  }
}

const manifest = JSON.parse(await readFile(join(EXT, "manifest.json"), "utf-8"));

test("every file the manifest names exists", async () => {
  const referenced = [
    manifest.background.service_worker,
    manifest.action.default_popup,
    manifest.options_page,
    ...Object.values(manifest.action.default_icon),
    ...Object.values(manifest.icons),
    ...manifest.content_scripts.flatMap((cs) => cs.js),
  ];
  for (const file of referenced) {
    assert.ok(await exists(join(EXT, file)), `manifest references missing file: ${file}`);
  }
});

test("the service worker is declared as a module", () => {
  // Every import in background.js is a bare ES module import; without this the
  // worker fails to load with a bare "Cannot use import statement" error.
  assert.equal(manifest.background.type, "module");
});

test("the CSP allows the wasm the encoder needs and nothing remote", () => {
  const csp = manifest.content_security_policy.extension_pages;
  assert.match(csp, /'wasm-unsafe-eval'/, "onnxruntime cannot start without this");
  assert.match(csp, /script-src 'self'/, "remote code must stay forbidden");
  assert.ok(!/https?:/.test(csp), `CSP must not whitelist a remote origin: ${csp}`);
});

test("the backend is an optional permission, not a required one", () => {
  // If loopback were in `host_permissions`, a standalone install would demand
  // network access it never uses.
  assert.ok(!manifest.host_permissions, "loopback must not be a required permission");
  assert.ok(manifest.optional_host_permissions.some((p) => p.includes("127.0.0.1")));
  for (const needed of ["offscreen", "alarms", "storage", "unlimitedStorage"]) {
    assert.ok(manifest.permissions.includes(needed), `missing permission: ${needed}`);
  }
});

test("the offscreen document and its script are both present", async () => {
  assert.ok(await exists(join(EXT, "offscreen.html")));
  assert.ok(await exists(join(EXT, "offscreen.js")));
  const html = await readFile(join(EXT, "offscreen.html"), "utf-8");
  assert.match(html, /type="module"/, "offscreen.js uses a dynamic import");
});

test("every relative import resolves to a real file", async () => {
  const problems = [];
  for await (const file of walk(EXT)) {
    const source = await readFile(file, "utf-8");
    const pattern = /(?:^|\n)\s*import[^;]*?from\s+["'](\.[^"']+)["']/g;
    let match;
    while ((match = pattern.exec(source))) {
      const target = resolve(dirname(file), match[1]);
      if (!(await exists(target))) {
        problems.push(`${relative(EXT, file)} -> ${match[1]}`);
      }
    }
  }
  assert.deepEqual(problems, [], `unresolvable imports:\n${problems.join("\n")}`);
});

test("every import carries its .js extension", async () => {
  // Node resolves extensionless relative imports in some modes; the browser
  // never does. This is the classic "works in tests, red in Chrome" failure.
  const problems = [];
  for await (const file of walk(EXT)) {
    const source = await readFile(file, "utf-8");
    const pattern = /from\s+["'](\.[^"']+)["']/g;
    let match;
    while ((match = pattern.exec(source))) {
      if (!match[1].endsWith(".js")) problems.push(`${relative(EXT, file)} -> ${match[1]}`);
    }
  }
  assert.deepEqual(problems, [], `extensionless imports:\n${problems.join("\n")}`);
});

test("no extension source imports a bare package name", async () => {
  // There is no bundler in this build, so a bare specifier would simply 404.
  const problems = [];
  for await (const file of walk(EXT)) {
    const source = await readFile(file, "utf-8");
    const pattern = /(?:^|\n)\s*import[^;]*?from\s+["']([^."'][^"']*)["']/g;
    let match;
    while ((match = pattern.exec(source))) {
      problems.push(`${relative(EXT, file)} -> ${match[1]}`);
    }
  }
  assert.deepEqual(problems, [], `bare imports need a bundler:\n${problems.join("\n")}`);
});

test("core/ stays free of browser and extension globals", async () => {
  // This is what lets the planned Android app take core/ unchanged. The moment
  // something reaches for chrome.* or document here, that stops being true.
  const problems = [];
  for await (const file of walk(join(EXT, "core"))) {
    const source = await readFile(file, "utf-8");
    for (const banned of [/\bchrome\./, /\bdocument\./, /\bwindow\./, /\bfetch\(/]) {
      if (banned.test(source)) problems.push(`${relative(EXT, file)} uses ${banned}`);
    }
  }
  assert.deepEqual(problems, [], `core/ must stay platform-free:\n${problems.join("\n")}`);
});

test("the popup and options pages load their scripts as files, not inline", async () => {
  // Inline script is forbidden by the extension CSP.
  for (const page of ["popup.html", "options.html"]) {
    const html = await readFile(join(EXT, page), "utf-8");
    const inline = /<script(?![^>]*\bsrc=)[^>]*>[\s\S]*?\S[\s\S]*?<\/script>/.test(html);
    assert.ok(!inline, `${page} has an inline script, which the CSP blocks`);
  }
});
