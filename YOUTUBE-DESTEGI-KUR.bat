@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Acik Video Indirici - YouTube Destegi

echo ==================================================
echo   YOUTUBE DESTEGI - DENO KURULUMU
echo ==================================================
echo.
where winget >nul 2>&1
if errorlevel 1 (
  echo [HATA] winget bulunamadi.
  echo Deno 2.3 veya daha yenisini https://deno.com adresinden kurun.
  pause
  exit /b 1
)

winget install --id DenoLand.Deno -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  echo.
  echo [HATA] Deno kurulumu tamamlanamadi.
  pause
  exit /b 1
)

echo.
echo [TAMAM] Deno kuruldu. Acik Video Indirici'yi yeniden baslatin.
pause
