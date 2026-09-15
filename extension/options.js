/* Settings. The site list is generated from the recipe table rather than
 * hand-written, so adding a recipe adds its switch automatically — the whole
 * point of keeping site knowledge in one place. */
(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);

  const DEFAULT_SITES = {
    youtube: true, bilibili: true, zhihu: true, xiaohongshu: true, wechat: true,
    weibo: true, juejin: true, csdn: true, jianshu: true, reddit: true,
    x: true, stackoverflow: true, medium: true,
  };
  const DEFAULTS = {
    enabled: true,
    serverUrl: "http://127.0.0.1:8700",
    useBackend: false,
    useModel: true,
    sites: DEFAULT_SITES,
    captureOnSave: true,
    cooldownMinutes: 45,
    maxItems: 3,
    autoCollapse: false,
  };
  const LABELS = {
    youtube: "YouTube", bilibili: "哔哩哔哩", zhihu: "知乎", xiaohongshu: "小红书",
    wechat: "微信公众号", weibo: "微博", juejin: "掘金", csdn: "CSDN",
    jianshu: "简书", reddit: "Reddit", x: "X / Twitter",
    stackoverflow: "Stack Overflow", medium: "Medium",
  };

  const LOOPBACK = { origins: ["http://127.0.0.1/*", "http://localhost/*"] };

  const send = (message) =>
    new Promise((resolve) => chrome.runtime.sendMessage(message, (r) => resolve(r || {})));

  const stored = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
  const sites = { ...DEFAULT_SITES, ...(stored.sites || {}) };

  $("serverUrl").value = stored.serverUrl;
  $("enabled").checked = stored.enabled;
  $("captureOnSave").checked = stored.captureOnSave !== false;
  $("autoCollapse").checked = stored.autoCollapse;
  $("cooldownMinutes").value = stored.cooldownMinutes;
  $("maxItems").value = stored.maxItems;
  $("useModel").checked = stored.useModel !== false;
  $("useBackend").checked = stored.useBackend === true;

  $("sites").innerHTML = Object.keys(LABELS)
    .map(
      (name) => `
      <div class="check">
        <input type="checkbox" id="site-${name}" data-site="${name}"
               ${sites[name] === false ? "" : "checked"} />
        <label for="site-${name}">${LABELS[name]}</label>
      </div>`
    )
    .join("");

  /**
   * Reaching a local server needs a host permission the extension does not ask
   * for at install time — a standalone install should not request network
   * access it never uses. Chrome only grants it from a user gesture, which is
   * why this hangs off the checkbox rather than off the save button.
   */
  $("useBackend").addEventListener("change", async () => {
    if (!$("useBackend").checked) return;
    const granted = await chrome.permissions.request(LOOPBACK).catch(() => false);
    if (!granted) {
      $("useBackend").checked = false;
      $("backendState").textContent = "没有授权访问本机地址，已保持关闭。";
      return;
    }
    $("backendState").textContent = "已授权，保存后生效。";
  });

  async function refreshState() {
    const result = await send({ type: "status" });
    if (!result.ok) {
      $("modelState").textContent = "读不到本地索引状态。";
      return;
    }
    const status = result.status;

    if (status.model) {
      const pct = Math.round((status.vectorCoverage || 0) * 100);
      $("modelState").textContent =
        pct >= 100
          ? `已就绪：${status.model}`
          : `已加载 ${status.model}，正在重建索引 ${pct}%。未建好的部分仍可用关键词检索到。`;
    } else if (status.modelError) {
      $("modelState").textContent = `模型没能加载：${status.modelError}。当前使用关键词检索。`;
    } else {
      $("modelState").textContent = "没有检测到模型，当前使用关键词检索（扩展照常可用）。";
    }

    if ($("useBackend").checked) {
      $("backendState").textContent = status.backend
        ? "已连上本机服务。"
        : `连不上：${status.backendError || "服务没在运行"}。不影响扩展本身。`;
    }
  }

  $("save").addEventListener("click", async () => {
    const chosen = {};
    document.querySelectorAll("[data-site]").forEach((input) => {
      chosen[input.dataset.site] = input.checked;
    });
    await chrome.storage.sync.set({
      serverUrl: ($("serverUrl").value.trim() || DEFAULTS.serverUrl).replace(/\/+$/, ""),
      enabled: $("enabled").checked,
      captureOnSave: $("captureOnSave").checked,
      autoCollapse: $("autoCollapse").checked,
      useModel: $("useModel").checked,
      useBackend: $("useBackend").checked,
      cooldownMinutes: Math.max(0, Number($("cooldownMinutes").value) || DEFAULTS.cooldownMinutes),
      maxItems: Math.min(10, Math.max(1, Number($("maxItems").value) || DEFAULTS.maxItems)),
      sites: chosen,
    });
    $("saved").classList.add("show");
    setTimeout(() => $("saved").classList.remove("show"), 1600);
    refreshState();
  });

  refreshState();
})();
