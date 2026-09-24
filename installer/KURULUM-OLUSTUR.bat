@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================================
echo   Açık Video İndirici v7.4.1 - Setup Üretici
echo   PyInstaller (tek EXE) + Inno Setup (setup.exe)
echo ==========================================================
echo.

REM ---------- 1) Python bul ----------
set "PYCMD="
py -3 --version >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
  echo [HATA] Python bulunamadi. python.org adresinden Python 3.11+ kurun,
  echo        kurulumda "Add python.exe to PATH" isaretleyin ve yeniden deneyin.
  pause
  exit /b 1
)
echo [1/5] Python: %PYCMD%

REM ---------- 2) Kısa derleme kökü + sanal ortam (MAX_PATH koruması) ----------
REM Windows 260 karakter yol sınırını aşmamak için venv ve derleme ara çıktıları
REM repo dışında kısa bir kökte tutulur; AVI_BUILD_DIR ile değiştirilebilir.
set "BUILD=%AVI_BUILD_DIR%"
if not defined BUILD set "BUILD=%LOCALAPPDATA%\AVI-Build"
mkdir "%BUILD%" 2>nul
if not exist "%BUILD%" (
  set "BUILD=%~dp0build-root"
  mkdir "%BUILD%" 2>nul
)
echo [2/5] Derleme kökü (kisa yol, MAX_PATH korumasi): %BUILD%

if not exist "%BUILD%\venv\Scripts\python.exe" (
  echo       Sanal ortam olusturuluyor...
  %PYCMD% -m venv "%BUILD%\venv"
  if errorlevel 1 goto :fail
) else (
  echo       Sanal ortam mevcut; pip dogrulaniyor...
)
"%BUILD%\venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ready
echo       pip eksik; ensurepip ile onariliyor...
"%BUILD%\venv\Scripts\python.exe" -m ensurepip --upgrade --default-pip >nul 2>&1
"%BUILD%\venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ready
echo       Onarim basarisiz; venv bir kez temiz yeniden olusturuluyor...
rmdir /s /q "%BUILD%\venv" >nul 2>&1
if exist "%BUILD%\venv" (
  echo [HATA] Bozuk venv klasoru silinemedi. Kullanan terminalleri kapatip elle silin.
  goto :fail
)
%PYCMD% -m venv "%BUILD%\venv"
if errorlevel 1 goto :fail
"%BUILD%\venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ready
echo [HATA] Sanal ortamda pip olusturulamadi. Python yukleyicisinde Modify/Repair
echo        secip pip ve venv bilesenlerini onarin, sonra yeniden deneyin.
goto :fail
:pip_ready
"%BUILD%\venv\Scripts\python.exe" -m pip install --upgrade pip >nul
"%BUILD%\venv\Scripts\python.exe" -m pip install -r "..\python_app\requirements.txt" pyinstaller
if errorlevel 1 goto :fail

REM ---------- 3) PyInstaller: app.py -> tek EXE ----------
echo [3/5] PyInstaller: app.py tek EXE olarak donduruluyor (birkaç dakika sürebilir)...
"%BUILD%\venv\Scripts\pyinstaller.exe" --noconfirm --clean --distpath "%BUILD%\dist" --workpath "%BUILD%\work" "%~dp0app.spec"
if errorlevel 1 goto :fail
if not exist "%BUILD%\dist\AcikVideoIndirici.exe" (
  echo [HATA] AcikVideoIndirici.exe üretilmedi.
  goto :fail
)
REM yt-dlp EXE'ye gömülmez; güncellenebilir pylibs/ olarak dist içine kurulur.
echo       Güncellenebilir yt-dlp pylibs klasörü hazırlanıyor...
"%BUILD%\venv\Scripts\python.exe" -m pip install --upgrade --target "%BUILD%\dist\pylibs" yt-dlp yt-dlp-ejs
if errorlevel 1 goto :fail

REM ---------- 4) Inno Setup (ISCC) bul ----------
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo [4/5] Inno Setup 6 bulunamadi.
  set /p "WANT=winget ile kurulsun mu? (E/H): "
  if /i "!WANT!"=="E" (
    winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Microsoft\WinGet\Links\ISCC.exe"
    if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
  )
)
if not defined ISCC (
  echo [HATA] ISCC.exe bulunamadi. https://jrsoftware.org/isinfo.php adresinden
  echo        Inno Setup 6 kurup betiği yeniden çalıştırın.
  pause
  exit /b 1
)
echo [4/5] Inno Setup derleniyor...
"%ISCC%" /DDistDir="%BUILD%\dist" "%~dp0AcikVideoIndirici.iss"
if errorlevel 1 goto :fail

REM ---------- 5) Extension klasörünü setup yanına kopyala ----------
echo [5/5] Eklenti klasörü Output\extension altına kopyalanıyor...
if not exist "Output\extension" mkdir "Output\extension"
xcopy /E /I /Y "%~dp0..\extension" "%~dp0Output\extension" >nul

echo.
echo ==========================================================
echo   KURULUM PAKETI HAZIR
echo   Dosya : installer\Output\Acik-Video-Indirici-Kurulum-7.4.1.exe
echo   Klasör: installer\Output\extension   (setup ile birlikte taşınır)
echo   Derleme kökü: %BUILD%   (venv/work/dist; gerekirse elle silebilirsiniz)
echo   SHA-256:
certutil -hashfile "Output\Acik-Video-Indirici-Kurulum-7.4.1.exe" SHA256
echo.
echo   Not: Imzasız EXE olduğundan Windows SmartScreen uyarısı gösterebilir;
echo        "Daha fazla bilgi" -^> "Yine de çalıştır" ile devam edilir.
echo ==========================================================
pause
exit /b 0

:fail
echo.
echo [HATA] Setup üretimi başarısız oldu. Yukarıdaki çıktıyı inceleyin.
pause
exit /b 1
