(() => {
  "use strict";

  const VIDEO_KEY_PROP = Symbol.for("acik-video-yakala.video-key");
  const CONTEXT_REQUEST = "__ACIK_VIDEO_YT_CONTEXT_REQUEST_V1__";
  const CONTEXT_RESPONSE = "__ACIK_VIDEO_YT_CONTEXT_RESPONSE_V1__";
  const states = new Map();
  let scanScheduled = false;

  function ensureVideoKey(video) {
    if (!video[VIDEO_KEY_PROP]) {
      video[VIDEO_KEY_PROP] = `video-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }
    return video[VIDEO_KEY_PROP];
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
    const card = video.closest("article, li, [role='article'], [class*='card'], [class*='player']");
    const localTitle = card?.querySelector("h1, h2, h3, [id*='title'], [class*='title']")?.textContent;
    const aria = video.getAttribute("aria-label") || video.getAttribute("title");
    const documentTitle = document.title.replace(/\s+-\s+YouTube\s*$/i, "");
    for (const candidate of [youtubeTitle, metaTitle, localTitle, aria, documentTitle]) {
      if (usable(candidate)) return clean(candidate);
    }
    return "Video";
  }

  function isYouTubeUrl(url) {
    try {
      const host = new URL(url).hostname.replace(/^www\./, "");
      return host === "youtube.com" || host.endsWith(".youtube.com") || host === "youtu.be";
    } catch {
      return false;
    }
  }

  function requestYouTubeContext() {
    return new Promise((resolve) => {
      const nonce = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const finish = (value) => {
        clearTimeout(timer);
        window.removeEventListener("message", receive);
        resolve(value || {});
      };
      const receive = (event) => {
        if (
          event.source === window
          && event.data?.channel === CONTEXT_RESPONSE
          && event.data?.nonce === nonce
        ) {
          finish({ visitorData: String(event.data.visitorData || "").slice(0, 2048) });
        }
      };
      const timer = setTimeout(() => finish({}), 700);
      window.addEventListener("message", receive);
      window.postMessage({ channel: CONTEXT_REQUEST, nonce }, "*");
    });
  }

  function createHost(video) {
    const host = document.createElement("div");
    host.setAttribute("data-acik-video-overlay", "1");
    Object.assign(host.style, {
      all: "initial",
      position: "fixed",
      left: "0",
      top: "0",
      width: "0",
      height: "0",
      display: "none",
      zIndex: "2147483647",
      pointerEvents: "none",
    });

    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }
      button {
        all: initial;
        position: absolute;
        right: 0;
        top: 0;
        display: inline-flex;
        align-items: center;
        gap: 7px;
        min-height: 34px;
        box-sizing: border-box;
        padding: 7px 12px;
        border: 1px solid rgba(255,255,255,.28);
        border-radius: 9px;
        background: linear-gradient(135deg, rgba(19,119,205,.97), rgba(8,77,143,.97));
        box-shadow: 0 5px 18px rgba(0,0,0,.42);
        color: white;
        cursor: pointer;
        font: 600 13px/1.2 "Segoe UI", system-ui, sans-serif;
        letter-spacing: .1px;
        white-space: nowrap;
        pointer-events: auto;
        user-select: none;
        -webkit-font-smoothing: antialiased;
        transition: transform .12s ease, filter .12s ease, opacity .12s ease;
      }
      button:hover { filter: brightness(1.13); transform: translateY(-1px); }
      button:active { transform: translateY(0); }
      button:disabled { cursor: wait; opacity: .82; }
      .icon { font: 700 17px/1 system-ui, sans-serif; }
    `;
    const button = document.createElement("button");
    button.type = "button";
    button.title = isYouTubeUrl(location.href)
      ? "YouTube oturum bilgilerini yalnız yerel indiriciyle kullanarak analiz et"
      : "Bu videoyu Açık Video İndirici'de analiz et";
    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = "↓";
    const label = document.createElement("span");
    label.textContent = isYouTubeUrl(location.href) ? "İndir (oturumla)" : "İndir";
    button.append(icon, label);
    shadow.append(style, button);
    document.documentElement.append(host);

    const state = {
      video,
      host,
      button,
      label,
      hovered: false,
      lastActivity: 0,
      lastNotice: 0,
    };
    states.set(video, state);

    const markActive = () => {
      state.lastActivity = Date.now();
      notifyActivity(state);
      updatePosition(state);
    };
    video.addEventListener("play", markActive, true);
    video.addEventListener("playing", markActive, true);
    video.addEventListener("loadedmetadata", markActive, true);
    video.addEventListener("durationchange", markActive, true);
    video.addEventListener("mouseenter", () => {
      state.hovered = true;
      updatePosition(state);
    });
    video.addEventListener("mouseleave", () => {
      state.hovered = false;
      updatePosition(state);
    });

    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await requestDownload(state);
    });
    markActive();
    return state;
  }

  function notifyActivity(state) {
    const now = Date.now();
    if (now - state.lastNotice < 450) return;
    state.lastNotice = now;
    const video = state.video;
    chrome.runtime.sendMessage({
      type: "VIDEO_ACTIVITY",
      video: {
        videoKey: ensureVideoKey(video),
        pageUrl: location.href,
        currentSrc: video.currentSrc || video.src || "",
        title: inferVideoTitle(video),
        width: video.videoWidth || Math.round(video.getBoundingClientRect().width),
        height: video.videoHeight || Math.round(video.getBoundingClientRect().height),
      },
    }).catch(() => undefined);
  }

  async function requestDownload(state) {
    const { video, button, label } = state;
    button.disabled = true;
    label.textContent = "Gönderiliyor…";
    try {
      const youtube = isYouTubeUrl(location.href);
      const youtubeContext = youtube ? await requestYouTubeContext() : {};
      const response = await chrome.runtime.sendMessage({
        type: "OVERLAY_DOWNLOAD",
        video: {
          videoKey: ensureVideoKey(video),
          pageUrl: location.href,
          currentSrc: video.currentSrc || video.src || "",
          title: inferVideoTitle(video),
          isYouTube: youtube,
          visitorData: youtubeContext.visitorData || "",
          useYouTubeSession: youtube,
          userAgent: navigator.userAgent,
        },
      });
      if (!response?.ok) throw new Error(response?.error || "Uygulamaya gönderilemedi");
      label.textContent = response.selectedType === "page" ? "Sayfa gönderildi ✓" : "Video gönderildi ✓";
      button.title = "Açık Video İndirici analizi başlattı";
    } catch (error) {
      const message = String(error?.message || error);
      label.textContent = /fetch|bağlan|failed/i.test(message) ? "Uygulama kapalı" : "Gönderilemedi";
      button.title = message;
    } finally {
      setTimeout(() => {
        if (!video.isConnected) return;
        label.textContent = isYouTubeUrl(location.href) ? "İndir (oturumla)" : "İndir";
        button.title = isYouTubeUrl(location.href)
          ? "YouTube oturum bilgilerini yalnız yerel indiriciyle kullanarak analiz et"
          : "Bu videoyu Açık Video İndirici'de analiz et";
        button.disabled = false;
      }, 2800);
    }
  }

  function desiredParent(video) {
    const fullscreen = document.fullscreenElement;
    if (fullscreen && fullscreen !== video && fullscreen.contains(video)) return fullscreen;
    return document.documentElement;
  }

  function updatePosition(state) {
    const { video, host } = state;
    if (!video.isConnected) {
      host.remove();
      states.delete(video);
      return;
    }
    const rect = video.getBoundingClientRect();
    const style = getComputedStyle(video);
    const inViewport = rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    const largeEnough = rect.width >= 260 && rect.height >= 145;
    const hasPlayed = (!video.paused && !video.ended) || video.currentTime > 0 || state.hovered;
    const visible = style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0;
    const fullscreenVideoOnly = document.fullscreenElement === video;

    if (!inViewport || !largeEnough || !hasPlayed || !visible || fullscreenVideoOnly) {
      host.style.display = "none";
      return;
    }

    const parent = desiredParent(video);
    if (host.parentNode !== parent) parent.append(host);
    host.style.display = "block";
    host.style.left = `${Math.min(innerWidth - 8, Math.max(90, rect.right - 12))}px`;
    host.style.top = `${Math.max(8, rect.top + 12)}px`;
  }

  function scanVideos() {
    scanScheduled = false;
    for (const video of document.querySelectorAll("video")) {
      if (!states.has(video)) createHost(video);
    }
    for (const state of states.values()) updatePosition(state);
  }

  function scheduleScan() {
    if (scanScheduled) return;
    scanScheduled = true;
    requestAnimationFrame(scanVideos);
  }

  const observer = new MutationObserver(scheduleScan);
  function start() {
    observer.observe(document.documentElement, { childList: true, subtree: true });
    scanVideos();
    setInterval(scanVideos, 500);
    addEventListener("scroll", scheduleScan, true);
    addEventListener("resize", scheduleScan, true);
    document.addEventListener("fullscreenchange", scheduleScan, true);
  }

  if (document.documentElement) start();
  else document.addEventListener("DOMContentLoaded", start, { once: true });
})();
