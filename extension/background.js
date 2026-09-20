"use strict";

const BRIDGE_BASE = "http://127.0.0.1:17852";
const STORAGE_PREFIX = "captured-media:";
const MAX_ITEMS_PER_TAB = 250;
const MAX_URL_LENGTH = 32768;

const MEDIA_EXTENSION_RE = /\.(?:mp4|m4v|webm|mov|mkv|ts|m2ts|m3u8|mpd|m4a|mp3|opus|ogg|wav|vtt|srt|ass|ssa|ttml)(?:$|[?#/])/i;
const HLS_RE = /\.m3u8(?:$|[?#/])/i;
const DASH_RE = /\.mpd(?:$|[?#/])/i;
const DIRECT_RE = /\.(?:mp4|m4v|webm|mov|mkv|ts|m2ts)(?:$|[?#/])/i;
const AUDIO_RE = /\.(?:m4a|mp3|opus|ogg|wav)(?:$|[?#/])/i;
const SUBTITLE_RE = /\.(?:vtt|srt|ass|ssa|ttml)(?:$|[?#/])/i;
const SUBTITLE_MIME_RE = /(?:text\/vtt|application\/(?:x-subrip|ttml\+xml|octet-stream.*subtitle))/i;
const SEGMENT_RE = /\.(?:ts|m4s|cmfv|cmfa|aac)(?:$|[?#/])/i;
const HLS_MIME_RE = /(?:application|audio)\/(?:vnd\.apple\.mpegurl|x-mpegurl)/i;
const DASH_MIME_RE = /application\/dash\+xml/i;

const tabChains = new Map();
const activeVideos = new Map();

function activeVideoKey(tabId, frameId) {
  return `${tabId}:${Number.isInteger(frameId) ? frameId : 0}`;
}

function recentActiveVideo(tabId, frameId) {
  const active = activeVideos.get(activeVideoKey(tabId, frameId));
  return active && Date.now() - active.updatedAt < 30_000 ? active : null;
}

function clearActiveVideos(tabId) {
  const prefix = `${tabId}:`;
  for (const key of activeVideos.keys()) {
    if (key.startsWith(prefix)) activeVideos.delete(key);
  }
}

function storageKey(tabId) {
  return `${STORAGE_PREFIX}${tabId}`;
}

function serializeForTab(tabId, operation) {
  const previous = tabChains.get(tabId) || Promise.resolve();
  const next = previous.catch(() => undefined).then(operation);
  tabChains.set(tabId, next);
  next.finally(() => {
    if (tabChains.get(tabId) === next) tabChains.delete(tabId);
  });
  return next;
}

function safeHttpOrBlobUrl(raw) {
  if (typeof raw !== "string" || raw.length < 5 || raw.length > MAX_URL_LENGTH) {
    return null;
  }
  const text = raw.trim();
  try {
    const parsed = new URL(text);
    if (!["http:", "https:", "blob:"].includes(parsed.protocol)) return null;
    parsed.hash = "";
    return parsed.href;
  } catch {
    return null;
  }
}

function contentTypeFromHeaders(headers = []) {
  const header = headers.find((entry) => entry.name?.toLowerCase() === "content-type");
  return String(header?.value || "").split(";", 1)[0].trim().toLowerCase();
}

function contentLengthFromHeaders(headers = []) {
  const header = headers.find((entry) => entry.name?.toLowerCase() === "content-length");
  const parsed = Number(header?.value || 0);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function classifyMedia(url, contentType = "") {
  const mime = String(contentType).toLowerCase();
  if (url.startsWith("blob:")) return "blob";
  if (SUBTITLE_RE.test(url) || SUBTITLE_MIME_RE.test(mime)) return "subtitle";
  if (HLS_RE.test(url) || HLS_MIME_RE.test(mime)) return "hls";
  if (DASH_RE.test(url) || DASH_MIME_RE.test(mime)) return "dash";
  if (AUDIO_RE.test(url) || (mime.startsWith("audio/") && !HLS_MIME_RE.test(mime))) return "audio";
  if (DIRECT_RE.test(url) || (mime.startsWith("video/") && !mime.includes("mp2t"))) {
    return "direct";
  }
  return "unknown";
}

function isMediaCandidate(url, contentType = "", requestType = "") {
  if (!url) return false;
  const mime = String(contentType).toLowerCase();
  if (SEGMENT_RE.test(url) || mime.includes("video/mp2t")) {
    // Ignore hundreds of HLS XHR fragments, but allow a standalone TS opened
    // as the browser's actual media resource.
    return requestType === "media" && (/\.(?:ts|m2ts)(?:$|[?#/])/i.test(url) || mime.includes("video/mp2t"));
  }
  return (
    url.startsWith("blob:") ||
    MEDIA_EXTENSION_RE.test(url) ||
    HLS_MIME_RE.test(mime) ||
    DASH_MIME_RE.test(mime) ||
    SUBTITLE_MIME_RE.test(mime) ||
    mime.startsWith("video/") ||
    (mime.startsWith("audio/") && !mime.includes("mp2t"))
  );
}

function normalizeSource(source) {
  const allowed = new Set(["network", "headers", "dom", "fetch", "xhr", "performance"]);
  return allowed.has(source) ? source : "network";
}

async function getItems(tabId) {
  if (!Number.isInteger(tabId) || tabId < 0) return [];
  const result = await chrome.storage.session.get(storageKey(tabId));
  const items = result[storageKey(tabId)];
  return Array.isArray(items) ? items : [];
}

async function setBadge(tabId, count) {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1777c7" });
    await chrome.action.setBadgeText({ tabId, text: count ? String(Math.min(count, 99)) : "" });
  } catch {
    // The tab may have disappeared while an async write was pending.
  }
}

function addMedia(tabId, candidate) {
  if (!Number.isInteger(tabId) || tabId < 0) return Promise.resolve(false);
  const url = safeHttpOrBlobUrl(candidate.url);
  const contentType = String(candidate.contentType || "").slice(0, 160).toLowerCase();
  if (!url || !isMediaCandidate(url, contentType, candidate.requestType || "")) return Promise.resolve(false);

  return serializeForTab(tabId, async () => {
    const items = await getItems(tabId);
    const existingIndex = items.findIndex((item) => item.url === url);
    const now = Date.now();
    const source = normalizeSource(candidate.source);
    const mediaType = classifyMedia(url, contentType);
    const frameId = Number.isInteger(candidate.frameId) ? candidate.frameId : 0;
    const active = recentActiveVideo(tabId, frameId);
    const pageUrl = safeHttpOrBlobUrl(candidate.pageUrl || active?.pageUrl || "");
    const title = String(candidate.title || active?.title || "").trim().slice(0, 240);
    const videoKey = String(candidate.videoKey || active?.videoKey || "").slice(0, 100);
    const language = String(candidate.language || "").replace(/[\t\r\n]/g, "").slice(0, 40);
    const label = String(candidate.label || "").replace(/[\t\r\n]/g, "").slice(0, 120);
    const manifestKind = ["master", "video", "audio", "unknown"].includes(candidate.manifestKind)
      ? candidate.manifestKind : "unknown";
    const rawManifestText = String(candidate.manifestText || "").slice(0, 1_000_000);
    const manifestText = /^\s*(?:#EXTM3U|<\?xml|<MPD)/i.test(rawManifestText)
      ? rawManifestText : "";
    const size = Number(candidate.size || 0);

    if (existingIndex >= 0) {
      const current = items[existingIndex];
      const sources = Array.from(new Set([...(current.sources || []), source]));
      items[existingIndex] = {
        ...current,
        contentType: contentType || current.contentType || "",
        mediaType: current.mediaType === "unknown" ? mediaType : current.mediaType,
        pageUrl: pageUrl || current.pageUrl || "",
        title: title || current.title || "",
        videoKey: videoKey || current.videoKey || "",
        frameId: Number.isInteger(current.frameId) ? current.frameId : frameId,
        language: language || current.language || "",
        label: label || current.label || "",
        manifestKind: manifestKind !== "unknown" ? manifestKind : current.manifestKind || "unknown",
        manifestText: manifestText || current.manifestText || "",
        size: size > 0 ? size : current.size || 0,
        sources,
        capturedAt: now,
      };
      const [updated] = items.splice(existingIndex, 1);
      items.unshift(updated);
    } else {
      items.unshift({
        id: `${now}-${Math.random().toString(36).slice(2, 9)}`,
        url,
        contentType,
        mediaType,
        pageUrl: pageUrl || "",
        title,
        videoKey,
        frameId,
        language,
        label,
        manifestKind,
        manifestText,
        size: size > 0 ? size : 0,
        sources: [source],
        capturedAt: now,
      });
    }

    if (items.length > MAX_ITEMS_PER_TAB) items.length = MAX_ITEMS_PER_TAB;
    await chrome.storage.session.set({ [storageKey(tabId)]: items });
    await setBadge(tabId, items.length);
    return true;
  });
}

async function clearTab(tabId) {
  if (!Number.isInteger(tabId) || tabId < 0) return;
  await serializeForTab(tabId, async () => {
    await chrome.storage.session.remove(storageKey(tabId));
    await setBadge(tabId, 0);
  });
}

function filenameFrom(item) {
  let extension = "mp4";
  try {
    const path = new URL(item.url).pathname;
    const matched = path.match(/\.([a-z0-9]{2,5})$/i);
    if (matched && ["mp4", "m4v", "webm", "mov", "mkv"].includes(matched[1].toLowerCase())) {
      extension = matched[1].toLowerCase();
    }
  } catch {
    // Keep fallback.
  }
  const base = String(item.title || "video")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/g, "")
    .slice(0, 150) || "video";
  return `${base}.${extension}`;
}

async function directDownload(item) {
  const url = safeHttpOrBlobUrl(item?.url || "");
  if (!url || url.startsWith("blob:") || classifyMedia(url, item?.contentType) !== "direct") {
    throw new Error("Bu kayıt doğrudan tarayıcı indirmesine uygun değil.");
  }
  const downloadId = await chrome.downloads.download({
    url,
    filename: filenameFrom(item),
    saveAs: true,
    conflictAction: "uniquify",
  });
  return { ok: true, downloadId };
}

async function sendToCompanion(item) {
  const url = safeHttpOrBlobUrl(item?.url || "");
  if (!url || url.startsWith("blob:")) {
    throw new Error("blob: adresi tarayıcı dışına aktarılamaz; gerçek HLS/DASH isteğini seçin.");
  }
  const pageUrl = safeHttpOrBlobUrl(item?.pageUrl || "");
  const response = await fetch(`${BRIDGE_BASE}/api/open`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Aloha-Bridge": "1",
    },
    body: JSON.stringify({
      url,
      pageUrl: pageUrl?.startsWith("http") ? pageUrl : "",
      title: String(item?.title || "").slice(0, 240),
      source: "chrome-extension",
      mediaType: String(item?.mediaType || "unknown").slice(0, 24),
      captureSources: Array.isArray(item?.sources)
        ? item.sources.slice(0, 6).join(",")
        : "",
      userAgent: String(item?.userAgent || "").replace(/[\r\n]/g, "").slice(0, 500),
      visitorData: String(item?.visitorData || "").replace(/[\r\n]/g, "").slice(0, 2048),
      mediaCookieHeader: String(item?.mediaCookieHeader || "").replace(/[\r\n]/g, "").slice(0, 16_384),
      mediaCookies: Array.isArray(item?.mediaCookies) ? item.mediaCookies.slice(0, 200) : [],
      manifestText: String(item?.manifestText || "").slice(0, 1_000_000),
      primaryLanguage: String(item?.primaryLanguage || "").replace(/[^a-zA-Z_-]/g, "").slice(0, 20),
      youtubeCookies: Array.isArray(item?.youtubeCookies)
        ? item.youtubeCookies.slice(0, 250)
        : [],
      youtubeAuthenticated: Boolean(item?.youtubeAuthenticated),
      siteCookies: Array.isArray(item?.siteCookies) ? item.siteCookies.slice(0, 200) : [],
      externalSubtitles: Array.isArray(item?.externalSubtitles)
        ? item.externalSubtitles.slice(0, 20)
        : [],
      externalAudioTracks: Array.isArray(item?.externalAudioTracks)
        ? item.externalAudioTracks.slice(0, 12)
        : [],
    }),
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // A useful status message is produced below.
  }
  if (!response.ok) {
    throw new Error(payload.error || `Yerel uygulama HTTP ${response.status} döndürdü.`);
  }
  return { ok: true, message: payload.message || "Uygulamaya gönderildi." };
}

function isYouTubeUrl(raw) {
  try {
    const host = new URL(raw).hostname.replace(/^www\./, "");
    return host === "youtube.com" || host.endsWith(".youtube.com") || host === "youtu.be";
  } catch {
    return false;
  }
}

function isXUrl(raw) {
  try {
    const host = new URL(raw).hostname.replace(/^www\./, "");
    return host === "x.com" || host.endsWith(".x.com")
      || host === "twitter.com" || host.endsWith(".twitter.com");
  } catch {
    return false;
  }
}

async function getYouTubeCookiesForTab(tabId) {
  if (!chrome.cookies?.getAll) return [];
  let storeId;
  try {
    const stores = await chrome.cookies.getAllCookieStores();
    storeId = stores.find((store) => store.tabIds?.includes(tabId))?.id;
  } catch {
    // The default cookie store is sufficient when store discovery fails.
  }
  const details = { domain: "youtube.com" };
  if (storeId) details.storeId = storeId;
  const cookies = await chrome.cookies.getAll(details);
  const deduplicated = new Map();
  for (const cookie of cookies) {
    const domain = String(cookie.domain || "").toLowerCase();
    if (!(domain === "youtube.com" || domain.endsWith(".youtube.com"))) continue;
    const name = String(cookie.name || "").replace(/[\t\r\n]/g, "").slice(0, 256);
    const value = String(cookie.value || "").replace(/[\t\r\n]/g, "").slice(0, 8192);
    if (!name) continue;
    const normalized = {
      domain: domain.slice(0, 255),
      path: String(cookie.path || "/").replace(/[\t\r\n]/g, "").slice(0, 1024) || "/",
      secure: Boolean(cookie.secure),
      httpOnly: Boolean(cookie.httpOnly),
      expirationDate: Number(cookie.expirationDate || 0),
      name,
      value,
    };
    deduplicated.set(`${normalized.domain}\n${normalized.path}\n${name}`, normalized);
  }
  return [...deduplicated.values()].slice(0, 250);
}

function inferTrackLanguage(item, index = 0, prefix = "ext") {
  if (item.language) return String(item.language).slice(0, 40);
  const text = `${item.label || ""} ${item.url || ""}`.toLowerCase();
  if (/(?:^|[^a-z])(tr|tur|turkish|türkçe|turkce|dublaj|dubbed)(?:[^a-z]|$)/.test(text)) return "tr";
  if (/(?:^|[^a-z])(en|eng|english|original|orijinal|org)(?:[^a-z]|$)/.test(text)) return "en";
  return `und-${prefix}${index + 1}`;
}

async function getSiteCookiesForUrl(tabId, rawUrl) {
  if (!chrome.cookies?.getAll) return [];
  const url = safeHttpOrBlobUrl(rawUrl || "");
  if (!url?.startsWith("http")) return [];
  let storeId;
  try {
    const stores = await chrome.cookies.getAllCookieStores();
    storeId = stores.find((store) => store.tabIds?.includes(tabId))?.id;
  } catch {
    // Use default store.
  }
  try {
    const details = { url };
    if (storeId) details.storeId = storeId;
    const cookies = await chrome.cookies.getAll(details);
    return cookies.slice(0, 200).map((cookie) => ({
      domain: String(cookie.domain || "").slice(0, 255),
      path: String(cookie.path || "/").slice(0, 1024),
      secure: Boolean(cookie.secure),
      expirationDate: Number(cookie.expirationDate || 0),
      name: String(cookie.name || "").replace(/[\t\r\n]/g, "").slice(0, 256),
      value: String(cookie.value || "").replace(/[\t\r\n]/g, "").slice(0, 8192),
    })).filter((cookie) => cookie.name);
  } catch {
    return [];
  }
}

async function getCookieHeaderForUrl(tabId, rawUrl) {
  if (!chrome.cookies?.getAll) return "";
  const url = safeHttpOrBlobUrl(rawUrl || "");
  if (!url?.startsWith("http")) return "";
  let storeId;
  try {
    const stores = await chrome.cookies.getAllCookieStores();
    storeId = stores.find((store) => store.tabIds?.includes(tabId))?.id;
  } catch {
    // Use default store.
  }
  try {
    const details = { url };
    if (storeId) details.storeId = storeId;
    const cookies = await chrome.cookies.getAll(details);
    return cookies
      .filter((cookie) => cookie.name && cookie.value)
      .slice(0, 120)
      .map((cookie) => `${String(cookie.name).replace(/[;\r\n]/g, "")}=${String(cookie.value).replace(/[;\r\n]/g, "")}`)
      .join("; ")
      .slice(0, 16_384);
  } catch {
    return "";
  }
}

function isAudioLikeItem(item) {
  const url = String(item?.url || "").toLowerCase();
  return item?.mediaType === "audio"
    || item?.manifestKind === "audio"
    || /(?:^|[\/_-])(?:audio|mp4a|ac-?3|ec-?3|eac3|opus)(?:[\/_-]|$)|\.(?:aac|m4a)(?:$|[?#])/.test(url);
}

function overlayCandidateScore(item, video, frameId) {
  const typeScore = { hls: 0, dash: 10, direct: 20, unknown: 60, blob: 10_000, subtitle: 20_000 };
  const url = String(item.url || "").toLowerCase();
  let score = typeScore[item.mediaType] ?? 100;
  if (item.manifestKind === "master") score -= 1200;
  if (item.manifestKind === "video") score -= 500;
  if (item.manifestKind === "audio") score += 6000;
  if (/(?:^|[\/_-])(?:audio|mp4a|ac-?3|ec-?3|eac3|opus)(?:[\/_-]|$)|\.(?:aac|m4a)(?:$|[?#])/.test(url)) score += 3500;
  if (item.url === video.currentSrc) score -= 3000;
  if (video.videoKey && item.videoKey === video.videoKey) score -= 1500;
  if (Number.isInteger(item.frameId) && item.frameId === frameId) score -= 250;
  if (/master|manifest|playlist|index/.test(url)) score -= 5;
  if (/doubleclick|googleads|\/ads?[\/_-]|vast|preroll|promo/.test(url)) score += 5000;
  score += Math.min(100, Math.max(0, Date.now() - Number(item.capturedAt || 0)) / 1000);
  return score;
}

async function handleOverlayDownload(video, sender) {
  const tabId = sender.tab?.id;
  if (!Number.isInteger(tabId)) throw new Error("Etkin sekme bulunamadı.");
  const frameId = Number.isInteger(sender.frameId) ? sender.frameId : 0;
  const tab = await chrome.tabs.get(tabId);
  const framePageUrl = safeHttpOrBlobUrl(video?.pageUrl || "");
  const tabUrl = safeHttpOrBlobUrl(tab?.url || "");
  const pageUrl = framePageUrl?.startsWith("http") ? framePageUrl : tabUrl;
  const title = String(video?.title || tab?.title || "Video")
    .replace(/\s+-\s+YouTube\s*$/i, "")
    .trim()
    .slice(0, 240);
  const userAgent = String(video?.userAgent || "").replace(/[\r\n]/g, "").slice(0, 500);

  // YouTube's page extractor is considerably more reliable than its short-lived
  // googlevideo URLs and is required for subtitles/multiple audio tracks.
  const youtubePage = [tabUrl, pageUrl].find((url) => url && isYouTubeUrl(url));
  if (video?.isYouTube || youtubePage) {
    const target = youtubePage || pageUrl;
    if (!target) throw new Error("YouTube sayfa adresi bulunamadı.");
    const youtubeCookies = video?.useYouTubeSession
      ? await getYouTubeCookiesForTab(tabId).catch(() => [])
      : [];
    const authCookieNames = new Set([
      "LOGIN_INFO", "SID", "HSID", "SSID", "APISID", "SAPISID", "SIDCC",
      "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
      "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    ]);
    const youtubeAuthenticated = youtubeCookies.some((cookie) => authCookieNames.has(cookie.name));
    await sendToCompanion({
      url: target,
      pageUrl: target,
      title,
      mediaType: "page",
      sources: ["overlay", "youtube"],
      userAgent,
      visitorData: String(video?.visitorData || "").slice(0, 2048),
      youtubeCookies,
      youtubeAuthenticated,
    });
    return {
      ok: true,
      selectedType: "page",
      message: youtubeCookies.length
        ? `YouTube sayfası ${youtubeCookies.length} oturum çereziyle gönderildi.`
        : "YouTube sayfası gönderildi; oturum çerezi bulunamadı.",
    };
  }

  // X/Twitter has a maintained yt-dlp extractor. Its page URL is more reliable
  // than short-lived per-codec HLS renditions such as /mp4a/32000/*.m3u8.
  const xPage = [tabUrl, pageUrl].find((url) => url && isXUrl(url));
  if (xPage) {
    const primaryCookies = await getSiteCookiesForUrl(tabId, xPage).catch(() => []);
    const alternateCookieUrl = new URL(xPage).hostname.includes("twitter.com")
      ? "https://x.com/" : "https://twitter.com/";
    const alternateCookies = await getSiteCookiesForUrl(tabId, alternateCookieUrl).catch(() => []);
    const cookieMap = new Map();
    for (const cookie of [...primaryCookies, ...alternateCookies]) {
      cookieMap.set(`${cookie.domain}\n${cookie.path}\n${cookie.name}`, cookie);
    }
    const siteCookies = [...cookieMap.values()].slice(0, 200);
    await sendToCompanion({
      url: xPage,
      pageUrl: xPage,
      title,
      mediaType: "page",
      sources: ["overlay", "x-extractor"],
      userAgent,
      siteCookies,
    });
    return {
      ok: true,
      selectedType: "page",
      message: `X/Twitter sayfası ${siteCookies.length} oturum çereziyle gönderildi.`,
    };
  }

  const items = await getItems(tabId);
  const currentSrc = safeHttpOrBlobUrl(video?.currentSrc || "");
  const wantedVideoKey = String(video?.videoKey || "");
  const usableItems = items.filter((item) =>
    item.mediaType !== "blob"
    && item.mediaType !== "subtitle"
    && !isAudioLikeItem(item));
  const subtitlePool = items.filter((item) => item.mediaType === "subtitle");
  const subtitleCutoff = Date.now() - 10 * 60_000;
  let associatedSubtitles = wantedVideoKey
    ? subtitlePool.filter((item) => item.videoKey === wantedVideoKey)
    : [];
  if (!associatedSubtitles.length) {
    associatedSubtitles = subtitlePool.filter((item) =>
      Number(item.capturedAt || 0) >= subtitleCutoff
      && (!Number.isInteger(item.frameId) || item.frameId === frameId)
      && (!pageUrl || !item.pageUrl || item.pageUrl === pageUrl));
  }
  let externalSubtitles = associatedSubtitles.slice(0, 20).map((item, index) => ({
    url: item.url,
    language: inferTrackLanguage(item, index, "sub"),
    label: item.label || "",
    ext: (() => {
      try { return new URL(item.url).pathname.split(".").pop()?.toLowerCase() || "vtt"; }
      catch { return "vtt"; }
    })(),
  }));

  const audioPool = items.filter((item) => isAudioLikeItem(item));
  let associatedAudio = wantedVideoKey
    ? audioPool.filter((item) => item.videoKey === wantedVideoKey)
    : [];
  if (!associatedAudio.length) {
    associatedAudio = audioPool.filter((item) =>
      Number(item.capturedAt || 0) >= subtitleCutoff
      && (!Number.isInteger(item.frameId) || item.frameId === frameId)
      && (!pageUrl || !item.pageUrl || item.pageUrl === pageUrl));
  }
  let externalAudioTracks = associatedAudio.slice(0, 12).map((item, index) => ({
    url: item.url,
    language: inferTrackLanguage(item, index, "audio"),
    label: item.label || "",
    isHls: item.mediaType === "hls" || item.manifestKind === "audio",
    ext: (() => {
      try { return new URL(item.url).pathname.split(".").pop()?.toLowerCase() || "m4a"; }
      catch { return "m4a"; }
    })(),
  }));
  let candidates = wantedVideoKey
    ? usableItems.filter((item) => item.videoKey === wantedVideoKey)
    : [];
  if (!candidates.length) {
    const cutoff = Date.now() - 120_000;
    candidates = usableItems.filter((item) =>
      Number(item.capturedAt || 0) >= cutoff
      && (!Number.isInteger(item.frameId) || item.frameId === frameId)
      && (!pageUrl || !item.pageUrl || item.pageUrl === pageUrl));
  }
  if (!candidates.length && usableItems.length === 1 && Date.now() - usableItems[0].capturedAt < 120_000) {
    candidates = [usableItems[0]];
  }
  if (currentSrc?.startsWith("http") && isMediaCandidate(currentSrc, "video/unknown")) {
    candidates.push({
      url: currentSrc,
      contentType: "video/unknown",
      mediaType: classifyMedia(currentSrc, "video/unknown"),
      pageUrl: pageUrl || "",
      title,
      videoKey: String(video?.videoKey || ""),
      frameId,
      capturedAt: Date.now(),
      sources: ["overlay", "dom"],
    });
  }
  candidates.sort((a, b) => overlayCandidateScore(a, video || {}, frameId) - overlayCandidateScore(b, video || {}, frameId));
  const selected = candidates[0];

  // Some players implement dubbed/original choices as completely separate
  // HLS sources instead of EXT-X-MEDIA audio renditions. If the non-selected
  // source is explicitly labeled in its URL/name, pass it as an audio source;
  // Python/FFmpeg will map only its audio stream into the final MKV.
  if (selected) {
    const knownAudioUrls = new Set(externalAudioTracks.map((track) => track.url));
    const alternateSources = usableItems.filter((item) =>
      item.url !== selected.url
      && item.mediaType === "hls"
      && (!wantedVideoKey || item.videoKey === wantedVideoKey));
    for (const item of alternateSources) {
      const language = inferTrackLanguage(item, externalAudioTracks.length, "audio");
      if (!["tr", "en"].includes(language) || knownAudioUrls.has(item.url)) continue;
      externalAudioTracks.push({
        url: item.url,
        language,
        label: item.label || (language === "tr" ? "Türkçe Dublaj" : "Original English"),
        ext: "m3u8",
        isHls: true,
        fullSource: true,
      });
      knownAudioUrls.add(item.url);
      if (externalAudioTracks.length >= 12) break;
    }
  }

  if (selected) {
    externalAudioTracks = await Promise.all(externalAudioTracks.map(async (track) => ({
      ...track,
      cookieHeader: await getCookieHeaderForUrl(tabId, track.url),
    })));
    externalSubtitles = await Promise.all(externalSubtitles.map(async (track) => ({
      ...track,
      cookieHeader: await getCookieHeaderForUrl(tabId, track.url),
    })));
    const mediaCookieHeader = await getCookieHeaderForUrl(tabId, selected.url);
    const mediaCookies = await getSiteCookiesForUrl(tabId, selected.url).catch(() => []);
    await sendToCompanion({
      ...selected,
      pageUrl: selected.pageUrl || pageUrl || "",
      title: title || selected.title || "Video",
      userAgent,
      mediaCookieHeader,
      mediaCookies,
      primaryLanguage: (() => {
        const language = inferTrackLanguage(selected, 0, "primary");
        return ["tr", "en"].includes(language) ? language : "";
      })(),
      externalSubtitles,
      externalAudioTracks,
      sources: Array.from(new Set([...(selected.sources || []), "overlay"])),
    });
    return { ok: true, selectedType: selected.mediaType, message: "Yakalanan video uygulamaya gönderildi." };
  }

  if (!pageUrl?.startsWith("http")) throw new Error("Bu videoya ait aktarılabilir adres bulunamadı.");
  externalAudioTracks = await Promise.all(externalAudioTracks.map(async (track) => ({
    ...track,
    cookieHeader: await getCookieHeaderForUrl(tabId, track.url),
  })));
  externalSubtitles = await Promise.all(externalSubtitles.map(async (track) => ({
    ...track,
    cookieHeader: await getCookieHeaderForUrl(tabId, track.url),
  })));
  await sendToCompanion({
    url: pageUrl,
    pageUrl,
    title,
    mediaType: "page",
    sources: ["overlay"],
    userAgent,
    externalSubtitles,
    externalAudioTracks,
  });
  return { ok: true, selectedType: "page", message: "Sayfa adresi uygulamaya gönderildi." };
}

async function pingCompanion() {
  try {
    const response = await fetch(`${BRIDGE_BASE}/health`, { cache: "no-store" });
    return { ok: response.ok };
  } catch {
    return { ok: false };
  }
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0 || !isMediaCandidate(details.url, "", details.type)) return;
    void addMedia(details.tabId, {
      url: details.url,
      pageUrl: details.documentUrl || details.initiator || "",
      frameId: details.frameId,
      requestType: details.type,
      source: "network",
    });
  },
  { urls: ["<all_urls>"] }
);

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const contentType = contentTypeFromHeaders(details.responseHeaders);
    if (!isMediaCandidate(details.url, contentType, details.type)) return;
    void addMedia(details.tabId, {
      url: details.url,
      pageUrl: details.documentUrl || details.initiator || "",
      frameId: details.frameId,
      requestType: details.type,
      contentType,
      size: contentLengthFromHeaders(details.responseHeaders),
      source: "headers",
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "MEDIA_FOUND": {
      const tabId = sender.tab?.id;
      if (!Number.isInteger(tabId)) return { ok: false };
      const item = message.item || {};
      return {
        ok: await addMedia(tabId, {
          ...item,
          frameId: sender.frameId,
          pageUrl: item.pageUrl || sender.url || "",
        }),
      };
    }
    case "VIDEO_ACTIVITY": {
      const tabId = sender.tab?.id;
      if (!Number.isInteger(tabId)) return { ok: false };
      const frameId = Number.isInteger(sender.frameId) ? sender.frameId : 0;
      const video = message.video || {};
      const active = {
        videoKey: String(video.videoKey || "").slice(0, 100),
        pageUrl: safeHttpOrBlobUrl(video.pageUrl || sender.url || "") || "",
        title: String(video.title || "").trim().slice(0, 240),
        updatedAt: Date.now(),
      };
      activeVideos.set(activeVideoKey(tabId, frameId), active);
      const currentSrc = safeHttpOrBlobUrl(video.currentSrc || "");
      if (currentSrc && isMediaCandidate(currentSrc, "video/unknown")) {
        await addMedia(tabId, {
          url: currentSrc,
          contentType: "video/unknown",
          source: "dom",
          frameId,
          videoKey: active.videoKey,
          pageUrl: active.pageUrl,
          title: active.title,
        });
      }
      return { ok: true };
    }
    case "OVERLAY_DOWNLOAD":
      return handleOverlayDownload(message.video || {}, sender);
    case "GET_MEDIA": {
      const tabId = Number(message.tabId);
      return { ok: true, items: await getItems(tabId) };
    }
    case "CLEAR_MEDIA": {
      await clearTab(Number(message.tabId));
      return { ok: true };
    }
    case "DIRECT_DOWNLOAD":
      return directDownload(message.item || {});
    case "SEND_TO_APP":
      return sendToCompanion(message.item || {});
    case "PING_APP":
      return pingCompanion();
    default:
      return { ok: false, error: "Bilinmeyen mesaj" };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    clearActiveVideos(tabId);
    void clearTab(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  clearActiveVideos(tabId);
  void chrome.storage.session.remove(storageKey(tabId));
});

chrome.runtime.onInstalled.addListener(() => {
  void chrome.action.setBadgeBackgroundColor({ color: "#1777c7" });
});
