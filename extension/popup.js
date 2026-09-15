/* The toolbar popup.
 *
 * Two jobs: save whatever page you are looking at, and make the library's state
 * legible — especially the one state that is otherwise indistinguishable from a
 * broken install, which is "your library is still too small for the reminder to
 * be trustworthy, so it is deliberately staying quiet".
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
      button.textContent = "收进藏知";
      button.disabled = false;
      note("读不到这个页面的内容（浏览器内置页面不支持）", "bad");
      return;
    }
    const saved = await send({ type: "capture", payload: { ...current.page, origin: "toolbar" } });
    if (saved.ok === false) {
      button.textContent = "收进藏知";
      button.disabled = false;
      note(saved.error || "本地服务没启动？", "bad");
      return;
    }
    button.textContent = saved.state === "skipped" ? "已经收过了 ✓" : "已收进藏知 ✓";
    refresh();
  });

  // ------------------------------------------------------------- state
  async function refresh() {
    const result = await send({ type: "status" });
    if (!result.ok) {
      note(`连不上本地服务。先运行 chekhovsgun serve（${settings.serverUrl}）`, "bad");
      return;
    }
    const stats = result.status.stats;
    const needed = result.status.popup_threshold || 0;
    $("progress").hidden = false;
    $("items").textContent = stats.items;
    $("digested").textContent = stats.items_digested ?? 0;
    $("bar").style.width = `${Math.round((stats.coverage || 0) * 100)}%`;
    $("pending").textContent = stats.pending_body ? `${stats.pending_body} 条待取正文` : "";

    if (needed && stats.items < needed) {
      // Without this the extension looks broken: it is working exactly as
      // designed, and saying nothing at all.
      note(
        `再收 ${needed - stats.items} 条就会开始提醒你。` +
          `收藏太少时判断不准，宁可先不打扰你 —— 搜索随时可用。`,
        "warm"
      );
      return;
    }
    note(`已连接 · ${stats.items} 条收藏，${stats.chunks} 个可检索片段`);
  }

  refresh();
})();
