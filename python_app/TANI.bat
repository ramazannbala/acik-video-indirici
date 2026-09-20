@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "OUT=%~dp0tani-sonucu.txt"

>"%OUT%" echo Acik Video Indirici tani sonucu
>>"%OUT%" echo Tarih: %date% %time%
>>"%OUT%" echo Klasor: %cd%
>>"%OUT%" echo.
>>"%OUT%" echo === DOSYALAR ===
dir /b >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === PY LAUNCHER ===
where py >>"%OUT%" 2>&1
py -0p >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === PYTHON ===
where python >>"%OUT%" 2>&1
python --version >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === VENV ===
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" --version >>"%OUT%" 2>&1
  "%~dp0.venv\Scripts\python.exe" -c "import tkinter, customtkinter, yt_dlp, yt_dlp_ejs, curl_cffi, tkinterdnd2; print('Importlar OK')" >>"%OUT%" 2>&1
) else (
  >>"%OUT%" echo .venv\Scripts\python.exe BULUNAMADI
)
>>"%OUT%" echo.
>>"%OUT%" echo === FFMPEG ===
where ffmpeg >>"%OUT%" 2>&1
ffmpeg -version >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === DENO / YOUTUBE ===
where deno >>"%OUT%" 2>&1
deno --version >>"%OUT%" 2>&1

echo Tani tamamlandi:
echo "%OUT%"
echo.
type "%OUT%"
pause
