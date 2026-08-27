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
echo   Shi yong ni zi ji de Ji Meng zhang hao shou quan
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

REM Xian cha dang qian shi fou yi jing deng lu
echo Cha xun ben ji dang qian de deng lu zhuang tai...
"%EXE%" user_credit >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   [!] Fa xian ben ji yi jing you deng lu ji lu
    echo ============================================
    "%EXE%" user_credit
    echo ============================================
    echo   An Y: shi yong shang shu zhang hao, bu chong xin deng lu
    echo   An R: qiang zhi chong xin deng lu (qie huan zhang hao)
    echo   (mo ren deng 3 miao hou chong xin deng lu, jian yi xin yong hu xuan R)
    echo ============================================
    choice /c YR /t 3 /d R /m "Qing xuan ze (Yi yong/R chong xin deng)"
    if errorlevel 2 goto :DO_RELOGIN
    if errorlevel 1 goto :END_SKIP
)

REM Mei you deng lu guo, huo yong hu xuan le R: zheng chang deng lu
:DO_LOGIN
echo.
echo Zheng zai qi dong shou quan liu cheng...
echo ============================================
echo   Qing zai liu lan qi li xuan ze NI ZI JI de Ji Meng zhang hao
echo   Bu yao xuan ze mo ren de qita zhang hao!
echo ============================================
echo.
"%EXE%" relogin
set "RET=%errorlevel%"
goto :SHOW_RESULT

:DO_RELOGIN
echo.
echo Zheng zai qing chu jiu deng lu tai, qiang zhi chong xin shou quan...
echo ============================================
echo   Qing zai liu lan qi li xuan ze NI ZI JI de Ji Meng zhang hao
echo   Bu yao xuan ze mo ren de qita zhang hao!
echo ============================================
echo.
"%EXE%" relogin
set "RET=%errorlevel%"
goto :SHOW_RESULT

:SHOW_RESULT
if %RET% neq 0 (
    echo.
    echo [Cuo wu] dreamina.exe tui chu ma: %RET%
    echo.
    echo Ke neng yuan yin:
    echo   1. Que shao VC++ yun xing ku: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo   2. Sha du ruan jian lan jie - qing tian jia bai ming dan
    echo   3. Xi tong ban ben di yu Windows 10 x64
) else (
    echo.
    echo Deng lu wan cheng! Dang qian zhang hao xin xi:
    "%EXE%" user_credit
)
goto :END

:END_SKIP
echo.
echo NIN XUAN ZE LE BAO CHI YONG YUAN ZHANG HAO, TIAO GUO DENG LU.
echo RU YAO QIE HUAN, QING SHI YONG "QIE HUAN JI MENG ZHANG HAO.BAT".

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
