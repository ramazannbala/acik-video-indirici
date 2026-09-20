@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Acik Video Indirici - Tek Tik Kurulum
cd /d "%~dp0" 2>nul
if errorlevel 1 goto path_error

if not exist "%~dp0python_app\app.py" goto not_extracted
if not exist "%~dp0python_app\run.bat" goto not_extracted

call "%~dp0python_app\run.bat"
exit /b %ERRORLEVEL%

:not_extracted
echo ==================================================
echo [HATA] Paket dosyalari bulunamadi.
echo ==================================================
echo.
echo Bu dosyayi ZIP onizlemesinin icinden calistirmissiniz veya
echo paket tam ayiklanmamis.
echo.
echo 1. ZIP dosyasina sag tiklayin.
echo 2. "Tumunu Ayikla" secenegine basin.
echo 3. Ayiklanan klasordeki KUR_VE_BASLAT.bat dosyasini calistirin.
echo.
pause
exit /b 1

:path_error
echo [HATA] Klasor yolu acilamadi.
echo Paketi C:\AcikVideo gibi kisa bir klasore ayiklayip yeniden deneyin.
pause
exit /b 1
