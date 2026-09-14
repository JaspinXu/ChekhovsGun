(async () => {
  "use strict";
  const $ = (id) => document.getElementById(id);

  const send = (message) =>
    new Promise((resolve) => chrome.runtime.sendMessage(message, (r) => resolve(r || {})));

  const settings = await send({ type: "settings" });
  $("enabled").checked = settings.enabled !== false;
  $("youtube").checked = settings.sites?.youtube !== false;
  $("bilibili").checked = settings.sites?.bilibili !== false;
  $("explain").checked = settings.explain !== false;
  $("dashboard").href = settings.serverUrl || "http://127.0.0.1:8700";

  const save = async () => {
    await chrome.storage.sync.set({
      enabled: $("enabled").checked,
      explain: $("explain").checked,
      sites: { youtube: $("youtube").checked, bilibili: $("bilibili").checked },
    });
  };
  ["enabled", "youtube", "bilibili", "explain"].forEach((id) =>
    $(id).addEventListener("change", save));

  const result = await send({ type: "status" });
  const box = $("status");
  if (!result.ok) {
    box.className = "status bad";
    box.textContent = `连不上本地服务。先运行 chekhovsgun serve（${settings.serverUrl}）`;
    return;
  }
  const stats = result.status.stats;
  box.textContent = `已连接 · ${result.status.embedding}`;
  $("stats").innerHTML = [
    ["收藏总数", stats.items],
    ["可检索片段", stats.chunks],
    ["已开火", stats.items_fired],
  ]
    .map(([label, value]) => `<div class="stat"><span>${label}</span><b>${value}</b></div>`)
    .join("");
})();
