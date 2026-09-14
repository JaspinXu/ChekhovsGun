(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const DEFAULTS = {
    enabled: true,
    serverUrl: "http://127.0.0.1:8700",
    sites: { youtube: true, bilibili: true },
    cooldownMinutes: 45,
    maxItems: 3,
    explain: true,
    autoCollapse: false,
  };

  const stored = { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
  $("serverUrl").value = stored.serverUrl;
  $("enabled").checked = stored.enabled;
  $("youtube").checked = stored.sites?.youtube !== false;
  $("bilibili").checked = stored.sites?.bilibili !== false;
  $("explain").checked = stored.explain;
  $("autoCollapse").checked = stored.autoCollapse;
  $("cooldownMinutes").value = stored.cooldownMinutes;
  $("maxItems").value = stored.maxItems;

  $("save").addEventListener("click", async () => {
    await chrome.storage.sync.set({
      serverUrl: ($("serverUrl").value.trim() || DEFAULTS.serverUrl).replace(/\/+$/, ""),
      enabled: $("enabled").checked,
      explain: $("explain").checked,
      autoCollapse: $("autoCollapse").checked,
      cooldownMinutes: Math.max(0, Number($("cooldownMinutes").value) || DEFAULTS.cooldownMinutes),
      maxItems: Math.min(10, Math.max(1, Number($("maxItems").value) || DEFAULTS.maxItems)),
      sites: { youtube: $("youtube").checked, bilibili: $("bilibili").checked },
    });
    $("saved").classList.add("show");
    setTimeout(() => $("saved").classList.remove("show"), 1600);
  });
})();
