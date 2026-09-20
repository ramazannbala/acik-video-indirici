(() => {
  "use strict";

  const CHANNEL = "__ACIK_VIDEO_MEDIA_V1__";
  const MEDIA_RE = /\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|m4a|mp3|opus|ogg|wav|vtt|srt|ass|ssa|ttml)(?:$|[?#/])/i;
  const PLAYLIST_TEXT_RE = /https?:\\?\/\\?\/[^"'\s<>]+?\.(?:m3u8|mpd)(?:\?[^"'\s<>]*)?/gi;
  const VIDEO_KEY_PROP = Symbol.for("acik-video-yakala.video-key");
  const sent = new Set();

  function ensureVideoKey(video) {
    if (!(video instanceof HTMLVideoElement)) return "";
    if (!video[VIDEO_KEY_PROP]) {
      video[VIDEO_KEY_PROP] = `video-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }
    return video[VIDEO_KEY_PROP];
  }

  function videoScore(video, candidateUrl = "") {
    const rect = video.getBoundingClientRect();
    let score = Math.max(0, rect.width) * Math.max(0, rect.height);
    if (!video.paused && !video.ended) score += 10_000_000;
    if (video.readyState >= 2) score += 1_000_000;
    if (candidateUrl && absoluteUrl(video.currentSrc || video.src) === candidateUrl) score += 100_000_000;
    return score;
  }

  function bestVideo(candidateUrl = "") {
    return [...document.querySelectorAll("video")]
      .filter((video) => video.isConnected)
      .sort((a, b) => videoScore(b, candidateUrl) - videoScore(a, candidateUrl))[0] || null;
  }

  function inferVideoTitle(video) {
    const clean = (value) => String(value || "").replace(/\s+/g, " ").trim().slice(0, 240);
    const usable = (value) => {
      const text = clean(value);
      return text.length > 3 && !/(?:video\s+başlamadı|video\s+yüklen|didn.?t\s+start|player\s*error|^video$|^watch$|bir\s+hata\s+oluştu)/i.test(text);
    };
    const youtubeTitle = document.querySelector(
      "h1.ytd-watch-metadata yt-formatted-string, #title h1, h1.title"
    )?.textContent;
    const metaTitle = document.querySelector(
      "meta[property='og:title'], meta[name='twitter:title'], meta[name='title']"
    )?.content;
    const card = video?.closest("article, li, [role='article'], [class*='card'], [class*='player']");
    const localTitle = card?.querySelector("h1, h2, h3, [id*='title'], [class*='title']")?.textContent;
    const aria = video?.getAttribute("aria-label") || video?.getAttribute("title");
    const documentTitle = document.title.replace(/\s+-\s+YouTube\s*$/i, "");
    for (const candidate of [youtubeTitle, metaTitle, localTitle, aria, documentTitle]) {
      if (usable(candidate)) return clean(candidate);
    }
    return "Video";
  }

  function absoluteUrl(raw) {
    if (typeof raw !== "string" || !raw.trim() || raw.length > 32768) return "";
    let text = raw.trim().replace(/\\\//g, "/").replace(/&amp;/g, "&");
    try {
      const url = new URL(text, document.baseURI);
      if (!["http:", "https:", "blob:"].includes(url.protocol)) return "";
      url.hash = "";
      return url.href;
    } catch {
      return "";
    }
  }

  function send(rawUrl, source = "dom", contentType = "", linkedVideo = null, metadata = {}) {
    const url = absoluteUrl(rawUrl);
    if (!url) return;
    const video = linkedVideo instanceof HTMLVideoElement ? linkedVideo : bestVideo(url);
    const videoKey = ensureVideoKey(video);
    const language = String(metadata.language || "").slice(0, 40);
    const key = `${url}\n${contentType}\n${videoKey}\n${language}`;
    if (sent.has(key)) return;
    sent.add(key);
    if (sent.size > 1000) sent.clear();
    chrome.runtime.sendMessage({
      type: "MEDIA_FOUND",
      item: {
        url,
        source,
        contentType: String(contentType || "").slice(0, 160),
        pageUrl: location.href,
        title: inferVideoTitle(video),
        videoKey,
        language,
        label: String(metadata.label || "").slice(0, 120),
        manifestKind: String(metadata.manifestKind || "unknown"),
        manifestText: String(metadata.manifestText || "").slice(0, 1_000_000),
        requestType: linkedVideo instanceof HTMLVideoElement ? "media" : String(metadata.requestType || ""),
      },
    }).catch(() => {
      // The MV3 worker can restart while a page is navigating; later scans retry.
    });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== CHANNEL) return;
    const payload = event.data.payload;
    if (!payload || typeof payload !== "object") return;
    send(payload.url, payload.source, payload.contentType, null, {
      language: payload.language,
      label: payload.label,
      manifestKind: payload.manifestKind,
      manifestText: payload.manifestText,
    });
  });

  function scanMediaElement(element) {
    if (!(element instanceof Element)) return;
    if (element.matches("video, audio")) {
      const linkedVideo = element instanceof HTMLVideoElement ? element : null;
      send(element.currentSrc, "dom", linkedVideo ? "video/unknown" : "", linkedVideo);
      send(element.getAttribute("src"), "dom", linkedVideo ? "video/unknown" : "", linkedVideo);
      for (const source of element.querySelectorAll("source[src]")) {
        send(source.getAttribute("src"), "dom", source.getAttribute("type") || "", linkedVideo);
      }
    } else if (element.matches("source[src]")) {
      const linkedVideo = element.closest("video");
      send(element.getAttribute("src"), "dom", element.getAttribute("type") || "", linkedVideo);
    } else if (element.matches("track[src]")) {
      const linkedVideo = element.closest("video") || bestVideo();
      send(element.getAttribute("src"), "dom", element.getAttribute("type") || "text/vtt", linkedVideo, {
        language: element.getAttribute("srclang") || "",
        label: element.getAttribute("label") || "",
      });
    }
    for (const media of element.querySelectorAll?.("video, audio, source[src], track[src]") || []) {
      if (media !== element) scanMediaElement(media);
    }
  }

  function scanDocument() {
    for (const media of document.querySelectorAll("video, audio, track[src]")) scanMediaElement(media);
  }

  function scanInlinePlaylists() {
    // Limit scanning to script text and one megabyte total; this avoids copying
    // arbitrary page HTML and keeps large single-page apps responsive.
    let inspected = 0;
    for (const script of document.scripts) {
      const text = script.textContent || "";
      if (!text || inspected >= 1_000_000) break;
      const chunk = text.slice(0, Math.min(250_000, 1_000_000 - inspected));
      inspected += chunk.length;
      const normalized = chunk
        .replace(/\\u002[fF]/g, "/")
        .replace(/\\x2[fF]/g, "/")
        .replace(/\\u0026/g, "&");
      const matches = normalized.match(PLAYLIST_TEXT_RE) || [];
      for (const match of matches.slice(0, 80)) send(match, "dom");
    }
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "attributes") {
        scanMediaElement(mutation.target);
      }
      for (const node of mutation.addedNodes) {
        if (node instanceof Element) scanMediaElement(node);
      }
    }
  });

  function beginDomObservation() {
    if (!document.documentElement) return;
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["src", "type", "srclang", "label", "kind"],
    });
    scanDocument();
    scanInlinePlaylists();
  }

  if (document.documentElement) beginDomObservation();
  else document.addEventListener("DOMContentLoaded", beginDomObservation, { once: true });

  document.addEventListener(
    "loadedmetadata",
    (event) => {
      if (event.target instanceof Element) scanMediaElement(event.target);
    },
    true
  );

  // Resource Timing catches media requested before a late DOM mutation and
  // requests made by page code that does not use window.fetch/XHR.
  try {
    const inspectEntry = (entry) => {
      if (entry?.name && MEDIA_RE.test(entry.name)) send(entry.name, "performance");
    };
    for (const entry of performance.getEntriesByType("resource")) inspectEntry(entry);
    const perfObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) inspectEntry(entry);
    });
    perfObserver.observe({ type: "resource", buffered: true });
  } catch {
    // Resource Timing can be disabled; the other layers remain available.
  }

  window.addEventListener("load", () => {
    scanDocument();
    scanInlinePlaylists();
  }, { once: true });
})();
