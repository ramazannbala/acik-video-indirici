@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Acik Video Indirici

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%" 2>nul
if errorlevel 1 goto path_error

if not exist "%APP_DIR%app.py" goto files_missing
if not exist "%APP_DIR%requirements.txt" goto files_missing

set "VENV_PY=%APP_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto install_needed
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 goto install_needed
"%VENV_PY%" -c "import tkinter, customtkinter, yt_dlp, yt_dlp_ejs, curl_cffi, tkinterdnd2" >nul 2>&1
if errorlevel 1 goto install_needed
goto launch

:install_needed
echo Kurulum bulunamadi veya eksik. Otomatik kurulum baslatiliyor...
echo.
set "AVI_NOPAUSE=1"
call "%APP_DIR%install.bat"
set "INSTALL_RC=%ERRORLEVEL%"
set "AVI_NOPAUSE="
if not "%INSTALL_RC%"=="0" goto install_failed
if not exist "%VENV_PY%" goto install_failed

:launch
echo Uygulama baslatiliyor...
set "ERROR_LOG=%APP_DIR%uygulama-hata.log"
del /q "%ERROR_LOG%" >nul 2>&1
"%VENV_PY%" "%APP_DIR%app.py" 2>"%ERROR_LOG%"
set "APP_RC=%ERRORLEVEL%"
if "%APP_RC%"=="0" exit /b 0

echo.
echo [HATA] Uygulama acilamadi. Cikis kodu: %APP_RC%
echo Hata gunlugu: "%ERROR_LOG%"
echo.
if exist "%ERROR_LOG%" type "%ERROR_LOG%"
pause
exit /b %APP_RC%

:install_failed
echo.
echo [HATA] Otomatik kurulum tamamlanamadi.
echo Su dosyayi acip son satirlari paylasabilirsiniz:
echo "%APP_DIR%kurulum-log.txt"
pause
exit /b 1

:files_missing
echo.
echo [HATA] Uygulama dosyalari bulunamadi.
echo ZIP dosyasinin icinden calistirmayin.
echo ZIP'e sag tiklayip "Tumunu Ayikla" secin; sonra ayiklanan klasorden acin.
pause
exit /b 1

:path_error
echo [HATA] Belirtilen klasor bulunamadi: "%~dp0"
echo Paketi kisa bir yola ayiklamayi deneyin, ornek: C:\AcikVideo
pause
exit /b 1
