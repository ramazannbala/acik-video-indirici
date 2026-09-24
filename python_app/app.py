from __future__ import annotations

import gc
import hashlib
import html
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

# Setup (dondurulmuş) sürümde yt-dlp EXE'ye gömülmez; EXE yanındaki pylibs/
# klasöründen yüklenir ve uygulama içinden güncellenebilir (README kural 24).
if getattr(sys, "frozen", False):
    _PYLIBS_DIR = Path(sys.executable).resolve().parent / "pylibs"
    if _PYLIBS_DIR.is_dir():
        sys.path.insert(0, str(_PYLIBS_DIR))

import customtkinter as ctk

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
except ImportError:
    if getattr(sys, "frozen", False):
        from tkinter import messagebox as _mb

        _mb.showerror(
            "Açık Video İndirici",
            "yt-dlp kitaplığı bulunamadı: kurulum klasöründeki pylibs eksik veya bozuk. "
            "Kurulumu yeniden çalıştırın veya pylibs klasörünü geri yükleyin.",
        )
        raise SystemExit(1)
    raise


APP_NAME = "Açık Video İndirici"
APP_VERSION = "7.4.1"
# PyInstaller ile dondurulmuş EXE (setup kurulumu) içinde True olur.
IS_FROZEN = bool(getattr(sys, "frozen", False))
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 17852
MAX_BRIDGE_BODY = 2 * 1024 * 1024
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
COOKIE_ACCESS_ERROR_MARKERS = (
    "could not copy chrome cookie database",
    "could not find chrome cookie database",
    "failed to decrypt with dpapi",
    "cookie database is locked",
)


# ---------- Small helpers ----------


def human_bytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def human_speed(value: Any) -> str:
    result = human_bytes(value)
    return "—" if result == "—" else f"{result}/sn"


def clean_text(value: Any, limit: int = 600) -> str:
    text = ANSI_RE.sub("", str(value or "")).replace("\r", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_http_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def is_browser_cookie_access_error(error: BaseException) -> bool:
    text = clean_text(error, 4000).lower()
    if any(marker in text for marker in COOKIE_ACCESS_ERROR_MARKERS):
        return True
    return "permission denied" in text and "cookie" in text


def redacted_url_label(value: str) -> str:
    """Return host + path for logs without leaking signed query parameters."""
    try:
        parsed = urllib.parse.urlsplit(value)
        path = parsed.path or "/"
        if len(path) > 100:
            path = path[:99] + "…"
        return f"{parsed.netloc}{path}"
    except ValueError:
        return "geçersiz-adres"


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads / "Acik Video Indirici"


def settings_file() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path.home() / ".config"
    return base / "AcikVideoIndirici" / "settings.json"


def job_history_file() -> Path:
    return settings_file().with_name("downloads.json")


def find_ffmpeg() -> str | None:
    candidates: list[str | Path | None] = []
    app_dir = Path(__file__).resolve().parent
    # Dondurulmuş EXE'de __file__ geçici açılım klasörünü gösterir; kurulum
    # klasöründeki (EXE yanı) ffmpeg.exe kopyalarını da aday olarak tara.
    exe_dir: Path | None = (
        Path(sys.executable).resolve().parent if IS_FROZEN else None
    )

    # A newly installed WinGet package may not be visible in the PATH of the
    # already-running GUI. Inspect its standard locations as well, so the
    # in-app updater can use the new binary without relying only on a reboot.
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        winget_roots: list[Path] = []
        winget_candidates: list[Path] = []
        if local_app_data:
            local = Path(local_app_data) / "Microsoft" / "WinGet"
            candidates.append(local / "Links" / "ffmpeg.exe")
            winget_roots.append(local / "Packages")
        if program_files:
            winget_roots.append(Path(program_files) / "WinGet" / "Packages")
        for root in winget_roots:
            if not root.is_dir():
                continue
            try:
                for package_dir in root.glob("Gyan.FFmpeg_*"):
                    winget_candidates.extend(package_dir.rglob("ffmpeg.exe"))
            except OSError:
                continue
        try:
            winget_candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            pass
        candidates.extend(winget_candidates)

    # Prefer a WinGet-managed build after an in-app update; otherwise fall
    # back to the ordinary PATH and finally app-local binaries.
    candidates.append(shutil.which("ffmpeg"))
    candidates.extend(
        [
            app_dir / "ffmpeg.exe",
            app_dir / "bin" / "ffmpeg.exe",
            app_dir / "ffmpeg",
            app_dir / "bin" / "ffmpeg",
        ]
    )
    if exe_dir is not None:
        candidates.extend([exe_dir / "ffmpeg.exe", exe_dir / "bin" / "ffmpeg.exe"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate).resolve()
        except OSError:
            continue
        normalized = os.path.normcase(str(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.is_file():
            return str(path)
    return None


def ffmpeg_version(executable: str | None = None) -> str:
    path = executable or find_ffmpeg()
    if not path:
        return ""
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    first_line = next(
        (line.strip() for line in (result.stdout or result.stderr).splitlines() if line.strip()),
        "",
    )
    match = re.match(r"ffmpeg\s+version\s+([^\s]+)", first_line, flags=re.IGNORECASE)
    token = match.group(1) if match else first_line
    numeric_release = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", token)
    return clean_text(numeric_release.group(1) if numeric_release else token, 40)


def find_ffprobe(ffmpeg_executable: str | None = None) -> str | None:
    ffmpeg_path = ffmpeg_executable or find_ffmpeg()
    candidates: list[str | Path | None] = []
    if ffmpeg_path:
        ffmpeg_file = Path(ffmpeg_path)
        probe_name = "ffprobe.exe" if ffmpeg_file.suffix.lower() == ".exe" or os.name == "nt" else "ffprobe"
        candidates.append(ffmpeg_file.with_name(probe_name))
    candidates.append(shutil.which("ffprobe"))
    app_dir = Path(__file__).resolve().parent
    candidates.extend(
        [
            app_dir / "ffprobe.exe",
            app_dir / "bin" / "ffprobe.exe",
            app_dir / "ffprobe",
            app_dir / "bin" / "ffprobe",
        ]
    )
    if IS_FROZEN:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "ffprobe.exe", exe_dir / "bin" / "ffprobe.exe"])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(candidate).resolve()
        except OSError:
            continue
        if path.is_file():
            return str(path)
    return None


def find_deno() -> str | None:
    candidates: list[str | None] = [shutil.which("deno")]
    home = Path.home()
    candidates.append(str(home / ".deno" / "bin" / "deno.exe"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local = Path(local_app_data)
        candidates.append(str(local / "deno" / "deno.exe"))
        winget_root = local / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            candidates.extend(str(path) for path in winget_root.glob("DenoLand.Deno_*/*/deno.exe"))
            candidates.extend(str(path) for path in winget_root.glob("DenoLand.Deno_*/deno.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def is_youtube_url(value: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(value).hostname or "").lower()
        return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"} or host.endswith(
            ".youtube.com"
        )
    except ValueError:
        return False


def is_usable_source_title(value: Any) -> bool:
    text = html.unescape(clean_text(value, 300)).strip()
    if len(text) < 4:
        return False
    if re.search(r"(?:video\s+başlamadı|video\s+yüklen|didn.?t\s+start|player\s*error|bir\s+hata\s+oluştu)", text, re.IGNORECASE):
        return False
    compact = re.sub(r"[^A-Za-z0-9+/=]", "", text)
    if len(text) > 55 and len(compact) / max(1, len(text)) > 0.92:
        return False
    return text.lower() not in {"video", "watch", "player", "master"}


def title_from_page_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        candidate = parts[-1] if parts else ""
        if candidate and not candidate.isdigit() and len(candidate) <= 100:
            candidate = re.sub(r"[-_]+", " ", candidate)
            if is_usable_source_title(candidate):
                return candidate.strip().title()
        host = (parsed.hostname or "Video").removeprefix("www.").split(".")[0]
        return f"{host.title()} Video"
    except ValueError:
        return "Video"


def safe_source_filename(value: str) -> str:
    text = html.unescape(clean_text(value, 300))
    text = re.sub(r"\s+-\s+YouTube\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = "Video"
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if text.upper() in reserved:
        text = f"_{text}"
    return text[:180].rstrip(" .") or "Video"


def youtube_cookies_to_netscape(cookies: list[dict[str, Any]]) -> str:
    lines = ["# Netscape HTTP Cookie File", "# In-memory YouTube session from browser extension", ""]
    for cookie in cookies[:250]:
        domain = str(cookie.get("domain") or "").lower().strip()
        if not (domain == "youtube.com" or domain.endswith(".youtube.com")):
            continue
        name = str(cookie.get("name") or "").replace("\t", "").replace("\r", "").replace("\n", "")[:256]
        value = str(cookie.get("value") or "").replace("\t", "").replace("\r", "").replace("\n", "")[:8192]
        path = str(cookie.get("path") or "/").replace("\t", "").replace("\r", "").replace("\n", "")[:1024] or "/"
        if not name:
            continue
        try:
            expires = max(0, int(float(cookie.get("expirationDate") or 0)))
        except (TypeError, ValueError, OverflowError):
            expires = 0
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        lines.append("\t".join((domain, include_subdomains, path, secure, str(expires), name, value)))
    return "\n".join(lines) + "\n"


def site_cookies_to_netscape(cookies: list[dict[str, Any]], page_url: str) -> str:
    try:
        page_host = (urllib.parse.urlsplit(page_url).hostname or "").lower()
    except ValueError:
        page_host = ""
    lines = ["# Netscape HTTP Cookie File", "# In-memory current-site session", ""]
    for cookie in cookies[:200]:
        domain = str(cookie.get("domain") or "").lower().strip()
        plain_domain = domain.lstrip(".")
        related_x_domain = (
            page_host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
            and plain_domain in {"x.com", "twitter.com"}
        )
        if not page_host or not (
            page_host == plain_domain or page_host.endswith(f".{plain_domain}") or related_x_domain
        ):
            continue
        name = str(cookie.get("name") or "").replace("\t", "").replace("\r", "").replace("\n", "")[:256]
        value = str(cookie.get("value") or "").replace("\t", "").replace("\r", "").replace("\n", "")[:8192]
        path = str(cookie.get("path") or "/").replace("\t", "").replace("\r", "").replace("\n", "")[:1024] or "/"
        if not name:
            continue
        try:
            expires = max(0, int(float(cookie.get("expirationDate") or 0)))
        except (TypeError, ValueError, OverflowError):
            expires = 0
        lines.append("\t".join((
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            path,
            "TRUE" if cookie.get("secure") else "FALSE",
            str(expires),
            name,
            value,
        )))
    return "\n".join(lines) + "\n"


def cookie_header_to_netscape(header: str, url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    lines = ["# Netscape HTTP Cookie File", "# In-memory media cookie header", ""]
    if not host:
        return "\n".join(lines) + "\n"
    for part in str(header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        name = name.replace("\t", "").replace("\r", "").replace("\n", "")[:256]
        value = value.replace("\t", "").replace("\r", "").replace("\n", "")[:8192]
        if sep and name:
            lines.append("\t".join((host, "FALSE", "/", "TRUE", "0", name, value)))
    return "\n".join(lines) + "\n"


def shortened_codec(value: Any) -> str:
    codec = str(value or "none")
    if codec == "none":
        return "—"
    return codec.split(".", 1)[0][:16]


JOB_STATUS_LABELS = {
    "queued": "Kuyrukta",
    "downloading": "İndiriliyor",
    "processing": "Birleştiriliyor",
    "finalizing": "Dosya doğrulanıyor",
    "pausing": "Duraklatılıyor",
    "cancelling": "İptal ediliyor",
    "paused": "Duraklatıldı",
    "completed": "Tamamlandı",
    "cancelled": "İptal edildi",
    "failed": "Hata",
    "interrupted": "Yarım kaldı",
}
TERMINAL_JOB_STATUSES = {"completed", "cancelled", "failed", "interrupted"}
MEDIA_FILE_EXTENSIONS = {".mkv", ".mp4", ".webm", ".mov", ".m4v", ".avi", ".ts", ".m2ts", ".mp3", ".m4a", ".mka"}


@dataclass
class DownloadJob:
    id: str
    url: str
    title: str
    quality: str
    format_label: str
    output_dir: str
    ydl_opts: dict[str, Any] = field(default_factory=dict, repr=False)
    external_audio_tracks: list[dict[str, Any]] = field(default_factory=list, repr=False)
    external_subtitle_tracks: list[dict[str, Any]] = field(default_factory=list, repr=False)
    resume_headers: dict[str, str] = field(default_factory=dict, repr=False)
    output_mode: str = "sidecar"
    job_type: str = "video"
    parent_id: str = ""
    parent_filepath: str = ""
    package_title: str = ""
    children_spawned: bool = False
    auto_mux_job_id: str = ""
    mux_video_path: str = ""
    mux_audio_tracks: list[dict[str, str]] = field(default_factory=list, repr=False)
    mux_subtitle_tracks: list[dict[str, str]] = field(default_factory=list, repr=False)
    mux_output_path: str = ""
    mux_container: str = "mkv"
    status: str = "queued"
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0
    eta: int | None = None
    fragment_index: int = 0
    fragment_count: int = 0
    filepath: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    related_files: set[str] = field(default_factory=set, repr=False)
    pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    history_only: bool = False
    sidecar_only: bool = False
    last_progress_emit: float = field(default=0.0, repr=False)

    def to_history(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "quality": self.quality,
            "format_label": self.format_label,
            "output_dir": self.output_dir,
            "output_mode": self.output_mode,
            "job_type": self.job_type,
            "parent_id": self.parent_id,
            "parent_filepath": self.parent_filepath,
            "package_title": self.package_title,
            "children_spawned": self.children_spawned,
            "auto_mux_job_id": self.auto_mux_job_id,
            "mux_video_path": self.mux_video_path,
            "mux_audio_tracks": self.mux_audio_tracks,
            "mux_subtitle_tracks": self.mux_subtitle_tracks,
            "mux_output_path": self.mux_output_path,
            "mux_container": self.mux_container,
            "status": self.status,
            "progress": self.progress,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "filepath": self.filepath,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "related_files": sorted(self.related_files),
            "external_audio_tracks": [
                {key: value for key, value in track.items() if key != "cookieHeader"}
                for track in self.external_audio_tracks
            ],
            "external_subtitle_tracks": [
                {key: value for key, value in track.items() if key != "cookieHeader"}
                for track in self.external_subtitle_tracks
            ],
            "resume_headers": {
                key: value for key, value in self.resume_headers.items()
                if key in {"Referer", "Origin", "User-Agent"}
            },
        }

    @classmethod
    def from_history(cls, data: dict[str, Any]) -> "DownloadJob":
        status = str(data.get("status") or "interrupted")
        if status in {"queued", "downloading", "processing", "finalizing", "paused", "pausing", "cancelling"}:
            status = "interrupted"
        job = cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            url=str(data.get("url") or ""),
            title=str(data.get("title") or "Video"),
            quality=str(data.get("quality") or "—"),
            format_label=str(data.get("format_label") or "—"),
            output_dir=str(data.get("output_dir") or default_download_dir()),
            external_audio_tracks=[
                dict(track) for track in data.get("external_audio_tracks") or [] if isinstance(track, dict)
            ],
            external_subtitle_tracks=[
                dict(track) for track in data.get("external_subtitle_tracks") or [] if isinstance(track, dict)
            ],
            resume_headers={
                str(key): str(value) for key, value in (data.get("resume_headers") or {}).items()
                if key in {"Referer", "Origin", "User-Agent"}
            },
            output_mode=str(data.get("output_mode") or "sidecar"),
            job_type=str(data.get("job_type") or "video"),
            parent_id=str(data.get("parent_id") or ""),
            parent_filepath=str(data.get("parent_filepath") or ""),
            package_title=str(data.get("package_title") or data.get("title") or "Video"),
            children_spawned=bool(data.get("children_spawned")),
            auto_mux_job_id=str(data.get("auto_mux_job_id") or ""),
            mux_video_path=str(data.get("mux_video_path") or ""),
            mux_audio_tracks=[dict(track) for track in data.get("mux_audio_tracks") or [] if isinstance(track, dict)],
            mux_subtitle_tracks=[dict(track) for track in data.get("mux_subtitle_tracks") or [] if isinstance(track, dict)],
            mux_output_path=str(data.get("mux_output_path") or ""),
            mux_container=str(data.get("mux_container") or "mkv"),
            status=status,
            progress=float(data.get("progress") or 0),
            downloaded_bytes=int(data.get("downloaded_bytes") or 0),
            total_bytes=int(data.get("total_bytes") or 0),
            filepath=str(data.get("filepath") or ""),
            error=str(data.get("error") or ""),
            created_at=float(data.get("created_at") or time.time()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            related_files=set(map(str, data.get("related_files") or [])),
            history_only=True,
        )
        return job


# ---------- Loopback bridge used by the browser extension ----------


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def bridge_handler_factory(event_queue: queue.Queue):
    class BridgeHandler(BaseHTTPRequestHandler):
        server_version = "AcikVideoBridge/1.0"

        def log_message(self, _format: str, *_args: Any) -> None:
            # Do not print signed media URLs or request details to a console.
            return

        def _origin(self) -> str:
            return self.headers.get("Origin", "")

        def _origin_allowed(self) -> bool:
            origin = self._origin()
            # Extension fetches normally include an extension Origin. An absent
            # Origin is also accepted for local diagnostics, but POST still
            # requires the non-simple X-Aloha-Bridge header below.
            return not origin or origin.startswith(
                ("chrome-extension://", "edge-extension://")
            )

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self._origin()
            if origin and self._origin_allowed():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            if not self._origin_allowed():
                self._send_json(403, {"ok": False, "error": "İzin verilmeyen origin"})
                return
            self.send_response(204)
            origin = self._origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Aloha-Bridge"
            )
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/health":
                self._send_json(404, {"ok": False, "error": "Bulunamadı"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "accepts": ["http", "https"],
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/api/open":
                self._send_json(404, {"ok": False, "error": "Bulunamadı"})
                return
            if not self._origin_allowed():
                self._send_json(403, {"ok": False, "error": "İzin verilmeyen origin"})
                return
            if self.headers.get("X-Aloha-Bridge") != "1":
                self._send_json(403, {"ok": False, "error": "Köprü başlığı eksik"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BRIDGE_BODY:
                self._send_json(413, {"ok": False, "error": "Geçersiz istek boyutu"})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "Geçersiz JSON"})
                return

            url = str(payload.get("url", "")).strip()
            page_url = str(payload.get("pageUrl", "")).strip()
            title = clean_text(payload.get("title", ""), 240)
            media_type = clean_text(payload.get("mediaType", "unknown"), 24).lower()
            if media_type not in {"page", "hls", "dash", "direct", "unknown"}:
                media_type = "unknown"
            capture_sources = clean_text(payload.get("captureSources", ""), 120)
            user_agent = clean_text(payload.get("userAgent", ""), 500)
            visitor_data = clean_text(payload.get("visitorData", ""), 2048)
            media_cookie_header = str(payload.get("mediaCookieHeader") or "").replace("\r", "").replace("\n", "")[:16_384]
            raw_manifest_text = str(payload.get("manifestText") or "")[:1_000_000]
            manifest_text = raw_manifest_text if re.match(r"^\s*(?:#EXTM3U|<\?xml|<MPD)", raw_manifest_text, flags=re.IGNORECASE) else ""
            primary_language = clean_text(payload.get("primaryLanguage", ""), 20).lower()
            if primary_language not in {"tr", "en"}:
                primary_language = ""
            raw_cookies = payload.get("youtubeCookies")
            youtube_authenticated = bool(payload.get("youtubeAuthenticated"))
            youtube_cookies: list[dict[str, Any]] = []
            site_cookies: list[dict[str, Any]] = []
            raw_site_cookies = payload.get("siteCookies")
            if isinstance(raw_site_cookies, list):
                for raw_cookie in raw_site_cookies[:200]:
                    if not isinstance(raw_cookie, dict):
                        continue
                    site_cookies.append(
                        {
                            "domain": str(raw_cookie.get("domain") or "")[:255],
                            "path": str(raw_cookie.get("path") or "/")[:1024],
                            "secure": bool(raw_cookie.get("secure")),
                            "expirationDate": raw_cookie.get("expirationDate") or 0,
                            "name": str(raw_cookie.get("name") or "")[:256],
                            "value": str(raw_cookie.get("value") or "")[:8192],
                        }
                    )
            media_cookies: list[dict[str, Any]] = []
            raw_media_cookies = payload.get("mediaCookies")
            if isinstance(raw_media_cookies, list):
                for raw_cookie in raw_media_cookies[:200]:
                    if not isinstance(raw_cookie, dict):
                        continue
                    media_cookies.append(
                        {
                            "domain": str(raw_cookie.get("domain") or "")[:255],
                            "path": str(raw_cookie.get("path") or "/")[:1024],
                            "secure": bool(raw_cookie.get("secure")),
                            "expirationDate": raw_cookie.get("expirationDate") or 0,
                            "name": str(raw_cookie.get("name") or "")[:256],
                            "value": str(raw_cookie.get("value") or "")[:8192],
                        }
                    )
            external_subtitles: list[dict[str, str]] = []
            external_audio_tracks: list[dict[str, Any]] = []
            raw_external_subtitles = payload.get("externalSubtitles")
            if isinstance(raw_external_subtitles, list):
                for index, raw_subtitle in enumerate(raw_external_subtitles[:20]):
                    if not isinstance(raw_subtitle, dict):
                        continue
                    subtitle_url = str(raw_subtitle.get("url") or "").strip()
                    if not is_http_url(subtitle_url) or len(subtitle_url) > 16_384:
                        continue
                    language = clean_text(raw_subtitle.get("language") or f"und-ext{index + 1}", 40)
                    label = clean_text(raw_subtitle.get("label") or "", 120)
                    ext = clean_text(raw_subtitle.get("ext") or "vtt", 10).lower().lstrip(".")
                    if ext not in {"vtt", "srt", "ass", "ssa", "ttml", "m3u8"}:
                        ext = "vtt"
                    cookie_header = str(raw_subtitle.get("cookieHeader") or "").replace("\r", "").replace("\n", "")[:16_384]
                    external_subtitles.append(
                        {
                            "url": subtitle_url,
                            "language": language,
                            "label": label,
                            "ext": ext,
                            "cookieHeader": cookie_header,
                        }
                    )
            raw_external_audio = payload.get("externalAudioTracks")
            if isinstance(raw_external_audio, list):
                for index, raw_audio in enumerate(raw_external_audio[:12]):
                    if not isinstance(raw_audio, dict):
                        continue
                    audio_url = str(raw_audio.get("url") or "").strip()
                    if not is_http_url(audio_url) or len(audio_url) > 16_384:
                        continue
                    language = clean_text(raw_audio.get("language") or f"und-audio{index + 1}", 40)
                    label = clean_text(raw_audio.get("label") or "", 120)
                    ext = clean_text(raw_audio.get("ext") or "m4a", 10).lower().lstrip(".")
                    if ext not in {"m3u8", "m4a", "aac", "mp3", "opus", "ogg", "wav", "webm", "mp4"}:
                        ext = "m4a"
                    cookie_header = str(raw_audio.get("cookieHeader") or "").replace("\r", "").replace("\n", "")[:16_384]
                    external_audio_tracks.append(
                        {
                            "url": audio_url,
                            "language": language,
                            "label": label,
                            "ext": ext,
                            "isHls": bool(raw_audio.get("isHls")),
                            "fullSource": bool(raw_audio.get("fullSource")),
                            "cookieHeader": cookie_header,
                        }
                    )
            if isinstance(raw_cookies, list):
                for raw_cookie in raw_cookies[:250]:
                    if not isinstance(raw_cookie, dict):
                        continue
                    youtube_cookies.append(
                        {
                            "domain": str(raw_cookie.get("domain") or "")[:255],
                            "path": str(raw_cookie.get("path") or "/")[:1024],
                            "secure": bool(raw_cookie.get("secure")),
                            "expirationDate": raw_cookie.get("expirationDate") or 0,
                            "name": str(raw_cookie.get("name") or "")[:256],
                            "value": str(raw_cookie.get("value") or "")[:8192],
                        }
                    )
            if len(url) > 16_384 or not is_http_url(url):
                self._send_json(
                    400,
                    {
                        "ok": False,
                        "error": "Yalnızca geçerli http/https adresleri kabul edilir",
                    },
                )
                return
            if page_url and (len(page_url) > 16_384 or not is_http_url(page_url)):
                page_url = ""

            event_queue.put(
                (
                    "bridge_open",
                    {
                        "url": url,
                        "pageUrl": page_url,
                        "title": title,
                        "mediaType": media_type,
                        "captureSources": capture_sources,
                        "userAgent": user_agent,
                        "visitorData": visitor_data,
                        "mediaCookieHeader": media_cookie_header,
                        "manifestText": manifest_text,
                        "primaryLanguage": primary_language,
                        "youtubeCookies": youtube_cookies,
                        "siteCookies": site_cookies,
                        "mediaCookies": media_cookies,
                        "youtubeAuthenticated": youtube_authenticated,
                        "externalSubtitles": external_subtitles,
                        "externalAudioTracks": external_audio_tracks,
                    },
                )
            )
            self._send_json(202, {"ok": True, "message": "Uygulamaya gönderildi"})

    return BridgeHandler


class BridgeServer:
    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self.httpd: ReusableThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> tuple[bool, str]:
        try:
            self.httpd = ReusableThreadingHTTPServer(
                (BRIDGE_HOST, BRIDGE_PORT), bridge_handler_factory(self.event_queue)
            )
        except OSError as exc:
            return False, f"Yerel köprü başlatılamadı: {clean_text(exc)}"

        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="browser-extension-bridge",
            daemon=True,
        )
        self.thread.start()
        return True, f"Tarayıcı köprüsü açık: {BRIDGE_HOST}:{BRIDGE_PORT}"

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


# ---------- yt-dlp logger ----------


class ResilientSubtitleYoutubeDL(YoutubeDL):
    """Inject captured subtitle tracks and make only subtitle failures non-fatal."""

    def __init__(
        self,
        *args: Any,
        external_subtitles: list[dict[str, str]] | None = None,
        external_audio_tracks: list[dict[str, Any]] | None = None,
        primary_language: str = "",
        **kwargs: Any,
    ):
        self._external_subtitles = external_subtitles or []
        self._external_audio_tracks = external_audio_tracks or []
        self._primary_language = primary_language if primary_language in {"tr", "en"} else ""
        super().__init__(*args, **kwargs)

    def process_video_result(self, info_dict: dict[str, Any], download: bool = True):
        formats = info_dict.get("formats") or []
        info_dict["formats"] = formats
        if self._primary_language:
            for item in formats:
                if not isinstance(item, dict) or item.get("language"):
                    continue
                has_video = item.get("vcodec") != "none" and (
                    item.get("height") or item.get("width") or item.get("vcodec") not in (None, "")
                )
                has_audio = item.get("acodec") != "none"
                if has_video and has_audio:
                    item["language"] = self._primary_language
        if self._external_audio_tracks:
            existing_ids = {str(item.get("format_id")) for item in formats if isinstance(item, dict)}
            for index, track in enumerate(self._external_audio_tracks):
                language = clean_text(track.get("language") or f"und-audio{index + 1}", 40)
                format_id = f"extaudio-{index + 1}-{re.sub(r'[^a-zA-Z0-9_-]+', '-', language)}"
                if format_id in existing_ids or not track.get("url"):
                    continue
                source_ext = str(track.get("ext") or "m4a").lower()
                is_hls = bool(track.get("isHls")) or source_ext == "m3u8" or ".m3u8" in str(track.get("url"))
                formats.append(
                    {
                        "format_id": format_id,
                        "url": track.get("url"),
                        "ext": "m4a" if is_hls else source_ext,
                        "protocol": "m3u8_native" if is_hls else (urllib.parse.urlsplit(str(track.get("url"))).scheme or "https"),
                        "vcodec": "none",
                        "acodec": "unknown",
                        "audio_ext": "m4a" if is_hls else source_ext,
                        "video_ext": "none",
                        "language": language,
                        "format_note": f"Harici ses • {track.get('label') or language}",
                        "resolution": "audio only",
                        "source_preference": -5,
                    }
                )
                existing_ids.add(format_id)
        if self._external_subtitles:
            subtitles = info_dict.setdefault("subtitles", {})
            for index, subtitle in enumerate(self._external_subtitles):
                language = clean_text(subtitle.get("language") or f"und-ext{index + 1}", 40)
                subtitle_ext = subtitle.get("ext") or "vtt"
                entry = {
                    "url": subtitle.get("url"),
                    "ext": "vtt" if subtitle_ext == "m3u8" else subtitle_ext,
                    "name": subtitle.get("label") or language,
                }
                if subtitle_ext == "m3u8":
                    entry["protocol"] = "m3u8_native"
                cookie_header = str(subtitle.get("cookieHeader") or "")
                if cookie_header:
                    subtitle_headers = dict(info_dict.get("http_headers") or {})
                    subtitle_headers["Cookie"] = cookie_header
                    entry["http_headers"] = subtitle_headers
                if entry["url"] and not any(
                    item.get("url") == entry["url"] for item in subtitles.get(language, [])
                ):
                    subtitles.setdefault(language, []).append(entry)
        return super().process_video_result(info_dict, download=download)

    def _write_subtitles(self, info_dict: dict[str, Any], filename: str):
        previous = self.params.get("ignoreerrors")
        self.params["ignoreerrors"] = True
        try:
            return super()._write_subtitles(info_dict, filename)
        finally:
            if previous is None:
                self.params.pop("ignoreerrors", None)
            else:
                self.params["ignoreerrors"] = previous


class QueueLogger:
    def __init__(self, event_queue: queue.Queue, prefix: str = ""):
        self.event_queue = event_queue
        self.prefix = clean_text(prefix, 45)
        self.cookie_warning_sent = False

    def _decorate(self, text: str) -> str:
        return f"[{self.prefix}] {text}" if self.prefix else text

    def debug(self, message: str) -> None:
        # yt-dlp routes normal output through debug(). Keep only useful lines.
        text = clean_text(message)
        if text and not text.startswith("[debug]"):
            # Per-chunk/fragment progress is rendered in the manager table.
            # Suppress yt-dlp's byte extrapolation (which can show tens of GB
            # after a completed .part rename failure at fragment 0).
            if text.startswith("[download]") and (" ETA " in text or "% of" in text):
                return
            self.event_queue.put(("log", self._decorate(text)))

    def info(self, message: str) -> None:
        text = clean_text(message)
        if text:
            self.event_queue.put(("log", self._decorate(text)))

    def warning(self, message: str) -> None:
        text = clean_text(message)
        if text and "__APP_PAUSE__" not in text and "__APP_CANCEL__" not in text:
            self.event_queue.put(("log", self._decorate(f"Uyarı: {text}")))

    def error(self, message: str) -> None:
        text = clean_text(message)
        if not text or "__APP_PAUSE__" in text or "__APP_CANCEL__" in text:
            return
        if is_browser_cookie_access_error(RuntimeError(text)):
            if not self.cookie_warning_sent:
                self.cookie_warning_sent = True
                self.event_queue.put(("log", self._decorate(f"Çerez erişim uyarısı: {text}")))
        else:
            self.event_queue.put(("log", self._decorate(f"Hata: {text}")))


# ---------- Main GUI ----------


class VideoDownloaderApp(ctk.CTk):
    COOKIE_LABELS = {
        "Yok": None,
        "Chrome": "chrome",
        "Edge": "edge",
        "Firefox": "firefox",
        "Brave": "brave",
        "Dosya": None,
    }

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1020, 700)

        self.event_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy_kind: str | None = None
        self.current_url = ""
        self.current_context: dict[str, Any] = {}
        self.extension_cookie_text = ""
        self.format_rows: dict[str, dict[str, Any]] = {}
        self.analysis_info: dict[str, Any] | None = None
        self.prepared_analysis_url = ""
        self.bridge = BridgeServer(self.event_queue)
        self.ffmpeg_path = find_ffmpeg()
        self.deno_path = find_deno()
        self.youtube_warning_shown = False
        self.settings = self._load_settings()
        self.jobs: dict[str, DownloadJob] = {}
        self.pending_job_ids: deque[str] = deque()
        self.active_job_ids: set[str] = set()
        self.job_filter = "all"
        self.job_filter_buttons: dict[str, ctk.CTkButton] = {}
        self.job_windows: dict[str, dict[str, Any]] = {}
        self.format_dialog: ctk.CTkToplevel | None = None

        saved_theme = str(self.settings.get("theme", self.settings.get("appearance", "light"))).lower()
        if saved_theme not in {"light", "dark", "system"}:
            saved_theme = "light"
        ctk.set_appearance_mode(saved_theme)
        ctk.set_default_color_theme("blue")
        self.theme_var = ctk.StringVar(value={"light": "Açık", "dark": "Koyu", "system": "Sistem"}[saved_theme])
        self.dnd_available = False
        self.dnd_files_token = None
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            TkinterDnD._require(self)
            self.dnd_files_token = DND_FILES
            self.dnd_available = True
        except Exception:
            pass

        self.url_var = ctk.StringVar(value="")
        self.folder_var = ctk.StringVar(
            value=self.settings.get("download_dir", str(default_download_dir()))
        )
        saved_cookie_mode = self.settings.get("cookie_browser", "Yok")
        if saved_cookie_mode not in self.COOKIE_LABELS:
            saved_cookie_mode = "Yok"
        self.cookie_var = ctk.StringVar(value=saved_cookie_mode)
        self.cookie_file_path = str(self.settings.get("cookie_file", ""))
        self.language_pack_var = ctk.BooleanVar(value=bool(self.settings.get("language_pack", True)))
        self.auto_subs_var = ctk.BooleanVar(value=bool(self.settings.get("auto_subs", True)))
        saved_output_mode = self.settings.get("output_mode", "Ayrı dosyalar (önerilen)")
        if saved_output_mode == "MKV içine göm":
            saved_output_mode = "Otomatik MKV birleştir"
        if saved_output_mode not in {
            "Ayrı dosyalar (önerilen)",
            "Otomatik MKV birleştir",
            "Otomatik MP4 birleştir",
        }:
            saved_output_mode = "Ayrı dosyalar (önerilen)"
        self.output_mode_var = ctk.StringVar(value=saved_output_mode)
        self.output_name_var = ctk.StringVar(value="")
        self.inferred_output_name = ""
        self.mux_video_var = ctk.StringVar(value="")
        self.mux_output_var = ctk.StringVar(value="")
        self.mux_container_var = ctk.StringVar(value="MKV (önerilen, kayıpsız kopya)")
        self.mux_status_var = ctk.StringVar(value="Video, ses ve altyazı dosyalarını ekleyin.")
        self.mux_video_tracks: dict[str, dict[str, str]] = {}
        self.mux_audio_tracks: dict[str, dict[str, str]] = {}
        self.mux_subtitle_tracks: dict[str, dict[str, str]] = {}
        self.quality_var = ctk.StringVar(value="Kalite seçin…")
        self.quality_map: dict[str, str] = {}
        try:
            if int(self.settings.get("concurrency_schema", 0)) < 2:
                max_concurrent = 20
            else:
                max_concurrent = max(1, min(20, int(self.settings.get("max_concurrent", 20))))
        except (TypeError, ValueError):
            max_concurrent = 20
        self.max_concurrent_var = ctk.StringVar(value=str(max_concurrent))
        self.job_summary_var = ctk.StringVar(value="0 indirme")
        self.status_var = ctk.StringVar(value="Hazır")
        self.component_var = ctk.StringVar(value="")
        self.bridge_var = ctk.StringVar(value="Tarayıcı köprüsü başlatılıyor…")

        self._build_ui()
        self._load_job_history()
        self._refresh_component_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_events)
        self.after(150, self._start_bridge)

    # ----- Settings -----

    def _load_settings(self) -> dict[str, Any]:
        path = settings_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        path = settings_file()
        payload = {
            "download_dir": self.folder_var.get().strip(),
            "cookie_browser": self.cookie_var.get(),
            "cookie_file": self.cookie_file_path,
            "language_pack": self.language_pack_var.get(),
            "auto_subs": self.auto_subs_var.get(),
            "output_mode": self.output_mode_var.get(),
            "max_concurrent": int(self.max_concurrent_var.get()),
            "concurrency_schema": 2,
            "theme": {"Açık": "light", "Koyu": "dark", "Sistem": "system"}.get(self.theme_var.get(), "light"),
            "appearance": ctk.get_appearance_mode().lower(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _load_job_history(self) -> None:
        path = job_history_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = []
        if not isinstance(data, list):
            data = []
        for item in data[-500:]:
            if not isinstance(item, dict):
                continue
            try:
                job = DownloadJob.from_history(item)
            except (TypeError, ValueError):
                continue
            self.jobs[job.id] = job
        self._refresh_job_table()

    def _save_job_history(self) -> None:
        path = job_history_file()
        history = [
            job.to_history()
            for job in sorted(self.jobs.values(), key=lambda item: item.created_at)
            if job.status in TERMINAL_JOB_STATUSES or job.history_only
        ][-500:]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ----- UI construction -----

    def _build_menu_bar(self) -> None:
        menu_bar = tk.Menu(self)
        tasks = tk.Menu(menu_bar, tearoff=False)
        tasks.add_command(label="Yeni indirme", command=self._show_new_download)
        tasks.add_command(label="Birleştirici", command=self._show_muxer)
        tasks.add_separator()
        tasks.add_command(label="Başlat / Devam", command=self._resume_selected_jobs)
        tasks.add_command(label="Duraklat", command=self._pause_selected_jobs)
        tasks.add_command(label="İptal", command=self._cancel_selected_jobs)
        tasks.add_separator()
        tasks.add_command(label="Çıkış", command=self._on_close)
        menu_bar.add_cascade(label="Görevler", menu=tasks)

        screens = tk.Menu(menu_bar, tearoff=False)
        screens.add_command(label="İndirmeler", command=lambda: self._switch_main_screen("İndirmeler"))
        screens.add_command(label="Format Seçimi", command=lambda: self._switch_main_screen("Format Seçimi"))
        screens.add_command(label="Birleştirici", command=lambda: self._switch_main_screen("Birleştirici"))
        menu_bar.add_cascade(label="Ekranlar", menu=screens)

        appearance = tk.Menu(menu_bar, tearoff=False)
        appearance.add_command(label="Açık tema", command=lambda: self._apply_theme("Açık"))
        appearance.add_command(label="Koyu tema", command=lambda: self._apply_theme("Koyu"))
        appearance.add_command(label="Sistem teması", command=lambda: self._apply_theme("Sistem"))
        menu_bar.add_cascade(label="Görünüm", menu=appearance)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(
            label="Hakkında",
            command=lambda: messagebox.showinfo(
                "Açık Video İndirici",
                f"Sürüm {APP_VERSION}\nVideo indirme, ayrı iz kuyruğu ve MKV/MP4 birleştirici.",
            ),
        )
        menu_bar.add_cascade(label="Yardım", menu=help_menu)
        self.configure(menu=menu_bar)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build_menu_bar()

        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#f5f7fa", "#10233f"))
        self.header_frame = header
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Açık Video İndirici",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, padx=22, pady=(15, 0), sticky="w")
        ctk.CTkLabel(
            header,
            text="İndirme yöneticisi • Çoklu kuyruk • Duraklat/devam • yt-dlp + FFmpeg • DRM çözmez",
            text_color=("#315477", "#9fc5ef"),
        ).grid(row=1, column=0, padx=22, pady=(2, 15), sticky="w")
        self.theme_menu = ctk.CTkOptionMenu(
            header,
            values=["Açık", "Koyu", "Sistem"],
            variable=self.theme_var,
            command=self._apply_theme,
            width=92,
        )
        self.theme_menu.grid(row=0, column=1, rowspan=2, padx=(8, 4), sticky="e")
        ctk.CTkLabel(header, textvariable=self.component_var).grid(
            row=0, column=2, rowspan=2, padx=(4, 18), sticky="e"
        )

        input_frame = ctk.CTkFrame(self)
        self.input_frame = input_frame
        input_frame.grid(row=1, column=0, padx=18, pady=(7, 5), sticky="ew")
        input_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(input_frame, text="Video / sayfa adresi").grid(
            row=0, column=0, padx=(14, 8), pady=7, sticky="w"
        )
        self.url_entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.url_var,
            placeholder_text="https://ornek.com/video",
            height=32,
        )
        self.url_entry.grid(row=0, column=1, padx=4, pady=7, sticky="ew")
        self.url_entry.bind("<Return>", lambda _event: self._start_analysis())
        ctk.CTkButton(
            input_frame, text="Yapıştır", width=82, command=self._paste_url
        ).grid(row=0, column=2, padx=4, pady=7)
        self.analyze_button = ctk.CTkButton(
            input_frame,
            text="Analiz Et",
            width=105,
            command=self._start_analysis,
        )
        self.analyze_button.grid(row=0, column=3, padx=(4, 14), pady=7)

        options = ctk.CTkFrame(self)
        self.options_frame = options
        options.grid(row=2, column=0, padx=18, pady=0, sticky="ew")
        options.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(options, text="Kayıt klasörü").grid(
            row=0, column=0, padx=(14, 8), pady=6, sticky="w"
        )
        ctk.CTkEntry(options, textvariable=self.folder_var).grid(
            row=0, column=1, padx=4, pady=6, sticky="ew"
        )
        ctk.CTkButton(
            options, text="Seç…", width=72, command=self._choose_folder
        ).grid(row=0, column=2, padx=4, pady=6)
        ctk.CTkButton(
            options, text="Klasörü Aç", width=96, command=self._open_folder
        ).grid(row=0, column=3, padx=4, pady=6)
        ctk.CTkLabel(options, text="Çerez (gerekirse)").grid(
            row=0, column=4, padx=(14, 6), pady=6
        )
        self.cookie_menu = ctk.CTkOptionMenu(
            options,
            values=list(self.COOKIE_LABELS),
            variable=self.cookie_var,
            width=92,
        )
        self.cookie_menu.grid(row=0, column=5, padx=4, pady=6)
        self.cookie_file_button = ctk.CTkButton(
            options,
            text="Dosya…",
            width=70,
            fg_color="#45546b",
            hover_color="#566780",
            command=self._choose_cookie_file,
        )
        self.cookie_file_button.grid(row=0, column=6, padx=(4, 14), pady=6)

        self.language_pack_check = ctk.CTkCheckBox(
            options,
            text="TR/EN ses ve altyazıları indir / paketle",
            variable=self.language_pack_var,
        )
        self.language_pack_check.grid(
            row=1, column=1, columnspan=3, padx=4, pady=(0, 6), sticky="w"
        )
        self.auto_subs_check = ctk.CTkCheckBox(
            options,
            text="Otomatik TR/EN altyazıları da kullan",
            variable=self.auto_subs_var,
        )
        self.auto_subs_check.grid(
            row=1, column=4, columnspan=3, padx=(14, 14), pady=(0, 6), sticky="w"
        )
        ctk.CTkLabel(options, text="Çıktı düzeni").grid(
            row=2, column=0, padx=(14, 8), pady=(0, 6), sticky="w"
        )
        self.output_mode_menu = ctk.CTkOptionMenu(
            options,
            values=[
                "Ayrı dosyalar (önerilen)",
                "Otomatik MKV birleştir",
                "Otomatik MP4 birleştir",
            ],
            variable=self.output_mode_var,
            width=220,
        )
        self.output_mode_menu.grid(row=2, column=1, columnspan=2, padx=4, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            options,
            text="Otomatik mod: video + ayrı ses/altyazı işleri bitince seçilen MKV/MP4 kuyruğa eklenir; yan dosyalar korunur.",
            text_color=("#4d6179", "#9fb4cc"),
        ).grid(row=2, column=3, columnspan=4, padx=(10, 14), pady=(0, 6), sticky="w")
        self.main_tabs = ctk.CTkTabview(self, command=self._on_main_tab_change)
        self.main_tabs.grid(row=3, column=0, padx=18, pady=8, sticky="nsew")
        downloads_tab = self.main_tabs.add("İndirmeler")
        formats_tab = self.main_tabs.add("Format Seçimi")
        mux_tab = self.main_tabs.add("Birleştirici")
        downloads_tab.grid_columnconfigure(0, weight=1)
        downloads_tab.grid_rowconfigure(0, weight=1)
        formats_tab.grid_columnconfigure(0, weight=1)
        formats_tab.grid_rowconfigure(0, weight=1)
        mux_tab.grid_columnconfigure(0, weight=1)
        mux_tab.grid_rowconfigure(0, weight=1)
        self._build_download_manager(downloads_tab)
        self._build_muxer(mux_tab)

        center = ctk.CTkFrame(formats_tab)
        center.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")
        center.grid_columnconfigure(0, weight=1)
        center.grid_rowconfigure(2, weight=1)

        filename_row = ctk.CTkFrame(center)
        filename_row.grid(row=0, column=0, padx=10, pady=(9, 4), sticky="ew")
        filename_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(filename_row, text="Çıktı dosya adı").grid(row=0, column=0, padx=(10, 7), pady=7)
        self.output_name_entry = ctk.CTkEntry(
            filename_row,
            textvariable=self.output_name_var,
            placeholder_text="Analizden sonra düzenleyebilirsiniz",
        )
        self.output_name_entry.grid(row=0, column=1, padx=4, pady=7, sticky="ew")
        self.output_name_reset_button = ctk.CTkButton(
            filename_row, text="Sayfa adını kullan", width=130, command=self._reset_output_name
        )
        self.output_name_reset_button.grid(row=0, column=2, padx=(4, 10), pady=7)

        self.video_title = ctk.CTkLabel(
            center,
            text="Bir adres girip “Analiz Et” düğmesine basın.",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.video_title.grid(row=1, column=0, padx=12, pady=(4, 6), sticky="ew")

        table_wrap = ctk.CTkFrame(center, fg_color="transparent")
        table_wrap.grid(row=2, column=0, padx=10, pady=(0, 8), sticky="nsew")
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Media.Treeview",
            background="#172238",
            fieldbackground="#172238",
            foreground="#e8eef8",
            rowheight=29,
            borderwidth=0,
        )
        style.map(
            "Media.Treeview",
            background=[("selected", "#1f6aa5")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Media.Treeview.Heading",
            background="#263652",
            foreground="#f6f8fb",
            relief="flat",
            padding=6,
        )

        columns = (
            "format",
            "resolution",
            "fps",
            "kind",
            "codec",
            "ext",
            "size",
            "protocol",
        )
        self.format_tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Media.Treeview",
            height=18,
        )
        headings = {
            "format": "Format",
            "resolution": "Çözünürlük",
            "fps": "FPS",
            "kind": "İçerik",
            "codec": "Kodek",
            "ext": "Uzantı",
            "size": "Boyut",
            "protocol": "Aktarım",
        }
        widths = {
            "format": 210,
            "resolution": 110,
            "fps": 55,
            "kind": 135,
            "codec": 145,
            "ext": 65,
            "size": 90,
            "protocol": 105,
        }
        for col in columns:
            self.format_tree.heading(col, text=headings[col])
            self.format_tree.column(
                col,
                width=widths[col],
                minwidth=45,
                stretch=col in {"format", "kind", "codec"},
                anchor="w" if col in {"format", "kind", "codec"} else "center",
            )
        self.format_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(table_wrap, command=self.format_tree.yview)
        scrollbar.grid(row=0, column=1, padx=(5, 0), sticky="ns")
        self.format_tree.configure(yscrollcommand=scrollbar.set)
        self.format_tree.bind("<<TreeviewSelect>>", self._on_tree_selection)

        actions = ctk.CTkFrame(self)
        self.format_actions = actions
        actions.grid(row=4, column=0, padx=18, pady=(0, 8), sticky="ew")
        actions.grid_columnconfigure(6, weight=1)
        self.quality_menu = ctk.CTkOptionMenu(
            actions,
            values=["Kalite seçin…"],
            variable=self.quality_var,
            width=155,
            command=self._on_quality_selected,
        )
        self.quality_menu.grid(row=0, column=0, padx=(12, 5), pady=11)
        self.download_button = ctk.CTkButton(
            actions,
            text="Kuyruğa Ekle",
            width=175,
            state="disabled",
            command=self._start_download,
        )
        self.download_button.grid(row=0, column=1, padx=5, pady=11)
        self.cancel_button = ctk.CTkButton(
            actions,
            text="İptal",
            width=80,
            state="disabled",
            fg_color="#8f3340",
            hover_color="#702632",
            command=self._cancel_current,
        )
        self.cancel_button.grid(row=0, column=2, padx=5, pady=11)
        self.ytdlp_update_button = ctk.CTkButton(
            actions,
            text="yt-dlp Güncelle",
            width=115,
            fg_color="#45546b",
            hover_color="#566780",
            command=self._update_ytdlp,
        )
        self.ytdlp_update_button.grid(row=0, column=3, padx=5, pady=11)
        self.deno_button = ctk.CTkButton(
            actions,
            text="YouTube / Deno",
            width=115,
            fg_color="#45546b",
            hover_color="#566780",
            command=self._install_deno,
        )
        self.deno_button.grid(row=0, column=4, padx=5, pady=11)
        self.ffmpeg_update_button = ctk.CTkButton(
            actions,
            text="FFmpeg Güncelle",
            width=120,
            fg_color="#45546b",
            hover_color="#566780",
            command=self._update_ffmpeg,
        )
        self.ffmpeg_update_button.grid(row=0, column=5, padx=5, pady=11)
        self.progress = ctk.CTkProgressBar(actions, width=110)
        self.progress.set(0)
        self.progress.grid(row=0, column=6, padx=12, pady=11, sticky="ew")

        lower = ctk.CTkFrame(self)
        lower.grid(row=5, column=0, padx=18, pady=(0, 8), sticky="ew")
        lower.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(
            lower, textvariable=self.status_var, anchor="w"
        )
        self.status_label.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="ew")
        self.log_box = ctk.CTkTextbox(lower, height=62, wrap="word")
        self.log_box.grid(row=1, column=0, padx=10, pady=(2, 8), sticky="ew")
        self.log_box.configure(state="disabled")
        ctk.CTkLabel(
            lower,
            textvariable=self.bridge_var,
            text_color=("#3c6382", "#8db7dc"),
            anchor="e",
        ).grid(row=0, column=1, padx=12, pady=(8, 2), sticky="e")

        ctk.CTkLabel(
            self,
            text=(
                "Yalnızca indirme hakkınız olan içerikleri kullanın. Bu araç DRM/Widevine "
                "çözmez ve ücretli erişim kontrollerini aşmak için tasarlanmamıştır."
            ),
            text_color=("#6a4c22", "#e0b56c"),
            wraplength=1050,
        ).grid(row=6, column=0, padx=24, pady=(0, 10), sticky="ew")
        self.main_tabs.set("İndirmeler")
        self._on_main_tab_change()
        self.after(0, lambda: self._apply_theme(self.theme_var.get()))

    def _build_download_manager(self, parent: ctk.CTkFrame) -> None:
        manager = ctk.CTkFrame(parent, fg_color="transparent")
        manager.grid(row=0, column=0, sticky="nsew")
        manager.grid_columnconfigure(0, weight=1)
        manager.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(manager, corner_radius=8)
        toolbar.grid(row=0, column=0, padx=4, pady=(4, 7), sticky="ew")
        ctk.CTkButton(toolbar, text="＋ Yeni", width=82, command=self._show_new_download).pack(
            side="left", padx=(8, 3), pady=8
        )
        ctk.CTkButton(toolbar, text="Birleştirici", width=96, command=self._show_muxer).pack(
            side="left", padx=3, pady=8
        )
        ctk.CTkButton(toolbar, text="▶ Başlat", width=88, command=self._resume_selected_jobs).pack(
            side="left", padx=3, pady=8
        )
        ctk.CTkButton(
            toolbar, text="Ⅱ Duraklat", width=96, command=self._pause_selected_jobs,
            fg_color="#9a6a21", hover_color="#7f5417"
        ).pack(side="left", padx=3, pady=8)
        ctk.CTkButton(
            toolbar, text="■ İptal", width=82, command=self._cancel_selected_jobs,
            fg_color="#8f3340", hover_color="#702632"
        ).pack(side="left", padx=3, pady=8)
        ctk.CTkButton(toolbar, text="✎ Adlandır", width=100, command=self._rename_selected_job).pack(
            side="left", padx=3, pady=8
        )
        ctk.CTkButton(toolbar, text="🗑 Sil", width=72, command=self._delete_selected_jobs).pack(
            side="left", padx=3, pady=8
        )
        ctk.CTkButton(toolbar, text="📁 Klasör", width=90, command=self._open_selected_job_folder).pack(
            side="left", padx=3, pady=8
        )
        ctk.CTkButton(
            toolbar, text="Temizle", width=78, command=self._clear_finished_jobs,
            fg_color="#45546b", hover_color="#566780"
        ).pack(side="left", padx=3, pady=8)
        ctk.CTkLabel(toolbar, text="Aynı anda:").pack(side="left", padx=(14, 4))
        self.concurrent_menu = ctk.CTkOptionMenu(
            toolbar,
            values=[str(value) for value in range(1, 21)],
            variable=self.max_concurrent_var,
            width=62,
            command=self._on_concurrency_changed,
        )
        self.concurrent_menu.pack(side="left", padx=(0, 8), pady=8)

        body = ctk.CTkFrame(manager, fg_color="transparent")
        body.grid(row=1, column=0, padx=4, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkScrollableFrame(
            body, width=190, label_text="KATEGORİLER",
            label_font=ctk.CTkFont(size=12, weight="bold"),
        )
        sidebar.grid(row=0, column=0, padx=(0, 7), sticky="nsew")
        filters = [
            ("all", "Tüm İndirmeler"),
            ("video", "Video"),
            ("audio", "Ses"),
            ("subtitle", "Altyazı"),
            ("mux", "Birleştirme"),
            ("active", "İndiriliyor"),
            ("queued", "Kuyrukta"),
            ("paused", "Duraklatılan"),
            ("completed", "Tamamlanan"),
            ("problem", "Hata / İptal"),
        ]
        for key, label in filters:
            button = ctk.CTkButton(
                sidebar,
                text=label,
                width=154,
                height=30,
                anchor="w",
                fg_color="#1f6aa5" if key == "all" else "transparent",
                hover_color="#294866",
                command=lambda value=key: self._set_job_filter(value),
            )
            button.pack(padx=10, pady=2)
            self.job_filter_buttons[key] = button

        table_frame = ctk.CTkFrame(body)
        table_frame.grid(row=0, column=1, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Jobs.Treeview",
            background="#172238",
            fieldbackground="#172238",
            foreground="#e8eef8",
            rowheight=30,
            borderwidth=0,
        )
        style.map(
            "Jobs.Treeview",
            background=[("selected", "#1f6aa5")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Jobs.Treeview.Heading",
            background="#263652",
            foreground="#f6f8fb",
            relief="flat",
            padding=7,
        )
        columns = ("name", "type", "size", "status", "progress", "speed", "eta", "quality", "added")
        self.job_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            style="Jobs.Treeview",
        )
        headings = {
            "name": "Dosya adı",
            "type": "Tür",
            "size": "Boyut",
            "status": "Durum",
            "progress": "İlerleme",
            "speed": "Hız",
            "eta": "Kalan",
            "quality": "Kalite",
            "added": "Eklendi",
        }
        widths = {"name": 330, "type": 85, "size": 90, "status": 110, "progress": 80, "speed": 95, "eta": 70, "quality": 90, "added": 75}
        for column in columns:
            self.job_tree.heading(column, text=headings[column])
            self.job_tree.column(
                column,
                width=widths[column],
                minwidth=55,
                stretch=column == "name",
                anchor="w" if column == "name" else "center",
            )
        self.job_tree.grid(row=0, column=0, sticky="nsew")
        job_scroll = ctk.CTkScrollbar(table_frame, command=self.job_tree.yview)
        job_scroll.grid(row=0, column=1, padx=(4, 0), sticky="ns")
        self.job_tree.configure(yscrollcommand=job_scroll.set)
        self.job_tree.bind("<Double-1>", self._on_job_double_click)
        self.job_tree.tag_configure("completed", foreground="#73d6a8")
        self.job_tree.tag_configure("failed", foreground="#ff8795")
        self.job_tree.tag_configure("cancelled", foreground="#d99aa3")
        self.job_tree.tag_configure("paused", foreground="#f2c46d")
        self.job_tree.tag_configure("pausing", foreground="#f2c46d")
        self.job_tree.tag_configure("cancelling", foreground="#d99aa3")
        self.job_tree.tag_configure("downloading", foreground="#82c3ff")
        self.job_tree.tag_configure("processing", foreground="#b69bff")
        self.job_tree.tag_configure("finalizing", foreground="#9cd7ff")
        self.job_tree.tag_configure("queued", foreground="#b9c5d6")
        self.job_tree.tag_configure("interrupted", foreground="#e1a56d")

        footer = ctk.CTkFrame(manager)
        footer.grid(row=2, column=0, padx=4, pady=(7, 4), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(footer, textvariable=self.job_summary_var, anchor="w").grid(
            row=0, column=0, padx=10, pady=7, sticky="w"
        )
        self.aggregate_progress = ctk.CTkProgressBar(footer)
        self.aggregate_progress.set(0)
        self.aggregate_progress.grid(row=0, column=1, padx=10, pady=7, sticky="ew")

    def _build_muxer(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        drop_text = (
            "Video, ses ve altyazı dosyalarını buraya sürükleyin"
            if self.dnd_available else
            "Sürükle-bırak kullanılamıyor; Ekle düğmelerini kullanın"
        )
        self.mux_drop_zone = ctk.CTkLabel(
            frame, text=drop_text, height=50, corner_radius=8,
            fg_color=("#e8f1fb", "#193554"), font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.mux_drop_zone.grid(row=0, column=0, padx=6, pady=(6, 8), sticky="ew")
        if self.dnd_available:
            try:
                self.mux_drop_zone.drop_target_register(self.dnd_files_token)
                self.mux_drop_zone.dnd_bind("<<Drop>>", self._on_mux_drop)
            except Exception:
                self.dnd_available = False

        list_box = ctk.CTkFrame(frame)
        list_box.grid(row=1, column=0, padx=6, pady=0, sticky="nsew")
        list_box.grid_columnconfigure(0, weight=1)
        list_box.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            list_box,
            text="BİRLEŞTİRME SIRASI — ANA VİDEO, SESLER VE ALTYAZILAR",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(9, 5), sticky="w")
        self.mux_track_tree = ttk.Treeview(
            list_box,
            columns=("order", "type", "role", "name", "language", "label", "path"),
            show="headings", selectmode="extended", style="Mux.Treeview", height=15,
        )
        columns = (
            ("order", "Sıra", 48, False), ("type", "Tür", 82, False),
            ("role", "Rol", 62, False), ("name", "Dosya", 260, True),
            ("language", "Dil", 55, False), ("label", "Etiket", 150, True),
            ("path", "Konum", 380, True),
        )
        for col, text, width, stretch in columns:
            self.mux_track_tree.heading(col, text=text)
            self.mux_track_tree.column(col, width=width, minwidth=45, stretch=stretch)
        self.mux_track_tree.grid(row=1, column=0, padx=8, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(list_box, command=self.mux_track_tree.yview)
        scrollbar.grid(row=1, column=1, padx=(3, 7), sticky="ns")
        self.mux_track_tree.configure(yscrollcommand=scrollbar.set)

        buttons = ctk.CTkFrame(list_box, fg_color="transparent")
        buttons.grid(row=2, column=0, columnspan=2, padx=6, pady=8, sticky="ew")
        ctk.CTkButton(buttons, text="Video Ekle…", width=95, command=self._choose_mux_video).pack(side="left", padx=2)
        ctk.CTkButton(buttons, text="Ses Ekle…", width=90, command=self._add_mux_audio_files).pack(side="left", padx=2)
        ctk.CTkButton(buttons, text="Altyazı Ekle…", width=105, command=self._add_mux_subtitle_files).pack(side="left", padx=2)
        ctk.CTkButton(buttons, text="Ana Video Yap", width=105, command=self._set_main_mux_video).pack(side="left", padx=(12, 2))
        ctk.CTkButton(buttons, text="Dil / Etiket", width=95, command=self._edit_selected_mux_track).pack(side="left", padx=2)
        ctk.CTkButton(buttons, text="Seçilenleri Çıkar", width=115, command=self._remove_selected_mux_tracks, fg_color="#8f3340").pack(side="left", padx=2)

        options = ctk.CTkFrame(frame)
        options.grid(row=2, column=0, padx=6, pady=(8, 6), sticky="ew")
        options.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(options, text="Çıktı container").grid(row=0, column=0, padx=(10, 5), pady=9)
        self.mux_container_menu = ctk.CTkOptionMenu(
            options,
            values=["MKV (önerilen, kayıpsız kopya)", "MP4 (ses AAC, altyazı mov_text)"],
            variable=self.mux_container_var, width=235, command=self._on_mux_container_changed,
        )
        self.mux_container_menu.grid(row=0, column=1, padx=4, pady=9)
        ctk.CTkLabel(options, text="Çıktı").grid(row=0, column=2, padx=(10, 5), pady=9)
        ctk.CTkEntry(options, textvariable=self.mux_output_var).grid(row=0, column=3, padx=4, pady=9, sticky="ew")
        ctk.CTkButton(options, text="Kaydet…", width=80, command=self._choose_mux_output).grid(row=0, column=4, padx=4, pady=9)
        ctk.CTkButton(
            options, text="Birleştirmeyi Kuyruğa Ekle", width=190,
            command=self._enqueue_mux_job, fg_color="#2386df",
        ).grid(row=0, column=5, padx=(4, 10), pady=9)
        ctk.CTkLabel(frame, textvariable=self.mux_status_var, anchor="w").grid(
            row=3, column=0, padx=12, pady=(0, 6), sticky="ew"
        )

    # ----- UI actions -----

    @staticmethod
    def _infer_track_language_from_name(path: str) -> str:
        name = Path(path).stem.lower()
        if re.search(r"(?:^|[._ -])(?:tr|tur|turkce|türkçe|dublaj)(?:$|[._ -])", name):
            return "tr"
        if re.search(r"(?:^|[._ -])(?:en|eng|english|original|orijinal)(?:$|[._ -])", name):
            return "en"
        return "und"

    def _default_mux_output(self) -> None:
        video = Path(self.mux_video_var.get()) if self.mux_video_var.get() else None
        if not video:
            return
        ext = ".mp4" if self.mux_container_var.get().startswith("MP4") else ".mkv"
        self.mux_output_var.set(str(video.with_name(f"{video.stem} - birlestirilmis{ext}")))

    def _choose_mux_video(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Video dosyalarını seçin",
            filetypes=[("Video", "*.mp4 *.mkv *.webm *.mov *.avi *.ts *.m2ts"), ("Tüm dosyalar", "*.*")],
        )
        self._add_mux_video_files(list(paths))

    def _add_mux_video_files(self, paths: list[str]) -> None:
        for raw_path in paths:
            path = str(Path(raw_path))
            if not Path(path).is_file() or any(item["path"] == path for item in self.mux_video_tracks.values()):
                continue
            iid = uuid.uuid4().hex
            self.mux_video_tracks[iid] = {"path": path}
            if not self.mux_video_var.get():
                self.mux_video_var.set(path)
        self._default_mux_output()
        self._refresh_mux_tracks()

    def _set_main_mux_video(self) -> None:
        selected = self.mux_track_tree.selection()
        if len(selected) != 1 or not selected[0].startswith("v:"):
            messagebox.showinfo("Tek video seçin", "Ana video yapmak için birleşik listeden tek bir Video satırı seçin.")
            return
        track_id = selected[0].split(":", 1)[1]
        self.mux_video_var.set(self.mux_video_tracks[track_id]["path"])
        self._default_mux_output()
        self._refresh_mux_tracks()

    def _add_mux_files(self, paths: list[str], kind: str) -> None:
        target = self.mux_audio_tracks if kind == "audio" else self.mux_subtitle_tracks
        for raw_path in paths:
            path = str(Path(raw_path))
            if not Path(path).is_file() or any(item["path"] == path for item in target.values()):
                continue
            language = self._infer_track_language_from_name(path)
            target[uuid.uuid4().hex] = {
                "path": path,
                "language": language,
                "label": Path(path).stem,
            }
        self._refresh_mux_tracks()

    def _add_mux_audio_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Ses dosyalarını seçin",
            filetypes=[("Ses", "*.mka *.m4a *.mp3 *.aac *.opus *.ogg *.wav *.flac *.ac3 *.eac3"), ("Tüm dosyalar", "*.*")],
        )
        self._add_mux_files(list(paths), "audio")

    def _add_mux_subtitle_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Altyazı dosyalarını seçin",
            filetypes=[("Altyazı", "*.srt *.vtt *.ass *.ssa *.ttml"), ("Tüm dosyalar", "*.*")],
        )
        self._add_mux_files(list(paths), "subtitle")

    def _on_mux_drop(self, event: Any) -> None:
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            return
        video_exts = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m2ts"}
        audio_exts = {".mka", ".m4a", ".mp3", ".aac", ".opus", ".ogg", ".wav", ".flac", ".ac3", ".eac3"}
        subtitle_exts = {".srt", ".vtt", ".ass", ".ssa", ".ttml"}
        videos: list[str] = []
        audio: list[str] = []
        subtitles: list[str] = []
        for path in paths:
            ext = Path(path).suffix.lower()
            if ext in video_exts:
                videos.append(path)
            elif ext in audio_exts:
                audio.append(path)
            elif ext in subtitle_exts:
                subtitles.append(path)
        self._add_mux_video_files(videos)
        self._add_mux_files(audio, "audio")
        self._add_mux_files(subtitles, "subtitle")

    def _refresh_mux_tracks(self) -> None:
        if not hasattr(self, "mux_track_tree"):
            return
        self.mux_track_tree.delete(*self.mux_track_tree.get_children())
        order = 1
        main_path = self.mux_video_var.get()
        videos = list(self.mux_video_tracks.items())
        videos.sort(key=lambda item: item[1]["path"] != main_path)
        for iid, track in videos:
            role = "Ana" if track["path"] == main_path else "Ek"
            self.mux_track_tree.insert(
                "", "end", iid=f"v:{iid}",
                values=(order, "Video", role, Path(track["path"]).name, "—", "Ana video" if role == "Ana" else "Ek video", track["path"]),
            )
            order += 1
        for iid, track in self.mux_audio_tracks.items():
            self.mux_track_tree.insert(
                "", "end", iid=f"a:{iid}",
                values=(order, "Ses", "İz", Path(track["path"]).name, track["language"], track["label"], track["path"]),
            )
            order += 1
        for iid, track in self.mux_subtitle_tracks.items():
            self.mux_track_tree.insert(
                "", "end", iid=f"s:{iid}",
                values=(order, "Altyazı", "İz", Path(track["path"]).name, track["language"], track["label"], track["path"]),
            )
            order += 1

    def _edit_selected_mux_track(self) -> None:
        selected = self.mux_track_tree.selection()
        if len(selected) != 1 or selected[0][0] not in {"a", "s"}:
            messagebox.showinfo("Tek iz seçin", "Dil/etiket düzenlemek için tek bir Ses veya Altyazı satırı seçin.")
            return
        prefix, track_id = selected[0].split(":", 1)
        tracks = self.mux_audio_tracks if prefix == "a" else self.mux_subtitle_tracks
        track = tracks[track_id]
        language = simpledialog.askstring("Dil kodu", "Dil (tr, en, und):", initialvalue=track["language"])
        if language is None:
            return
        label = simpledialog.askstring("İz etiketi", "Oynatıcıda görünecek etiket:", initialvalue=track["label"])
        if label is None:
            return
        track["language"] = self._canonical_language(language) or "und"
        track["label"] = clean_text(label, 100) or Path(track["path"]).stem
        self._refresh_mux_tracks()

    def _remove_selected_mux_tracks(self) -> None:
        removed_main = False
        for row_id in self.mux_track_tree.selection():
            prefix, track_id = row_id.split(":", 1)
            if prefix == "v":
                track = self.mux_video_tracks.pop(track_id, None)
                if track and track.get("path") == self.mux_video_var.get():
                    removed_main = True
            elif prefix == "a":
                self.mux_audio_tracks.pop(track_id, None)
            elif prefix == "s":
                self.mux_subtitle_tracks.pop(track_id, None)
        if removed_main:
            next_video = next(iter(self.mux_video_tracks.values()), {}).get("path", "")
            self.mux_video_var.set(next_video)
            self._default_mux_output()
        self._refresh_mux_tracks()

    def _on_mux_container_changed(self, _value: str) -> None:
        self._default_mux_output()
        if self.mux_container_var.get().startswith("MP4"):
            self.mux_status_var.set("MP4: video kopyalanır; tüm sesler AAC, altyazılar mov_text olarak dönüştürülür.")
        else:
            self.mux_status_var.set("MKV: video/ses/altyazı mümkün olduğunca yeniden kodlanmadan kopyalanır.")

    def _choose_mux_output(self) -> None:
        ext = ".mp4" if self.mux_container_var.get().startswith("MP4") else ".mkv"
        path = filedialog.asksaveasfilename(
            title="Birleştirilmiş dosyayı kaydet",
            defaultextension=ext,
            filetypes=[(ext.upper().lstrip("."), f"*{ext}")],
            initialfile=Path(self.mux_output_var.get()).name if self.mux_output_var.get() else f"birlestirilmis{ext}",
        )
        if path:
            self.mux_output_var.set(path)

    def _enqueue_mux_job(self) -> None:
        video = Path(self.mux_video_var.get())
        output = Path(self.mux_output_var.get()) if self.mux_output_var.get() else None
        if not video.is_file():
            messagebox.showwarning("Ana video eksik", "Önce geçerli bir ana video seçin.")
            return
        if not self.mux_audio_tracks and not self.mux_subtitle_tracks:
            messagebox.showwarning("İz ekleyin", "En az bir ses veya altyazı izi ekleyin.")
            return
        if not output:
            self._default_mux_output()
            output = Path(self.mux_output_var.get())
        container = "mp4" if self.mux_container_var.get().startswith("MP4") else "mkv"
        if output.suffix.lower() != f".{container}":
            output = output.with_suffix(f".{container}")
            self.mux_output_var.set(str(output))
        job = DownloadJob(
            id=uuid.uuid4().hex,
            url=str(video),
            title=f"{video.stem} — {container.upper()} birleştirme",
            quality=f"Birleştir • {container.upper()}",
            format_label="Manuel ses/altyazı",
            output_dir=str(output.parent),
            job_type="mux",
            mux_video_path=str(video),
            mux_audio_tracks=[dict(track) for track in self.mux_audio_tracks.values()],
            mux_subtitle_tracks=[dict(track) for track in self.mux_subtitle_tracks.values()],
            mux_output_path=str(output),
            mux_container=container,
        )
        self.jobs[job.id] = job
        self.pending_job_ids.append(job.id)
        self.main_tabs.set("İndirmeler")
        self._on_main_tab_change()
        self._append_log(f"Birleştirme kuyruğa eklendi: {video.name} → {output.name}")
        self._refresh_job_table()
        self._pump_download_queue()

    def _switch_main_screen(self, name: str) -> None:
        if hasattr(self, "main_tabs"):
            self.main_tabs.set(name)
            self._on_main_tab_change()

    def _apply_theme(self, value: str) -> None:
        mode = {"Açık": "light", "Koyu": "dark", "Sistem": "system"}.get(value, "light")
        self.theme_var.set(value)
        ctk.set_appearance_mode(mode)
        effective_dark = ctk.get_appearance_mode().lower() == "dark"
        style = ttk.Style()
        background = "#172238" if effective_dark else "#ffffff"
        foreground = "#e8eef8" if effective_dark else "#202124"
        heading_bg = "#263652" if effective_dark else "#e9eef5"
        heading_fg = "#f6f8fb" if effective_dark else "#202124"
        selected_bg = "#1f6aa5" if effective_dark else "#c9e2ff"
        selected_fg = "#ffffff" if effective_dark else "#10233f"
        for name in ("Jobs.Treeview", "Media.Treeview", "Mux.Treeview"):
            style.configure(
                name,
                background=background,
                fieldbackground=background,
                foreground=foreground,
                rowheight=30,
                borderwidth=0,
            )
            style.map(name, background=[("selected", selected_bg)], foreground=[("selected", selected_fg)])
            style.configure(f"{name}.Heading", background=heading_bg, foreground=heading_fg, relief="flat", padding=7)
        self._save_settings()

    def _on_main_tab_change(self) -> None:
        if not hasattr(self, "format_actions"):
            return
        show_format = self.main_tabs.get() == "Format Seçimi"
        if show_format:
            self.input_frame.grid()
            self.options_frame.grid()
            self.format_actions.grid()
        else:
            self.input_frame.grid_remove()
            self.options_frame.grid_remove()
            self.format_actions.grid_remove()

    def _show_new_download(self) -> None:
        self.main_tabs.set("Format Seçimi")
        self._on_main_tab_change()
        self.url_entry.focus_set()

    def _show_muxer(self) -> None:
        self.main_tabs.set("Birleştirici")
        self._on_main_tab_change()

    def _set_job_filter(self, value: str) -> None:
        self.job_filter = value
        for key, button in self.job_filter_buttons.items():
            button.configure(fg_color="#1f6aa5" if key == value else "transparent")
        self._refresh_job_table()

    def _job_visible(self, job: DownloadJob) -> bool:
        if self.job_filter == "all":
            return True
        if self.job_filter in {"video", "audio", "subtitle", "mux"}:
            return job.job_type == self.job_filter
        if self.job_filter == "active":
            return job.status in {"downloading", "processing", "finalizing", "pausing", "cancelling"}
        if self.job_filter == "problem":
            return job.status in {"failed", "cancelled", "interrupted"}
        return job.status == self.job_filter

    @staticmethod
    def _format_eta(seconds: int | None) -> str:
        if seconds is None or seconds < 0:
            return "—"
        minutes, secs = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _job_values(self, job: DownloadJob) -> tuple[str, ...]:
        size_value = job.total_bytes or job.downloaded_bytes
        progress = f"{max(0, min(100, job.progress * 100)):.1f}%"
        added = datetime.fromtimestamp(job.created_at).strftime("%H:%M")
        type_label = {"video": "Video", "audio": "Ses", "subtitle": "Altyazı", "mux": "Birleştirme"}.get(job.job_type, job.job_type)
        return (
            job.title,
            type_label,
            human_bytes(size_value),
            JOB_STATUS_LABELS.get(job.status, job.status),
            progress,
            human_speed(job.speed) if job.status == "downloading" else "—",
            self._format_eta(job.eta) if job.status == "downloading" else "—",
            job.quality,
            added,
        )

    def _refresh_job_table(self) -> None:
        if not hasattr(self, "job_tree"):
            return
        selected = set(self.job_tree.selection())
        existing = set(self.job_tree.get_children())
        visible_jobs = [
            job for job in sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)
            if self._job_visible(job)
        ]
        visible_ids = {job.id for job in visible_jobs}
        for iid in existing - visible_ids:
            self.job_tree.delete(iid)
        for job in visible_jobs:
            values = self._job_values(job)
            if self.job_tree.exists(job.id):
                self.job_tree.item(job.id, values=values, tags=(job.status,))
            else:
                self.job_tree.insert("", "end", iid=job.id, values=values, tags=(job.status,))
        keep_selected = [iid for iid in selected if iid in visible_ids]
        if keep_selected:
            self.job_tree.selection_set(keep_selected)

        counts = {
            "all": len(self.jobs),
            "video": sum(job.job_type == "video" for job in self.jobs.values()),
            "audio": sum(job.job_type == "audio" for job in self.jobs.values()),
            "subtitle": sum(job.job_type == "subtitle" for job in self.jobs.values()),
            "mux": sum(job.job_type == "mux" for job in self.jobs.values()),
            "active": sum(job.status in {"downloading", "processing", "finalizing", "pausing", "cancelling"} for job in self.jobs.values()),
            "queued": sum(job.status == "queued" for job in self.jobs.values()),
            "paused": sum(job.status == "paused" for job in self.jobs.values()),
            "completed": sum(job.status == "completed" for job in self.jobs.values()),
            "problem": sum(job.status in {"failed", "cancelled", "interrupted"} for job in self.jobs.values()),
        }
        labels = {
            "all": "Tüm İndirmeler", "video": "Video", "audio": "Ses",
            "subtitle": "Altyazı", "mux": "Birleştirme",
            "active": "İndiriliyor", "queued": "Kuyrukta", "paused": "Duraklatılan",
            "completed": "Tamamlanan", "problem": "Hata / İptal",
        }
        for key, button in self.job_filter_buttons.items():
            button.configure(text=f"{labels[key]}  ({counts[key]})")
        active = [
            job for job in self.jobs.values()
            if job.status in {"downloading", "processing", "finalizing", "pausing", "cancelling"}
        ]
        queued = counts["queued"]
        self.job_summary_var.set(
            f"{counts['all']} kayıt • {len(active)} etkin • {queued} kuyrukta • {counts['completed']} tamamlandı"
        )
        if active:
            known = [job.progress for job in active if job.progress > 0]
            self.aggregate_progress.set(sum(known) / len(known) if known else 0)
        else:
            self.aggregate_progress.set(0)
        for job in self.jobs.values():
            self._update_job_progress_window(job)

    def _reset_output_name(self) -> None:
        self.output_name_var.set(self.inferred_output_name)
        self.output_name_entry.focus_set()
        self.output_name_entry.icursor("end")

    def _on_quality_selected(self, choice: str) -> None: 
        iid = self.quality_map.get(choice)
        if not iid or iid not in self.format_rows:
            self.format_tree.selection_remove(*self.format_tree.selection())
            self.download_button.configure(state="disabled")
            return
        self.format_tree.selection_set(iid)
        self.format_tree.focus(iid)
        self.format_tree.see(iid)
        if not self.busy_kind:
            self.download_button.configure(state="normal")
        row = self.format_rows[iid]
        self.status_var.set(
            f"Seçilen kalite: {choice} • {row.get('kind', 'video')} • {row.get('codec', '')}"
        )

    def _on_tree_selection(self, _event: Any = None) -> None:
        selection = self.format_tree.selection()
        if not selection or selection[0] not in self.format_rows:
            if not self.busy_kind:
                self.download_button.configure(state="disabled")
            return
        iid = selection[0]
        choice = next((label for label, mapped in self.quality_map.items() if mapped == iid), None)
        row = self.format_rows[iid]
        if not choice:
            choice = f"Özel: {row.get('resolution', 'format')} • {row.get('label', '')[:35]}"
        self.quality_var.set(choice)
        if not self.busy_kind:
            self.download_button.configure(state="normal")

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:
            self.status_var.set("Panoda metin bulunamadı.")
            return
        self.url_var.set(text)
        self.current_context = {}

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="İndirme klasörünü seçin", initialdir=self.folder_var.get()
        )
        if selected:
            self.folder_var.set(selected)

    def _choose_cookie_file(self) -> None:
        initial = str(Path(self.cookie_file_path).parent) if self.cookie_file_path else str(Path.home())
        selected = filedialog.askopenfilename(
            title="Netscape biçimindeki cookies.txt dosyasını seçin",
            initialdir=initial,
            filetypes=[("Cookie metin dosyası", "*.txt"), ("Tüm dosyalar", "*.*")],
        )
        if selected:
            self.cookie_file_path = selected
            self.cookie_var.set("Dosya")
            self.status_var.set(f"Çerez dosyası seçildi: {Path(selected).name}")
            self._append_log("Yerel cookies.txt seçildi. Bu dosyayı kimseyle paylaşmayın.")

    def _cookie_selection_valid(self) -> bool:
        if self.cookie_var.get() != "Dosya":
            return True
        path = Path(self.cookie_file_path)
        if path.is_file():
            return True
        messagebox.showwarning(
            "Çerez dosyası bulunamadı",
            "Çerez modu 'Dosya' seçili ancak geçerli bir cookies.txt bulunamadı. "
            "Dosya… düğmesiyle seçin veya çerez seçeneğini 'Yok' yapın.",
        )
        return False

    def _open_folder(self) -> None:
        path = Path(self.folder_var.get().strip() or default_download_dir())
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.resolve().as_uri())
        except OSError as exc:
            messagebox.showerror("Klasör açılamadı", clean_text(exc))

    def _selected_jobs(self) -> list[DownloadJob]:
        return [self.jobs[iid] for iid in self.job_tree.selection() if iid in self.jobs]

    def _on_concurrency_changed(self, _value: str) -> None:
        self._save_settings()
        self._pump_download_queue()
        self._refresh_job_table()

    def _resume_selected_jobs(self) -> None:
        selected = self._selected_jobs()
        if not selected:
            messagebox.showinfo("İndirme seçin", "Listeden başlatılacak veya devam ettirilecek bir kayıt seçin.")
            return
        needs_reanalysis: DownloadJob | None = None
        for job in selected:
            if job.status == "queued":
                continue
            if job.status not in {"paused", "cancelled", "failed", "interrupted"}:
                continue
            if job.status == "failed" and job.job_type == "video":
                recovered = self._recover_completed_part(job, job.error, emit_events=False)
                if recovered:
                    job.filepath = recovered
                    job.status = "completed"
                    job.progress = 1.0
                    job.error = ""
                    job.finished_at = time.time()
                    if job.output_mode in {"sidecar", "auto_mkv", "auto_mp4"}:
                        if job.external_audio_tracks:
                            self._spawn_audio_child_jobs(job.id, recovered, list(job.external_audio_tracks))
                        if job.external_subtitle_tracks:
                            self._spawn_subtitle_child_jobs(job.id, recovered, list(job.external_subtitle_tracks))
                    self._save_job_history()
                    continue
            if not job.ydl_opts:
                if job.job_type == "mux" and Path(job.mux_video_path).is_file():
                    job.ydl_opts = {"_mux_resume": True}
                    job.history_only = False
                else:
                    resume_media = job.parent_filepath if job.job_type in {"audio", "subtitle"} else job.filepath
                    resume_tracks = (
                        job.external_audio_tracks if job.job_type == "audio"
                        else job.external_subtitle_tracks if job.job_type == "subtitle"
                        else job.external_audio_tracks
                    )
                    if (
                        job.output_mode == "sidecar"
                        and resume_media
                        and Path(resume_media).is_file()
                        and resume_tracks
                    ):
                        job.ydl_opts = {"http_headers": dict(job.resume_headers)}
                        job.sidecar_only = True
                        job.history_only = False
                    else:
                        needs_reanalysis = needs_reanalysis or job
                        continue
            job.pause_event.clear()
            job.cancel_event.clear()
            job.error = ""
            job.status = "queued"
            job.finished_at = None
            if job.id not in self.pending_job_ids:
                self.pending_job_ids.append(job.id)
        if needs_reanalysis:
            self.url_var.set(needs_reanalysis.url)
            self._show_new_download()
            self.status_var.set("Geçmiş kayıt yeniden analiz edilmeli; URL kutuya yerleştirildi.")
        self._refresh_job_table()
        self._pump_download_queue()

    def _pause_selected_jobs(self) -> None:
        selected = self._selected_jobs()
        if not selected:
            messagebox.showinfo("İndirme seçin", "Duraklatılacak indirmeyi seçin.")
            return
        processing = False
        for job in selected:
            if job.status == "queued":
                job.status = "paused"
                job.pause_event.set()
            elif job.status == "downloading":
                job.pause_event.set()
                job.status = "pausing"
            elif job.status in {"processing", "finalizing"}:
                if job.job_type == "mux" and job.status == "processing":
                    job.cancel_event.set()
                    job.status = "cancelling"
                else:
                    processing = True
        if processing:
            messagebox.showinfo(
                "Birleştirme sürüyor",
                "FFmpeg birleştirme/altyazı gömme aşaması güvenli biçimde duraklatılamaz. İşlemin bitmesini bekleyin.",
            )
        self._refresh_job_table()

    def _cancel_selected_jobs(self) -> None:
        selected = self._selected_jobs()
        if not selected:
            messagebox.showinfo("İndirme seçin", "İptal edilecek indirmeyi seçin.")
            return
        processing = False
        for job in selected:
            if job.status in {"queued", "paused"}:
                job.cancel_event.set()
                job.pause_event.clear()
                job.status = "cancelled"
                job.finished_at = time.time()
            elif job.status in {"downloading", "pausing"}:
                job.cancel_event.set()
                job.pause_event.clear()
                job.status = "cancelling"
            elif job.status in {"processing", "finalizing"}:
                processing = True
        if processing:
            messagebox.showinfo(
                "Birleştirme sürüyor",
                "FFmpeg dosyayı işlerken zorla iptal veri kaybına yol açabilir. İşlemin bitmesini bekleyin.",
            )
        self._save_job_history()
        self._refresh_job_table()
        self._pump_download_queue()

    def _rename_selected_job(self) -> None:
        selected = self._selected_jobs()
        if len(selected) != 1:
            messagebox.showinfo("Tek kayıt seçin", "Yeniden adlandırmak için yalnız bir kayıt seçin.")
            return
        job = selected[0]
        if job.status in {"downloading", "processing", "paused"}:
            messagebox.showinfo("Şu anda değiştirilemez", "Etkin veya duraklatılmış kısmi dosya yeniden adlandırılamaz.")
            return
        new_name = simpledialog.askstring("Dosya adını düzenle", "Yeni dosya adı:", initialvalue=Path(job.title).stem)
        if not new_name:
            return
        safe_name = safe_source_filename(new_name)
        if job.filepath and Path(job.filepath).is_file():
            old_path = Path(job.filepath)
            target = old_path.with_name(f"{safe_name}{old_path.suffix}")
            if target.exists() and target != old_path:
                messagebox.showerror("Dosya var", f"Bu adda bir dosya zaten var:\n{target}")
                return
            try:
                old_path.rename(target)
            except OSError as exc:
                messagebox.showerror("Yeniden adlandırılamadı", clean_text(exc))
                return
            job.related_files.discard(str(old_path))
            job.related_files.add(str(target))
            job.filepath = str(target)
        elif job.status == "queued" and job.ydl_opts:
            template = f"{safe_name.replace('%', '%%')} [%(id)s].%(ext)s"
            job.ydl_opts["outtmpl"] = {"default": template}
        job.title = safe_name
        self._save_job_history()
        self._refresh_job_table()

    def _delete_selected_jobs(self) -> None:
        selected = self._selected_jobs()
        if not selected:
            messagebox.showinfo("Kayıt seçin", "Silinecek tamamlanmış veya iptal edilmiş kayıtları seçin.")
            return
        if any(job.status not in TERMINAL_JOB_STATUSES for job in selected):
            messagebox.showwarning("Önce durdurun", "Yalnız tamamlanmış, iptal edilmiş veya hatalı kayıtlar silinebilir.")
            return
        answer = messagebox.askyesnocancel(
            "Kayıtları sil",
            "Evet: Listedeki kayıtları ve ilişkili dosyaları diskten sil.\n"
            "Hayır: Yalnız listeden kaldır.\n"
            "İptal: İşlem yapma.",
        )
        if answer is None:
            return
        if answer:
            for job in selected:
                root = Path(job.output_dir).resolve()
                candidates = set(job.related_files)
                if job.filepath:
                    candidates.add(job.filepath)
                for raw_path in candidates:
                    try:
                        path = Path(raw_path).resolve()
                        if path.is_relative_to(root) and path.is_file():
                            path.unlink()
                    except (OSError, ValueError):
                        continue
        for job in selected:
            self.jobs.pop(job.id, None)
        self._save_job_history()
        self._refresh_job_table()

    def _clear_finished_jobs(self) -> None:
        removable = [
            job_id for job_id, job in self.jobs.items()
            if job.status in TERMINAL_JOB_STATUSES
        ]
        if not removable:
            return
        if not messagebox.askyesno(
            "Listeyi temizle", "Tamamlanmış, iptal edilmiş ve hatalı kayıtlar yalnız listeden kaldırılsın mı?"
        ):
            return
        for job_id in removable:
            self.jobs.pop(job_id, None)
        self._save_job_history()
        self._refresh_job_table()

    def _open_selected_job_folder(self) -> None:
        selected = self._selected_jobs()
        path = Path(selected[0].filepath).parent if selected and selected[0].filepath else Path(
            selected[0].output_dir if selected else self.folder_var.get()
        )
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.resolve().as_uri())
        except OSError as exc:
            messagebox.showerror("Klasör açılamadı", clean_text(exc))

    def _on_job_double_click(self, _event: Any = None) -> None:
        selected = self._selected_jobs()
        if not selected:
            return
        job = selected[0]
        if job.status in {"queued", "downloading", "processing", "finalizing", "pausing", "paused", "cancelling"}:
            self._open_job_progress_window(job.id)
        else:
            self._open_selected_job_file()

    def _open_selected_job_file(self) -> None:
        selected = self._selected_jobs()
        if not selected or not selected[0].filepath or not Path(selected[0].filepath).is_file():
            return
        try:
            if os.name == "nt":
                os.startfile(selected[0].filepath)  # type: ignore[attr-defined]
            else:
                webbrowser.open(Path(selected[0].filepath).resolve().as_uri())
        except OSError as exc:
            messagebox.showerror("Dosya açılamadı", clean_text(exc))

    def _open_job_progress_window(self, job_id: str) -> None:
        if job_id in self.job_windows:
            window = self.job_windows[job_id]["window"]
            window.deiconify()
            window.lift()
            return
        job = self.jobs.get(job_id)
        if not job:
            return
        window = ctk.CTkToplevel(self)
        window.title(job.title)
        window.geometry("720x470")
        window.minsize(580, 340)
        status_var = ctk.StringVar()
        metrics_var = ctk.StringVar()
        url_var = ctk.StringVar(value=job.url)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(3, weight=1)
        top = ctk.CTkFrame(window)
        top.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="URL").grid(row=0, column=0, padx=(10, 6), pady=8)
        ctk.CTkEntry(top, textvariable=url_var, state="readonly").grid(row=0, column=1, padx=(0, 10), pady=8, sticky="ew")
        ctk.CTkLabel(window, textvariable=status_var, anchor="w").grid(row=1, column=0, padx=18, pady=(3, 2), sticky="ew")
        ctk.CTkLabel(window, textvariable=metrics_var, anchor="w").grid(row=2, column=0, padx=18, pady=(2, 5), sticky="ew")
        details = ctk.CTkFrame(window)
        details.grid(row=3, column=0, padx=12, pady=6, sticky="nsew")
        details.grid_columnconfigure(0, weight=1)
        details.grid_rowconfigure(1, weight=1)
        progress = ctk.CTkProgressBar(details)
        progress.set(job.progress)
        progress.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        tree = ttk.Treeview(details, columns=("n", "downloaded", "info"), show="headings", height=6, style="Jobs.Treeview")
        for col, text, width in (("n", "N.", 45), ("downloaded", "İndirilen", 120), ("info", "Bilgi", 390)):
            tree.heading(col, text=text)
            tree.column(col, width=width, stretch=col == "info")
        tree.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="nsew")
        tree.insert("", "end", iid="main", values=(1, human_bytes(job.downloaded_bytes), "Bağlantı hazırlanıyor"))
        controls = ctk.CTkFrame(window)
        controls.grid(row=4, column=0, padx=12, pady=(6, 12), sticky="ew")
        ctk.CTkButton(controls, text="▶ Başlat / Devam", command=lambda: self._resume_job_by_id(job_id)).pack(side="left", padx=8, pady=8)
        ctk.CTkButton(controls, text="Ⅱ Duraklat", command=lambda: self._pause_job_by_id(job_id), fg_color="#9a6a21").pack(side="left", padx=8, pady=8)
        ctk.CTkButton(controls, text="■ İptal", command=lambda: self._cancel_job_by_id(job_id), fg_color="#8f3340").pack(side="right", padx=8, pady=8)
        def close_window() -> None:
            self.job_windows.pop(job_id, None)
            window.destroy()
        window.protocol("WM_DELETE_WINDOW", close_window)
        self.job_windows[job_id] = {
            "window": window,
            "status": status_var,
            "metrics": metrics_var,
            "progress": progress,
            "tree": tree,
        }
        self._update_job_progress_window(job)

    def _update_job_progress_window(self, job: DownloadJob) -> None:
        data = self.job_windows.get(job.id)
        if not data:
            return
        percent = max(0.0, min(100.0, job.progress * 100))
        data["window"].title(f"{percent:.0f}% {job.title}")
        data["status"].set(f"Durum: {JOB_STATUS_LABELS.get(job.status, job.status)}")
        fragment = f" • Parça {job.fragment_index}/{job.fragment_count}" if job.fragment_count else ""
        data["metrics"].set(
            f"İndirilen: {human_bytes(job.downloaded_bytes)} • Hız: {human_speed(job.speed)} • "
            f"Kalan: {self._format_eta(job.eta)}{fragment}"
        )
        data["progress"].set(job.progress)
        info = "Bağlantı kesildi" if job.status in {"paused", "failed", "cancelled"} else "Aktarım sürüyor"
        data["tree"].item("main", values=(1, human_bytes(job.downloaded_bytes), info))

    def _pause_job_by_id(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.status == "queued":
            job.status = "paused"
            job.pause_event.set()
        elif job.status == "downloading":
            job.status = "pausing"
            job.pause_event.set()
        elif job.status in {"processing", "finalizing"}:
            messagebox.showinfo("İşleniyor", "Birleştirme/finalization aşaması duraklatılamaz.")
        self._refresh_job_table()

    def _resume_job_by_id(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job or job.status not in {"paused", "failed", "cancelled", "interrupted"}:
            return
        self._set_job_filter("all")
        if self.job_tree.exists(job_id):
            self.job_tree.selection_set(job_id)
            self._resume_selected_jobs()

    def _cancel_job_by_id(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.status in {"queued", "paused"}:
            job.cancel_event.set()
            job.status = "cancelled"
        elif job.status in {"downloading", "pausing"}:
            job.cancel_event.set()
            job.pause_event.clear()
            job.status = "cancelling"
        self._refresh_job_table()

    def _spawn_audio_child_jobs(
        self, parent_id: str, media_path: str, tracks: list[dict[str, Any]]
    ) -> None:
        parent = self.jobs.get(parent_id)
        if not parent or not tracks:
            return
        parent.filepath = media_path or parent.filepath
        existing_keys = {
            (
                job.parent_id,
                str((job.external_audio_tracks or [{}])[0].get("url") or ""),
            )
            for job in self.jobs.values()
            if job.job_type == "audio" and job.external_audio_tracks
        }
        created = 0
        for index, track in enumerate(tracks):
            track_url = str(track.get("url") or "")
            if not track_url or (parent_id, track_url) in existing_keys:
                continue
            language = self._canonical_language(track.get("language")) or f"und{index + 1}"
            display_language = {"tr": "Türkçe", "en": "English"}.get(language, language.upper())
            label = clean_text(track.get("label") or display_language, 80)
            child = DownloadJob(
                id=uuid.uuid4().hex,
                url=track_url,
                title=f"{parent.title} — {display_language} ses",
                quality=f"Ses • {language.upper()}",
                format_label=label,
                output_dir=parent.output_dir,
                ydl_opts={"http_headers": dict(parent.resume_headers)},
                external_audio_tracks=[dict(track)],
                resume_headers=dict(parent.resume_headers),
                output_mode="sidecar",
                job_type="audio",
                parent_id=parent.id,
                parent_filepath=parent.filepath,
                package_title=parent.title,
            )
            self.jobs[child.id] = child
            self.pending_job_ids.append(child.id)
            existing_keys.add((parent_id, track_url))
            created += 1
            self._append_log(f"Ayrı ses kuyruğuna eklendi: {parent.title} • {display_language} • {label}")
        parent.children_spawned = parent.children_spawned or created > 0
        if created:
            self.status_var.set(f"{created} ses izi ayrı indirme kuyruğuna eklendi.")
        self._refresh_job_table()
        self._pump_download_queue()

    def _spawn_subtitle_child_jobs(
        self, parent_id: str, media_path: str, tracks: list[dict[str, Any]]
    ) -> None:
        parent = self.jobs.get(parent_id)
        if not parent or not tracks:
            return
        parent.filepath = media_path or parent.filepath
        existing_keys = {
            (
                job.parent_id,
                str((job.external_subtitle_tracks or [{}])[0].get("url") or ""),
            )
            for job in self.jobs.values()
            if job.job_type == "subtitle" and job.external_subtitle_tracks
        }
        created = 0
        for index, track in enumerate(tracks):
            track_url = str(track.get("url") or "")
            if not track_url or (parent_id, track_url) in existing_keys:
                continue
            language = self._canonical_language(track.get("language")) or f"und{index + 1}"
            display_language = {"tr": "Türkçe", "en": "English"}.get(language, language.upper())
            label = clean_text(track.get("label") or display_language, 80)
            child = DownloadJob(
                id=uuid.uuid4().hex,
                url=track_url,
                title=f"{parent.title} — {display_language} altyazı",
                quality=f"Altyazı • {language.upper()}",
                format_label=label,
                output_dir=parent.output_dir,
                ydl_opts={"http_headers": dict(parent.resume_headers)},
                external_subtitle_tracks=[dict(track)],
                resume_headers=dict(parent.resume_headers),
                output_mode="sidecar",
                job_type="subtitle",
                parent_id=parent.id,
                parent_filepath=parent.filepath,
                package_title=parent.title,
            )
            self.jobs[child.id] = child
            self.pending_job_ids.append(child.id)
            existing_keys.add((parent_id, track_url))
            created += 1
            self._append_log(f"Ayrı altyazı kuyruğuna eklendi: {parent.title} • {display_language} • {label}")
        parent.children_spawned = parent.children_spawned or created > 0
        if created:
            self.status_var.set(f"{created} altyazı ayrı indirme kuyruğuna eklendi.")
        self._refresh_job_table()
        self._pump_download_queue()

    def _maybe_enqueue_auto_mux(self, parent_id: str) -> None:
        parent = self.jobs.get(parent_id)
        if not parent or parent.output_mode not in {"auto_mkv", "auto_mp4"} or parent.auto_mux_job_id:
            return
        children = [
            job for job in self.jobs.values()
            if job.parent_id == parent_id and job.job_type in {"audio", "subtitle"}
        ]
        expected = len(parent.external_audio_tracks) + len(parent.external_subtitle_tracks)
        if expected == 0 or len(children) < expected:
            return
        if any(job.status in {"queued", "downloading", "processing", "finalizing", "pausing", "paused", "cancelling"} for job in children):
            return
        failed = [job for job in children if job.status != "completed" or not job.filepath or not Path(job.filepath).is_file()]
        if failed:
            self.status_var.set("Otomatik birleştirme, başarısız ses/altyazı işleri tamamlanana kadar bekliyor.")
            return
        if not parent.filepath or not Path(parent.filepath).is_file():
            return
        container = "mkv" if parent.output_mode == "auto_mkv" else "mp4"
        audio_tracks: list[dict[str, str]] = []
        subtitle_tracks: list[dict[str, str]] = []
        for child in children:
            source_track = (
                (child.external_audio_tracks or [{}])[0]
                if child.job_type == "audio"
                else (child.external_subtitle_tracks or [{}])[0]
            )
            track = {
                "path": child.filepath,
                "language": self._canonical_language(source_track.get("language")) or "und",
                "label": clean_text(source_track.get("label") or child.format_label, 100),
            }
            if child.job_type == "audio":
                audio_tracks.append(track)
            else:
                subtitle_tracks.append(track)
        output = Path(parent.output_dir) / f"{parent.title} - final.{container}"
        mux_job = DownloadJob(
            id=uuid.uuid4().hex,
            url=str(parent.filepath),
            title=f"{parent.title} — Otomatik {container.upper()} birleştirme",
            quality=f"Birleştir • {container.upper()}",
            format_label="Otomatik yan dosya birleştirme",
            output_dir=parent.output_dir,
            job_type="mux",
            parent_id=parent.id,
            mux_video_path=parent.filepath,
            mux_audio_tracks=audio_tracks,
            mux_subtitle_tracks=subtitle_tracks,
            mux_output_path=str(output),
            mux_container=container,
        )
        self.jobs[mux_job.id] = mux_job
        self.pending_job_ids.append(mux_job.id)
        parent.auto_mux_job_id = mux_job.id
        self._append_log(
            f"Otomatik {container.upper()} birleştirme kuyruğa eklendi: "
            f"{len(audio_tracks)} ses, {len(subtitle_tracks)} altyazı."
        )
        self.status_var.set(f"Tüm yan dosyalar tamamlandı; otomatik {container.upper()} kuyruğa eklendi.")
        self._save_job_history()
        self._refresh_job_table()
        self._pump_download_queue()

    def _pump_download_queue(self) -> None:
        try:
            limit = max(1, min(20, int(self.max_concurrent_var.get())))
        except ValueError:
            limit = 3
        while len(self.active_job_ids) < limit and self.pending_job_ids:
            job_id = self.pending_job_ids.popleft()
            job = self.jobs.get(job_id)
            if not job or job.status != "queued" or job.cancel_event.is_set():
                continue
            job.status = "downloading"
            job.started_at = job.started_at or time.time()
            job.finished_at = None
            job.history_only = False
            self.active_job_ids.add(job_id)
            threading.Thread(
                target=self._job_download_worker,
                args=(job_id,),
                name=f"download-{job_id[:8]}",
                daemon=True,
            ).start()
            if job.job_type == "video":
                self._open_job_progress_window(job_id)
        self._refresh_job_table()

    def _cancel_current(self) -> None:
        if self.busy_kind:
            self.cancel_event.set()
            self.status_var.set("Analiz/güncelleme için iptal isteği gönderildi…")
            self.cancel_button.configure(state="disabled")

    def _set_busy(self, kind: str | None) -> None:
        self.busy_kind = kind
        busy = kind is not None
        self.analyze_button.configure(state="disabled" if busy else "normal")
        self.cookie_menu.configure(state="disabled" if busy else "normal")
        self.cookie_file_button.configure(state="disabled" if busy else "normal")
        self.language_pack_check.configure(state="disabled" if busy else "normal")
        self.auto_subs_check.configure(state="disabled" if busy else "normal")
        self.output_mode_menu.configure(state="disabled" if busy else "normal")
        self.output_name_entry.configure(state="disabled" if busy else "normal")
        self.output_name_reset_button.configure(state="disabled" if busy else "normal")
        self.ytdlp_update_button.configure(state="disabled" if busy else "normal")
        self.deno_button.configure(state="disabled" if busy else "normal")
        self.ffmpeg_update_button.configure(state="disabled" if busy else "normal")
        self.quality_menu.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        selection = self.format_tree.selection()
        has_selection = bool(selection and selection[0] in self.format_rows)
        self.download_button.configure(
            state="disabled" if busy or not has_selection else "normal"
        )
        if not busy:
            self.cancel_event.clear()

    def _start_analysis(self) -> None:
        if self.busy_kind:
            return
        if not self._cookie_selection_valid():
            return
        url = self.url_var.get().strip()
        if not is_http_url(url):
            messagebox.showwarning(
                "Geçersiz adres", "Lütfen http:// veya https:// ile başlayan geçerli bir adres girin."
            )
            return
        self.deno_path = find_deno()
        if is_youtube_url(url) and not self.deno_path and not self.youtube_warning_shown:
            self.youtube_warning_shown = True
            messagebox.showwarning(
                "YouTube için Deno önerilir",
                "Güncel YouTube biçimlerinin çözümlenmesi için Deno 2.3+ gerekir. "
                "Analiz yine denenecek; formatlar eksikse ‘YouTube / Deno’ düğmesiyle kurun.",
            )

        self.current_url = url
        if self.current_context.get("url") != url:
            self.current_context = {}
        self.analysis_info = None
        self.prepared_analysis_url = ""
        self.format_rows.clear()
        self.quality_map.clear()
        self.quality_var.set("Kalite seçin…")
        self.output_name_var.set("")
        self.inferred_output_name = ""
        self.quality_menu.configure(values=["Kalite seçin…"])
        for item in self.format_tree.get_children():
            self.format_tree.delete(item)
        self.video_title.configure(text="Analiz ediliyor…")
        self.progress.set(0)
        self.status_var.set("yt-dlp adresi inceliyor…")
        self._append_log("Analiz başlatıldı.")
        self.cancel_event.clear()
        self._set_busy("analysis")

        opts = self._base_ydl_options()
        opts.update(
            {
                "skip_download": True,
                "noplaylist": True,
                "extract_flat": False,
            }
        )
        thread = threading.Thread(
            target=self._analysis_worker,
            args=(url, opts, dict(self.current_context)),
            name="yt-dlp-analysis",
            daemon=True,
        )
        thread.start()

    def _extract_with_cookie_fallback(
        self, url: str, opts: dict[str, Any], *, download: bool
    ) -> dict[str, Any] | None:
        def extract_once(options: dict[str, Any]) -> dict[str, Any] | None:
            runtime_options = dict(options)
            resilient_subtitles = bool(runtime_options.pop("_app_resilient_subtitles", False))
            external_subtitles = runtime_options.pop("_app_external_subtitles", [])
            external_audio_tracks = runtime_options.pop("_app_external_audio_tracks", [])
            primary_language = runtime_options.pop("_app_primary_language", "")
            cookie_stream = runtime_options.get("cookiefile")
            managed = resilient_subtitles or bool(external_subtitles) or bool(external_audio_tracks) or bool(primary_language)
            ydl_class = ResilientSubtitleYoutubeDL if managed else YoutubeDL
            try:
                if managed:
                    ydl_context = ydl_class(
                        runtime_options,
                        external_subtitles=external_subtitles,
                        external_audio_tracks=external_audio_tracks,
                        primary_language=primary_language,
                    )
                else:
                    ydl_context = ydl_class(runtime_options)
                with ydl_context as ydl:
                    return ydl.extract_info(url, download=download)
            finally:
                if isinstance(cookie_stream, io.StringIO):
                    updated = cookie_stream.getvalue()
                    if updated.startswith("# Netscape HTTP Cookie File") and len(updated) <= MAX_BRIDGE_BODY:
                        self.extension_cookie_text = updated

        try:
            return extract_once(opts)
        except Exception as exc:
            browser_spec = opts.get("cookiesfrombrowser")
            if not browser_spec or not is_browser_cookie_access_error(exc):
                raise

            browser = str(browser_spec[0] if isinstance(browser_spec, tuple) else browser_spec)
            retry_opts = dict(opts)
            retry_opts.pop("cookiesfrombrowser", None)
            self.event_queue.put(("cookie_fallback", browser))
            return extract_once(retry_opts)

    def _prepare_extensionless_hls(
        self, url: str, opts: dict[str, Any], context: dict[str, Any]
    ) -> str:
        if context.get("mediaType") != "hls":
            return url
        try:
            path = urllib.parse.urlsplit(url).path.lower()
        except ValueError:
            return url
        # Standard .m3u8 works directly; extensionless/.txt endpoints often
        # return text/plain and newer generic extractors treat them as files.
        if path.endswith(".m3u8"):
            return url
        cache_dir = settings_file().parent / "manifests"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{hashlib.sha1(url.encode('utf-8', 'ignore')).hexdigest()[:20]}.m3u8"
        headers = {
            key: str(value) for key, value in (opts.get("http_headers") or {}).items()
            if key in {"Referer", "Origin", "User-Agent"}
        }
        media_cookie = str(context.get("mediaCookieHeader") or "").replace("\r", "").replace("\n", "")
        if media_cookie:
            headers["Cookie"] = media_cookie
        browser_manifest = str(context.get("manifestText") or "")
        if re.match(r"^\s*#EXTM3U", browser_manifest, flags=re.IGNORECASE):
            prepared = self._write_hls_manifest_text(browser_manifest, url, cache_file)
            source_note = "tarayıcı yanıt gövdesinden"
        else:
            prepared = self._fetch_hls_playlist_to_local(url, cache_file, headers)
            source_note = "yeniden istekle"
        if not prepared:
            self.event_queue.put(("log", "Uyarı: Uzantısız HLS yerel manifest olarak hazırlanamadı; özgün URL deneniyor."))
            return url
        opts["enable_file_urls"] = True
        prepared_url = prepared.resolve().as_uri()
        self.event_queue.put(("log", f"Uzantısız HLS {source_note} yerel M3U8 olarak hazırlandı: {prepared.name}"))
        return prepared_url

    def _analysis_worker(
        self, url: str, opts: dict[str, Any], context: dict[str, Any]
    ) -> None:
        try:
            if self.cancel_event.is_set():
                self.event_queue.put(("cancelled", "Analiz iptal edildi."))
                return
            analysis_url = self._prepare_extensionless_hls(url, opts, context)
            info = self._extract_with_cookie_fallback(analysis_url, opts, download=False)
            if self.cancel_event.is_set():
                self.event_queue.put(("cancelled", "Analiz iptal edildi."))
                return
            if not info:
                raise DownloadError("Bu adreste indirilebilir bilgi bulunamadı.")
            rows = self._make_format_rows(info)
            self.event_queue.put(("analysis_done", info, rows, analysis_url))
        except Exception as exc:
            if self.cancel_event.is_set():
                self.event_queue.put(("cancelled", "Analiz iptal edildi."))
            else:
                detail = clean_text(exc, 1200)
                if is_youtube_url(url):
                    cookie_count = int(context.get("youtubeCookieCount") or 0)
                    if cookie_count and not context.get("youtubeAuthenticated"):
                        detail += (
                            f"\n\nEklenti {cookie_count} misafir YouTube çerezi aktardı ancak "
                            "giriş yapılmış hesap çerezi bulunmadı. Aynı Chrome profilinde "
                            "YouTube'a giriş yapın, sayfayı yenileyin ve video üstündeki "
                            "‘İndir (oturumla)’ düğmesini yeniden kullanın."
                        )
                    elif cookie_count:
                        detail += (
                            f"\n\nEklenti {cookie_count} YouTube oturum çerezini aktardı. "
                            "Buna rağmen 429 sürüyorsa YouTube bu IP/oturumu geçici olarak "
                            "sınırlamıştır. Aynı Chrome profilinde YouTube'u normal açın, "
                            "varsa doğrulamayı tamamlayın ve peş peşe denemeden bir süre bekleyin."
                        )
                    else:
                        detail += (
                            "\n\nYouTube oturum çerezi alınamadı. v2.1 eklentisini yeniden yükleyin, "
                            "Chrome'un istediği çerez iznini kabul edin ve YouTube'a giriş yapılmış "
                            "aynı profilde video üstündeki ‘İndir (oturumla)’ düğmesini kullanın."
                        )
                elif context.get("mediaType") in {"page", "unknown"}:
                    detail += (
                        "\n\nEklenti bir video manifesti yerine sayfa adresini göndermiş. "
                        "Videoyu oynatın; eklentide HLS/DASH kaydı görünürse "
                        "‘Yakalanan akışı gönder’ seçeneğini kullanın."
                    )
                self.event_queue.put(("operation_error", "Analiz başarısız", detail))

    @staticmethod
    def _format_has_video(item: dict[str, Any]) -> bool:
        vcodec = item.get("vcodec")
        note = str(item.get("format_note") or item.get("resolution") or "").lower()
        if vcodec == "none" or "audio only" in note or item.get("video_ext") == "none":
            return False
        if vcodec not in (None, ""):
            return True
        if item.get("height") or item.get("width"):
            return True
        ext = str(item.get("ext") or "").lower()
        # Generic direct/HLS extractors often leave codecs unknown. Treat known
        # video containers as video unless the extractor marked audio-only.
        return ext in {"mp4", "webm", "mkv", "mov", "m4v", "ts"}

    @staticmethod
    def _format_has_audio(item: dict[str, Any]) -> bool:
        acodec = item.get("acodec")
        note = str(item.get("format_note") or item.get("resolution") or "").lower()
        if acodec == "none" or item.get("audio_ext") == "none":
            return False
        if acodec not in (None, ""):
            return True
        if "audio only" in note:
            return True
        ext = str(item.get("ext") or "").lower()
        if ext in {"m4a", "mp3", "aac", "opus", "ogg", "wav"}:
            return True
        # Unknown-codec HLS/direct video usually contains muxed audio.
        return VideoDownloaderApp._format_has_video(item)

    def _make_format_rows(self, info: dict[str, Any]) -> list[dict[str, Any]]:
        entries = info.get("entries")
        if info.get("_type") in {"playlist", "multi_video"} and entries:
            first = next((entry for entry in entries if entry), None)
            if isinstance(first, dict) and first.get("formats"):
                info = first

        formats = [
            item
            for item in (info.get("formats") or [])
            if isinstance(item, dict)
            and (self._format_has_video(item) or self._format_has_audio(item))
        ]
        rows: list[dict[str, Any]] = [
            {
                "label": "En iyi kalite (önerilen)",
                "selector": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "resolution": "En iyi",
                "fps": "—",
                "kind": "Video + ses",
                "codec": "Otomatik",
                "ext": "mp4*",
                "size": "—",
                "protocol": "Otomatik",
                "needs_ffmpeg": True,
                "audio_mp3": False,
                "format_id": None,
                "has_video": True,
                "has_audio": True,
                "height": 0,
                "tbr": 0,
            },
            {
                "label": "En iyi tek dosya",
                "selector": "b",
                "resolution": "En iyi",
                "fps": "—",
                "kind": "Video + ses",
                "codec": "Otomatik",
                "ext": "kaynak",
                "size": "—",
                "protocol": "Otomatik",
                "needs_ffmpeg": False,
                "audio_mp3": False,
                "format_id": None,
                "has_video": True,
                "has_audio": True,
                "height": 0,
                "tbr": 0,
            },
        ]

        if any(self._format_has_audio(item) for item in formats):
            rows.append(
                {
                    "label": "Yalnızca ses (MP3)",
                    "selector": "bestaudio/best",
                    "resolution": "Ses",
                    "fps": "—",
                    "kind": "MP3 ses",
                    "codec": "Otomatik",
                    "ext": "mp3",
                    "size": "—",
                    "protocol": "Otomatik",
                    "needs_ffmpeg": True,
                    "audio_mp3": True,
                    "format_id": None,
                    "has_video": False,
                    "has_audio": True,
                    "height": 0,
                    "tbr": 0,
                }
            )

        def sort_key(item: dict[str, Any]) -> tuple[float, float, int]:
            return (
                float(item.get("height") or 0),
                float(item.get("tbr") or item.get("abr") or 0),
                int(self._format_has_audio(item)),
            )

        seen_ids: set[str] = set()
        for item in sorted(formats, key=sort_key, reverse=True)[:220]:
            format_id = str(item.get("format_id") or "").strip()
            if not format_id or format_id in seen_ids:
                continue
            seen_ids.add(format_id)
            has_video = self._format_has_video(item)
            has_audio = self._format_has_audio(item)
            if has_video and has_audio:
                kind = "Video + ses"
                selector = format_id
                needs_ffmpeg = False
            elif has_video:
                kind = "Video (+ en iyi ses)"
                selector = f"{format_id}+bestaudio/best"
                needs_ffmpeg = True
            else:
                kind = "Yalnızca ses"
                selector = format_id
                needs_ffmpeg = False

            width, height = item.get("width"), item.get("height")
            if width and height:
                resolution = f"{width}×{height}"
            elif height:
                resolution = f"{height}p"
            elif item.get("resolution") and item.get("resolution") != "audio only":
                resolution = str(item.get("resolution"))
            else:
                resolution = "Ses" if not has_video else "—"

            note = clean_text(item.get("format_note") or item.get("format") or format_id, 80)
            label = f"{format_id} • {note}" if note != format_id else format_id
            filesize = item.get("filesize") or item.get("filesize_approx")
            codecs = f"{shortened_codec(item.get('vcodec'))} / {shortened_codec(item.get('acodec'))}"
            rows.append(
                {
                    "label": label,
                    "selector": selector,
                    "resolution": resolution,
                    "fps": str(item.get("fps") or "—"),
                    "kind": kind,
                    "codec": codecs,
                    "ext": str(item.get("ext") or "—"),
                    "size": human_bytes(filesize),
                    "protocol": clean_text(item.get("protocol") or "—", 24),
                    "needs_ffmpeg": needs_ffmpeg,
                    "audio_mp3": False,
                    "format_id": format_id,
                    "has_video": has_video,
                    "has_audio": has_audio,
                    "height": int(item.get("height") or 0)
                    if isinstance(item.get("height"), (int, float)) else 0,
                    "tbr": float(item.get("tbr") or item.get("vbr") or 0)
                    if isinstance(item.get("tbr") or item.get("vbr"), (int, float)) else 0.0,
                }
            )
        return rows

    @staticmethod
    def _primary_media_info(info: dict[str, Any]) -> dict[str, Any]:
        entries = info.get("entries")
        if info.get("_type") in {"playlist", "multi_video"} and entries:
            first = next((entry for entry in entries if isinstance(entry, dict)), None)
            if first:
                return first
        return info

    @staticmethod
    def _canonical_language(value: Any) -> str:
        language = str(value or "").lower().replace("_", "-")
        if language.startswith("tr") or language == "tur":
            return "tr"
        if language.startswith("en") or language == "eng":
            return "en"
        return language.split("-", 1)[0]

    def _track_summary(self, info: dict[str, Any]) -> str:
        media = self._primary_media_info(info)
        audio_languages = {
            self._canonical_language(item.get("language"))
            for item in (media.get("formats") or [])
            if isinstance(item, dict)
            and self._format_has_audio(item)
            and item.get("language")
        }
        subtitle_languages = {
            self._canonical_language(language)
            for language in (media.get("subtitles") or {})
        }
        auto_languages = {
            self._canonical_language(language)
            for language in (media.get("automatic_captions") or {})
        }

        def describe(languages: set[str]) -> str:
            preferred = [label for code, label in (("tr", "TR"), ("en", "EN")) if code in languages]
            others = len({code for code in languages if code and code not in {"tr", "en"}})
            if others:
                preferred.append(f"+{others} dil")
            return ", ".join(preferred) if preferred else "belirtilmemiş"

        subtitle_text = describe(subtitle_languages)
        if auto_languages & {"tr", "en"}:
            subtitle_text += " + otomatik"
        return f"Ses: {describe(audio_languages)} • Altyazı: {subtitle_text}"

    def _select_subtitle_languages(self, info: dict[str, Any]) -> list[str]:
        media = self._primary_media_info(info)
        manual = media.get("subtitles") or {}
        automatic = media.get("automatic_captions") or {}
        selected: list[str] = []

        def pick(mapping: dict[str, Any], code: str, *, prefer_original: bool) -> str | None:
            candidates = [
                str(language) for language in mapping
                if self._canonical_language(language) == code
                and str(language).lower() != "live_chat"
            ]
            if not candidates:
                return None

            def score(language: str) -> tuple[int, int, int]:
                lower = language.lower()
                return (
                    int(prefer_original and "orig" in lower),
                    int(lower == code),
                    -len(lower),
                )

            return max(candidates, key=score)

        for code in ("tr", "en"):
            language = pick(manual, code, prefer_original=False)
            if not language and self.auto_subs_var.get():
                language = pick(automatic, code, prefer_original=True)
            if language:
                selected.append(language)
        return selected

    def _build_sidecar_subtitle_tracks(
        self, info: dict[str, Any], external_subtitles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for track in external_subtitles:
            language = self._canonical_language(track.get("language"))
            if language not in {"tr", "en"} or language in selected or not track.get("url"):
                continue
            normalized = dict(track)
            normalized["language"] = language
            selected[language] = normalized

        media = self._primary_media_info(info)
        manual = media.get("subtitles") or {}
        automatic = media.get("automatic_captions") or {}
        for language_key in self._select_subtitle_languages(info):
            language = self._canonical_language(language_key)
            if language not in {"tr", "en"} or language in selected:
                continue
            entries = manual.get(language_key) or automatic.get(language_key) or []
            if not entries:
                continue
            preference = {"srt": 5, "vtt": 4, "ass": 3, "ttml": 2, "srv3": 1}
            entry = max(entries, key=lambda item: preference.get(str(item.get("ext") or "").lower(), 0))
            if entry.get("url"):
                selected[language] = {
                    "url": entry["url"],
                    "language": language,
                    "label": entry.get("name") or language.upper(),
                    "ext": entry.get("ext") or "vtt",
                    "cookieHeader": "",
                }
        return [selected[code] for code in ("tr", "en") if code in selected]

    def _build_language_pack_selector(
        self,
        row: dict[str, Any],
        info: dict[str, Any],
        *,
        has_postmerge_audio: bool = False,
    ) -> tuple[Any, list[str], int]:
        if row.get("audio_mp3") or not row.get("has_video", True):
            return str(row["selector"]), [], 0

        media = self._primary_media_info(info)
        formats = [item for item in (media.get("formats") or []) if isinstance(item, dict)]

        def number(item: dict[str, Any], key: str) -> float:
            try:
                return float(item.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        def video_score(item: dict[str, Any]) -> tuple[float, float, float, float]:
            return (
                number(item, "height"),
                number(item, "fps"),
                number(item, "tbr"),
                number(item, "filesize") or number(item, "filesize_approx"),
            )

        requested_id = str(row.get("format_id") or "")
        base = next((item for item in formats if str(item.get("format_id")) == requested_id), None)
        if not base or not self._format_has_video(base):
            video_only = [
                item for item in formats
                if self._format_has_video(item) and not self._format_has_audio(item)
            ]
            combined = [
                item for item in formats
                if self._format_has_video(item) and self._format_has_audio(item)
            ]
            pool = video_only or combined
            base = max(pool, key=video_score) if pool else None

        if not base or not base.get("format_id"):
            return str(row["selector"]), [], 0

        base_id = str(base["format_id"])
        selected_ids = {base_id}
        parts = [base_id]
        selected_specs: list[tuple[str, bool]] = [(base_id, False)]
        selected_languages: list[str] = []
        base_has_audio = self._format_has_audio(base)
        base_language = self._canonical_language(base.get("language"))
        if base_has_audio and base_language in {"tr", "en"}:
            selected_languages.append(base_language.upper())

        audio_only = [
            item for item in formats
            if not self._format_has_video(item)
            and self._format_has_audio(item)
            and item.get("format_id")
            and not str(item.get("format_id")).startswith("extaudio-")
        ]
        combined_audio = [
            item for item in formats
            if self._format_has_video(item)
            and self._format_has_audio(item)
            and item.get("format_id")
            and str(item.get("format_id")) != base_id
        ]

        def audio_score(item: dict[str, Any]) -> tuple[float, float, float, float]:
            note = str(item.get("format_note") or "").lower()
            original = 1.0 if "original" in note or "default" in note else 0.0
            descriptive_penalty = -1.0 if "descriptive" in note or "audio description" in note else 0.0
            return (
                original + descriptive_penalty,
                number(item, "language_preference"),
                number(item, "abr") or number(item, "tbr"),
                number(item, "filesize") or number(item, "filesize_approx"),
            )

        def add_audio(
            item: dict[str, Any] | None, label: str, *, strip_video: bool = False
        ) -> None:
            if not item:
                return
            format_id = str(item.get("format_id") or "")
            if not format_id or format_id in selected_ids:
                return
            selected_ids.add(format_id)
            parts.append(format_id)
            selected_specs.append((format_id, strip_video))
            selected_languages.append(label)

        # Keep the source/default voice as the first audio stream, then add the
        # best Turkish and English variants if the extractor exposes them.
        if not base_has_audio:
            default_pool = audio_only or combined_audio
            default_audio = max(default_pool, key=audio_score) if default_pool else None
            default_label = (self._canonical_language(default_audio.get("language")) if default_audio else "") or "ORJ"
            add_audio(
                default_audio,
                default_label.upper(),
                strip_video=bool(default_audio and self._format_has_video(default_audio)),
            )

        def combined_fallback_score(item: dict[str, Any]) -> tuple[float, float, float]:
            # A combined fallback is downloaded only to harvest its audio. Prefer
            # good audio but a smaller video payload to avoid needless bandwidth.
            return (
                number(item, "abr"),
                -number(item, "height"),
                -number(item, "tbr"),
            )

        for code, label in (("tr", "TR"), ("en", "EN")):
            if label in selected_languages:
                continue
            candidates = [
                item for item in audio_only
                if self._canonical_language(item.get("language")) == code
            ]
            if candidates:
                add_audio(max(candidates, key=audio_score), label)
                continue
            combined_candidates = [
                item for item in combined_audio
                if self._canonical_language(item.get("language")) == code
            ]
            add_audio(
                max(combined_candidates, key=combined_fallback_score)
                if combined_candidates else None,
                label,
                strip_video=True,
            )

        if len(parts) == 1 and not base_has_audio and not has_postmerge_audio:
            parts.append("bestaudio")
            selected_languages.append("ORJ")

        selector: Any = "+".join(parts)
        if any(strip_video for _format_id, strip_video in selected_specs):
            specs = tuple(selected_specs)

            def multilang_selector(context: dict[str, Any]):
                current = {
                    str(item.get("format_id")): item
                    for item in (context.get("formats") or [])
                    if isinstance(item, dict) and item.get("format_id")
                }
                requested: list[dict[str, Any]] = []
                for format_id, strip_video in specs:
                    source = current.get(format_id)
                    if not source:
                        return
                    selected = dict(source)
                    if strip_video:
                        # FFmpegMerger maps streams according to these codec
                        # fields. The file is still downloaded normally, but
                        # only its audio stream is mapped into the final MKV.
                        selected["vcodec"] = "none"
                        selected["video_ext"] = "none"
                        selected["width"] = None
                        selected["height"] = None
                        selected["resolution"] = "audio only"
                    requested.append(selected)
                base_format = requested[0]
                yield {
                    "format_id": "+".join(item["format_id"] for item in requested),
                    "format": "+".join(str(item.get("format") or item["format_id"]) for item in requested),
                    "ext": base_format.get("ext") or "mkv",
                    "protocol": "+".join(str(item.get("protocol") or "https") for item in requested),
                    "requested_formats": requested,
                }

            selector = multilang_selector
        else:
            fallback = str(row.get("selector") or "bv*+ba/b")
            if selector != fallback:
                selector = f"{selector}/{fallback}"
        return selector, selected_languages, max(0, len(parts) - 1)

    def _open_format_selection_dialog(self) -> None:
        if self.format_dialog and self.format_dialog.winfo_exists():
            self.format_dialog.destroy()
        dialog = ctk.CTkToplevel(self)
        self.format_dialog = dialog
        dialog.title("Dosya İndirme Bilgisi ve Format Seçimi")
        dialog.geometry("1120x740")
        dialog.minsize(880, 580)
        dialog.grid_columnconfigure(1, weight=1)
        dialog.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(dialog, text="URL").grid(row=0, column=0, padx=(14, 7), pady=(14, 5), sticky="e")
        ctk.CTkEntry(dialog, textvariable=self.url_var, state="readonly").grid(
            row=0, column=1, columnspan=2, padx=(0, 14), pady=(14, 5), sticky="ew"
        )
        ctk.CTkLabel(dialog, text="Kategori").grid(row=1, column=0, padx=(14, 7), pady=5, sticky="e")
        ctk.CTkLabel(dialog, text="Video", anchor="w").grid(row=1, column=1, padx=4, pady=5, sticky="w")
        ctk.CTkLabel(dialog, text="Kaydet").grid(row=2, column=0, padx=(14, 7), pady=5, sticky="e")
        ctk.CTkEntry(dialog, textvariable=self.folder_var).grid(row=2, column=1, padx=4, pady=5, sticky="ew")
        ctk.CTkButton(dialog, text="…", width=38, command=self._choose_folder).grid(row=2, column=2, padx=(4, 14), pady=5)
        ctk.CTkLabel(dialog, text="Dosya adı").grid(row=3, column=0, padx=(14, 7), pady=5, sticky="e")
        ctk.CTkEntry(dialog, textvariable=self.output_name_var).grid(row=3, column=1, padx=4, pady=5, sticky="ew")
        quality_values = ["Kalite seçin…", *self.quality_map.keys()]
        dialog_quality = ctk.StringVar(value=self.quality_var.get())
        quality_menu = ctk.CTkOptionMenu(dialog, values=quality_values, variable=dialog_quality, width=180)
        quality_menu.grid(row=3, column=2, padx=(4, 14), pady=5)
        ctk.CTkLabel(dialog, text="Çıktı düzeni").grid(row=4, column=0, padx=(14, 7), pady=5, sticky="e")
        ctk.CTkOptionMenu(
            dialog,
            values=["Ayrı dosyalar (önerilen)", "Otomatik MKV birleştir", "Otomatik MP4 birleştir"],
            variable=self.output_mode_var,
            width=235,
        ).grid(row=4, column=1, columnspan=2, padx=(4, 14), pady=5, sticky="w")
        tree_frame = ctk.CTkFrame(dialog)
        tree_frame.grid(row=5, column=0, columnspan=3, padx=14, pady=10, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            tree_frame,
            columns=("format", "resolution", "fps", "kind", "codec", "ext", "size"),
            show="headings",
            selectmode="browse",
            style="Media.Treeview",
        )
        labels = {"format": "Format", "resolution": "Çözünürlük", "fps": "FPS", "kind": "İçerik", "codec": "Kodek", "ext": "Uzantı", "size": "Boyut"}
        for col in tree["columns"]:
            tree.heading(col, text=labels[col])
            tree.column(col, width=160 if col == "format" else 90, stretch=col in {"format", "codec"})
        for iid, row in self.format_rows.items():
            tree.insert("", "end", iid=iid, values=(row["label"], row["resolution"], row["fps"], row["kind"], row["codec"], row["ext"], row["size"]))
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(tree_frame, command=tree.yview)
        scroll.grid(row=0, column=1, padx=(4, 0), sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        def choose_quality(choice: str) -> None:
            iid = self.quality_map.get(choice)
            if iid and tree.exists(iid):
                tree.selection_set(iid)
                tree.see(iid)
                self._on_quality_selected(choice)

        quality_menu.configure(command=choose_quality)

        def tree_selected(_event: Any = None) -> None:
            selected = tree.selection()
            if not selected:
                return
            iid = selected[0]
            if self.format_tree.exists(iid):
                self.format_tree.selection_set(iid)
                self._on_tree_selection()
                dialog_quality.set(self.quality_var.get())

        tree.bind("<<TreeviewSelect>>", tree_selected)
        if self.quality_var.get() in self.quality_map:
            choose_quality(self.quality_var.get())

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=3, padx=14, pady=(0, 14), sticky="ew")

        def submit(start_now: bool) -> None:
            if not tree.selection():
                messagebox.showwarning("Kalite seçin", "Önce kalite veya format satırı seçin.", parent=dialog)
                return
            self._start_download(start_immediately=start_now)
            dialog.destroy()
            self.format_dialog = None

        ctk.CTkButton(buttons, text="Daha Sonra İndir", command=lambda: submit(False), fg_color="#566780").pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="İndirmeyi Başlat", command=lambda: submit(True), width=160).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="İptal", command=dialog.destroy, fg_color="#8f3340").pack(side="right", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.lift()
        dialog.focus_force()

    def _show_analysis(self, info: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.main_tabs.set("Format Seçimi")
        self._on_main_tab_change()
        self.analysis_info = info
        media = self._primary_media_info(info)
        extracted_title = clean_text(media.get("title") or info.get("title") or info.get("id") or "", 180)
        source_title = clean_text(self.current_context.get("title") or "", 180)
        if is_usable_source_title(source_title):
            title = source_title
        elif is_usable_source_title(extracted_title):
            title = extracted_title
        else:
            title = title_from_page_url(str(self.current_context.get("pageUrl") or self.current_url))
        duration = media.get("duration_string") or info.get("duration_string")
        suffix = f" • {duration}" if duration else ""
        self.video_title.configure(text=f"{title}{suffix}")
        self.inferred_output_name = safe_source_filename(title)
        if not self.output_name_var.get().strip():
            self.output_name_var.set(self.inferred_output_name)

        self.format_rows.clear()
        for item in self.format_tree.get_children():
            self.format_tree.delete(item)
        for index, row in enumerate(rows):
            iid = f"fmt-{index}"
            self.format_rows[iid] = row
            self.format_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row["label"],
                    row["resolution"],
                    row["fps"],
                    row["kind"],
                    row["codec"],
                    row["ext"],
                    row["size"],
                    row["protocol"],
                ),
            )
        if rows:
            self.quality_map.clear()
            if "fmt-0" in self.format_rows:
                self.quality_map["En iyi mevcut (otomatik)"] = "fmt-0"
            if "fmt-1" in self.format_rows:
                self.quality_map["En iyi tek dosya"] = "fmt-1"

            best_for_height: dict[int, tuple[str, dict[str, Any]]] = {}
            for iid, row in self.format_rows.items():
                height = int(row.get("height") or 0)
                if height <= 0 or not row.get("has_video"):
                    continue
                current = best_for_height.get(height)
                score = (float(row.get("tbr") or 0), int(not row.get("has_audio")))
                current_score = (
                    (float(current[1].get("tbr") or 0), int(not current[1].get("has_audio")))
                    if current else (-1.0, -1)
                )
                if not current or score > current_score:
                    best_for_height[height] = (iid, row)
            for height in sorted(best_for_height, reverse=True):
                self.quality_map[f"{height}p"] = best_for_height[height][0]

            values = ["Kalite seçin…", *self.quality_map.keys()]
            self.quality_menu.configure(values=values)
            self.quality_var.set("Kalite seçin…")
            self.format_tree.selection_remove(*self.format_tree.selection())
            self.download_button.configure(state="disabled")
            track_summary = self._track_summary(info)
            external_count = len(self.current_context.get("externalSubtitles") or [])
            if external_count:
                track_summary += f" • Harici altyazı: {external_count}"
            available = ", ".join(f"{height}p" for height in sorted(best_for_height, reverse=True))
            quality_note = available or "tablodaki formatlar"
            self.status_var.set(f"Önce kalite seçin: {quality_note} • {track_summary}")
            self._append_log(f"İz bilgisi: {track_summary}")
            self._append_log(f"Kalite seçimi bekleniyor: {quality_note}.")
        else:
            self.quality_map.clear()
            self.quality_menu.configure(values=["Kalite seçin…"])
            self.quality_var.set("Kalite seçin…")
            self.status_var.set("Format listesi bulunamadı; sayfa adresini doğrudan indirmeyi deneyin.")
        self._append_log("Analiz tamamlandı.")
        if rows:
            self.after(50, self._open_format_selection_dialog)

    def _start_download(self, start_immediately: bool = True) -> None:
        if self.busy_kind:
            return
        if not self._cookie_selection_valid():
            return
        selection = self.format_tree.selection()
        if not selection or selection[0] not in self.format_rows:
            messagebox.showinfo("Format seçin", "Önce tablodan bir format seçin.")
            return
        url = self.current_url or self.url_var.get().strip()
        if not is_http_url(url):
            messagebox.showwarning("Geçersiz adres", "Video adresi geçerli değil.")
            return

        row = self.format_rows[selection[0]]
        language_pack = bool(
            self.language_pack_var.get()
            and not row.get("audio_mp3")
            and row.get("has_video", True)
        )
        output_mode_label = self.output_mode_var.get()
        if output_mode_label.startswith("Otomatik MKV"):
            output_mode = "auto_mkv"
        elif output_mode_label.startswith("Otomatik MP4"):
            output_mode = "auto_mp4"
        else:
            output_mode = "sidecar"
        self.ffmpeg_path = find_ffmpeg()
        if (row.get("needs_ffmpeg") or language_pack) and not self.ffmpeg_path:
            proceed = messagebox.askyesno(
                "FFmpeg bulunamadı",
                "Bu seçim ayrı video/ses akışlarını, çoklu dil izlerini ve altyazıları "
                "birleştirmek için FFmpeg gerektirir. Yine de denensin mi?\n\n"
                "Önerilen kurulum: winget install --id Gyan.FFmpeg -e",
            )
            if not proceed:
                return

        output_dir = Path(self.folder_var.get().strip() or default_download_dir())
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Klasör oluşturulamadı", clean_text(exc))
            return

        selector = str(row["selector"])
        selected_languages: list[str] = []
        audio_extra_count = 0
        subtitle_languages: list[str] = []
        context_matches = self.current_context.get("url") == url
        external_subtitles = (
            list(self.current_context.get("externalSubtitles") or []) if context_matches else []
        )
        raw_external_audio = (
            list(self.current_context.get("externalAudioTracks") or []) if context_matches else []
        )
        external_audio_tracks: list[dict[str, Any]] = []
        seen_audio_urls: set[str] = set()
        for track in raw_external_audio:
            track_url = str(track.get("url") or "")
            language = self._canonical_language(track.get("language"))
            if not track_url or track_url in seen_audio_urls:
                continue
            normalized = dict(track)
            normalized["language"] = language or str(track.get("language") or "und")
            external_audio_tracks.append(normalized)
            seen_audio_urls.add(track_url)
        if language_pack and self.analysis_info:
            if output_mode == "_legacy_mkv":
                selector, selected_languages, audio_extra_count = self._build_language_pack_selector(
                    row,
                    self.analysis_info,
                    has_postmerge_audio=bool(external_audio_tracks),
                )
            elif external_audio_tracks and not row.get("has_audio") and row.get("format_id"):
                selector = str(row["format_id"])
            subtitle_languages = self._select_subtitle_languages(self.analysis_info)
            for subtitle in external_subtitles:
                language = str(subtitle.get("language") or "")
                if language and language not in subtitle_languages:
                    subtitle_languages.append(language)
        sidecar_subtitle_tracks = (
            self._build_sidecar_subtitle_tracks(self.analysis_info or {}, external_subtitles)
            if language_pack else []
        )

        source_title = self.current_context.get("title", "") if context_matches else ""
        media_info = self._primary_media_info(self.analysis_info or {})
        extracted_title = media_info.get("title") or ""
        page_identity = str(self.current_context.get("pageUrl") or url)
        custom_output_name = self.output_name_var.get().strip()
        if custom_output_name:
            chosen_title = custom_output_name
        elif is_usable_source_title(source_title):
            chosen_title = str(source_title)
        elif is_usable_source_title(extracted_title):
            chosen_title = str(extracted_title)
        else:
            chosen_title = title_from_page_url(page_identity)
        display_title = safe_source_filename(chosen_title)
        # Keep every generated path below conservative Windows/FFmpeg limits,
        # including `.part`, `.ytdl`, subtitle and sidecar suffixes.
        max_title_length = max(48, min(110, 205 - len(str(output_dir))))
        display_title = display_title[:max_title_length].rstrip(" .") or "Video"
        literal_title = display_title.replace("%", "%%")
        short_id = hashlib.sha1(page_identity.encode("utf-8", "ignore")).hexdigest()[:10]
        output_template = f"{literal_title} [{short_id}].%(ext)s"
        sidecar_root = output_dir / f"{display_title} - Ek Dosyalar"
        subtitle_template = str(
            sidecar_root / "Altyazi" / f"{display_title.replace('%', '%%')}.%(language)s.%(ext)s"
        )

        output_templates = {"default": output_template}
        if output_mode in {"sidecar", "auto_mkv", "auto_mp4"}:
            output_templates["subtitle"] = subtitle_template
        opts = self._base_ydl_options()
        # External audio is normalized with FFmpeg after the main media file is
        # downloaded. yt-dlp must not save an extensionless playlist as .m4a.
        opts.pop("_app_external_audio_tracks", None)
        if output_mode in {"sidecar", "auto_mkv", "auto_mp4"}:
            opts.pop("_app_external_subtitles", None)
        opts.update(
            {
                "format": selector,
                "paths": {"home": str(output_dir)},
                "outtmpl": output_templates,
                "windowsfilenames": True,
                "trim_file_name": 140,
                "continuedl": True,
                "overwrites": False,
                "retries": 10,
                "fragment_retries": 10,
                "file_access_retries": 12,
                "concurrent_fragment_downloads": 4,
                "merge_output_format": "mp4",
                "noplaylist": True,
            }
        )
        if self.prepared_analysis_url and self.prepared_analysis_url != url:
            opts["_app_download_url"] = self.prepared_analysis_url
            opts["enable_file_urls"] = True
        if row.get("audio_mp3"):
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        elif language_pack:
            if output_mode == "_legacy_mkv":
                opts.update(
                    {
                        "allow_multiple_audio_streams": True,
                        "_app_resilient_subtitles": True,
                        "_app_external_subtitles": external_subtitles,
                        "writesubtitles": True,
                        "writeautomaticsub": self.auto_subs_var.get(),
                        "subtitleslangs": subtitle_languages or ["tr", "en"],
                        "subtitlesformat": "srt/ass/vtt/best",
                        "final_ext": "mkv",
                        "postprocessors": [
                            {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"},
                            {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
                            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
                            {
                                "key": "FFmpegMetadata",
                                "add_metadata": True,
                                "add_chapters": True,
                                "add_infojson": False,
                            },
                        ],
                    }
                )
            postmerge_languages = [
                self._canonical_language(track.get("language")) or "belirsiz"
                for track in external_audio_tracks
            ]
            all_languages = list(dict.fromkeys([*selected_languages, *[code.upper() for code in postmerge_languages]]))
            language_note = ", ".join(all_languages) if all_languages else "kaynak ses"
            subtitle_note = ", ".join(subtitle_languages) if subtitle_languages else "bulunursa TR/EN"
            output_note = ({"sidecar": "ayrı Ses/ ve Altyazi/ klasörleri", "auto_mkv": "yan dosyalar + otomatik MKV", "auto_mp4": "yan dosyalar + otomatik MP4"}.get(output_mode, "ayrı dosyalar"))
            self._append_log(
                f"Çoklu dil paketi: {language_note}; "
                f"{audio_extra_count + len(external_audio_tracks)} ek ses izi; "
                f"altyazı: {subtitle_note}; {output_note}."
            )
            self._append_log("Bir altyazı 429/403 verirse atlanacak; video indirmesi devam edecek.")
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = str(Path(self.ffmpeg_path).parent)

        quality = self.quality_var.get()
        if quality.startswith("Özel:"):
            quality = row.get("resolution") or row.get("label") or "Özel"
        duplicate = next(
            (
                existing for existing in self.jobs.values()
                if existing.job_type == "video"
                and existing.url == url
                and existing.quality == str(quality)
                and existing.status in {"queued", "downloading", "processing", "finalizing", "pausing", "paused"}
            ),
            None,
        )
        if duplicate:
            self.main_tabs.set("İndirmeler")
            self._on_main_tab_change()
            self._set_job_filter("all")
            if self.job_tree.exists(duplicate.id):
                self.job_tree.selection_set(duplicate.id)
                self.job_tree.see(duplicate.id)
            messagebox.showinfo(
                "Zaten kuyrukta",
                "Aynı URL ve kalite için etkin/kuyrukta bir indirme zaten var. "
                "Aynı .part dosyasına iki işin yazması engellendi.",
            )
            return
        job = DownloadJob(
            id=uuid.uuid4().hex,
            url=url,
            title=display_title,
            quality=str(quality),
            format_label=str(row.get("label") or quality),
            output_dir=str(output_dir),
            ydl_opts=opts,
            external_audio_tracks=external_audio_tracks,
            external_subtitle_tracks=sidecar_subtitle_tracks,
            resume_headers={
                key: str(value) for key, value in (opts.get("http_headers") or {}).items()
                if key in {"Referer", "Origin", "User-Agent"}
            },
            output_mode=output_mode,
            status="queued" if start_immediately else "paused",
        )
        self.jobs[job.id] = job
        if start_immediately:
            self.pending_job_ids.append(job.id)
        action_text = "İndirme başlatıldı" if start_immediately else "Daha sonra için duraklatılmış kuyruğa eklendi"
        self._append_log(f"{action_text}: {display_title} • {quality} • {row['label']}")
        self.status_var.set(f"{action_text}: {display_title}")
        self.main_tabs.set("İndirmeler")
        self._on_main_tab_change()
        self._refresh_job_table()
        self._pump_download_queue()

    def _job_download_worker(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.job_type == "mux":
            try:
                self.event_queue.put(("job_stage", job_id, "processing", "Ses ve altyazı izleri birleştiriliyor…"))
                filepath = self._run_mux_job(job)
                self.event_queue.put(("job_completed", job_id, filepath))
            except Exception as exc:
                if job.cancel_event.is_set():
                    self.event_queue.put(("job_state", job_id, "cancelled", ""))
                else:
                    self.event_queue.put(("job_state", job_id, "failed", clean_text(exc, 1600)))
            finally:
                self.event_queue.put(("job_worker_finished", job_id))
            return
        if job.job_type == "audio":
            try:
                self.event_queue.put(
                    ("job_stage", job_id, "downloading", "Ayrı ses kuyruğu başlatıldı; HLS parçaları kontrol ediliyor…")
                )
                created = self._download_external_audio_sidecars(
                    job, job.parent_filepath or job.filepath
                )
                filepath = created[0] if created else job.filepath
                self.event_queue.put(("job_completed", job_id, filepath))
            except Exception as exc:
                if job.cancel_event.is_set():
                    self.event_queue.put(("job_state", job_id, "cancelled", ""))
                elif job.pause_event.is_set():
                    self.event_queue.put(("job_state", job_id, "paused", ""))
                else:
                    self.event_queue.put(("job_state", job_id, "failed", clean_text(exc, 1400)))
            finally:
                job.sidecar_only = False
                self.event_queue.put(("job_worker_finished", job_id))
            return
        if job.job_type == "subtitle":
            try:
                self.event_queue.put(
                    ("job_stage", job_id, "downloading", "Ayrı altyazı kuyruğu indiriliyor…")
                )
                filepath = self._download_external_subtitle_sidecar(job)
                self.event_queue.put(("job_completed", job_id, filepath))
            except Exception as exc:
                if job.cancel_event.is_set():
                    self.event_queue.put(("job_state", job_id, "cancelled", ""))
                elif job.pause_event.is_set():
                    self.event_queue.put(("job_state", job_id, "paused", ""))
                else:
                    self.event_queue.put(("job_state", job_id, "failed", clean_text(exc, 1400)))
            finally:
                job.sidecar_only = False
                self.event_queue.put(("job_worker_finished", job_id))
            return
        if job.sidecar_only:
            try:
                self.event_queue.put(
                    ("job_stage", job_id, "downloading", "Yarım kalan ayrı ses parçaları devam ettiriliyor…")
                )
                self._download_external_audio_sidecars(job, job.filepath)
                self.event_queue.put(("job_completed", job_id, job.filepath))
            except Exception as exc:
                if job.cancel_event.is_set():
                    self.event_queue.put(("job_state", job_id, "cancelled", ""))
                elif job.pause_event.is_set():
                    self.event_queue.put(("job_state", job_id, "paused", ""))
                else:
                    self.event_queue.put(("job_state", job_id, "failed", clean_text(exc, 1400)))
            finally:
                job.sidecar_only = False
                self.event_queue.put(("job_worker_finished", job_id))
            return
        options = dict(job.ydl_opts)
        options["logger"] = QueueLogger(self.event_queue, job.title)
        cookie_stream = options.get("cookiefile")
        if isinstance(cookie_stream, io.StringIO):
            options["cookiefile"] = io.StringIO(cookie_stream.getvalue())
        options["progress_hooks"] = [self._make_job_progress_hook(job_id)]
        options["postprocessor_hooks"] = [self._make_job_postprocessor_hook(job_id)]
        download_url = options.pop("_app_download_url", job.url)
        try:
            result = self._extract_with_cookie_fallback(download_url, options, download=True)
            if job.cancel_event.is_set():
                self.event_queue.put(("job_state", job_id, "cancelled", ""))
            elif job.pause_event.is_set():
                self.event_queue.put(("job_state", job_id, "paused", ""))
            elif not result:
                raise DownloadError("İndirme sonucu alınamadı")
            else:
                filepath = self._find_job_media_file(job, result)
                if filepath:
                    job.filepath = filepath
                    job.related_files.add(filepath)
                if job.output_mode in {"sidecar", "auto_mkv", "auto_mp4"}:
                    if not filepath and (job.external_audio_tracks or job.external_subtitle_tracks):
                        raise DownloadError("Yan ses/altyazı işleri oluşturulmadan önce ana video bulunamadı")
                    if job.external_audio_tracks:
                        self.event_queue.put(
                            ("spawn_audio_jobs", job_id, filepath, list(job.external_audio_tracks))
                        )
                    if job.external_subtitle_tracks:
                        self.event_queue.put(
                            ("spawn_subtitle_jobs", job_id, filepath, list(job.external_subtitle_tracks))
                        )
                elif job.external_audio_tracks:
                    if not filepath:
                        raise DownloadError("Harici sesler işlenmeden önce ana video dosyası bulunamadı")
                    self.event_queue.put(
                        ("job_stage", job_id, "processing", "Harici ses izleri doğrulanıyor ve ekleniyor…")
                    )
                    filepath = self._merge_external_audio_tracks(job, filepath)
                self.event_queue.put(("job_completed", job_id, filepath))
        except Exception as exc:
            if job.cancel_event.is_set():
                self.event_queue.put(("job_state", job_id, "cancelled", ""))
            elif job.pause_event.is_set():
                self.event_queue.put(("job_state", job_id, "paused", ""))
            else:
                recovered = self._recover_completed_part(job, exc)
                if recovered:
                    job.filepath = recovered
                    if job.output_mode in {"sidecar", "auto_mkv", "auto_mp4"}:
                        if job.external_audio_tracks:
                            self.event_queue.put(
                                ("spawn_audio_jobs", job_id, recovered, list(job.external_audio_tracks))
                            )
                        if job.external_subtitle_tracks:
                            self.event_queue.put(
                                ("spawn_subtitle_jobs", job_id, recovered, list(job.external_subtitle_tracks))
                            )
                    self.event_queue.put(("job_completed", job_id, recovered))
                else:
                    self.event_queue.put(("job_state", job_id, "failed", clean_text(exc, 1400)))
        finally:
            if is_youtube_url(job.url) and self.extension_cookie_text:
                job.ydl_opts["cookiefile"] = io.StringIO(self.extension_cookie_text)
            self.event_queue.put(("job_worker_finished", job_id))

    def _make_job_progress_hook(self, job_id: str):
        subtitle_exts = {".srt", ".vtt", ".ass", ".lrc", ".ttml", ".srv1", ".srv2", ".srv3"}

        def hook(data: dict[str, Any]) -> None:
            job = self.jobs.get(job_id)
            if not job:
                raise RuntimeError("__APP_CANCEL__")
            for key in ("filename", "tmpfilename"):
                value = data.get(key)
                if value:
                    job.related_files.add(str(value))
            if job.cancel_event.is_set():
                raise RuntimeError("__APP_CANCEL__")
            if job.pause_event.is_set():
                raise RuntimeError("__APP_PAUSE__")
            filename = str(data.get("filename") or "")
            is_subtitle = Path(filename).suffix.lower() in subtitle_exts
            status = data.get("status")
            if status == "downloading" and not is_subtitle:
                fragment_count = int(data.get("fragment_count") or 0)
                fragment_index = int(data.get("fragment_index") or 0)
                downloaded = int(data.get("downloaded_bytes") or 0)
                if fragment_count:
                    # Byte estimates extrapolate an existing completed .part at
                    # fragment 0 and can incorrectly display 80+ GiB. Fragment
                    # progress is stable for HLS VOD.
                    fraction = min(1.0, max(0.0, fragment_index / fragment_count))
                    total = int(data.get("total_bytes") or 0)
                else:
                    total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                    fraction = min(1.0, downloaded / total) if total else job.progress
                now = time.monotonic()
                if now - job.last_progress_emit < 0.15 and fraction < 1.0:
                    return
                job.last_progress_emit = now
                eta = data.get("eta")
                self.event_queue.put(
                    (
                        "job_progress",
                        job_id,
                        fraction,
                        downloaded,
                        total,
                        float(data.get("speed") or 0),
                        int(eta) if isinstance(eta, (int, float)) else None,
                        fragment_index,
                        fragment_count,
                    )
                )
            elif status == "finished" and not is_subtitle:
                self.event_queue.put(("job_stage", job_id, "processing", "Dosya indirildi; işleniyor…"))

        return hook

    def _make_job_postprocessor_hook(self, job_id: str):
        def hook(data: dict[str, Any]) -> None:
            job = self.jobs.get(job_id)
            if not job:
                return
            info = data.get("info_dict") or {}
            for key in ("filepath", "_filename"):
                value = info.get(key)
                if value:
                    job.related_files.add(str(value))
            if data.get("status") == "started":
                name = clean_text(data.get("postprocessor") or "FFmpeg", 80)
                self.event_queue.put(("job_stage", job_id, "processing", f"İşleniyor: {name}"))
        return hook

    def _find_job_media_file(self, job: DownloadJob, result: dict[str, Any]) -> str:
        def collect(info: Any) -> None:
            if not isinstance(info, dict):
                return
            for key in ("filepath", "_filename"):
                value = info.get(key)
                if value:
                    job.related_files.add(str(value))
            for key in ("requested_downloads", "requested_formats", "entries"):
                for child in info.get(key) or []:
                    collect(child)

        collect(result)
        root = Path(job.output_dir)
        try:
            for path in root.glob(f"{job.title}*"):
                if path.is_file():
                    job.related_files.add(str(path))
        except OSError:
            pass
        candidates: list[Path] = []
        for raw_path in job.related_files:
            try:
                path = Path(raw_path)
                if path.is_file() and path.suffix.lower() in MEDIA_FILE_EXTENSIONS:
                    candidates.append(path)
            except OSError:
                continue
        if not candidates:
            return ""
        probed_video = [path for path in candidates if self._ffprobe_video_count(path) > 0]
        if probed_video:
            candidates = probed_video
        priority = {".mkv": 7, ".mp4": 6, ".webm": 5, ".mov": 4, ".m4v": 4, ".avi": 3, ".ts": 2, ".m2ts": 2, ".m4a": 1, ".mp3": 1, ".mka": 1}
        candidates.sort(
            key=lambda path: (priority.get(path.suffix.lower(), 0), path.stat().st_mtime), reverse=True
        )
        return str(candidates[0])

    def _recover_completed_part(self, job: DownloadJob, error: Any, *, emit_events: bool = True) -> str:
        message = clean_text(error, 2400).lower()
        if "unable to rename file" not in message and "winerror 32" not in message:
            return ""
        root = Path(job.output_dir)
        candidates: set[Path] = set()
        for raw_path in job.related_files:
            path = Path(raw_path)
            if str(path).lower().endswith(".part"):
                candidates.add(path)
        try:
            candidates.update(path for path in root.glob(f"{job.title}*.part") if path.is_file())
        except OSError:
            pass
        candidates = {path for path in candidates if path.is_file() and path.stat().st_size > 0}
        if not candidates:
            return ""
        part = max(candidates, key=lambda path: path.stat().st_size)
        final_path = Path(str(part)[:-5])

        def finalized_ok(path: Path) -> bool:
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            ffprobe_available = bool(find_ffprobe(self.ffmpeg_path))
            return self._ffprobe_video_count(path) > 0 if ffprobe_available else True

        if emit_events:
            self.event_queue.put(
                ("job_stage", job.id, "finalizing", "İndirme tamamlandı; kilitli .part dosyası doğrulanıp adlandırılıyor…")
            )
        gc.collect()
        last_error = ""
        for attempt in range(12):
            try:
                if final_path.exists() and final_path.stat().st_size == part.stat().st_size and finalized_ok(final_path):
                    part.unlink(missing_ok=True)
                    job.related_files.add(str(final_path))
                    return str(final_path)
                os.replace(part, final_path)
                if finalized_ok(final_path):
                    job.related_files.discard(str(part))
                    job.related_files.add(str(final_path))
                    return str(final_path)
                last_error = "Adlandırılan dosyada geçerli video stream bulunamadı"
                os.replace(final_path, part)
            except OSError as exc:
                last_error = clean_text(exc, 300)
                time.sleep(min(4.0, 0.5 + attempt * 0.35))
        # Antivirus/indexer locks can allow reading while denying rename. Copy
        # to the final name as a last resort, then verify size before deleting.
        try:
            shutil.copy2(part, final_path)
            if final_path.is_file() and final_path.stat().st_size == part.stat().st_size and finalized_ok(final_path):
                part.unlink(missing_ok=True)
                job.related_files.discard(str(part))
                job.related_files.add(str(final_path))
                return str(final_path)
        except OSError as exc:
            last_error = clean_text(exc, 300)
        self.event_queue.put(("log", f"[{job.title}] Kilitli .part dosyası sonlandırılamadı: {last_error}"))
        return ""

    def _ffprobe_stream_count(self, path: Path, stream_selector: str) -> int:
        ffprobe = find_ffprobe(self.ffmpeg_path)
        if not ffprobe:
            return 0
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", stream_selector, "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            return len([line for line in result.stdout.splitlines() if line.strip()]) if result.returncode == 0 else 0
        except (OSError, subprocess.SubprocessError):
            return 0

    def _ffprobe_audio_count(self, path: Path) -> int:
        return self._ffprobe_stream_count(path, "a")

    def _ffprobe_audio_languages(self, path: Path) -> list[str]:
        ffprobe = find_ffprobe(self.ffmpeg_path)
        if not ffprobe:
            return []
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream_tags=language", "-of", "json", str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            if result.returncode != 0:
                return []
            data = json.loads(result.stdout or "{}")
            return [
                self._canonical_language((stream.get("tags") or {}).get("language"))
                for stream in data.get("streams") or []
                if (stream.get("tags") or {}).get("language")
            ]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return []

    def _ffprobe_video_count(self, path: Path) -> int:
        return self._ffprobe_stream_count(path, "v")

    def _ffprobe_duration(self, path: Path) -> float:
        ffprobe = find_ffprobe(self.ffmpeg_path)
        if not ffprobe:
            return 0.0
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            return float(result.stdout.strip() or 0) if result.returncode == 0 else 0.0
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0

    def _run_mux_job(self, job: DownloadJob) -> str:
        ffmpeg = self.ffmpeg_path or find_ffmpeg()
        if not ffmpeg:
            raise DownloadError("Birleştirme için FFmpeg bulunamadı")
        video = Path(job.mux_video_path)
        output = Path(job.mux_output_path)
        audio_tracks = [track for track in job.mux_audio_tracks if Path(track.get("path", "")).is_file()]
        subtitle_tracks = [track for track in job.mux_subtitle_tracks if Path(track.get("path", "")).is_file()]
        if not video.is_file() or not (audio_tracks or subtitle_tracks):
            raise DownloadError("Ana video veya eklenecek izler bulunamadı")
        if output.resolve() == video.resolve():
            raise DownloadError("Çıktı dosyası ana video ile aynı olamaz")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_name(f".{output.stem}.mux-part{output.suffix}")
        command = [str(ffmpeg), "-hide_banner", "-y", "-i", str(video)]
        for track in audio_tracks:
            command.extend(["-i", track["path"]])
        for track in subtitle_tracks:
            command.extend(["-i", track["path"]])
        # The explicit list is authoritative: preserve base video/audio, then
        # add every listed audio/subtitle. Standalone SRT/VTT inputs are mapped
        # by stream index 0 so unusual demuxer labels cannot make them vanish.
        command.extend(["-map", "0:v:0?", "-map", "0:a?"])
        audio_input_start = 1
        subtitle_input_start = 1 + len(audio_tracks)
        for index in range(len(audio_tracks)):
            command.extend(["-map", f"{audio_input_start + index}:a:0"])
        for index in range(len(subtitle_tracks)):
            command.extend(["-map", f"{subtitle_input_start + index}:0"])
        command.extend(["-map_metadata", "0", "-map_chapters", "0", "-c:v", "copy"])
        if job.mux_container == "mp4":
            command.extend(["-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", "-movflags", "+faststart"])
        else:
            command.extend(["-c:a", "copy", "-c:s", "srt"])
        base_audio_count = self._ffprobe_audio_count(video)
        base_subtitle_count = 0
        language_map = {"tr": "tur", "en": "eng"}
        for index, track in enumerate(audio_tracks):
            stream_index = base_audio_count + index
            language = self._canonical_language(track.get("language")) or "und"
            command.extend([
                f"-metadata:s:a:{stream_index}", f"language={language_map.get(language, language)}",
                f"-metadata:s:a:{stream_index}", f"title={track.get('label') or language.upper()}",
                f"-disposition:a:{stream_index}", "0",
            ])
        for index, track in enumerate(subtitle_tracks):
            stream_index = base_subtitle_count + index
            language = self._canonical_language(track.get("language")) or "und"
            command.extend([
                f"-metadata:s:s:{stream_index}", f"language={language_map.get(language, language)}",
                f"-metadata:s:s:{stream_index}", f"title={track.get('label') or language.upper()}",
                f"-disposition:s:{stream_index}", "0",
            ])
        if subtitle_tracks:
            command.extend(["-disposition:s:0", "default"])
        command.extend(["-progress", "pipe:1", "-nostats", str(temp_output)])
        duration = self._ffprobe_duration(video)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        output_lines: deque[str] = deque(maxlen=80)
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            output_lines.append(line)
            if job.cancel_event.is_set():
                process.terminate()
                process.wait(timeout=10)
                raise RuntimeError("__APP_CANCEL__")
            if line.startswith(("out_time_us=", "out_time_ms=")) and duration > 0:
                try:
                    microseconds = int(line.split("=", 1)[1])
                    fraction = min(1.0, microseconds / (duration * 1_000_000))
                    self.event_queue.put(("job_progress", job.id, fraction, 0, 0, 0.0, None))
                except ValueError:
                    pass
        return_code = process.wait()
        if return_code != 0 or not temp_output.is_file():
            temp_output.unlink(missing_ok=True)
            raise DownloadError("FFmpeg birleştirme hatası: " + clean_text("\n".join(output_lines), 1400))
        os.replace(temp_output, output)
        if subtitle_tracks:
            subtitle_count = self._ffprobe_stream_count(output, "s")
            if subtitle_count < len(subtitle_tracks):
                raise DownloadError(
                    f"Birleştirme altyazı doğrulaması başarısız: beklenen {len(subtitle_tracks)}, "
                    f"bulunan {subtitle_count}. Kaynak dosyalar korunuyor."
                )
            self.event_queue.put(
                ("log", f"[{job.title}] Final altyazı doğrulaması: {subtitle_count} iz başarıyla gömüldü.")
            )
        job.related_files.add(str(output))
        return str(output)

    def _write_hls_manifest_text(self, text: str, base_url: str, target: Path) -> Path | None:
        text = str(text or "").lstrip("\ufeff")
        if not re.match(r"^\s*#EXTM3U", text, flags=re.IGNORECASE):
            return None

        def replace_uri(match: re.Match[str]) -> str:
            absolute = urllib.parse.urljoin(base_url, match.group(1))
            return f'URI="{absolute}"'

        rewritten: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                rewritten.append("")
            elif line.startswith("#"):
                rewritten.append(re.sub(r'URI="([^"]+)"', replace_uri, raw_line, flags=re.IGNORECASE))
            else:
                rewritten.append(urllib.parse.urljoin(base_url, line))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        return target

    def _fetch_hls_playlist_to_local(
        self, url: str, target: Path, headers: dict[str, str]
    ) -> Path | None:
        text = ""
        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                url,
                headers=headers,
                impersonate="chrome",
                timeout=40,
                allow_redirects=True,
            )
            if response.status_code < 400:
                text = response.text
        except Exception:
            text = ""
        if not text:
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=40) as response:
                    text = response.read(4 * 1024 * 1024).decode("utf-8", "replace")
            except Exception:
                return None
        return self._write_hls_manifest_text(text, url, target)

    def _download_resource_resumable(
        self, url: str, destination: Path, headers: dict[str, str], job: DownloadJob
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        partial = destination.with_suffix(destination.suffix + ".part")
        last_error = ""
        for attempt in range(4):
            if job.cancel_event.is_set():
                raise RuntimeError("__APP_CANCEL__")
            if job.pause_event.is_set():
                raise RuntimeError("__APP_PAUSE__")
            start = partial.stat().st_size if partial.is_file() else 0
            request_headers = dict(headers)
            if start:
                request_headers["Range"] = f"bytes={start}-"
            try:
                from curl_cffi import requests as curl_requests

                response = curl_requests.get(
                    url,
                    headers=request_headers,
                    impersonate="chrome",
                    timeout=45,
                    allow_redirects=True,
                    stream=True,
                )
                if response.status_code >= 400:
                    raise OSError(f"HTTP {response.status_code}")
                if start and response.status_code != 206:
                    partial.unlink(missing_ok=True)
                    start = 0
                mode = "ab" if start else "wb"
                written = start
                expected = int(response.headers.get("content-length") or 0) + start
                with partial.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        if job.cancel_event.is_set():
                            response.close()
                            raise RuntimeError("__APP_CANCEL__")
                        if job.pause_event.is_set():
                            response.close()
                            raise RuntimeError("__APP_PAUSE__")
                        if chunk:
                            output.write(chunk)
                            written += len(chunk)
                response.close()
                if expected and written < expected:
                    raise OSError(f"Eksik kaynak: {written}/{expected} bayt")
                os.replace(partial, destination)
                return destination
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = clean_text(exc, 300)
                time.sleep(1 + attempt * 2)
        raise DownloadError(f"Kaynak indirilemedi: {last_error}")

    def _materialize_hls_playlist(
        self, track: dict[str, Any], cache_dir: Path, job: DownloadJob
    ) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            key: str(value).replace("\r", "").replace("\n", "")
            for key, value in (job.ydl_opts.get("http_headers") or {}).items()
            if key in {"Referer", "Origin", "User-Agent"} and value
        }
        cookie_header = str(track.get("cookieHeader") or "").replace("\r", "").replace("\n", "")
        if cookie_header:
            headers["Cookie"] = cookie_header
        current_url = str(track.get("url") or "")
        source_playlist = None
        for depth in range(3):
            cached_source = cache_dir / f"source-{depth}.m3u8"
            if cached_source.is_file() and cached_source.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff").startswith("#EXTM3U"):
                source_playlist = cached_source
            else:
                source_playlist = self._fetch_hls_playlist_to_local(
                    current_url, cached_source, headers
                )
            if not source_playlist:
                raise DownloadError("HLS playlist alınamadı")
            lines = source_playlist.read_text(encoding="utf-8", errors="replace").splitlines()
            variants: list[tuple[int, str]] = []
            for index, line in enumerate(lines):
                if not line.startswith("#EXT-X-STREAM-INF"):
                    continue
                match = re.search(r"BANDWIDTH=(\d+)", line)
                bandwidth = int(match.group(1)) if match else 0
                for candidate in lines[index + 1:]:
                    candidate = candidate.strip()
                    if candidate and not candidate.startswith("#"):
                        variants.append((bandwidth, candidate))
                        break
            if not variants:
                break
            current_url = max(variants, key=lambda item: item[0])[1]
        if not source_playlist:
            raise DownloadError("HLS media playlist bulunamadı")

        lines = source_playlist.read_text(encoding="utf-8", errors="replace").splitlines()
        resource_urls: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                resource_urls.append(stripped)
            if stripped.startswith("#"):
                resource_urls.extend(re.findall(r'URI="([^"]+)"', stripped, flags=re.IGNORECASE))
        unique_urls = list(dict.fromkeys(resource_urls))
        mapping: dict[str, Path] = {}
        for index, resource_url in enumerate(unique_urls):
            suffix = Path(urllib.parse.urlsplit(resource_url).path).suffix or ".bin"
            mapping[resource_url] = cache_dir / f"resource-{index + 1:05d}{suffix}"

        completed = 0
        lock = threading.Lock()

        def fetch(resource_url: str) -> Path:
            return self._download_resource_resumable(resource_url, mapping[resource_url], headers, job)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fetch, url): url for url in unique_urls}
            for future in as_completed(futures):
                future.result()
                with lock:
                    completed += 1
                    self.event_queue.put(
                        (
                            "job_stage",
                            job.id,
                            "downloading",
                            f"{track.get('label') or track.get('language') or 'İz'}: "
                            f"{completed}/{len(unique_urls)} HLS parçası hazır",
                        )
                    )
                    self.event_queue.put(
                        (
                            "job_progress",
                            job.id,
                            completed / max(1, len(unique_urls)),
                            0,
                            0,
                            0.0,
                            None,
                            completed,
                            len(unique_urls),
                        )
                    )

        def replace_uri(match: re.Match[str]) -> str:
            original = match.group(1)
            return f'URI="{mapping[original].name}"' if original in mapping else match.group(0)

        localized: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped in mapping:
                localized.append(mapping[stripped].name)
            elif stripped.startswith("#"):
                localized.append(re.sub(r'URI="([^"]+)"', replace_uri, line, flags=re.IGNORECASE))
            else:
                localized.append(line)
        local_playlist = cache_dir / "local-resumable.m3u8"
        local_playlist.write_text("\n".join(localized) + "\n", encoding="utf-8")
        return local_playlist

    def _download_external_audio_sidecars(self, job: DownloadJob, media_path: str) -> list[str]:
        ffmpeg = self.ffmpeg_path or find_ffmpeg()
        if not ffmpeg:
            raise DownloadError("Harici sesleri ayrı kaydetmek için FFmpeg bulunamadı")
        package_title = job.package_title or job.title
        sidecar_root = Path(job.output_dir) / f"{package_title} - Ek Dosyalar"
        audio_dir = sidecar_root / "Ses"
        subtitle_dir = sidecar_root / "Altyazi"
        audio_dir.mkdir(parents=True, exist_ok=True)
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        base_headers = {
            key: str(value).replace("\r", "").replace("\n", "")
            for key, value in (job.ydl_opts.get("http_headers") or {}).items()
            if key in {"Referer", "Origin", "User-Agent"} and value
        }
        completed_languages: list[str] = []
        created_files: list[str] = []
        errors: list[str] = []
        for index, track in enumerate(job.external_audio_tracks):
            language = self._canonical_language(track.get("language")) or f"und{index + 1}"
            display_language = {"tr": "Turkce", "en": "English"}.get(language, language)
            label = safe_source_filename(track.get("label") or display_language)
            final_audio = audio_dir / f"{display_language} - {label}.mka"
            if final_audio.is_file() and self._ffprobe_audio_count(final_audio) > 0:
                completed_languages.append(language)
                created_files.append(str(final_audio))
                job.related_files.add(str(final_audio))
                continue
            stable_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(str(track.get("url") or ""))[:3], "", ""))
            cache_hash = hashlib.sha1(stable_url.encode("utf-8", "ignore")).hexdigest()[:12]
            cache_dir = audio_dir / f".parts-{language}-{cache_hash}"
            try:
                if track.get("isHls") or track.get("ext") == "m3u8" or track.get("fullSource"):
                    input_source = self._materialize_hls_playlist(track, cache_dir, job)
                    command = [
                        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "hls", "-allowed_extensions", "ALL",
                        "-allowed_segment_extensions", "ALL", "-extension_picky", "0",
                        "-protocol_whitelist", "file,crypto,data", "-i", str(input_source),
                        "-map", "0:a:0", "-vn", "-c:a", "copy", str(final_audio.with_suffix(".part.mka")),
                    ]
                else:
                    source_ext = Path(urllib.parse.urlsplit(str(track.get("url") or "")).path).suffix or ".bin"
                    direct_headers = dict(base_headers)
                    if track.get("cookieHeader"):
                        direct_headers["Cookie"] = str(track.get("cookieHeader"))
                    raw_source = self._download_resource_resumable(
                        str(track.get("url") or ""), cache_dir / f"source{source_ext}", direct_headers, job
                    )
                    command = [
                        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw_source),
                        "-map", "0:a:0", "-vn", "-c:a", "copy", str(final_audio.with_suffix(".part.mka")),
                    ]
                self.event_queue.put(
                    ("job_stage", job.id, "processing", f"{display_language} ses dosyası oluşturuluyor…")
                )
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                    check=False,
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                )
                partial_audio = final_audio.with_suffix(".part.mka")
                if result.returncode != 0 or not partial_audio.is_file() or self._ffprobe_audio_count(partial_audio) == 0:
                    raise DownloadError(clean_text(result.stderr or "Audio doğrulanamadı", 600))
                os.replace(partial_audio, final_audio)
                completed_languages.append(language)
                created_files.append(str(final_audio))
                job.related_files.add(str(final_audio))
                for child in cache_dir.glob("*"):
                    child.unlink(missing_ok=True)
                cache_dir.rmdir()
            except RuntimeError:
                raise
            except Exception as exc:
                errors.append(f"{display_language}: {clean_text(exc, 500)}")
                self.event_queue.put(("log", f"[{job.title}] Uyarı: {display_language} ayrı ses dosyası tamamlanamadı; parçalar korundu."))

        readme = sidecar_root / "NASIL-KULLANILIR.txt"
        readme.write_text(
            "Video ana klasördedir. Ses klasöründeki MKA dosyasını ve Altyazi klasöründeki SRT dosyasını "
            "VLC/mpv/MPC oynatıcısına sürükleyip bırakabilirsiniz.\n"
            "Yarım HLS parçaları .parts-* klasöründe korunur; aynı URL yeniden analiz edilip kuyruğa "
            "eklendiğinde mevcut parçalar atlanır.\n",
            encoding="utf-8",
        )
        job.related_files.add(str(readme))
        if "en" in {self._canonical_language(track.get("language")) for track in job.external_audio_tracks} and "en" not in completed_languages:
            raise DownloadError("İngilizce ayrı ses dosyası tamamlanamadı: " + "; ".join(errors))
        return created_files

    def _download_external_subtitle_sidecar(self, job: DownloadJob) -> str:
        if not job.external_subtitle_tracks:
            raise DownloadError("Altyazı track bilgisi bulunamadı")
        track = job.external_subtitle_tracks[0]
        language = self._canonical_language(track.get("language")) or "und"
        display_language = {"tr": "Turkce", "en": "English"}.get(language, language)
        label = safe_source_filename(track.get("label") or display_language)
        package_title = job.package_title or job.title
        subtitle_dir = Path(job.output_dir) / f"{package_title} - Ek Dosyalar" / "Altyazi"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        final_srt = subtitle_dir / f"{display_language} - {label}.srt"
        if final_srt.is_file() and final_srt.stat().st_size > 0:
            job.related_files.add(str(final_srt))
            return str(final_srt)

        track_url = str(track.get("url") or "")
        stable_url = urllib.parse.urlunsplit((*urllib.parse.urlsplit(track_url)[:3], "", ""))
        cache_hash = hashlib.sha1(stable_url.encode("utf-8", "ignore")).hexdigest()[:12]
        cache_dir = subtitle_dir / f".parts-{language}-{cache_hash}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            key: str(value).replace("\r", "").replace("\n", "")
            for key, value in (job.ydl_opts.get("http_headers") or {}).items()
            if key in {"Referer", "Origin", "User-Agent"} and value
        }
        if track.get("cookieHeader"):
            headers["Cookie"] = str(track.get("cookieHeader"))
        ext = str(track.get("ext") or "vtt").lower().lstrip(".")
        is_hls = ext == "m3u8" or track.get("isHls") or ".m3u8" in track_url
        if is_hls:
            source = self._materialize_hls_playlist(track, cache_dir, job)
        else:
            source = self._download_resource_resumable(
                track_url, cache_dir / f"source.{ext or 'vtt'}", headers, job
            )
        if ext == "srt" and not is_hls:
            shutil.copy2(source, final_srt)
        else:
            ffmpeg = self.ffmpeg_path or find_ffmpeg()
            if not ffmpeg:
                fallback = final_srt.with_suffix(f".{ext or 'vtt'}")
                shutil.copy2(source, fallback)
                job.related_files.add(str(fallback))
                return str(fallback)
            partial_srt = final_srt.with_suffix(".part.srt")
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y"]
            if is_hls:
                command.extend([
                    "-f", "hls", "-allowed_extensions", "ALL",
                    "-allowed_segment_extensions", "ALL", "-extension_picky", "0",
                    "-protocol_whitelist", "file,crypto,data",
                ])
            command.extend(["-i", str(source), "-map", "0:s:0", "-c:s", "srt", str(partial_srt)])
            self.event_queue.put(
                ("job_stage", job.id, "processing", f"{display_language} altyazı SRT'ye dönüştürülüyor…")
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            if result.returncode != 0 or not partial_srt.is_file() or partial_srt.stat().st_size == 0:
                fallback = final_srt.with_suffix(f".{ext or 'vtt'}")
                shutil.copy2(source, fallback)
                job.related_files.add(str(fallback))
                return str(fallback)
            os.replace(partial_srt, final_srt)
        job.related_files.add(str(final_srt))
        for child in cache_dir.glob("*"):
            child.unlink(missing_ok=True)
        try:
            cache_dir.rmdir()
        except OSError:
            pass
        return str(final_srt)

    def _merge_external_audio_tracks(self, job: DownloadJob, media_path: str) -> str:
        base = Path(media_path)
        ffmpeg = self.ffmpeg_path or find_ffmpeg()
        if not ffmpeg or not base.is_file():
            raise DownloadError("Harici sesleri eklemek için FFmpeg veya ana video bulunamadı")

        headers = job.ydl_opts.get("http_headers") or {}

        work_dir = Path(job.output_dir) / f".acik-audio-{job.id[:10]}"
        work_dir.mkdir(parents=True, exist_ok=True)
        prepared: list[tuple[Path, str, str]] = []
        errors: list[str] = []
        try:
            for index, track in enumerate(job.external_audio_tracks):
                language = self._canonical_language(track.get("language")) or f"und{index + 1}"
                label = clean_text(track.get("label") or language.upper(), 80)
                target = work_dir / f"audio-{index + 1}-{language}.mka"
                track_url = str(track.get("url") or "")
                is_hls = bool(
                    track.get("isHls") or track.get("ext") == "m3u8"
                    or ".m3u8" in track_url or track.get("fullSource")
                )
                request_headers = {
                    key: str(value).replace("\r", "").replace("\n", "")
                    for key, value in headers.items()
                    if key in {"Referer", "Origin", "User-Agent"} and value
                }
                cookie_header = str(track.get("cookieHeader") or "").replace("\r", "").replace("\n", "")
                if cookie_header:
                    request_headers["Cookie"] = cookie_header
                local_playlist = None
                if is_hls:
                    local_playlist = self._fetch_hls_playlist_to_local(
                        track_url,
                        work_dir / f"playlist-{index + 1}-{language}.m3u8",
                        request_headers,
                    )
                input_source = str(local_playlist or track_url)
                command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y"]
                if not local_playlist:
                    command.extend([
                        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                        "-rw_timeout", "30000000",
                    ])
                if is_hls:
                    command.extend([
                        "-f", "hls", "-allowed_extensions", "ALL",
                        "-allowed_segment_extensions", "ALL", "-extension_picky", "0",
                        "-protocol_whitelist", "file,http,https,tcp,tls,crypto,data",
                    ])
                track_header_blob = "\r\n".join(
                    f"{key}: {value}" for key, value in request_headers.items()
                )
                if track_header_blob:
                    command.extend(["-headers", track_header_blob + "\r\n"])
                command.extend([
                    "-i", input_source,
                    "-map", "0:a:0", "-vn", "-c:a", "copy", str(target),
                ])
                success = False
                last_error = ""
                for attempt in range(3):
                    if job.cancel_event.is_set():
                        raise RuntimeError("__APP_CANCEL__")
                    self.event_queue.put(
                        ("job_stage", job.id, "processing", f"{label} ses izi hazırlanıyor ({attempt + 1}/3)…")
                    )
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        check=False,
                        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                    )
                    last_error = clean_text(result.stderr or result.stdout, 500)
                    if result.returncode == 0 and target.is_file() and self._ffprobe_audio_count(target) > 0:
                        success = True
                        break
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                    time.sleep(1 + attempt * 2)
                if success:
                    prepared.append((target, language, label))
                    job.related_files.add(str(target))
                else:
                    errors.append(f"{label}: {last_error or 'geçerli audio stream bulunamadı'}")
                    self.event_queue.put(("log", f"[{job.title}] Uyarı: {label} ses izi atlandı: {last_error}"))

            base_audio_count = self._ffprobe_audio_count(base)
            base_audio_languages = set(self._ffprobe_audio_languages(base))
            requested_languages = {
                self._canonical_language(track.get("language")) for track in job.external_audio_tracks
            }
            prepared_languages = {language for _path, language, _label in prepared}
            if "en" in requested_languages and "en" not in prepared_languages and "en" not in base_audio_languages:
                raise DownloadError(
                    "İngilizce/orijinal ses URL'si yakalandı ancak geçerli audio stream üretmedi. "
                    + "; ".join(errors)
                )
            if not prepared:
                if base_audio_count:
                    self.event_queue.put(("log", f"[{job.title}] Harici sesler doğrulanamadı; mevcut ana ses korunuyor."))
                    return str(base)
                raise DownloadError("Harici ses izleri geçerli medya üretmedi: " + "; ".join(errors))

            final_path = base if base.suffix.lower() == ".mkv" else base.with_suffix(".mkv")
            temp_output = final_path.with_name(f"{final_path.stem}.multiaudio.tmp.mkv")
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(base)]
            for audio_path, _language, _label in prepared:
                command.extend(["-i", str(audio_path)])
            command.extend(["-map", "0"])
            for index in range(len(prepared)):
                command.extend(["-map", f"{index + 1}:a:0"])
            command.extend(["-map_metadata", "0", "-map_chapters", "0", "-c", "copy"])
            language_map = {"tr": "tur", "en": "eng"}
            for index, (_audio_path, language, label) in enumerate(prepared):
                stream_index = base_audio_count + index
                command.extend([
                    f"-metadata:s:a:{stream_index}", f"language={language_map.get(language, language)}",
                    f"-metadata:s:a:{stream_index}", f"title={label}",
                    f"-disposition:a:{stream_index}", "0",
                ])
            if base_audio_count == 0:
                command.extend(["-disposition:a:0", "default"])
            command.append(str(temp_output))
            self.event_queue.put(("job_stage", job.id, "processing", "Doğrulanan ses izleri MKV'ye ekleniyor…"))
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            if result.returncode != 0 or not temp_output.is_file():
                raise DownloadError("FFmpeg çoklu ses birleştirme hatası: " + clean_text(result.stderr, 900))
            if final_path != base:
                final_path.unlink(missing_ok=True)
            os.replace(temp_output, final_path)
            if final_path != base:
                try:
                    base.unlink()
                    job.related_files.discard(str(base))
                except OSError:
                    pass
            job.related_files.add(str(final_path))
            final_audio_count = self._ffprobe_audio_count(final_path)
            final_languages = set(self._ffprobe_audio_languages(final_path))
            expected_count = base_audio_count + len(prepared)
            if final_audio_count and final_audio_count < expected_count:
                raise DownloadError(
                    f"Final MKV ses doğrulaması başarısız: beklenen {expected_count}, bulunan {final_audio_count}"
                )
            if "en" in prepared_languages and final_languages and "en" not in final_languages:
                raise DownloadError("Final MKV içinde İngilizce ses metadata'sı doğrulanamadı")
            self.event_queue.put(
                (
                    "log",
                    f"[{job.title}] Final ses doğrulaması: {final_audio_count or expected_count} iz; "
                    f"diller: {', '.join(sorted(final_languages)) or 'metadata belirtilmemiş'}.",
                )
            )
            return str(final_path)
        finally:
            for audio_path, _language, _label in prepared:
                job.related_files.discard(str(audio_path))
            try:
                for child in work_dir.iterdir():
                    if child.is_file():
                        child.unlink(missing_ok=True)
                work_dir.rmdir()
            except OSError:
                pass

    def _base_ydl_options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": False,
            "logger": QueueLogger(self.event_queue),
            "socket_timeout": 30,
            "extractor_retries": 5,
            "cachedir": True,
        }
        context_url = str(self.current_context.get("url") or self.current_url or "")
        if self.extension_cookie_text and (
            is_youtube_url(context_url) or self.current_context.get("siteCookieCount")
        ):
            # A fresh stream is created for each YoutubeDL instance. Extension
            # cookies stay in memory and are never written to disk/history.
            opts["cookiefile"] = io.StringIO(self.extension_cookie_text)
        else:
            cookie_mode = self.cookie_var.get()
            browser = self.COOKIE_LABELS.get(cookie_mode)
            if browser:
                opts["cookiesfrombrowser"] = (browser,)
            elif cookie_mode == "Dosya" and Path(self.cookie_file_path).is_file():
                opts["cookiefile"] = self.cookie_file_path
        context_page = self.current_context.get("pageUrl", "")
        context_user_agent = self.current_context.get("userAgent", "")
        headers: dict[str, str] = {}
        if context_page and is_http_url(context_page):
            parsed_page = urllib.parse.urlsplit(context_page)
            headers["Referer"] = context_page
            if self.current_context.get("mediaType") in {"hls", "dash", "direct"}:
                headers["Origin"] = f"{parsed_page.scheme}://{parsed_page.netloc}"
        if context_user_agent and "\n" not in context_user_agent and "\r" not in context_user_agent:
            headers["User-Agent"] = context_user_agent[:500]
        media_cookie_header = str(self.current_context.get("mediaCookieHeader") or "").replace("\r", "").replace("\n", "")
        if media_cookie_header and not self.extension_cookie_text:
            # Prefer CookieJar when extension supplied structured cookies.
            # Direct Cookie headers trigger yt-dlp deprecation/security errors.
            headers["Cookie"] = media_cookie_header[:16_384]
        if headers:
            opts["http_headers"] = headers
        if is_youtube_url(context_url):
            opts["sleep_interval_requests"] = 0.75
            visitor_data = clean_text(self.current_context.get("visitorData", ""), 2048)
            if visitor_data:
                opts["extractor_args"] = {
                    "youtube": {"visitor_data": [visitor_data]},
                }
        external_subtitles = self.current_context.get("externalSubtitles") or []
        external_audio_tracks = self.current_context.get("externalAudioTracks") or []
        if external_subtitles:
            opts["_app_external_subtitles"] = list(external_subtitles)
        if external_audio_tracks:
            opts["_app_external_audio_tracks"] = list(external_audio_tracks)
        primary_language = str(self.current_context.get("primaryLanguage") or "")
        if primary_language in {"tr", "en"}:
            opts["_app_primary_language"] = primary_language
        self.deno_path = find_deno()
        if self.deno_path:
            opts["js_runtimes"] = {"deno": {"path": self.deno_path}}
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = str(Path(self.ffmpeg_path).parent)
        return opts

    def _install_deno(self) -> None:
        self.deno_path = find_deno()
        if self.deno_path:
            messagebox.showinfo(
                "Deno hazır",
                f"YouTube JavaScript çalışma zamanı bulundu:\n{self.deno_path}",
            )
            return
        if self.busy_kind:
            messagebox.showinfo("İşlem sürüyor", "Önce mevcut işlemin bitmesini bekleyin.")
            return
        if not messagebox.askyesno(
            "YouTube / Deno kurulumu",
            "Güncel YouTube format desteği için Deno, Windows Package Manager ile "
            "kurulacak. Devam edilsin mi?\n\nPaket: DenoLand.Deno",
        ):
            return
        self._set_busy("deno")
        self.status_var.set("Deno kuruluyor…")
        self._append_log("Deno kurulumu başlatıldı (winget DenoLand.Deno).")
        threading.Thread(target=self._deno_install_worker, daemon=True).start()

    def _deno_install_worker(self) -> None:
        try:
            result = subprocess.run(
                [
                    "winget",
                    "install",
                    "--id",
                    "DenoLand.Deno",
                    "-e",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            output = clean_text(result.stdout or result.stderr, 1800)
            if result.returncode != 0:
                raise RuntimeError(output or f"winget çıkış kodu: {result.returncode}")
            self.event_queue.put(("deno_done", output))
        except FileNotFoundError:
            self.event_queue.put(
                (
                    "operation_error",
                    "Deno kurulamadı",
                    "winget bulunamadı. https://deno.com adresinden Deno 2.3+ kurun.",
                )
            )
        except Exception as exc:
            self.event_queue.put(("operation_error", "Deno kurulamadı", clean_text(exc, 1600)))

    def _update_ffmpeg(self) -> None:
        if self.busy_kind:
            messagebox.showinfo("İşlem sürüyor", "Önce mevcut işlemin bitmesini bekleyin.")
            return
        if self.active_job_ids:
            messagebox.showinfo(
                "İndirme sürüyor",
                "FFmpeg güncellenirken kullanılan dosyalar kilitlenebilir. Önce etkin indirme "
                "ve birleştirme işlerinin tamamlanmasını veya güvenli biçimde durmasını bekleyin.",
            )
            return
        if os.name != "nt":
            messagebox.showerror(
                "FFmpeg güncellenemedi",
                "Uygulama içi FFmpeg güncellemesi Windows Package Manager (winget) kullanır "
                "ve yalnız Windows'ta çalışır.",
            )
            return

        self.ffmpeg_path = find_ffmpeg()
        current_version = ffmpeg_version(self.ffmpeg_path)
        current_note = (
            f"Mevcut sürüm: {current_version or 'algılandı'}"
            if self.ffmpeg_path
            else "FFmpeg bulunamadı; en güncel sürüm kurulacak."
        )
        if not messagebox.askyesno(
            "FFmpeg güncelle / kur",
            "FFmpeg ve FFprobe, Windows Package Manager üzerinden Gyan.FFmpeg "
            "paketinin en güncel sürümüne yükseltilecek. Paket kurulu değilse otomatik "
            f"olarak kurulacak.\n\n{current_note}\n\nDevam edilsin mi?",
        ):
            return

        self.progress.set(0)
        self._set_busy("ffmpeg_update")
        self.status_var.set("FFmpeg güncelleniyor…")
        self._append_log("FFmpeg güncellemesi başlatıldı (winget Gyan.FFmpeg).")
        threading.Thread(
            target=self._ffmpeg_update_worker,
            name="ffmpeg-update",
            daemon=True,
        ).start()

    def _ffmpeg_update_worker(self) -> None:
        try:
            winget = shutil.which("winget")
            if not winget:
                raise FileNotFoundError("winget bulunamadı")

            common_args = [
                "--id",
                "Gyan.FFmpeg",
                "-e",
                "--source",
                "winget",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
            had_ffmpeg = bool(self.ffmpeg_path or find_ffmpeg())
            action = "upgrade" if had_ffmpeg else "install"
            outputs: list[str] = []

            def run_winget(command: str) -> subprocess.CompletedProcess[str]:
                result = subprocess.run(
                    [winget, command, *common_args],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=900,
                    check=False,
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                )
                raw_output = "\n".join(
                    part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
                )
                outputs.append(f"winget {command}:\n{raw_output or '(çıktı yok)'}")
                return result

            result = run_winget(action)
            combined_lower = "\n".join(outputs).lower()
            no_update_markers = (
                "no applicable upgrade found",
                "no available upgrade found",
                "no newer package versions are available",
                "uygulanabilir yükseltme bulunamadı",
                "kullanılabilir yükseltme bulunamadı",
                "daha yeni paket sürümü bulunamadı",
            )
            already_current = any(
                marker in combined_lower for marker in no_update_markers
            )
            unmanaged_markers = (
                "no installed package found matching input criteria",
                "no installed package found",
                "ölçütlerle eşleşen yüklü paket bulunamadı",
                "eşleşen yüklü paket bulunamadı",
            )
            package_not_managed = any(
                marker in combined_lower for marker in unmanaged_markers
            )

            # A manually copied/PATH FFmpeg can exist although WinGet does not
            # own it. In that case `upgrade` cannot update it; install the
            # managed package and prefer that location on component refresh.
            if (
                action == "upgrade"
                and not already_current
                and (result.returncode != 0 or package_not_managed)
            ):
                result = run_winget("install")
                combined_lower = "\n".join(outputs).lower()
                already_current = any(
                    marker in combined_lower for marker in no_update_markers
                )

            if result.returncode != 0 and not already_current:
                raise RuntimeError(
                    clean_text("\n\n".join(outputs), 2400)
                    or f"winget çıkış kodu: {result.returncode}"
                )

            summary = clean_text("\n\n".join(outputs), 2400)
            self.event_queue.put(("ffmpeg_done", summary, already_current))
        except FileNotFoundError:
            self.event_queue.put(
                (
                    "operation_error",
                    "FFmpeg güncellenemedi",
                    "Windows Package Manager (winget) bulunamadı. Microsoft App Installer'ı "
                    "güncelleyin veya Yönetici PowerShell'de şu komutu çalıştırın:\n\n"
                    "winget install --id Gyan.FFmpeg -e",
                )
            )
        except subprocess.TimeoutExpired:
            self.event_queue.put(
                (
                    "operation_error",
                    "FFmpeg güncellenemedi",
                    "winget işlemi 15 dakika içinde tamamlanmadı. İnternet bağlantısını ve "
                    "bekleyen Windows kurulum pencerelerini kontrol edip yeniden deneyin.",
                )
            )
        except Exception as exc:
            self.event_queue.put(
                ("operation_error", "FFmpeg güncellenemedi", clean_text(exc, 2400))
            )

    def _update_ytdlp(self) -> None:
        if self.busy_kind:
            messagebox.showinfo("İşlem sürüyor", "Önce mevcut işlemin bitmesini bekleyin.")
            return
        if IS_FROZEN:
            if not messagebox.askyesno(
                "yt-dlp güncelle",
                "yt-dlp, PyPI'den indirilip EXE yanındaki pylibs klasöründe güncellenecek. "
                "Güncelleme sonrası uygulama yeniden başlatılmalıdır. Devam edilsin mi?",
            ):
                return
            self._set_busy("update")
            self.status_var.set("yt-dlp güncelleniyor…")
            self._append_log("yt-dlp PyPI wheel güncellemesi başlatıldı (pylibs).")
            threading.Thread(target=self._frozen_ytdlp_worker, daemon=True).start()
            return
        if not messagebox.askyesno(
            "yt-dlp güncelle",
            "Etkin Python ortamında yt-dlp en son sürüme yükseltilecek. Devam edilsin mi?",
        ):
            return
        self._set_busy("update")
        self.status_var.set("yt-dlp güncelleniyor…")
        self._append_log("Güncelleme başlatıldı.")
        threading.Thread(target=self._update_worker, daemon=True).start()

    @staticmethod
    def _pypi_latest_wheel(package: str) -> tuple[str, str]:
        """PyPI JSON API'den en güncel wheel sürümünü ve indirme URL'sini döndürür."""
        api = f"https://pypi.org/pypi/{package}/json"
        with urllib.request.urlopen(api, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        version = str(data["info"]["version"])
        for item in data.get("urls", []):
            if item.get("packagetype") == "bdist_wheel":
                return version, str(item["url"])
        raise RuntimeError(f"{package} için PyPI'de wheel bulunamadı")

    @staticmethod
    def _download_to(url: str, target: Path) -> None:
        request = urllib.request.Request(
            url, headers={"User-Agent": f"AcikVideoIndirici/{APP_VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=120) as resp, open(target, "wb") as out:
            shutil.copyfileobj(resp, out)

    def _frozen_ytdlp_worker(self) -> None:
        """Setup sürümü: yt-dlp ve yt-dlp-ejs wheel'lerini PyPI'den indirip
        EXE yanındaki pylibs/ klasörünü yerinde günceller (pip kullanılmaz)."""
        try:
            pylibs = Path(sys.executable).resolve().parent / "pylibs"
            pylibs.mkdir(parents=True, exist_ok=True)
            current = ""
            try:
                import yt_dlp

                current = getattr(getattr(yt_dlp, "version", None), "__version__", "")
            except Exception:
                current = ""
            latest_version, wheel_url = self._pypi_latest_wheel("yt-dlp")
            if current and latest_version == current:
                self.event_queue.put(("update_done", f"yt-dlp zaten güncel ({current})."))
                return
            staging = Path(tempfile.mkdtemp(prefix="avi-ytdlp-"))
            try:
                updated: list[str] = []
                for package in ("yt-dlp", "yt-dlp-ejs"):
                    version, url = self._pypi_latest_wheel(package)
                    wheel_path = staging / url.rsplit("/", 1)[-1]
                    self._download_to(url, wheel_path)
                    extract_dir = staging / f"extract-{package}"
                    with zipfile.ZipFile(wheel_path) as zf:
                        zf.extractall(extract_dir)
                    for entry in sorted(extract_dir.iterdir()):
                        if entry.name.endswith(".data"):
                            # pip metadata/entry-point kabuğu; pylibs'e kopyalanmaz
                            continue
                        target = pylibs / entry.name
                        if entry.is_dir() and entry.name.endswith(".dist-info"):
                            # Eski sürümün dist-info kalıntılarını temizle
                            for old in pylibs.glob(f"{entry.name.split('-')[0]}-*.dist-info"):
                                shutil.rmtree(old, ignore_errors=True)
                        if target.exists():
                            if target.is_dir():
                                shutil.rmtree(target, ignore_errors=True)
                            else:
                                target.unlink(missing_ok=True)
                        shutil.move(str(entry), str(target))
                    updated.append(f"{package} {version}")
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            self.event_queue.put(
                (
                    "update_done",
                    "Güncellendi: " + ", ".join(updated) + ". Yeni sürüm için uygulamayı yeniden başlatın.",
                )
            )
        except Exception as exc:
            self.event_queue.put(
                ("operation_error", "Güncelleme başarısız", clean_text(exc, 1400))
            )

    def _update_worker(self) -> None:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "yt-dlp[default,curl-cffi]",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            output = clean_text(result.stdout or result.stderr, 1600)
            if result.returncode != 0:
                raise RuntimeError(output or f"pip çıkış kodu: {result.returncode}")
            self.event_queue.put(("update_done", output))
        except Exception as exc:
            self.event_queue.put(
                ("operation_error", "Güncelleme başarısız", clean_text(exc, 1400))
            )

    # ----- Bridge and event loop -----

    def _start_bridge(self) -> None:
        ok, message = self.bridge.start()
        self.bridge_var.set(message)
        self._append_log(message)
        if not ok:
            self.bridge_var.set("Tarayıcı köprüsü kapalı (port kullanımda olabilir)")

    def _handle_bridge_open(self, payload: dict[str, Any]) -> None:
        url = payload.get("url", "")
        if not is_http_url(url):
            return
        self.url_var.set(url)
        context = dict(payload)
        raw_youtube_cookies = context.pop("youtubeCookies", [])
        raw_site_cookies = context.pop("siteCookies", [])
        raw_media_cookies = context.pop("mediaCookies", [])
        if is_youtube_url(url) and isinstance(raw_youtube_cookies, list):
            cookie_text = youtube_cookies_to_netscape(raw_youtube_cookies)
            cookie_count = max(0, cookie_text.count("\n") - 3)
            self.extension_cookie_text = cookie_text if cookie_count else ""
        elif isinstance(raw_media_cookies, list) and raw_media_cookies:
            cookie_text = site_cookies_to_netscape(raw_media_cookies, url)
            cookie_count = max(0, cookie_text.count("\n") - 3)
            self.extension_cookie_text = cookie_text if cookie_count else ""
        elif context.get("mediaCookieHeader"):
            cookie_text = cookie_header_to_netscape(str(context.get("mediaCookieHeader")), url)
            cookie_count = max(0, cookie_text.count("\n") - 3)
            self.extension_cookie_text = cookie_text if cookie_count else ""
        elif isinstance(raw_site_cookies, list) and raw_site_cookies:
            cookie_text = site_cookies_to_netscape(raw_site_cookies, url)
            cookie_count = max(0, cookie_text.count("\n") - 3)
            self.extension_cookie_text = cookie_text if cookie_count else ""
        else:
            cookie_count = 0
            self.extension_cookie_text = ""
        context["youtubeCookieCount"] = cookie_count if is_youtube_url(url) else 0
        context["siteCookieCount"] = cookie_count if not is_youtube_url(url) else 0
        self.current_context = context
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(500, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        title = payload.get("title") or "Tarayıcıdaki medya"
        media_type = payload.get("mediaType", "unknown")
        sources = payload.get("captureSources", "")
        kind_labels = {
            "page": "sayfa",
            "hls": "HLS akışı",
            "dash": "DASH akışı",
            "direct": "doğrudan dosya",
            "unknown": "bilinmeyen medya",
        }
        kind = kind_labels.get(media_type, "bilinmeyen medya")
        self.status_var.set(f"Eklentiden alındı: {title}")
        source_note = f", kaynak: {sources}" if sources else ""
        self._append_log(
            f"Tarayıcı eklentisinden {kind} alındı "
            f"({redacted_url_label(url)}{source_note})."
        )
        external_subtitle_count = len(self.current_context.get("externalSubtitles") or [])
        external_audio_count = len(self.current_context.get("externalAudioTracks") or [])
        if external_subtitle_count:
            self._append_log(f"Eklenti bu videoyla ilişkili {external_subtitle_count} harici altyazı yakaladı.")
        if external_audio_count:
            audio_languages = ", ".join(
                str(track.get("language") or "belirsiz")
                for track in self.current_context.get("externalAudioTracks") or []
            )
            self._append_log(
                f"Eklenti bu videoyla ilişkili {external_audio_count} harici ses izi yakaladı: {audio_languages}."
            )
        if is_youtube_url(url):
            visitor_state = "var" if self.current_context.get("visitorData") else "yok"
            auth_state = "giriş yapılmış profil" if self.current_context.get("youtubeAuthenticated") else "misafir profil"
            self._append_log(
                f"YouTube oturum bağlamı: {cookie_count} çerez, Visitor Data {visitor_state}, "
                f"{auth_state}; çerez değerleri yalnız bellekte tutuluyor."
            )
        if self.busy_kind:
            self.status_var.set("Eklenti adresi kutuya yerleştirildi; mevcut işlem bitince analiz edin.")
        else:
            self._start_analysis()

    def _poll_events(self) -> None:
        try:
            for _ in range(120):
                event = self.event_queue.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "status":
                    self.status_var.set(event[1])
                elif kind == "progress":
                    fraction, text = event[1], event[2]
                    if fraction >= 0:
                        self.progress.set(fraction)
                    self.status_var.set(text)
                elif kind == "job_progress":
                    job = self.jobs.get(event[1])
                    if job and job.status not in {"paused", "cancelled", "pausing", "cancelling"}:
                        job.status = "downloading"
                        job.progress = max(0.0, min(1.0, float(event[2])))
                        job.downloaded_bytes = int(event[3])
                        job.total_bytes = int(event[4])
                        job.speed = float(event[5])
                        job.eta = event[6]
                        if len(event) > 8:
                            job.fragment_index = int(event[7] or 0)
                            job.fragment_count = int(event[8] or 0)
                        self.status_var.set(
                            f"{job.title}: {job.progress * 100:.1f}% • {human_speed(job.speed)}"
                        )
                        self._refresh_job_table()
                elif kind == "job_stage":
                    job = self.jobs.get(event[1])
                    if job and job.status not in {"paused", "cancelled", "pausing", "cancelling"}:
                        job.status = event[2]
                        job.speed = 0
                        job.eta = None
                        self.status_var.set(f"{job.title}: {event[3]}")
                        self._refresh_job_table()
                elif kind == "spawn_audio_jobs":
                    self._spawn_audio_child_jobs(event[1], event[2], event[3])
                elif kind == "spawn_subtitle_jobs":
                    self._spawn_subtitle_child_jobs(event[1], event[2], event[3])
                elif kind == "job_completed":
                    job = self.jobs.get(event[1])
                    if job:
                        job.status = "completed"
                        job.progress = 1.0
                        job.speed = 0
                        job.eta = None
                        job.finished_at = time.time()
                        job.filepath = event[2] or job.filepath
                        if job.filepath:
                            job.related_files.add(job.filepath)
                        self.status_var.set(f"Tamamlandı: {job.title}")
                        self._append_log(f"Tamamlandı: {job.title} • {job.quality}")
                        self._save_job_history()
                        self._refresh_job_table()
                        if job.parent_id and job.job_type in {"audio", "subtitle"}:
                            self._maybe_enqueue_auto_mux(job.parent_id)
                elif kind == "job_state":
                    job = self.jobs.get(event[1])
                    if job:
                        job.status = event[2]
                        job.error = event[3]
                        job.speed = 0
                        job.eta = None
                        if job.status in TERMINAL_JOB_STATUSES:
                            job.finished_at = time.time()
                        label = JOB_STATUS_LABELS.get(job.status, job.status)
                        self.status_var.set(f"{label}: {job.title}")
                        if job.error:
                            self._append_log(f"{label}: {job.title} • {job.error}")
                        self._save_job_history()
                        self._refresh_job_table()
                        if job.parent_id and job.job_type in {"audio", "subtitle"}:
                            self._maybe_enqueue_auto_mux(job.parent_id)
                elif kind == "job_worker_finished":
                    self.active_job_ids.discard(event[1])
                    self._refresh_job_table()
                    self._pump_download_queue()
                elif kind == "cookie_fallback":
                    browser = event[1].capitalize()
                    self.cookie_var.set("Yok")
                    warning = (
                        f"{browser} çerez veritabanı Windows tarafından kilitlendi; "
                        "analiz çerezsiz olarak otomatik yeniden deneniyor."
                    )
                    self.status_var.set(warning)
                    self._append_log(f"Uyarı: {warning}")
                elif kind == "analysis_done":
                    self.prepared_analysis_url = event[3] if len(event) > 3 else self.current_url
                    self._show_analysis(event[1], event[2])
                    self._set_busy(None)
                elif kind == "download_done":
                    self.progress.set(1)
                    self.status_var.set(f"Tamamlandı: {event[1]}")
                    self._append_log("Dosya başarıyla kaydedildi.")
                    self._set_busy(None)
                    messagebox.showinfo(
                        "İndirme tamamlandı",
                        f"{event[1]}\n\nKlasör: {self.folder_var.get()}",
                    )
                elif kind == "cancelled":
                    self.status_var.set(event[1])
                    self._append_log(event[1])
                    self._set_busy(None)
                elif kind == "operation_error":
                    self.status_var.set(event[1])
                    self._append_log(f"{event[1]}: {event[2]}")
                    self._set_busy(None)
                    messagebox.showerror(event[1], event[2])
                elif kind == "deno_done":
                    self.deno_path = find_deno()
                    self.status_var.set(
                        "Deno hazır; YouTube desteği etkin."
                        if self.deno_path
                        else "Deno kuruldu; algılanması için uygulamayı yeniden başlatın."
                    )
                    self._append_log(event[1] or "Deno kuruldu.")
                    self._set_busy(None)
                    self._refresh_component_status()
                    messagebox.showinfo(
                        "Deno kurulumu tamamlandı",
                        "Deno kuruldu. Uygulamayı yeniden başlatmanız önerilir.",
                    )
                elif kind == "ffmpeg_done":
                    self.ffmpeg_path = find_ffmpeg()
                    ffprobe_path = find_ffprobe(self.ffmpeg_path)
                    detected_version = ffmpeg_version(self.ffmpeg_path)
                    already_current = bool(event[2]) if len(event) > 2 else False
                    if self.ffmpeg_path and ffprobe_path:
                        version_note = f" {detected_version}" if detected_version else ""
                        result_note = (
                            f"FFmpeg{version_note} ve FFprobe zaten güncel."
                            if already_current
                            else f"FFmpeg{version_note} ve FFprobe hazır."
                        )
                        restart_note = (
                            "Yeni FFmpeg yolu sonraki işler için kullanılacak. Uygulamayı yeniden "
                            "başlatmanız yine de önerilir."
                        )
                    elif self.ffmpeg_path:
                        version_note = f" {detected_version}" if detected_version else ""
                        result_note = f"FFmpeg{version_note} bulundu; FFprobe henüz algılanmadı."
                        restart_note = "Uygulamayı kapatıp yeniden başlatın; sorun sürerse WinGet kurulumunu onarın."
                    else:
                        result_note = "winget işlemi tamamlandı; FFmpeg bu oturumda henüz algılanmadı."
                        restart_note = "Uygulamayı kapatıp yeniden başlatın."
                    self.status_var.set(result_note)
                    self._append_log(event[1] or result_note)
                    self._append_log(result_note)
                    self._set_busy(None)
                    self._refresh_component_status()
                    messagebox.showinfo(
                        "FFmpeg güncellemesi tamamlandı",
                        f"{result_note}\n\n{restart_note}",
                    )
                elif kind == "update_done":
                    self.status_var.set("yt-dlp güncellendi; uygulamayı yeniden başlatın.")
                    self._append_log(event[1] or "yt-dlp güncellendi.")
                    self._set_busy(None)
                    messagebox.showinfo(
                        "Güncelleme tamamlandı",
                        "yt-dlp güncellendi. Yeni sürümün yüklenmesi için uygulamayı yeniden başlatın.",
                    )
                elif kind == "bridge_open":
                    self._handle_bridge_open(event[1])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_events)

    def _append_log(self, message: str) -> None:
        text = clean_text(message, 1400)
        if not text:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh_component_status(self) -> None:
        try:
            import yt_dlp

            version = getattr(getattr(yt_dlp, "version", None), "__version__", "kurulu")
        except Exception:
            version = "bilinmiyor"
        self.ffmpeg_path = find_ffmpeg()
        self.deno_path = find_deno()
        try:
            import curl_cffi  # noqa: F401

            impersonation = "TLS ✓"
        except Exception:
            impersonation = "TLS yok"
        ffmpeg_release = ffmpeg_version(self.ffmpeg_path)
        ffprobe_ready = bool(find_ffprobe(self.ffmpeg_path))
        ffmpeg = (
            f"FFmpeg {ffmpeg_release} ✓" if self.ffmpeg_path and ffprobe_ready and ffmpeg_release
            else "FFmpeg ✓" if self.ffmpeg_path and ffprobe_ready
            else "FFprobe yok" if self.ffmpeg_path
            else "FFmpeg yok"
        )
        deno = "Deno ✓" if self.deno_path else "Deno yok"
        self.component_var.set(
            f"yt-dlp {version}  •  {ffmpeg}  •  {deno}  •  {impersonation}"
        )

    def _on_close(self) -> None:
        self.cancel_event.set()
        for job in self.jobs.values():
            if job.status in {"queued", "downloading", "processing", "finalizing", "paused", "pausing", "cancelling"}:
                job.pause_event.set()
                job.status = "interrupted"
                job.error = "Uygulama kapatıldı; yeniden analiz ederek devam edin."
                job.finished_at = time.time()
        self.extension_cookie_text = ""
        self._save_settings()
        self._save_job_history()
        try:
            self.bridge.stop()
        finally:
            self.destroy()


def main() -> int:
    app = VideoDownloaderApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
