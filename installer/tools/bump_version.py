"""Sürüm işaretlerini birlikte artırır (README kural 1/22/23).

Kullanım:  python installer/tools/bump_version.py 7.5.0
Günceller: python_app/app.py (APP_VERSION), extension/manifest.json ("version"),
           installer/AcikVideoIndirici.iss (MyAppVersion).
Satır sonu biçimlerini (LF/CRLF) olduğu gibi korur.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sub(path: Path, pattern: str, repl: str) -> None:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    new_text, count = re.subn(pattern, repl, text, count=1)
    if count != 1:
        sys.exit(f"[HATA] {path.name} içinde eşleşme bulunamadı: {pattern}")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1].strip()):
        sys.exit("Kullanım: bump_version.py X.Y.Z   (örn. 7.5.0)")
    new = sys.argv[1].strip()
    sub(ROOT / "python_app" / "app.py", r'APP_VERSION = "[0-9.]+"', f'APP_VERSION = "{new}"')
    sub(ROOT / "extension" / "manifest.json", r'"version": "[0-9.]+"', f'"version": "{new}"')
    sub(ROOT / "installer" / "AcikVideoIndirici.iss", r'#define MyAppVersion "[0-9.]+"', f'#define MyAppVersion "{new}"')
    print(f"[OK] Sürüm {new} yapıldı: app.py + manifest.json + AcikVideoIndirici.iss")
    print("     Tek belge kuralı: README.md içindeki sürüm satırlarını da güncelleyin.")


if __name__ == "__main__":
    main()
