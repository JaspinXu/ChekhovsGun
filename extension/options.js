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
    sites: DEFAULT_SITES,
    captureOnSave: true,
    cooldownMinutes: 45,
    maxItems: 3,
    explain: true,
    autoCollapse: false,
  };
  const LABELS = {
    youtube: "YouTube", bilibili: "哔哩哔哩", zhihu: "知乎", xiaohongshu: "小红书",
    wechat: "微信公众号", weibo: "微博", juejin: "掘金", csdn: "CSDN",
    jianshu: "简书", reddit: "Reddit", x: "X / Twitter",
    stackoverflow: "Stack Overflow", medium: "Medium",
  };

  const stored = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
  const sites = { ...DEFAULT_SITES, ...(stored.sites || {}) };

  $("serverUrl").value = stored.serverUrl;
  $("enabled").checked = stored.enabled;
  $("captureOnSave").checked = stored.captureOnSave !== false;
  $("explain").checked = stored.explain;
  $("autoCollapse").checked = stored.autoCollapse;
  $("cooldownMinutes").value = stored.cooldownMinutes;
  $("maxItems").value = stored.maxItems;

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

  $("save").addEventListener("click", async () => {
    const chosen = {};
    document.querySelectorAll("[data-site]").forEach((input) => {
      chosen[input.dataset.site] = input.checked;
    });
    await chrome.storage.sync.set({
      serverUrl: ($("serverUrl").value.trim() || DEFAULTS.serverUrl).replace(/\/+$/, ""),
      enabled: $("enabled").checked,
      captureOnSave: $("captureOnSave").checked,
      explain: $("explain").checked,
      autoCollapse: $("autoCollapse").checked,
      cooldownMinutes: Math.max(0, Number($("cooldownMinutes").value) || DEFAULTS.cooldownMinutes),
      maxItems: Math.min(10, Math.max(1, Number($("maxItems").value) || DEFAULTS.maxItems)),
      sites: chosen,
    });
    $("saved").classList.add("show");
    setTimeout(() => $("saved").classList.remove("show"), 1600);
  });
})();
