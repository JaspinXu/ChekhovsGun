/* ChekhovsGun content script — YouTube and Bilibili.
 *
 * Both sites are single-page apps that swap the video without a page load, so
 * there is no navigation event to hang this on for both. We watch three things
 * at once (history API patches, the site's own navigation event, and a slow
 * href poll as a backstop) and funnel them into one debounced handler.
 *
 * All UI lives inside a shadow root: YouTube and Bilibili both ship aggressive
 * global CSS, and a closed shadow tree is the only way to guarantee the card
 * looks the same on both and never leaks styles back into the page.
 */
(() => {
  "use strict";
  if (window.__chekhovsgunLoaded) return;
  window.__chekhovsgunLoaded = true;

  const SITE = location.hostname.includes("bilibili") ? "bilibili" : "youtube";
  const DEBOUNCE_MS = 1400;
  const METADATA_RETRIES = 12;

  // ------------------------------------------------------------ site probes
  const text = (selector, root = document) => {
    const node = root.querySelector(selector);
    return node ? (node.textContent || "").trim() : "";
  };
  const attr = (selector, name) => document.querySelector(selector)?.getAttribute(name)?.trim() || "";

  const PROBES = {
    youtube: {
      id() {
        const url = new URL(location.href);
        if (url.pathname.startsWith("/shorts/")) return url.pathname.split("/")[2] || "";
        return url.searchParams.get("v") || "";
      },
      title() {
        return (
          text("#title h1 yt-formatted-string") ||
          text("h1.ytd-watch-metadata") ||
          text("ytd-reel-player-header-renderer h2") ||
          attr('meta[name="title"]', "content") ||
          document.title.replace(/ - YouTube$/, "")
        );
      },
      author() {
        return (
          text("#owner #channel-name a") ||
          text("ytd-channel-name#channel-name a") ||
          text("ytd-reel-player-header-renderer #channel-name") ||
          attr('link[itemprop="name"]', "content")
        );
      },
      description() {
        return (
          text("#description-inline-expander ytd-text-inline-expander") ||
          text("#description-inline-expander") ||
          attr('meta[name="description"]', "content")
        );
      },
      tags() {
        return Array.from(document.querySelectorAll('meta[property="og:video:tag"]'))
          .map((node) => node.content)
          .filter(Boolean)
          .slice(0, 20);
      },
    },
    bilibili: {
      id() {
        const match = location.pathname.match(/\/video\/(BV[0-9A-Za-z]{10}|av\d+)/i);
        return match ? match[1] : "";
      },
      title() {
        return (
          text("h1.video-title") ||
          text(".video-info-title-inner .video-title") ||
          attr('h1[title]', "title") ||
          document.title.replace(/_哔哩哔哩.*$/, "")
        );
      },
      author() {
        return text(".up-info--right .up-name") || text(".up-name") || text(".username");
      },
      description() {
        return (
          text(".basic-desc-info") ||
          text(".desc-info-text") ||
          text("#v_desc .desc-info") ||
          attr('meta[name="description"]', "content")
        );
      },
      tags() {
        return Array.from(document.querySelectorAll(".tag-panel .tag-link, .video-tag-container .tag"))
          .map((node) => (node.textContent || "").trim())
          .filter(Boolean)
          .slice(0, 20);
      },
    },
  };

  const probe = PROBES[SITE];

  function readContext() {
    const source_id = probe.id();
    if (!source_id) return null;
    return {
      source: SITE,
      source_id,
      title: probe.title().slice(0, 300),
      author: probe.author().slice(0, 120),
      description: probe.description().slice(0, 1200),
      tags: probe.tags(),
      url: location.href.split("&")[0],
    };
  }

  // -------------------------------------------------------------------- card
  const CARD_CSS = `
    :host { all: initial; }
    .root {
      position: fixed; right: 20px; bottom: 20px; width: 360px; max-width: calc(100vw - 32px);
      z-index: 2147483000;
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
            "Microsoft YaHei", Roboto, sans-serif;
      color: #e8eaf0; background: #14171f;
      border: 1px solid #2a2f3c; border-radius: 14px;
      box-shadow: 0 18px 48px rgba(0,0,0,.45);
      overflow: hidden;
      animation: rise .28s cubic-bezier(.2,.9,.3,1);
    }
    @keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
    @media (prefers-color-scheme: light) {
      .root { color: #1b1d22; background: #fffdf9; border-color: #e2ded5; box-shadow: 0 18px 48px rgba(0,0,0,.18); }
      .quote { color: #5a6070 !important; border-left-color: #e2ded5 !important; }
      .meta, .foot { color: #7b8194 !important; }
      .explain { background: rgba(169,112,58,.09) !important; }
      .item:hover { background: rgba(0,0,0,.035) !important; }
    }
    header {
      display: flex; align-items: center; gap: 8px;
      padding: 11px 13px; border-bottom: 1px solid rgba(128,128,128,.18);
      cursor: pointer; user-select: none;
    }
    .mark { width: 9px; height: 9px; border-radius: 50%; background: #e0a458; flex: none; }
    .brand { font-weight: 650; font-size: 13px; letter-spacing: .01em; }
    .count { font-size: 11.5px; opacity: .6; margin-left: auto; }
    .iconbtn {
      border: 0; background: transparent; color: inherit; opacity: .55;
      cursor: pointer; font-size: 15px; line-height: 1; padding: 3px 5px; border-radius: 6px;
    }
    .iconbtn:hover { opacity: 1; background: rgba(128,128,128,.16); }
    .body { max-height: 62vh; overflow-y: auto; }
    .explain {
      margin: 0; padding: 12px 13px; font-size: 13.5px;
      background: rgba(224,164,88,.11);
      border-bottom: 1px solid rgba(128,128,128,.14);
    }
    .item { display: block; padding: 11px 13px; text-decoration: none; color: inherit;
            border-bottom: 1px solid rgba(128,128,128,.1); }
    .item:last-child { border-bottom: 0; }
    .item:hover { background: rgba(255,255,255,.04); }
    .t { font-weight: 600; font-size: 13.5px; margin: 0 0 3px; }
    .meta { font-size: 11.5px; color: #9aa2b4; display: flex; gap: 6px; flex-wrap: wrap; }
    .src { padding: 0 6px; border-radius: 20px; border: 1px solid currentColor; font-size: 10.5px; }
    .quote {
      margin: 6px 0 0; font-size: 12.5px; color: #9aa2b4;
      border-left: 2px solid #2a2f3c; padding-left: 9px;
    }
    .ts { color: #e0a458; font-variant-numeric: tabular-nums; margin-right: 5px; }
    .foot {
      display: flex; gap: 8px; align-items: center; padding: 9px 13px;
      font-size: 11.5px; color: #9aa2b4; border-top: 1px solid rgba(128,128,128,.14);
    }
    .foot button { margin-left: auto; }
    .linkish { background: none; border: 0; color: inherit; cursor: pointer; font: inherit;
               text-decoration: underline; text-underline-offset: 2px; opacity: .75; padding: 0; }
    .linkish:hover { opacity: 1; }
    .root.collapsed .body, .root.collapsed .foot { display: none; }
  `;

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

  const SOURCE_LABEL = { youtube: "YouTube", bilibili: "B站", local: "本地" };

  function render(result, context, settings) {
    ensureHost();
    const hits = result.hits || [];
    const explanation = result.explanation && result.explanation.text ? result.explanation.text : "";

    const items = hits
      .map((hit) => {
        const item = hit.item;
        const quote = (hit.chunks || []).find((chunk) => chunk.kind !== "title");
        const quoteHtml = quote
          ? `<p class="quote">${quote.start ? `<span class="ts">${stamp(quote.start)}</span>` : ""}${escapeHtml(
              quote.text.slice(0, 150)
            )}</p>`
          : "";
        return `
          <a class="item" href="${escapeHtml(hit.deep_link || item.url)}" target="_blank" rel="noopener"
             data-item="${escapeHtml(item.id)}">
            <p class="t">${escapeHtml(item.title)}</p>
            <div class="meta">
              <span class="src">${escapeHtml(SOURCE_LABEL[item.source] || item.source)}</span>
              ${item.author ? `<span>${escapeHtml(item.author)}</span>` : ""}
              ${item.folder ? `<span>· ${escapeHtml(item.folder)}</span>` : ""}
            </div>
            ${quoteHtml}
          </a>`;
      })
      .join("");

    shadow.innerHTML = `
      <style>${CARD_CSS}</style>
      <section class="root${settings.autoCollapse ? " collapsed" : ""}" role="complementary" aria-label="ChekhovsGun">
        <header id="head" title="点击折叠 / 展开">
          <span class="mark"></span>
          <span class="brand">你收藏过这个</span>
          <span class="count">${hits.length} 条</span>
          <button class="iconbtn" id="close" title="关闭" aria-label="关闭">×</button>
        </header>
        <div class="body">
          ${explanation ? `<p class="explain">${escapeHtml(explanation)}</p>` : ""}
          ${items}
        </div>
        <div class="foot">
          <span>${result.cached ? "缓存" : `${Math.round(result.took_ms || 0)}ms`}</span>
          <button class="linkish" id="mute">这个视频不再提示</button>
          <button class="iconbtn" id="bad" title="不相关">👎</button>
        </div>
      </section>`;

    shadow.getElementById("head").addEventListener("click", (event) => {
      if (event.target.id === "close") return;
      shadow.querySelector(".root").classList.toggle("collapsed");
    });
    shadow.getElementById("close").addEventListener("click", dismiss);
    shadow.getElementById("mute").addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "mute", key: `${context.source}:${context.source_id}` });
      dismiss();
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

  // ------------------------------------------------------------- the loop
  let currentKey = "";
  let timer = null;

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (response) => {
          if (chrome.runtime.lastError) resolve({ ok: false, error: chrome.runtime.lastError.message });
          else resolve(response || {});
        });
      } catch (error) {
        resolve({ ok: false, error: String(error) });
      }
    });
  }

  async function evaluate(attempt = 0) {
    const context = readContext();
    if (!context) {
      dismiss();
      currentKey = "";
      return;
    }
    // The SPA swaps the URL before it swaps the title; retry briefly rather
    // than querying the server with the previous video's metadata.
    if (!context.title && attempt < METADATA_RETRIES) {
      setTimeout(() => evaluate(attempt + 1), 400);
      return;
    }

    const key = `${context.source}:${context.source_id}`;
    if (key === currentKey) return;
    currentKey = key;
    dismiss();

    const settings = await send({ type: "settings" });
    if (settings && settings.enabled === false) return;

    const result = await send({ type: "relate", context });
    if (!result || !result.fired || !(result.hits || []).length) return;
    if (currentKey !== key) return; // the user scrolled on while we waited
    render(result, context, settings || {});
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => evaluate(0), DEBOUNCE_MS);
  }

  // 1. the site's own SPA navigation event (YouTube fires this reliably)
  window.addEventListener("yt-navigate-finish", schedule, true);
  window.addEventListener("popstate", schedule);
  window.addEventListener("hashchange", schedule);

  // 2. history API patches — Bilibili has no public navigation event
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
