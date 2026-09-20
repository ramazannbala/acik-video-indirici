(() => {
  "use strict";

  const CHANNEL = "__ACIK_VIDEO_MEDIA_V1__";
  const CONTEXT_REQUEST = "__ACIK_VIDEO_YT_CONTEXT_REQUEST_V1__";
  const CONTEXT_RESPONSE = "__ACIK_VIDEO_YT_CONTEXT_RESPONSE_V1__";
  const INSTALLED = Symbol.for("acik-video-yakala.page-hook.installed");
  const MAX_TEXT_BYTES = 2 * 1024 * 1024;
  const MAX_TEXT_CHARS = 2 * 1024 * 1024;
  const MEDIA_RE = /\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|m4a|mp3|opus|ogg|wav|vtt|srt|ass|ssa|ttml)(?:$|[?#/])/i;
  const HLS_MIME_RE = /(?:application|audio)\/(?:vnd\.apple\.mpegurl|x-mpegurl)/i;
  const DASH_MIME_RE = /application\/dash\+xml/i;
  const SUBTITLE_MIME_RE = /(?:text\/vtt|application\/(?:x-subrip|ttml\+xml))/i;
  const ABS_MEDIA_IN_TEXT_RE = /(?:https?:)?\/\/[^\s"'<>\\]+?\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|m4a|mp3|opus|ogg|wav|vtt|srt|ass|ssa|ttml)(?:\?[^\s"'<>\\]*)?/gi;
  const QUOTED_MEDIA_IN_TEXT_RE = /["']([^"'<>]{1,4096}\.(?:mp4|m4v|webm|mov|mkv|m3u8|mpd|m4a|mp3|opus|ogg|wav|vtt|srt|ass|ssa|ttml)(?:\?[^"'<>]{0,4096})?)["']/gi;

  if (window[INSTALLED]) return;
  window[INSTALLED] = true;

  function readYouTubeVisitorData() {
    try {
      return String(
        window.ytcfg?.get?.("VISITOR_DATA")
        || window.ytcfg?.data_?.VISITOR_DATA
        || window.ytcfg?.get?.("INNERTUBE_CONTEXT")?.client?.visitorData
        || window.ytInitialPlayerResponse?.responseContext?.visitorData
        || window.ytInitialData?.responseContext?.visitorData
        || ""
      ).slice(0, 2048);
    } catch {
      return "";
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== CONTEXT_REQUEST) return;
    const nonce = String(event.data?.nonce || "").slice(0, 100);
    if (!nonce) return;
    window.postMessage(
      {
        channel: CONTEXT_RESPONSE,
        nonce,
        visitorData: readYouTubeVisitorData(),
      },
      "*"
    );
  });

  function normalizeEmbeddedText(text) {
    return String(text || "")
      .replace(/\\u002[fF]/g, "/")
      .replace(/\\x2[fF]/g, "/")
      .replace(/\\u0026/g, "&")
      .replace(/\\\//g, "/")
      .replace(/&amp;/g, "&");
  }

  function absoluteUrl(raw, base = document.baseURI) {
    if (typeof raw !== "string" || raw.length > 32768) return "";
    try {
      const url = new URL(normalizeEmbeddedText(raw), base);
      if (!["http:", "https:", "blob:"].includes(url.protocol)) return "";
      url.hash = "";
      return url.href;
    } catch {
      return "";
    }
  }

  function isInteresting(url, contentType = "") {
    const mime = String(contentType).toLowerCase();
    return (
      typeof url === "string" &&
      (MEDIA_RE.test(url) ||
        HLS_MIME_RE.test(mime) ||
        DASH_MIME_RE.test(mime) ||
        SUBTITLE_MIME_RE.test(mime) ||
        mime.startsWith("video/") ||
        mime.startsWith("audio/"))
    );
  }

  function publish(rawUrl, source, contentType = "", base = document.baseURI, metadata = {}) {
    const url = absoluteUrl(rawUrl, base);
    if (!url || !isInteresting(url, contentType)) return;
    window.postMessage(
      {
        channel: CHANNEL,
        payload: {
          url,
          source,
          contentType: String(contentType || "").slice(0, 160),
          language: String(metadata.language || "").slice(0, 40),
          label: String(metadata.label || "").slice(0, 120),
          manifestKind: String(metadata.manifestKind || "unknown"),
          manifestText: String(metadata.manifestText || "").slice(0, 1_000_000),
        },
      },
      "*"
    );
  }

  function inferSubtitleLanguageFromText(text) {
    const sample = String(text || "").slice(0, 30_000).toLowerCase();
    const turkish = (sample.match(/[çğıöşü]/g) || []).length * 3
      + (sample.match(/\b(?:ve|bir|bu|için|değil|ben|sen|biz|ama|çok|var|yok)\b/g) || []).length;
    const english = (sample.match(/\b(?:the|and|you|this|that|with|for|not|are|have|but|what)\b/g) || []).length;
    if (turkish >= 4 && turkish > english * 1.4) return "tr";
    if (english >= 4 && english > turkish * 1.4) return "en";
    return "";
  }

  function scanTextForMedia(rawText, responseUrl, source) {
    if (typeof rawText !== "string" || !rawText || rawText.length > MAX_TEXT_CHARS) return;
    const text = normalizeEmbeddedText(rawText);
    const base = absoluteUrl(responseUrl) || document.baseURI;

    // Subtitle endpoints are often extensionless and mislabeled as text/plain.
    const inferredSubtitleLanguage = inferSubtitleLanguageFromText(text);
    if (/^\s*WEBVTT(?:\s|$)/i.test(text)) {
      publish(responseUrl, source, "text/vtt", base, { language: inferredSubtitleLanguage });
    } else if (/\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}/.test(text)) {
      publish(responseUrl, source, "application/x-subrip", base, { language: inferredSubtitleLanguage });
    } else if (/<tt(?:\s|>)[\s\S]*?<\/tt>/i.test(text)) {
      publish(responseUrl, source, "application/ttml+xml", base, { language: inferredSubtitleLanguage });
    }

    // Some players return a manifest from an extensionless API endpoint with
    // text/plain or application/octet-stream. Classify master/video/audio so
    // the overlay never mistakes a standalone audio rendition for the video.
    if (/^\s*#EXTM3U/im.test(text)) {
      const hasStreamVariants = /#EXT-X-STREAM-INF:/i.test(text);
      const audioHint = /(?:^|[\/_-])(?:audio|mp4a|ac-?3|ec-?3|eac3|opus)(?:[\/_-]|$)|\.(?:aac|m4a)(?:$|[?#])/i.test(responseUrl);
      const audioSegments = /^\s*[^#\r\n]+\.(?:aac|m4a|mp3)(?:[?#][^\r\n]*)?\s*$/im.test(text);
      const manifestKind = hasStreamVariants ? "master" : (audioHint || audioSegments) ? "audio" : "video";
      publish(responseUrl, source, "application/vnd.apple.mpegurl", base, {
        manifestKind,
        manifestText: text,
      });

      for (const line of text.split(/\r?\n/)) {
        if (!/#EXT-X-MEDIA:/i.test(line)) continue;
        const attrs = {};
        const body = line.slice(line.indexOf(":") + 1);
        for (const match of body.matchAll(/([A-Z0-9-]+)=("[^"]*"|[^,]*)/gi)) {
          attrs[match[1].toUpperCase()] = match[2].replace(/^"|"$/g, "");
        }
        if (!attrs.URI) continue;
        if (String(attrs.TYPE || "").toUpperCase() === "SUBTITLES") {
          publish(attrs.URI, source, "text/vtt", base, {
            language: attrs.LANGUAGE || "",
            label: attrs.NAME || "",
          });
        } else if (String(attrs.TYPE || "").toUpperCase() === "AUDIO") {
          publish(attrs.URI, source, "application/vnd.apple.mpegurl", base, {
            language: attrs.LANGUAGE || "",
            label: attrs.NAME || "",
            manifestKind: "audio",
          });
        }
      }
    }
    if (/<MPD(?:\s|>)/i.test(text)) {
      publish(responseUrl, source, "application/dash+xml", base, {
        manifestKind: "master",
        manifestText: text,
      });
    }

    ABS_MEDIA_IN_TEXT_RE.lastIndex = 0;
    for (let match; (match = ABS_MEDIA_IN_TEXT_RE.exec(text)); ) {
      publish(match[0], source, "", base);
    }
    QUOTED_MEDIA_IN_TEXT_RE.lastIndex = 0;
    for (let match; (match = QUOTED_MEDIA_IN_TEXT_RE.exec(text)); ) {
      publish(match[1], source, "", base);
    }
  }

  function shouldInspectResponseBody(response, contentType) {
    const mime = String(contentType || "").toLowerCase();
    const length = Number(response?.headers?.get("content-length") || 0);
    if (length > MAX_TEXT_BYTES) return false;
    if (HLS_MIME_RE.test(mime) || DASH_MIME_RE.test(mime) || SUBTITLE_MIME_RE.test(mime)) return true;
    if (mime.startsWith("video/") || mime.startsWith("audio/") || mime.startsWith("image/")) {
      return false;
    }
    if (/json|text|javascript|xml|mpegurl|dash/.test(mime)) return true;
    if (mime.includes("octet-stream")) return length > 0 && length <= MAX_TEXT_BYTES;
    // For mislabeled API responses, inspect only when a small length is known.
    return length > 0 && length <= MAX_TEXT_BYTES;
  }

  async function readResponseTextLimited(response) {
    const clone = response.clone();
    if (!clone.body?.getReader) {
      const text = await clone.text();
      return text.length <= MAX_TEXT_CHARS ? text : "";
    }
    const reader = clone.body.getReader();
    const decoder = new TextDecoder();
    let total = 0;
    let text = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value?.byteLength || 0;
        if (total > MAX_TEXT_BYTES) {
          await reader.cancel();
          return "";
        }
        text += decoder.decode(value, { stream: true });
      }
      text += decoder.decode();
      return text.length <= MAX_TEXT_CHARS ? text : "";
    } finally {
      reader.releaseLock?.();
    }
  }

  async function inspectFetchResponse(response) {
    const responseUrl = response?.url || "";
    const contentType = response?.headers?.get("content-type") || "";
    publish(responseUrl, "fetch", contentType);
    if (!shouldInspectResponseBody(response, contentType)) return;
    const text = await readResponseTextLimited(response);
    if (text) scanTextForMedia(text, responseUrl, "fetch");
  }

  // Hook page-world fetch. The original response is returned unchanged. Only
  // small textual clones are inspected, and response bodies never leave page.
  try {
    const originalFetch = window.fetch;
    if (typeof originalFetch === "function") {
      window.fetch = function acikVideoFetch(...args) {
        try {
          const input = args[0];
          publish(typeof input === "string" ? input : input?.url, "fetch");
        } catch {
          // Detection must never break the host page.
        }
        const promise = Reflect.apply(originalFetch, this, args);
        return promise.then(
          (response) => {
            void inspectFetchResponse(response).catch(() => undefined);
            return response;
          },
          (error) => Promise.reject(error)
        );
      };
    }
  } catch {
    // Some pages freeze or proxy globals. Network observation still works.
  }

  // Hook page-world XMLHttpRequest. Text is inspected only after load and only
  // under the same two-megabyte limit.
  try {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    const requestUrls = new WeakMap();

    XMLHttpRequest.prototype.open = function acikVideoOpen(method, url, ...rest) {
      try {
        requestUrls.set(this, String(url || ""));
        publish(String(url || ""), "xhr");
      } catch {
        // Ignore and preserve normal XHR behavior.
      }
      return Reflect.apply(originalOpen, this, [method, url, ...rest]);
    };

    XMLHttpRequest.prototype.send = function acikVideoSend(...args) {
      const inspectHeaders = () => {
        try {
          const contentType = this.getResponseHeader("content-type") || "";
          publish(this.responseURL || requestUrls.get(this) || "", "xhr", contentType);
        } catch {
          // Cross-origin response headers may be unavailable to page code.
        }
      };
      const inspectBody = () => {
        try {
          inspectHeaders();
          let text = "";
          if (this.responseType === "" || this.responseType === "text") {
            text = this.responseText || "";
          } else if (this.responseType === "json" && this.response) {
            text = JSON.stringify(this.response);
          }
          if (text && text.length <= MAX_TEXT_CHARS) {
            scanTextForMedia(text, this.responseURL || requestUrls.get(this) || "", "xhr");
          }
        } catch {
          // Preserve XHR even when a response is opaque or binary.
        }
      };
      try {
        this.addEventListener("readystatechange", () => {
          if (this.readyState === 2) inspectHeaders();
        });
        this.addEventListener("load", inspectBody, { once: true });
      } catch {
        // Preserve XHR if listeners cannot be attached.
      }
      return Reflect.apply(originalSend, this, args);
    };
  } catch {
    // Observation through webRequest and the DOM remains active.
  }
})();
