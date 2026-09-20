"use strict";

const state = {
  tab: null,
  items: [],
  filter: "all",
  appOnline: false,
};

const elements = {
  pageHost: document.querySelector("#pageHost"),
  count: document.querySelector("#count"),
  appDot: document.querySelector("#appDot"),
  appStatus: document.querySelector("#appStatus"),
  sendBest: document.querySelector("#sendBest"),
  sendPage: document.querySelector("#sendPage"),
  list: document.querySelector("#mediaList"),
  empty: document.querySelector("#empty"),
  toast: document.querySelector("#toast"),
  refresh: document.querySelector("#refresh"),
  clear: document.querySelector("#clear"),
  showAll: document.querySelector("#showAll"),
  showStreams: document.querySelector("#showStreams"),
  showDirect: document.querySelector("#showDirect"),
};

function humanBytes(value) {
  let size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return "boyut bilinmiyor";
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function typeLabel(type) {
  return { hls: "HLS", dash: "DASH", direct: "Dosya", audio: "Ses", subtitle: "Altyazı", blob: "Blob", unknown: "Medya" }[type] || "Medya";
}

function sourceLabel(sources = []) {
  const labels = {
    network: "Ağ",
    headers: "Başlık",
    dom: "DOM",
    fetch: "Fetch",
    xhr: "XHR",
    performance: "Kaynak",
  };
  return sources.slice(0, 2).map((source) => labels[source] || source).join(" + ") || "Tespit";
}

function visibleItems() {
  if (state.filter === "streams") {
    return state.items.filter((item) => ["hls", "dash"].includes(item.mediaType));
  }
  if (state.filter === "direct") {
    return state.items.filter((item) => item.mediaType === "direct");
  }
  return state.items;
}

function bestCandidate() {
  const ranking = { hls: 0, dash: 10, direct: 20, unknown: 30 };
  const score = (item) => {
    const url = String(item.url || "").toLowerCase();
    let value = ranking[item.mediaType] ?? 90;
    if (/master|playlist|index|manifest/.test(url)) value -= 2;
    if (/doubleclick|googleads|\/ads?[\/_-]|vast|preroll|promo/.test(url)) value += 100;
    return value;
  };
  return state.items
    .filter((item) => !["blob", "subtitle", "audio"].includes(item.mediaType) && item.manifestKind !== "audio" && item.url?.startsWith("http"))
    .sort((a, b) => score(a) - score(b))[0] || null;
}

function displayUrl(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol === "blob:") return "blob: oynatıcı nesnesi (tek başına aktarılamaz)";
    const path = `${url.pathname}${url.search}`;
    return `${url.hostname}${path}`;
  } catch {
    return raw;
  }
}

function showToast(text, error = false) {
  elements.toast.textContent = text;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => elements.toast.classList.add("hidden"), 2600);
}

function makeButton(text, className, handler, disabled = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  button.className = className;
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast("Adres panoya kopyalandı.");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    showToast("Adres panoya kopyalandı.");
  }
}

async function sendItem(item) {
  if (!state.appOnline) {
    showToast("Önce Python uygulamasını çalıştırın.", true);
    return;
  }
  const response = await chrome.runtime.sendMessage({
    type: "SEND_TO_APP",
    item: {
      ...item,
      pageUrl: item.pageUrl || state.tab?.url || "",
      title: item.title || state.tab?.title || "Video",
      userAgent: navigator.userAgent,
    },
  });
  if (!response?.ok) throw new Error(response?.error || "Uygulamaya gönderilemedi.");
  showToast(response.message || "Uygulamaya gönderildi.");
}

async function downloadItem(item) {
  const response = await chrome.runtime.sendMessage({
    type: "DIRECT_DOWNLOAD",
    item: { ...item, title: item.title || state.tab?.title || "video" },
  });
  if (!response?.ok) throw new Error(response?.error || "İndirme başlatılamadı.");
  showToast("Chrome indirmesi başlatıldı.");
}

function render() {
  const items = visibleItems();
  const best = bestCandidate();
  elements.count.textContent = String(state.items.length);
  elements.sendBest.classList.toggle("hidden", !best);
  elements.sendBest.disabled = !state.appOnline || !best;
  elements.sendBest.textContent = best
    ? `Yakalanan ${typeLabel(best.mediaType)} akışını gönder`
    : "Yakalanan akışı uygulamaya gönder";
  elements.list.replaceChildren();
  elements.empty.classList.toggle("hidden", items.length !== 0);
  elements.list.classList.toggle("hidden", items.length === 0);

  for (const item of items) {
    const card = document.createElement("article");
    card.className = "media-item";

    const head = document.createElement("div");
    head.className = "media-head";
    const type = document.createElement("span");
    type.className = `type-badge type-${item.mediaType || "unknown"}`;
    type.textContent = typeLabel(item.mediaType);
    const source = document.createElement("span");
    source.className = "source-badge";
    source.textContent = sourceLabel(item.sources);
    head.append(type, source);

    const url = document.createElement("div");
    url.className = "media-url";
    url.textContent = displayUrl(item.url);
    url.title = item.url;

    const meta = document.createElement("div");
    meta.className = "media-meta";
    const mime = item.contentType || "MIME bilinmiyor";
    meta.textContent = `${mime} • ${humanBytes(item.size)}`;

    const actions = document.createElement("div");
    actions.className = "item-actions";
    const isBlob = item.mediaType === "blob";
    const isSubtitle = item.mediaType === "subtitle";
    const isAudio = item.mediaType === "audio" || item.manifestKind === "audio";
    const appButton = makeButton(
      isBlob ? "Gerçek akışı seçin" : (isSubtitle || isAudio) ? "Videoyla birlikte eklenir" : "Uygulamaya gönder",
      "secondary",
      () => sendItem(item).catch((error) => showToast(error.message, true)),
      isBlob || isSubtitle || isAudio || !state.appOnline
    );
    actions.append(appButton);
    if (item.mediaType === "direct") {
      actions.append(
        makeButton("Chrome ile indir", "copy-button", () =>
          downloadItem(item).catch((error) => showToast(error.message, true))
        )
      );
    }
    actions.append(makeButton("Kopyala", "copy-button", () => copyText(item.url)));

    card.append(head, url, meta, actions);
    elements.list.append(card);
  }
}

async function loadMedia() {
  if (!state.tab?.id) return;
  const response = await chrome.runtime.sendMessage({ type: "GET_MEDIA", tabId: state.tab.id });
  state.items = Array.isArray(response?.items) ? response.items : [];
  render();
}

async function checkApp() {
  const response = await chrome.runtime.sendMessage({ type: "PING_APP" });
  state.appOnline = Boolean(response?.ok);
  elements.appDot.classList.toggle("online", state.appOnline);
  elements.appDot.classList.toggle("offline", !state.appOnline);
  elements.appStatus.textContent = state.appOnline
    ? "Bağlı • 127.0.0.1:17852"
    : "Kapalı • Python uygulamasını başlatın";
  elements.sendPage.disabled = !state.appOnline || !state.tab?.url?.startsWith("http");
  render();
}

function setFilter(filter) {
  state.filter = filter;
  elements.showAll.classList.toggle("active", filter === "all");
  elements.showStreams.classList.toggle("active", filter === "streams");
  elements.showDirect.classList.toggle("active", filter === "direct");
  render();
}

elements.showAll.addEventListener("click", () => setFilter("all"));
elements.showStreams.addEventListener("click", () => setFilter("streams"));
elements.showDirect.addEventListener("click", () => setFilter("direct"));

elements.refresh.addEventListener("click", () => {
  Promise.all([loadMedia(), checkApp()]).catch((error) => showToast(error.message, true));
});

elements.clear.addEventListener("click", async () => {
  if (!state.tab?.id) return;
  await chrome.runtime.sendMessage({ type: "CLEAR_MEDIA", tabId: state.tab.id });
  state.items = [];
  render();
  showToast("Yakalanan liste temizlendi.");
});

elements.sendBest.addEventListener("click", () => {
  const item = bestCandidate();
  if (!item) {
    showToast("Henüz aktarılabilir bir akış yakalanmadı.", true);
    return;
  }
  sendItem(item).catch((error) => showToast(error.message, true));
});

elements.sendPage.addEventListener("click", () => {
  if (!state.tab?.url) return;
  sendItem({
    url: state.tab.url,
    pageUrl: state.tab.url,
    title: state.tab.title || "Video sayfası",
    mediaType: "page",
  }).catch((error) => showToast(error.message, true));
});

async function initialize() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  state.tab = tabs[0] || null;
  if (state.tab?.url) {
    try {
      elements.pageHost.textContent = new URL(state.tab.url).hostname || state.tab.url;
    } catch {
      elements.pageHost.textContent = "Bu sayfada tarama kullanılamıyor";
    }
  } else {
    elements.pageHost.textContent = "Etkin sekme bulunamadı";
  }
  await Promise.all([loadMedia(), checkApp()]);
}

initialize().catch((error) => {
  showToast(String(error?.message || error), true);
  elements.appStatus.textContent = "Başlatma hatası";
});
