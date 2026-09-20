@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Acik Video Indirici - Kurulum

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%" 2>nul
if errorlevel 1 goto path_error

set "LOG=%APP_DIR%kurulum-log.txt"
>"%LOG%" echo Acik Video Indirici kurulum gunlugu
>>"%LOG%" echo Tarih: %date% %time%
>>"%LOG%" echo Klasor: %APP_DIR%
>>"%LOG%" echo.

echo ==================================================
echo   ACIK VIDEO INDIRICI - KURULUM
echo ==================================================
echo.

if not exist "%APP_DIR%app.py" goto files_missing
if not exist "%APP_DIR%requirements.txt" goto files_missing

echo [1/5] Python araniyor...

py -3.11 -c "import sys; raise SystemExit(0 if (sys.version_info.major == 3 and sys.version_info.minor in range(10,30)) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.11"
  goto python_found
)

py -3 -c "import sys; raise SystemExit(0 if (sys.version_info.major == 3 and sys.version_info.minor in range(10,30)) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  goto python_found
)

python -c "import sys; raise SystemExit(0 if (sys.version_info.major == 3 and sys.version_info.minor in range(10,30)) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto python_found
)

python3 -c "import sys; raise SystemExit(0 if (sys.version_info.major == 3 and sys.version_info.minor in range(10,30)) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python3"
  goto python_found
)

goto python_missing

:python_found
echo       Kullanilacak komut: %PYTHON_CMD%
call %PYTHON_CMD% --version
call %PYTHON_CMD% --version >>"%LOG%" 2>&1

echo [2/5] Sanal ortam ve pip kontrol ediliyor...
set "VENV_REPAIRED=0"
set "VENV_PY=%APP_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto recreate_venv
"%VENV_PY%" -c "import sys; print(sys.version)" >>"%LOG%" 2>&1
if errorlevel 1 goto recreate_venv
goto verify_venv_pip

:recreate_venv
set "VENV_REPAIRED=1"
if exist "%APP_DIR%.venv" (
  echo       Eksik veya bozuk sanal ortam temizleniyor...
  >>"%LOG%" echo Eksik veya bozuk sanal ortam temizleniyor.
  rmdir /s /q "%APP_DIR%.venv" >>"%LOG%" 2>&1
)
if exist "%APP_DIR%.venv" goto venv_cleanup_error
echo       .venv olusturuluyor. Bu islem biraz surebilir...
call %PYTHON_CMD% -m venv "%APP_DIR%.venv" >>"%LOG%" 2>&1
if errorlevel 1 goto install_error
set "VENV_PY=%APP_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto install_error

:verify_venv_pip
"%VENV_PY%" -m pip --version >>"%LOG%" 2>&1
if not errorlevel 1 goto pip_ready
echo       pip eksik; Python ensurepip ile onariliyor...
>>"%LOG%" echo pip eksik; ensurepip onarimi baslatiliyor.
"%VENV_PY%" -m ensurepip --upgrade --default-pip >>"%LOG%" 2>&1
"%VENV_PY%" -m pip --version >>"%LOG%" 2>&1
if not errorlevel 1 goto pip_ready
if "%VENV_REPAIRED%"=="1" goto pip_missing
set "VENV_REPAIRED=1"
echo       Mevcut .venv onarilamadi; temiz olarak yeniden kuruluyor...
goto recreate_venv

:pip_ready
echo [3/5] pip guncelleniyor...
"%VENV_PY%" -m pip install --upgrade pip >>"%LOG%" 2>&1
if errorlevel 1 goto install_error

echo [4/5] Uygulama paketleri indiriliyor...
echo       Internet hizina gore 1-3 dakika surebilir.
"%VENV_PY%" -m pip install --upgrade -r "%APP_DIR%requirements.txt" >>"%LOG%" 2>&1
if errorlevel 1 goto install_error

echo [5/5] Kurulum dogrulaniyor...
"%VENV_PY%" -c "import tkinter, customtkinter, yt_dlp, yt_dlp_ejs, curl_cffi, tkinterdnd2; print('Bagimliliklar OK')" >>"%LOG%" 2>&1
if errorlevel 1 goto install_error

>"%APP_DIR%.kurulum-tamam" echo %date% %time%
echo.
echo [TAMAM] Python uygulamasi kuruldu.
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [UYARI] FFmpeg bulunamadi. Coklu ses ve altyazi icin kurun:
  echo         winget install --id Gyan.FFmpeg -e
) else (
  echo [TAMAM] FFmpeg bulundu.
)
where deno >nul 2>&1
if errorlevel 1 (
  echo [UYARI] Deno bulunamadi. Guncel YouTube destegi icin kurun:
  echo         winget install --id DenoLand.Deno -e
) else (
  echo [TAMAM] Deno bulundu.
)
echo.
echo Kurulum gunlugu: "%LOG%"
if defined AVI_NOPAUSE exit /b 0
echo Devam etmek icin bir tusa basin...
pause >nul
exit /b 0

:python_missing
echo.
echo [HATA] Python 3.10 veya daha yeni bir surum bulunamadi.
echo.
echo 1. https://www.python.org/downloads/windows/ adresinden Python kurun.
echo 2. Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
echo 3. Bu dosyayi yeniden calistirin.
>>"%LOG%" echo HATA: Uygun Python bulunamadi.
goto fail

:files_missing
echo.
echo [HATA] app.py veya requirements.txt bulunamadi.
echo ZIP dosyasinin icinden calistirmayin.
echo ZIP'e sag tiklayip "Tumunu Ayikla" secin, sonra ayiklanan klasorden acin.
>>"%LOG%" echo HATA: Kaynak dosyalari bulunamadi. ZIP ayiklanmamis olabilir.
goto fail

:pip_missing
echo.
echo [HATA] Sanal ortamda pip olusturulamadi.
echo Python kurulumundaki ensurepip/pip bileseni eksik veya bozuk.
echo.
echo 1. Python yukleyicisini acip Modify veya Repair secin.
echo 2. pip ve venv ozelliklerinin kurulu oldugunu dogrulayin.
echo 3. Gerekirse Python'u https://www.python.org/downloads/windows/ adresinden yeniden kurun.
echo 4. Sonra KUR_VE_BASLAT.bat dosyasini yeniden calistirin.
>>"%LOG%" echo HATA: ensurepip sanal ortamda pip olusturamadi.
goto fail

:venv_cleanup_error
echo.
echo [HATA] Bozuk .venv klasoru silinemedi.
echo Uygulamayi ve bu klasoru kullanan terminalleri kapatin.
echo Ardindan "%APP_DIR%.venv" klasorunu elle silip yeniden deneyin.
>>"%LOG%" echo HATA: Bozuk .venv klasoru silinemedi.
goto fail

:path_error
echo [HATA] Uygulama klasorune girilemedi: "%~dp0"
goto fail_no_log

:install_error
echo.
echo [HATA] Kurulum tamamlanamadi.
echo Ayrinti dosyasi: "%LOG%"
echo.
echo Son gunluk satirlari:
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 25 }" 2>nul
goto fail

:fail
if defined AVI_NOPAUSE exit /b 1
echo.
echo Pencereyi kapatmadan once hata metnini okuyun.
pause
exit /b 1

:fail_no_log
if defined AVI_NOPAUSE exit /b 1
pause
exit /b 1
