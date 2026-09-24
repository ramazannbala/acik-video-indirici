# -*- coding: utf-8 -*-
"""Açık Video İndirici v7.4.1 - PyInstaller spec (tek EXE / setup.exe girdisi).

Windows'ta installer/KURULUM-OLUSTUR.bat ile veya elle:

  .venv\Scripts\pyinstaller.exe --noconfirm --clean ^
      --distpath installer\dist --workpath installer\build installer\app.spec

Notlar:
- Tek EXE (onefile) modu: EXE() içine a.binaries/a.datas gömülür; COLLECT yok.
- FFmpeg ve Deno bilinçli olarak pakete EKLENMEZ; uygulama içi bakım
  düğmeleri (FFmpeg Güncelle / YouTube-Deno) WinGet ile kurar.
- Cookie/token değeri hiçbir derleme girdisine yazılmaz.
"""
import os

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

SPEC_DIR = os.path.abspath(SPECPATH)
ROOT_DIR = os.path.dirname(SPEC_DIR)
APP_ENTRY = os.path.join(ROOT_DIR, "python_app", "app.py")
ICON_PATH = os.path.join(SPEC_DIR, "assets", "app.ico")

datas = []
binaries = []

# customtkinter tema/asset dosyaları EXE içine gömülür.
datas += collect_data_files("customtkinter")
# tkinterdnd2: tkdnd Tcl paketi + yerel kütüphaneler (sürükle-bırak).
datas += collect_data_files("tkinterdnd2")
binaries += collect_dynamic_libs("tkinterdnd2")
# curl_cffi: TLS impersonation yerel kütüphaneleri.
binaries += collect_dynamic_libs("curl_cffi")
# CA sertifikaları (requests / curl_cffi).
datas += collect_data_files("certifi")

# yt-dlp BİLİNÇLİ OLARAK DONDURULMAZ: EXE yanındaki pylibs/ klasöründen
# yüklenir ve uygulama içi "yt-dlp Güncelle" düğmesi PyPI wheel'leriyle
# yerinde günceller (README kural 24). curl_cffi dondurulur; pylibs'teki
# yt-dlp onu çalışma anında frozen importer üzerinden kullanır.
hiddenimports = []


def _safe_collect(module_name):
    try:
        return collect_submodules(module_name)
    except Exception:
        return []


hiddenimports += _safe_collect("curl_cffi")
hiddenimports += _safe_collect("tkinterdnd2")

a = Analysis(
    [APP_ENTRY],
    pathex=[os.path.join(ROOT_DIR, "python_app")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["yt_dlp", "yt_dlp_ejs", "websockets", "brotli"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AcikVideoIndirici",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)
