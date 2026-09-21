@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "PYCMD="
py -3 --version >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
  echo [HATA] Python bulunamadi.
  exit /b 1
)

if "%~1"=="" (
  echo Kullanim: SURUM-ARTIR.bat YENI_SURUM
  echo   Ornek : SURUM-ARTIR.bat 7.5.0
  echo   app.py + manifest.json + AcikVideoIndirici.iss birlikte güncellenir.
  echo   Sonra KURULUM-OLUSTUR.bat ile yeni setup üretilir.
  exit /b 1
)

%PYCMD% tools\bump_version.py %~1
exit /b %errorlevel%
