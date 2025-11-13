@echo off
title SAFE AI BOT CONTROL PANEL
color 0A
cd /d %~dp0

:menu
cls
echo ===============================================
echo           🤖 SAFE AI BOT VALDYMO MENIU
echo ===============================================
echo.
echo  [1] Paleisti BOT + Dashboard
echo  [2] Sustabdyti BOT ir Dashboard
echo  [3] Pilnas DB isvalymas (testavimui)
echo  [4] Tikrinti DB struktura
echo  [5] Testinis paleidimas 12 val.
echo  [0] Iseiti
echo.
set /p choice=Pasirink numeri: 

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto reset
if "%choice%"=="4" goto checkdb
if "%choice%"=="5" goto test
if "%choice%"=="0" exit
goto menu

:start
cls
echo 🟢 Paleidziamas botas ir dashboard...
python manage.py start
pause
goto menu

:stop
cls
echo 🔴 Stabdomi visi procesai...
python manage.py stop
pause
goto menu

:reset
cls
echo ⚠️ Isvaloma DB ir duomenys...
python manage.py reset
pause
goto menu

:checkdb
cls
echo 🔍 Tikrinama DB struktura...
python manage.py checkdb
pause
goto menu

:test
cls
echo 🧪 Testinis paleidimas 12 valandu...
python manage.py start
echo.
echo 🕒 Botas veiks 12 valandu, po to bus uzdarytas.
timeout /t 43200 >nul
python manage.py stop
echo ✅ Testas baigtas.
pause
goto menu
