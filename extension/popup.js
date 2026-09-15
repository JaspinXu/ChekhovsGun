/* The toolbar popup.
 *
 * Two jobs: save whatever page you are looking at, and make the library's state
 * legible — especially the one state that is otherwise indistinguishable from a
 * broken install, which is "your library is still too small for the reminder to
 * be trustworthy, so it is deliberately staying quiet".
 *
 * Everything here reads the in-browser library. There is no server to connect
 * to, so there is no "connecting…" state and no failure mode where the popup
 * has nothing to say.
 *
 * Saving works on sites with no content script too: `activeTab` lets us inject
 * the reader for the duration of this click and nothing more, so the extension
 * never holds standing permission to read every page you visit.
 */
(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);

  const send = (message) =>
    new Promise((resolve) => chrome.runtime.sendMessage(message, (r) => resolve(r || {})));

  const tabMessage = (tabId, message) =>
    new Promise((resolve) => {
      chrome.tabs.sendMessage(tabId, message, (response) => {
        if (chrome.runtime.lastError) resolve(null);
        else resolve(response || null);
      });
    });

  const note = (text, kind = "") => {
    $("note").className = `note ${kind}`.trim();
    $("note").textContent = text;
  };

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const settings = await send({ type: "settings" });
  $("enabled").checked = settings.enabled !== false;
  $("captureOnSave").checked = settings.captureOnSave !== false;
  // Only meaningful when the optional Python backend is switched on.
  $("dashboard").hidden = !settings.useBackend;
  $("dashboard").href = settings.serverUrl || "http://127.0.0.1:8700";

  $("enabled").addEventListener("change", () =>
    chrome.storage.sync.set({ enabled: $("enabled").checked }));
  $("captureOnSave").addEventListener("change", () =>
    chrome.storage.sync.set({ captureOnSave: $("captureOnSave").checked }));
  $("options").addEventListener("click", (event) => {
    event.preventDefault();
    chrome.runtime.openOptionsPage();
  });

  // ------------------------------------------------------------- saving
  /** Read the page, whether or not a content script is already running there. */
  async function readActivePage() {
    const viaContentScript = await tabMessage(tab.id, { type: "peek" });
    if (viaContentScript?.page) return viaContentScript;

    // No recipe for this site — inject the reader just for this click.
    try {
      const [injected] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["recipes.js"],
      });
      if (injected === undefined) return null;
    } catch (error) {
      return null;
    }
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => self.ChekhovsGunRecipes.readPage(),
    });
    return result?.result ? { page: result.result, canScan: false } : null;
  }

  const peek = await readActivePage();
  if (peek?.canScan) {
    $("scan").hidden = false;
    $("scan").addEventListener("click", async () => {
      await tabMessage(tab.id, { type: "scanNow" });
      window.close();
    });
  }

  $("capture").addEventListener("click", async () => {
    const button = $("capture");
    button.disabled = true;
    button.textContent = "正在收…";
    const current = peek || (await readActivePage());
    if (!current?.page?.url) {
      button.textContent = "收进 ChekhovsGun";
      button.disabled = false;
      note("读不到这个页面的内容（浏览器内置页面不支持）", "bad");
      return;
    }
    const saved = await send({ type: "capture", payload: { ...current.page, origin: "toolbar" } });
    if (saved.ok === false) {
      button.textContent = "收进 ChekhovsGun";
      button.disabled = false;
      note(saved.error || "没能收进来，再试一次", "bad");
      return;
    }
    button.textContent = saved.state === "skipped" ? "已经收过了 ✓" : "已收进 ChekhovsGun ✓";
    refresh();
  });

  // ------------------------------------------------------------- state
  async function refresh() {
    const result = await send({ type: "status" });
    if (!result.ok) {
      note(result.error || "本地索引打不开了，试试重新加载扩展", "bad");
      return;
    }
    const stats = result.status;
    $("progress").hidden = false;
    $("items").textContent = stats.items;
    $("digested").textContent = stats.digested ?? 0;
    $("bar").style.width = `${stats.items ? Math.round(((stats.digested || 0) / stats.items) * 100) : 0}%`;
    $("pending").textContent = stats.chunks ? `${stats.chunks} 个片段` : "";

    if (!stats.ready) {
      // Without this the extension looks broken: it is working exactly as
      // designed, and saying nothing at all.
      const left = Math.max(0, (stats.minLibraryItems || 0) - stats.items);
      note(
        `再收 ${left} 条就会开始提醒你。收藏太少时判断不准，宁可先不打扰你 —— 搜索随时可用。`,
        "warm"
      );
      return;
    }

    // The encoder is the one piece that can be "working, but not at full
    // strength", and that is worth saying out loud rather than leaving the user
    // to wonder why results feel shallow.
    const parts = [`${stats.items} 条收藏 · ${stats.chunks} 个可检索片段`];
    if (stats.model) {
      const pct = Math.round((stats.vectorCoverage || 0) * 100);
      parts.push(pct >= 100 ? "语义模型已就绪" : `语义模型建索引中 ${pct}%`);
    } else {
      parts.push("关键词检索中（语义模型未装）");
    }
    if (stats.backend) parts.push("已接上本地服务");
    note(parts.join(" · "));
  }

  refresh();
})();
