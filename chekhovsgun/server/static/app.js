/* 藏知 dashboard. Vanilla JS, no build step, no external requests. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const api = async (path, options) => {
    const response = await fetch(path, options);
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`${response.status}: ${detail.slice(0, 200)}`);
    }
    return response.json();
  };
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const timestamp = (seconds) => {
    const total = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(total / 60);
    const s = String(total % 60).padStart(2, "0");
    return total >= 3600
      ? `${Math.floor(total / 3600)}:${String(m % 60).padStart(2, "0")}:${s}`
      : `${m}:${s}`;
  };

  const ago = (epoch) => {
    if (!epoch) return "";
    const delta = Date.now() / 1000 - epoch;
    if (delta < 60) return "刚刚";
    if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
    if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
    return `${Math.floor(delta / 86400)} 天前`;
  };

  const SOURCE_LABEL = {
    youtube: "YouTube", bilibili: "哔哩哔哩", zhihu: "知乎", xiaohongshu: "小红书",
    wechat: "微信公众号", weibo: "微博", juejin: "掘金", csdn: "CSDN",
    jianshu: "简书", douban: "豆瓣", reddit: "Reddit", x: "X", medium: "Medium",
    stackoverflow: "Stack Overflow", web: "网页", local: "本地导入",
  };
  const sourceLabel = (name) => SOURCE_LABEL[name] || name;

  const QUIET = {
    no_match: "没有够相关的收藏 —— 这正是它该保持安静的时候",
    self_saved: "这条本身就在你的藏书里；除它以外没有别的相关收藏",
    unknown_url: "这不是一个能打开的链接",
    page_unreadable: "读不出这个页面的内容，没有东西可以拿来比对",
    empty_context: "没有可以用来检索的标题或正文",
    library_too_small: "藏书还太少，判断不准，先不打扰你",
  };
  const STATE_LABEL = { digested: "已学完", muted: "已静音" };

  let popupThreshold = 0;

  // ------------------------------------------------------------------ render
  function renderHit(hit, options = {}) {
    const item = hit.item;
    const link = hit.deep_link || item.url;
    const isPost = item.media_kind === "post";

    const quotes = (hit.chunks || [])
      .filter((chunk) => chunk.kind !== "title")
      .slice(0, 2)
      .map((chunk) => {
        // A post has no timeline, so a timestamp there would be a lie; its deep
        // link carries a text fragment instead and lands on the same passage.
        const stamp = !isPost && chunk.start
          ? `<span class="ts">${timestamp(chunk.start)}</span>` : "";
        const badge = chunk.kind === "comment" ? `<span class="kind">评论</span> ` : "";
        return `<p class="quote">${stamp}${badge}${esc(chunk.text.slice(0, 220))}</p>`;
      })
      .join("");

    const thumb = item.thumbnail
      ? `<img class="thumb" src="${esc(item.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
      : `<div class="thumb placeholder${isPost ? " post" : ""}">${
          esc((item.title || "?").trim().charAt(0))}</div>`;

    const state = item.status && item.status !== "active"
      ? `<span class="state ${esc(item.status)}">${esc(STATE_LABEL[item.status] || item.status)}</span>`
      : "";
    const userTags = (item.user_tags || [])
      .map((tag) => `<span class="utag">${esc(tag)}</span>`).join("");
    const marks = options.actions
      ? `<div class="marks">
           <button class="btn tiny" data-mark="digested" data-id="${esc(item.id)}">✓ 学完了</button>
           <button class="btn tiny" data-mark="muted" data-id="${esc(item.id)}">别再提醒</button>
           ${item.status !== "active"
             ? `<button class="btn tiny" data-mark="active" data-id="${esc(item.id)}">放回</button>`
             : ""}
         </div>`
      : "";

    return `
      <article class="hit ${item.status && item.status !== "active" ? "is-" + esc(item.status) : ""}">
        ${thumb}
        <div class="body">
          <p class="title"><a href="${esc(link)}" target="_blank" rel="noopener">${esc(item.title)}</a></p>
          <div class="meta">
            <span class="dot ${esc(item.source)}"></span>
            <span>${esc(sourceLabel(item.source))}</span>
            <span class="kind">${isPost ? "帖子" : "视频"}</span>
            ${item.author ? `<span>${esc(item.author)}</span>` : ""}
            ${item.folder ? `<span>${esc(item.folder)}</span>` : ""}
            ${hit.score != null ? `<span class="score">${Number(hit.score).toFixed(2)}</span>` : ""}
            ${state}
            ${userTags}
          </div>
          ${quotes}
          ${marks}
        </div>
      </article>`;
  }

  // ------------------------------------------------------------------ ledger
  /** One spine per save: filled when you went back and finished it.
   *  Capped, because past a screenful more spines stop adding information. */
  function renderShelf(items) {
    const MAX = 130;
    const shown = items.slice(0, MAX);
    $("shelf").innerHTML = shown
      .map((item) => `<i class="${item.status === "digested" ? "done"
                                : item.status === "muted" ? "muted" : ""}"></i>`)
      .join("");
    $("shelf-note").textContent = shown.length
      ? items.length > MAX
        ? `最近 ${MAX} 条 · 实心是已经学完的`
        : "实心是已经学完的"
      : "";
  }

  async function loadLedger() {
    let status;
    try {
      status = await api("/api/status");
    } catch (error) {
      $("tally").innerHTML =
        `<p class="error">连不上本地服务：${esc(error.message)}。先运行 <code>chekhovsgun serve</code>。</p>`;
      return null;
    }
    const s = status.stats;
    popupThreshold = status.popup_threshold || 0;
    const owed = (s.by_status && s.by_status.active) || 0;
    const done = s.items_digested || 0;
    const media = s.by_media || {};

    $("tally").innerHTML = `
      <div class="figure owed"><b>${owed}</b><span>还欠着</span></div>
      <div class="figure"><b>${done}</b><span>已学完</span></div>
      <div class="rest">
        共 <em>${s.items}</em> 条 · 视频 <em>${media.video || 0}</em> · 帖子 <em>${media.post || 0}</em><br>
        ${s.chunks} 个可检索片段${s.pending_body ? ` · <em>${s.pending_body}</em> 条待取正文` : ""}
      </div>`;

    // The library is the shelf, newest first — the same order you saved them in.
    try {
      const recent = await api("/api/items?limit=130");
      renderShelf(recent.items);
    } catch {
      /* the shelf is illustration; its absence is not an error worth showing */
    }

    const box = $("onboard");
    if (popupThreshold && s.items < popupThreshold) {
      box.hidden = false;
      box.innerHTML = `
        <b>再收 ${popupThreshold - s.items} 条，提醒就会打开。</b>
        <p>藏书太少时判断不准，一个常见的词就足以让毫不相干的东西匹配上，所以现在宁可不打扰你。
           上面的「问一问」不受影响，随时可用。</p>`;
    } else if (s.items && !done) {
      box.hidden = false;
      box.innerHTML = `
        <b>还没有标记过「学完了」。</b>
        <p>刷到相关内容时卡片会弹出来，看完点一下「学完了」，它就不会再来烦你 ——
           这个数字才是这个东西有没有用的唯一指标。</p>`;
    } else {
      box.hidden = true;
    }
    return status;
  }

  // ----------------------------------------------------------------- sources
  const CAPTURE_CARD = `
    <div class="card">
      <h3><span class="dot web"></span>浏览器采集<span class="badge ok">随时可用</span></h3>
      <p>在知乎、小红书、公众号、B站…点网站自己的「收藏」，藏知就收进来。
         收藏夹页面上还会出现「整个收进来」。</p>
      <div class="actions">
        <button class="btn tiny" id="hydrate">补齐正文</button>
      </div>
    </div>`;

  function renderSources(status) {
    const s = status.stats;
    const cards = status.adapters.map((adapter) => {
      const count = s.by_source[adapter.name] || 0;
      const badge = adapter.configured
        ? `<span class="badge ok">已连上</span>`
        : `<span class="badge warn">未配置</span>`;
      return `
        <div class="card">
          <h3><span class="dot ${esc(adapter.name)}"></span>${esc(adapter.label)}${badge}</h3>
          <p>${count} 条已收进来
             ${adapter.hint ? `<span class="setup">${esc(adapter.hint)}</span>` : ""}</p>
          <div class="actions">
            <button class="btn tiny" data-sync="${esc(adapter.name)}" ${adapter.configured ? "" : "disabled"}>同步</button>
            <button class="btn tiny" data-sync="${esc(adapter.name)}" data-limit="10" ${adapter.configured ? "" : "disabled"}>先试 10 条</button>
          </div>
        </div>`;
    });
    $("sources").innerHTML = cards.join("") + CAPTURE_CARD;

    document.querySelectorAll("[data-sync]").forEach((button) =>
      button.addEventListener("click", () =>
        startJob("/api/ingest", {
          source: button.dataset.sync,
          limit: button.dataset.limit ? Number(button.dataset.limit) : null,
        }, `同步 ${sourceLabel(button.dataset.sync)}`)));
    $("hydrate").addEventListener("click", () =>
      startJob("/api/hydrate", { limit: 500 }, "补齐正文"));

    // Source filter options follow what is actually in the library.
    const select = $("library-source");
    const current = select.value;
    select.innerHTML = `<option value="">全部来源</option>` +
      Object.keys(s.by_source).sort()
        .map((name) => `<option value="${esc(name)}">${esc(sourceLabel(name))} (${s.by_source[name]})</option>`)
        .join("");
    select.value = current;
  }

  // -------------------------------------------------------------------- jobs
  let pollTimer = null;
  async function startJob(path, body, label) {
    const box = $("job");
    box.hidden = false;
    box.textContent = `${label}…`;
    try {
      const job = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      clearInterval(pollTimer);
      pollTimer = setInterval(() => pollJob(job.job_id, label), 900);
    } catch (error) {
      box.textContent = `${label}失败：${error.message}`;
    }
  }

  async function pollJob(jobId, label) {
    const box = $("job");
    try {
      const job = await api(`/api/jobs/${jobId}`);
      if (job.state === "running") {
        const p = job.progress || {};
        const seen = p.total ? `${p.seen || 0}/${p.total}` : `${p.seen || 0} 条`;
        box.textContent = `${label}… ${seen}  ${(p.title || "").slice(0, 46)}`;
        return;
      }
      clearInterval(pollTimer);
      if (job.state === "failed") {
        box.textContent = `${label}失败：${job.error}`;
        return;
      }
      box.textContent = summarise(job) || `${label}完成`;
      refresh();
    } catch (error) {
      clearInterval(pollTimer);
      box.textContent = `查不到任务状态：${error.message}`;
    }
  }

  function summarise(job) {
    const result = job.result;
    if (!result) return "";
    if (Array.isArray(result)) {
      return result
        .map((r) => `${sourceLabel(r.source)}：新增 ${r.added} · 更新 ${r.updated} · 未变 ${r.skipped}`)
        .join("   ") || "没有可同步的来源";
    }
    if (result.indexed != null) {
      return `补齐 ${result.indexed} 条正文 · ${result.failed} 条读不到 · ${result.chunks} 个片段`;
    }
    return "";
  }

  // --------------------------------------------------------------------- ask
  $("ask-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = $("ask-input").value.trim();
    const target = $("ask-result");
    if (!value) return;
    target.innerHTML = `<p class="empty">正在找…</p>`;
    // One box, two questions. A link asks "would this have interrupted me?";
    // words ask "what did I save about this?". Splitting them into two panels
    // made the user pick a mode before they had a thought.
    const isUrl = /^https?:\/\//i.test(value);
    try {
      if (isUrl) {
        const result = await api("/api/relate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: value, fetch: true }),
        });
        if (!result.fired) {
          target.innerHTML =
            `<p class="empty">不会提醒你 —— ${esc(QUIET[result.reason_code] || result.reason)}</p>`;
          return;
        }
        const why = result.explanation;
        const head = why && why.text
          ? `<div class="why"><span class="tag">${
              why.generated ? `模型生成 · ${esc(why.model)}` : "摘自原文（未配置 LLM）"
            } · ${result.took_ms}ms</span>${esc(why.text)}</div>`
          : "";
        target.innerHTML = head + result.hits.map((hit) => renderHit(hit)).join("");
      } else {
        const result = await api(`/api/search?${new URLSearchParams({ q: value, limit: "10" })}`);
        target.innerHTML = result.hits.length
          ? result.hits.map((hit) => renderHit(hit)).join("")
          : `<p class="empty">藏书里没有相关的东西。</p>`;
      }
    } catch (error) {
      target.innerHTML = `<p class="error">${esc(error.message)}</p>`;
    }
  });

  // ----------------------------------------------------------------- library
  let offset = 0;
  const PAGE = 20;
  const FILTERS = [
    ["library-status", "status"], ["library-source", "source"],
    ["library-tag", "tag"], ["library-media", "media_kind"],
  ];

  async function loadLibrary(reset) {
    if (reset) {
      offset = 0;
      $("library").innerHTML = "";
    }
    try {
      const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      for (const [id, key] of FILTERS) {
        const value = $(id) && $(id).value;
        if (value) params.set(key, value);
      }
      const result = await api(`/api/items?${params}`);
      $("library").insertAdjacentHTML(
        "beforeend",
        result.items
          .map((item) => renderHit({ item, chunks: [], score: null, deep_link: item.url },
                                   { actions: true }))
          .join("")
      );
      bindMarks($("library"));
      offset += result.items.length;
      $("library-count").textContent = offset ? `已显示 ${offset} 条` : "";
      $("load-more").hidden = result.items.length < PAGE;
      if (!offset) {
        $("library").innerHTML = `
          <p class="empty">藏书是空的。装上浏览器扩展后点网站的「收藏」就会进来，
            或者先运行 <code>chekhovsgun demo</code> 灌一批示例看看效果。</p>`;
      }
    } catch (error) {
      $("library").innerHTML = `<p class="error">${esc(error.message)}</p>`;
    }
  }

  $("load-more").addEventListener("click", () => loadLibrary(false));
  FILTERS.forEach(([id]) => $(id).addEventListener("change", () => loadLibrary(true)));

  function bindMarks(root) {
    root.querySelectorAll("[data-mark]").forEach((button) => {
      if (button.dataset.bound) return;
      button.dataset.bound = "1";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`/api/items/${encodeURIComponent(button.dataset.id)}/mark`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: button.dataset.mark }),
          });
          loadLibrary(true);
          refresh();
          loadTags();
        } catch (error) {
          button.disabled = false;
          console.error(error);
        }
      });
    });
  }

  async function loadTags() {
    try {
      const result = await api("/api/tags");
      const select = $("library-tag");
      const current = select.value;
      select.innerHTML =
        `<option value="">全部标签</option>` +
        result.tags.map((row) =>
          `<option value="${esc(row.tag)}">${esc(row.tag)} (${row.count})</option>`).join("");
      select.value = current;
    } catch {
      /* tags are optional */
    }
  }

  // ------------------------------------------------------------------ recent
  const EVENT_TEXT = {
    fired: (e) => `在《${(e.payload.watching || "").slice(0, 50)}》上想起了 ${e.payload.matched} 条收藏`,
    captured: (e) => `收进《${(e.payload.title || "").slice(0, 50)}》`,
    ingest: (e) => `同步 ${sourceLabel(e.source)}：新增 ${e.payload.added || 0} · 更新 ${e.payload.updated || 0}`,
    status: (e) => (e.payload.status === "digested" ? "标记了一条「学完了」" : "改了一条的状态"),
  };

  async function loadEvents() {
    try {
      const result = await api("/api/events?limit=20");
      const rows = result.events.filter((event) => EVENT_TEXT[event.kind]);
      $("events").innerHTML = rows.length
        ? rows.slice(0, 12)
            .map((event) =>
              `<li><time>${esc(ago(event.ts))}</time><span>${esc(EVENT_TEXT[event.kind](event))}</span></li>`)
            .join("")
        : `<li class="empty">还没有动静。</li>`;
    } catch {
      $("events").innerHTML = "";
    }
  }

  $("sync-all").addEventListener("click", () => startJob("/api/ingest", { source: "" }, "同步全部"));

  async function refresh() {
    const status = await loadLedger();
    if (status) renderSources(status);
  }

  refresh();
  loadLibrary(true);
  loadEvents();
  loadTags();
  setInterval(refresh, 30000);
})();
