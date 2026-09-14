/* ChekhovsGun dashboard. Vanilla JS, no build step, no external requests. */
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
  const escape = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const timestamp = (seconds) => {
    const total = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(total / 60);
    const s = String(total % 60).padStart(2, "0");
    return total >= 3600 ? `${Math.floor(total / 3600)}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`;
  };

  const ago = (epoch) => {
    if (!epoch) return "";
    const delta = Date.now() / 1000 - epoch;
    if (delta < 60) return "刚刚";
    if (delta < 3600) return `${Math.floor(delta / 60)} 分钟前`;
    if (delta < 86400) return `${Math.floor(delta / 3600)} 小时前`;
    return `${Math.floor(delta / 86400)} 天前`;
  };

  const SOURCE_LABEL = { youtube: "YouTube", bilibili: "Bilibili", local: "本地" };

  const REASON = {
    no_match: "没有足够相关的收藏 — 这正是它该保持安静的时候",
    self_saved: "这条本身就在你的收藏里；排除自身之后没有其他相关收藏",
    unknown_url: "这不像是 YouTube 或 Bilibili 的视频链接",
    empty_context: "没有可以用来检索的标题或简介",
  };

  // ----------------------------------------------------------------- render
  function renderHit(hit) {
    const item = hit.item;
    const link = hit.deep_link || item.url;
    const quotes = (hit.chunks || [])
      .filter((chunk) => chunk.kind !== "title")
      .slice(0, 2)
      .map((chunk) => {
        const stamp = chunk.start ? `<span class="ts">${timestamp(chunk.start)}</span>` : "";
        return `<p class="quote">${stamp}${escape(chunk.text.slice(0, 220))}</p>`;
      })
      .join("");
    // Imported items often have no cover art; a blank grey box reads as a broken
    // image, so fall back to a source-tinted monogram instead.
    const thumb = item.thumbnail
      ? `<img class="thumb" src="${escape(item.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
      : `<div class="thumb placeholder ${escape(item.source)}">${escape(
          (item.title || "?").trim().charAt(0)
        )}</div>`;
    return `
      <article class="hit">
        ${thumb}
        <div class="body">
          <p class="title"><a href="${escape(link)}" target="_blank" rel="noopener">${escape(item.title)}</a></p>
          <div class="meta">
            <span class="dot ${escape(item.source)}"></span>
            <span>${escape(SOURCE_LABEL[item.source] || item.source)}</span>
            ${item.author ? `<span>· ${escape(item.author)}</span>` : ""}
            ${item.folder ? `<span>· ${escape(item.folder)}</span>` : ""}
            ${hit.score != null ? `<span class="score">${Number(hit.score).toFixed(2)}</span>` : ""}
          </div>
          ${quotes}
        </div>
      </article>`;
  }

  function renderHits(target, hits, emptyText) {
    if (!hits || !hits.length) {
      target.innerHTML = `<p class="empty">${escape(emptyText)}</p>`;
      return;
    }
    target.innerHTML = hits.map(renderHit).join("");
  }

  // ----------------------------------------------------------------- status
  async function loadStatus() {
    try {
      const status = await api("/api/status");
      const s = status.stats;
      $("statline").innerHTML = [
        ["收藏", s.items],
        ["片段", s.chunks],
        ["已开火", s.items_fired],
        ["覆盖率", `${(s.coverage * 100).toFixed(0)}%`],
      ]
        .map(([label, value]) => `<div><span class="label">${label}</span><b>${escape(value)}</b></div>`)
        .join("");

      $("sources").innerHTML = status.adapters
        .map((adapter) => {
          const count = s.by_source[adapter.name] || 0;
          const badge = adapter.configured
            ? `<span class="badge ok">已配置</span>`
            : `<span class="badge warn">未配置</span>`;
          return `
            <div class="card">
              <h3><span class="dot ${escape(adapter.name)}"></span>${escape(adapter.label)} ${badge}</h3>
              <p>${count} 个收藏已入库${adapter.hint ? `<br>${escape(adapter.hint)}` : ""}</p>
              <div class="actions">
                <button class="btn tiny" data-sync="${escape(adapter.name)}" ${adapter.configured ? "" : "disabled"}>同步</button>
                <button class="btn tiny ghost" data-sync="${escape(adapter.name)}" data-limit="10" ${adapter.configured ? "" : "disabled"}>试同步 10 条</button>
              </div>
            </div>`;
        })
        .join("");

      document.querySelectorAll("[data-sync]").forEach((button) => {
        button.addEventListener("click", () =>
          startIngest(button.dataset.sync, button.dataset.limit ? Number(button.dataset.limit) : null));
      });
      return status;
    } catch (error) {
      $("statline").innerHTML = `<span class="error">无法连接本地服务：${escape(error.message)}</span>`;
      return null;
    }
  }

  // ----------------------------------------------------------------- ingest
  let pollTimer = null;
  async function startIngest(source, limit) {
    const box = $("job");
    box.hidden = false;
    box.textContent = `启动同步 ${source || "全部"}…`;
    try {
      const job = await api("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source || "", limit: limit || null }),
      });
      clearInterval(pollTimer);
      pollTimer = setInterval(() => pollJob(job.job_id), 900);
    } catch (error) {
      box.textContent = `同步失败：${error.message}`;
    }
  }

  async function pollJob(jobId) {
    const box = $("job");
    try {
      const job = await api(`/api/jobs/${jobId}`);
      if (job.state === "running") {
        const p = job.progress || {};
        box.textContent = `同步中… ${p.seen || 0} 条  ${(p.title || "").slice(0, 50)}`;
        return;
      }
      clearInterval(pollTimer);
      if (job.state === "failed") {
        box.textContent = `同步失败：${job.error}`;
        return;
      }
      const summary = (job.result || [])
        .map((r) => `${r.source}: 新增 ${r.added} · 更新 ${r.updated} · 未变 ${r.skipped} · 失败 ${r.failed}`)
        .join("   |   ");
      box.textContent = summary || "没有可同步的来源";
      loadStatus();
      loadLibrary(true);
      loadEvents();
    } catch (error) {
      clearInterval(pollTimer);
      box.textContent = `同步状态查询失败：${error.message}`;
    }
  }

  // ---------------------------------------------------------------- relate
  $("relate-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = $("relate-input").value.trim();
    const target = $("relate-result");
    if (!value) return;
    target.innerHTML = `<p class="empty">检索中…</p>`;
    try {
      const isUrl = /^https?:\/\//i.test(value);
      const result = await api("/api/relate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(isUrl ? { url: value } : { title: value }),
      });
      if (!result.fired) {
        const why = REASON[result.reason_code] || result.reason || "没有足够相关的收藏";
        target.innerHTML = `<p class="empty">没有开火 — ${escape(why)}</p>`;
        return;
      }
      const explanation = result.explanation;
      const head = explanation && explanation.text
        ? `<div class="explain"><span class="tag">${explanation.generated ? `模型生成 · ${escape(explanation.model)}` : "摘录（未配置 LLM）"} · ${result.took_ms}ms</span>${escape(explanation.text)}</div>`
        : "";
      target.innerHTML = head + result.hits.map(renderHit).join("");
    } catch (error) {
      target.innerHTML = `<p class="error">${escape(error.message)}</p>`;
    }
  });

  // ---------------------------------------------------------------- search
  $("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = $("search-input").value.trim();
    const target = $("search-result");
    if (!query) return;
    target.innerHTML = `<p class="empty">检索中…</p>`;
    try {
      const params = new URLSearchParams({ q: query, limit: "10" });
      const source = $("search-source").value;
      if (source) params.set("source", source);
      const result = await api(`/api/search?${params}`);
      renderHits(target, result.hits, "没有匹配的收藏");
    } catch (error) {
      target.innerHTML = `<p class="error">${escape(error.message)}</p>`;
    }
  });

  // --------------------------------------------------------------- library
  let offset = 0;
  const PAGE = 20;
  async function loadLibrary(reset) {
    if (reset) {
      offset = 0;
      $("library").innerHTML = "";
    }
    try {
      const result = await api(`/api/items?limit=${PAGE}&offset=${offset}`);
      const html = result.items
        .map((item) => renderHit({ item, chunks: [], score: null, deep_link: item.url }))
        .join("");
      $("library").insertAdjacentHTML("beforeend", html);
      offset += result.items.length;
      $("library-count").textContent = offset ? `已载入 ${offset} 条` : "";
      $("load-more").hidden = result.items.length < PAGE;
      if (!offset) {
        $("library").innerHTML =
          `<p class="empty">弹药库是空的。先配置来源并同步，或者运行 <code>chekhovsgun demo</code> 灌一批示例数据。</p>`;
      }
    } catch (error) {
      $("library").innerHTML = `<p class="error">${escape(error.message)}</p>`;
    }
  }
  $("load-more").addEventListener("click", () => loadLibrary(false));

  // ---------------------------------------------------------------- events
  async function loadEvents() {
    try {
      const result = await api("/api/events?limit=15");
      const rows = result.events.filter((e) => e.kind === "fired" || e.kind === "ingest");
      if (!rows.length) {
        $("events").innerHTML = `<li class="empty">还没有开过枪。</li>`;
        return;
      }
      $("events").innerHTML = rows
        .map((event) => {
          const body =
            event.kind === "fired"
              ? `在《${escape((event.payload.watching || "").slice(0, 60))}》上命中 ${event.payload.matched} 条收藏`
              : `同步 ${escape(event.source)}：新增 ${event.payload.added || 0} · 更新 ${event.payload.updated || 0}`;
          return `<li><time>${escape(ago(event.ts))}</time><span>${body}</span></li>`;
        })
        .join("");
    } catch {
      $("events").innerHTML = "";
    }
  }

  $("sync-all").addEventListener("click", () => startIngest("", null));

  loadStatus();
  loadLibrary(true);
  loadEvents();
  setInterval(loadStatus, 30000);
})();
