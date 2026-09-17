/* ChekhovsGun content script.
 *
 * Three jobs, all of them on the page because that is the only place with a
 * logged-in view of the user's own bookmarks:
 *
 *   1. COLLECT — when you click the site's own 收藏 button, read the page and
 *      send it to the local server. No API keys, no scraping credentials, and
 *      it works identically on a site nobody has written an adapter for.
 *   2. SCAN    — on a favourites page, walk the whole folder and send every
 *      link, so the backlog you already have comes in too.
 *   3. SURFACE — on an item's own page, ask whether anything saved is related
 *      and float a card if so.
 *
 * Both sites and all the post sites are single-page apps that swap content
 * without a page load, so there is no one navigation event to hang this on. We
 * watch three things at once (history API patches, the site's own navigation
 * event, and a slow href poll as a backstop) and funnel them into one debounced
 * handler.
 *
 * All UI lives inside a shadow root: every one of these sites ships aggressive
 * global CSS, and a shadow tree is the only way to guarantee the card looks the
 * same everywhere and never leaks styles back into the page.
 */
(() => {
  "use strict";
  if (window.__chekhovsgunLoaded) return;
  window.__chekhovsgunLoaded = true;

  const { recipeFor, readPage } = self.ChekhovsGunRecipes;
  const recipe = recipeFor();
  const DEBOUNCE_MS = 1400;
  const METADATA_RETRIES = 12;

  const send = (message) =>
    new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(response || {});
        });
      } catch (error) {
        resolve({ ok: false, error: String(error) });
      }
    });

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const stamp = (seconds) => {
    const total = Math.max(0, Math.floor(seconds || 0));
    const rest = String(total % 60).padStart(2, "0");
    const minutes = Math.floor(total / 60);
    return total >= 3600
      ? `${Math.floor(total / 3600)}:${String(minutes % 60).padStart(2, "0")}:${rest}`
      : `${minutes}:${rest}`;
  };

  const SOURCE_LABEL = {
    youtube: "YouTube", bilibili: "B站", zhihu: "知乎", xiaohongshu: "小红书",
    wechat: "公众号", weibo: "微博", juejin: "掘金", csdn: "CSDN",
    jianshu: "简书", reddit: "Reddit", x: "X", stackoverflow: "Stack Overflow",
    medium: "Medium", douban: "豆瓣", web: "网页", local: "本地",
  };
  const label = (source) => SOURCE_LABEL[source] || source || "网页";

  function readContext() {
    const page = readPage(recipe);
    if (!page.title) return null;
    return {
      source: page.source,
      source_id: "",
      title: page.title,
      author: page.author,
      // The live side matches on text, so a post sends its body here. The
      // server never stores this — it is the query, not a save.
      description: (page.text || page.excerpt || "").slice(0, 1500),
      tags: page.tags || [],
      url: location.href,
    };
  }

  // ------------------------------------------------------------------- styles
  const CSS = `
    :host { all: initial; }
    .root {
      position: fixed; right: 20px; bottom: 20px; width: 372px; max-width: calc(100vw - 32px);
      z-index: 2147483000;
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
            "Microsoft YaHei", Roboto, sans-serif;
      color: #e9ebf1; background: #14171f;
      border: 1px solid #2a2f3c; border-radius: 16px;
      box-shadow: 0 20px 52px rgba(0,0,0,.48);
      overflow: hidden;
      animation: rise .3s cubic-bezier(.2,.9,.3,1);
    }
    @keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
    @media (prefers-color-scheme: light) {
      .root { color: #1b1d22; background: #fffdf9; border-color: #e4e0d7;
              box-shadow: 0 20px 52px rgba(0,0,0,.16); }
      .quote { color: #5e6472 !important; border-left-color: #e4e0d7 !important; }
      .meta, .foot, .lede { color: #6f7586 !important; }
      .why { background: rgba(169,112,58,.09) !important; }
      .item:hover { background: rgba(0,0,0,.035) !important; }
    }
    header {
      display: flex; align-items: center; gap: 9px;
      padding: 12px 14px; border-bottom: 1px solid rgba(128,128,128,.16);
      cursor: pointer; user-select: none;
    }
    .mark { width: 8px; height: 8px; border-radius: 50%; background: #e0a458; flex: none;
            box-shadow: 0 0 0 3px rgba(224,164,88,.18); }
    .brand { font-weight: 640; font-size: 13.5px; letter-spacing: .01em; }
    .count { font-size: 11.5px; opacity: .55; margin-left: auto; font-variant-numeric: tabular-nums; }
    .iconbtn {
      border: 0; background: transparent; color: inherit; opacity: .5;
      cursor: pointer; font-size: 15px; line-height: 1; padding: 3px 6px; border-radius: 7px;
    }
    .iconbtn:hover { opacity: 1; background: rgba(128,128,128,.16); }
    .body { max-height: 64vh; overflow-y: auto; }
    .why {
      margin: 0; padding: 12px 14px; font-size: 13.5px; line-height: 1.6;
      background: rgba(224,164,88,.11);
      border-bottom: 1px solid rgba(128,128,128,.14);
    }
    .item { position: relative; padding: 12px 14px;
            border-bottom: 1px solid rgba(128,128,128,.1); }
    .item:last-child { border-bottom: 0; }
    .item:hover { background: rgba(255,255,255,.04); }
    .item .open { display: block; text-decoration: none; color: inherit; }
    .item.done { opacity: .4; }
    .t { font-weight: 600; font-size: 13.5px; margin: 0 0 4px; }
    .meta { font-size: 11.5px; color: #99a1b3; display: flex; gap: 6px; flex-wrap: wrap;
            align-items: center; }
    .src { padding: .5px 6px; border-radius: 20px; border: 1px solid currentColor;
           font-size: 10.5px; opacity: .8; }
    .quote {
      margin: 7px 0 0; font-size: 12.5px; color: #99a1b3; line-height: 1.6;
      border-left: 2px solid #2a2f3c; padding-left: 10px;
    }
    .ts { color: #e0a458; font-variant-numeric: tabular-nums; margin-right: 6px; }
    .actions { display: flex; gap: 7px; margin-top: 9px; }
    .btn {
      padding: 4.5px 11px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 11.5px;
      border: 1px solid rgba(128,128,128,.34); background: transparent; color: inherit; opacity: .78;
    }
    .btn:hover { opacity: 1; border-color: #e0a458; color: #e0a458; }
    .btn:disabled { cursor: default; opacity: .55; border-color: #56c271; color: #56c271; }
    .foot {
      display: flex; gap: 10px; align-items: center; padding: 10px 14px;
      font-size: 11.5px; color: #99a1b3; border-top: 1px solid rgba(128,128,128,.14);
    }
    .linkish { background: none; border: 0; color: inherit; cursor: pointer; font: inherit;
               text-decoration: underline; text-underline-offset: 2px; opacity: .72; padding: 0; }
    .linkish:hover { opacity: 1; }
    .foot .spacer { margin-left: auto; }
    .root.collapsed .body, .root.collapsed .foot { display: none; }

    /* toast — capture confirmations and scan progress */
    .toast {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
      display: flex; align-items: center; gap: 10px;
      padding: 12px 15px; border-radius: 13px; max-width: 340px;
      font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
            "Microsoft YaHei", Roboto, sans-serif;
      color: #e9ebf1; background: #14171f; border: 1px solid #2a2f3c;
      box-shadow: 0 16px 40px rgba(0,0,0,.42);
      animation: rise .26s cubic-bezier(.2,.9,.3,1);
    }
    @media (prefers-color-scheme: light) {
      .toast { color: #1b1d22; background: #fffdf9; border-color: #e4e0d7; }
    }
    .toast .mark { animation: pulse 1.4s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: .35; } }
    .toast .lede { font-size: 11.5px; color: #99a1b3; }

    /* scan launcher — only on a favourites page */
    .scan {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147482000;
      padding: 11px 16px; border-radius: 999px; cursor: pointer;
      border: 1px solid rgba(224,164,88,.5); background: #14171f; color: #e0a458;
      font: 600 13px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
            "Microsoft YaHei", Roboto, sans-serif;
      box-shadow: 0 14px 34px rgba(0,0,0,.4);
    }
    .scan:hover { background: #e0a458; color: #14171f; }
  `;

  // --------------------------------------------------------------- card shell
  let host = null;
  let shadow = null;

  function ensureHost() {
    if (host && document.documentElement.contains(host)) return;
    host = document.createElement("div");
    host.id = "chekhovsgun-host";
    host.style.cssText = "all:initial;position:fixed;z-index:2147483000;";
    shadow = host.attachShadow({ mode: "open" });
    document.documentElement.appendChild(host);
  }

  function dismiss() {
    if (host) host.remove();
    host = null;
    shadow = null;
  }

  /** A transient message. `sticky` keeps it until something replaces it. */
  function toast(title, detail = "", { sticky = false, ms = 3200 } = {}) {
    ensureHost();
    shadow.innerHTML = `
      <style>${CSS}</style>
      <div class="toast" role="status">
        <span class="mark"></span>
        <div><div>${escapeHtml(title)}</div>
             ${detail ? `<div class="lede">${escapeHtml(detail)}</div>` : ""}</div>
      </div>`;
    if (!sticky) setTimeout(() => { if (shadow && shadow.querySelector(".toast")) dismiss(); }, ms);
  }

  // ------------------------------------------------------- 1. collect on save
  const ACTIVE = /(^|[\s_-])(active|selected|checked|on|liked|collected|fav(ou?rite)?d?)([\s_-]|$)/i;

  /** Did that click turn the bookmark ON, or off again?
   *
   * Sites toggle one control for both, and capturing on un-save would add the
   * thing the user just threw away. Where the control exposes its state we
   * honour it; where it does not, we capture — a spurious save is recoverable
   * from the dashboard, a missed one is invisible.
   */
  function looksSaved(element) {
    for (let el = element; el && el !== document.body; el = el.parentElement) {
      const pressed = el.getAttribute?.("aria-pressed") ?? el.getAttribute?.("aria-checked");
      if (pressed === "true") return true;
      if (pressed === "false") return false;
      if (typeof el.className === "string" && ACTIVE.test(el.className)) return true;
    }
    return true;
  }

  async function captureThisPage(origin, { quiet = false } = {}) {
    const page = readPage(recipe);
    if (!page.title) return { ok: false };
    if (!quiet) toast("正在收进 ChekhovsGun…", page.title.slice(0, 60), { sticky: true });
    const result = await send({ type: "capture", payload: { ...page, origin } });
    if (result && result.ok === false) {
      toast("没能收进来", result.error || "本地服务没启动？", { ms: 4200 });
      return result;
    }
    const state = result?.state;
    toast(
      state === "skipped" ? "已经在 ChekhovsGun 里了" : "已收进 ChekhovsGun",
      state === "skipped"
        ? page.title.slice(0, 60)
        : `${page.title.slice(0, 44)} · 之后刷到相关内容会提醒你`
    );
    return result;
  }

  if (recipe.saveButtons && recipe.saveButtons.length) {
    const selector = recipe.saveButtons.join(",");
    document.addEventListener(
      "click",
      (event) => {
        const target = event.target?.closest?.(selector);
        if (!target) return;
        // Let the site update its own state before reading it back.
        setTimeout(() => {
          if (looksSaved(target)) captureThisPage("save-click");
        }, 700);
      },
      true
    );
  }

  // ------------------------------------------------------ 2. scan a favourites folder
  const SCAN_MAX_ROUNDS = 60;
  const SCAN_SETTLE_MS = 700;

  async function scanFavourites() {
    const spec = recipe.favorites;
    if (!spec) return;
    const folder = typeof spec.folder === "function" ? spec.folder() : spec.folder || "";
    const seen = new Map();
    let idleRounds = 0;

    for (let round = 0; round < SCAN_MAX_ROUNDS; round += 1) {
      for (const node of document.querySelectorAll(spec.item)) {
        const anchor = node.querySelector(spec.link);
        const href = anchor?.href;
        if (!href || seen.has(href)) continue;
        const title =
          (spec.title ? node.querySelector(spec.title)?.textContent : anchor.textContent) || "";
        seen.set(href, { url: href, title: title.trim().slice(0, 300), folder });
      }
      toast("正在扫描收藏夹…", `已找到 ${seen.size} 条，继续往下翻`, { sticky: true });

      const before = document.documentElement.scrollHeight;
      window.scrollTo(0, before);
      await new Promise((resolve) => setTimeout(resolve, SCAN_SETTLE_MS));
      // Infinite feeds keep growing; a paginated list stops. Either way, two
      // rounds with no new height and no new items means we are at the end.
      if (document.documentElement.scrollHeight === before) {
        idleRounds += 1;
        if (idleRounds >= 2) break;
      } else {
        idleRounds = 0;
      }
    }

    if (!seen.size) {
      toast("没找到可以收的条目", "这个页面的结构可能变了", { ms: 4200 });
      return;
    }
    toast("正在收进 ChekhovsGun…", `${seen.size} 条`, { sticky: true });
    const result = await send({
      type: "captureBatch",
      payload: { items: [...seen.values()], origin: "scan" },
    });
    if (result && result.ok === false) {
      toast("没能收进来", result.error || "本地服务没启动？", { ms: 4600 });
      return;
    }
    const added = result?.added || 0;
    const known = (result?.skipped || 0) + (result?.updated || 0);
    toast(
      `收进来 ${added} 条`,
      `${known ? `${known} 条已经有了 · ` : ""}${result?.failed ? `${result.failed} 条未能保存 · ` : ""}` +
        (result?.backend ? "已尝试交给本地服务补正文" : "已保存链接和标题；打开原文后再次收藏可补全文"),
      { ms: 6000 }
    );
  }

  function mountScanButton() {
    if (!recipe.favorites?.isPage?.()) return;
    if (document.getElementById("chekhovsgun-scan")) return;
    const mount = document.createElement("div");
    mount.id = "chekhovsgun-scan";
    mount.style.cssText = "all:initial;position:fixed;z-index:2147482000;";
    const root = mount.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${CSS}</style><button class="scan">把这个收藏夹收进 ChekhovsGun</button>`;
    root.querySelector(".scan").addEventListener("click", () => {
      mount.remove();
      scanFavourites();
    });
    document.documentElement.appendChild(mount);
  }

  // ------------------------------------------------------------- 3. surface
  function render(result, context, settings) {
    ensureHost();
    const hits = result.hits || [];
    const why = result.explanation?.text || "";

    const items = hits
      .map((hit) => {
        const item = hit.item;
        const quote = (hit.chunks || []).find((chunk) => chunk.kind !== "title");
        const isPost = item.media_kind === "post";
        const ts = quote && !isPost && quote.start
          ? `<span class="ts">${stamp(quote.start)}</span>` : "";
        const quoteHtml = quote
          ? `<p class="quote">${ts}${escapeHtml(quote.text.slice(0, 160))}</p>` : "";
        const badge = quote?.kind === "comment" ? `<span class="src">评论</span>` : "";
        return `
          <div class="item">
            <a class="open" href="${escapeHtml(hit.deep_link || item.url)}" target="_blank" rel="noopener">
              <p class="t">${escapeHtml(item.title)}</p>
              <div class="meta">
                <span class="src">${escapeHtml(label(item.source))}</span>
                ${badge}
                ${item.author ? `<span>${escapeHtml(item.author)}</span>` : ""}
                ${item.folder ? `<span>· ${escapeHtml(item.folder)}</span>` : ""}
              </div>
              ${quoteHtml}
            </a>
            <div class="actions">
              <button class="btn digest" data-item="${escapeHtml(item.id)}"
                      title="看完了，以后不用再提醒我">✓ 学完了</button>
            </div>
          </div>`;
      })
      .join("");

    shadow.innerHTML = `
      <style>${CSS}</style>
      <section class="root${settings.autoCollapse ? " collapsed" : ""}" role="complementary"
               aria-label="ChekhovsGun">
        <header id="head" title="点击折叠 / 展开">
          <span class="mark"></span>
          <span class="brand">你收藏过相关的</span>
          <span class="count">${hits.length}</span>
          <button class="iconbtn" id="close" title="关闭" aria-label="关闭">×</button>
        </header>
        <div class="body">
          ${why ? `<p class="why">${escapeHtml(why)}</p>` : ""}
          ${items}
        </div>
        <div class="foot">
          <button class="linkish" id="mute">这条不用再提醒</button>
          <span class="spacer"></span>
          <button class="iconbtn" id="bad" title="没关系，别再这样推给我">👎</button>
        </div>
      </section>`;

    shadow.getElementById("head").addEventListener("click", (event) => {
      if (event.target.id === "close") return;
      shadow.querySelector(".root").classList.toggle("collapsed");
    });
    shadow.getElementById("close").addEventListener("click", dismiss);
    shadow.getElementById("mute").addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "mute", key: result.contextKey || `${context.source}:${context.source_id}` });
      dismiss();
    });
    // Marking something learned is the only action here that means the product
    // worked, so it gets the prominent affordance and immediate feedback.
    shadow.querySelectorAll(".digest").forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        button.disabled = true;
        button.textContent = "已学完 ✓";
        await send({ type: "mark", itemId: button.dataset.item, status: "digested" });
        button.closest(".item")?.classList.add("done");
        if (!shadow.querySelectorAll(".item:not(.done)").length) setTimeout(dismiss, 700);
      });
    });
    shadow.getElementById("bad").addEventListener("click", () => {
      chrome.runtime.sendMessage({
        type: "feedback",
        payload: {
          item_id: hits[0]?.item?.id || "",
          context_id: `${context.source}:${context.source_id}`,
          useful: false,
        },
      });
      dismiss();
    });
  }

  // ---------------------------------------------------------------- the loop
  let currentKey = "";
  let timer = null;

  async function evaluate(attempt = 0) {
    mountScanButton();
    if (!recipe.isDetail || !recipe.isDetail(location.href)) {
      // Feeds are deliberately excluded: a dozen posts share the viewport and
      // guessing which one you are reading turns the card into harassment.
      dismiss();
      currentKey = "";
      return;
    }

    const context = readContext();
    // These apps swap the URL before they swap the content; retry briefly
    // rather than querying with the previous page's metadata.
    if (!context && attempt < METADATA_RETRIES) {
      setTimeout(() => evaluate(attempt + 1), 400);
      return;
    }
    if (!context) {
      dismiss();
      currentKey = "";
      return;
    }

    const key = `${context.source}:${location.pathname}${location.search}`;
    if (key === currentKey) return;
    currentKey = key;
    dismiss();

    const settings = await send({ type: "settings" });
    if (settings && settings.enabled === false) return;
    if (settings?.sites && context.source && settings.sites[context.source] === false) return;

    const result = await send({ type: "relate", context });
    if (!result || !result.fired || !(result.hits || []).length) return;
    if (currentKey !== key) return; // the user scrolled on while we waited
    render(result, context, settings || {});
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => evaluate(0), DEBOUNCE_MS);
  }

  // Let the toolbar button reach this page for a manual save.
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "captureNow") {
      captureThisPage(message.origin || "toolbar").then(sendResponse);
      return true;
    }
    if (message?.type === "scanNow") {
      scanFavourites();
      sendResponse({ ok: true });
      return true;
    }
    if (message?.type === "peek") {
      sendResponse({ ok: true, page: readPage(recipe), canScan: !!recipe.favorites?.isPage?.() });
      return true;
    }
    return false;
  });

  // 1. the site's own SPA navigation event (YouTube fires this reliably)
  window.addEventListener("yt-navigate-finish", schedule, true);
  window.addEventListener("popstate", schedule);
  window.addEventListener("hashchange", schedule);

  // 2. history API patches — most of these sites expose no navigation event
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      schedule();
      return result;
    };
  }

  // 3. a slow href poll as the backstop for everything the above misses
  let lastHref = location.href;
  setInterval(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      schedule();
    }
  }, 1200);

  schedule();
})();
