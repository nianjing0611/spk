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
echo   Qie Huan Ji Meng Zhang Hao
echo   Jiang qing chu ben ji deng lu tai, qiang zhi chong xin deng lu.
echo   Neng gou qie huan dao zi ji de zhang hao shou quan.
echo ============================================
echo Dang qian mu lu: %BASE%
echo.

if not exist "%EXE%" (
    echo [Cuo wu] Wei zhao dao dreamina.exe
    echo Qing yi dong fen fa bao dao chun ying wen mu lu.
    goto :END
)

REM Xian cha xun dang qian zhang hao xin xi
echo --- Dang qian yi deng lu de zhang hao ---
"%EXE%" user_credit
set "CREDIT_RET=%errorlevel%"
echo.

if %CREDIT_RET% equ 0 (
    echo ============================================
    echo   Shang mian shi dang qian zhang hao de xin xi.
    echo   Ru guo bu shi zi ji de zhang hao, xia mian hui qiang zhi qie huan.
    echo ============================================
    echo.
)

REM Qiang zhi chong xin deng lu (qing chu jiu deng lu tai)
echo Zheng zai qing chu jiu deng lu tai, qi dong chong xin shou quan liu cheng...
echo ============================================
echo   Zhong dian: Qing xuan ze ni zi ji de Ji Meng zhang hao shou quan!
echo ============================================
echo.
"%EXE%" relogin
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

echo.
echo --- Xin zhang hao xin xi ---
"%EXE%" user_credit

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
