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
echo   Deng Lu Ji Meng Zhang Hao
echo   Qing an zhong duan ti shi, zai liu lan qi wan cheng shou quan
echo ============================================
echo Dang qian mu lu: %BASE%
echo.

if not exist "%EXE%" (
    echo [Cuo wu] Wei zhao dao dreamina.exe
    echo Qi wang lu jing: %EXE%
    echo.
    echo Chang jian yuan yin:
    echo   1. Jie ya lu jing han zhong wen/teshu zifu - qing yi dao C:\MyTool
    echo   2. Sha du ruan jian shan chu le exe - qing guan bi sha du chong xin jie ya
    goto :END
)

echo Zheng zai qi dong deng lu liu cheng...
echo.
"%EXE%" login
set "RET=%errorlevel%"

if %RET% neq 0 (
    echo.
    echo [Cuo wu] dreamina.exe tui chu ma: %RET%
    echo.
    echo Ke neng yuan yin:
    echo   1. Que shao VC++ yun xing ku: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo   2. Sha du ruan jian lan jie - qing tian jia bai ming dan
    echo   3. Xi tong ban ben di yu Windows 10 x64
)

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
