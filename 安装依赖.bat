@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"

echo ============================================
echo   An Zhuang Python yi lai (zhi xu zhi xing yi ci)
echo ============================================
echo Dang qian mu lu: %BASE%
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [Cuo wu] Wei jian ce dao Python.
    echo Qing xia zai an zhuang Python 3.10+, an zhuang shi gou xuan "Add Python to PATH":
    echo   https://www.python.org/downloads/
    goto :END
)

echo [1/2] Sheng ji pip...
python -m pip install --upgrade pip
echo.
echo [2/2] An zhuang Python yi lai bao...
python -m pip install -r "%BASE%requirements.txt"
echo.
echo ===== Yi lai an zhuang wan cheng =====
echo Ru guo you cuo wu xin xi, jie tu shang fang shu chu.

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
