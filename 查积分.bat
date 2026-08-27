@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"
set "EXE=%BASE%bin\dreamina.exe"

echo ============================================
echo   Cha Xun Ji Meng Zhang Hao Ji Fen Yu E
echo ============================================
echo Dang qian mu lu: %BASE%
echo.

if not exist "%EXE%" (
    echo [Cuo wu] Wei zhao dao dreamina.exe
    echo Qing yi dong fen fa bao dao chun ying wen mu lu chong shi.
    goto :END
)

"%EXE%" user_credit
echo.
echo Cha xun fan hui ma: %errorlevel%

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
