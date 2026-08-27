@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"

echo ============================================
echo   Qi dong MyTool fu wu
echo   Qi dong hou liu lan qi fang wen http://127.0.0.1:9527/
echo ============================================
echo Dang qian mu lu: %BASE%
echo.

if not exist "%BASE%app.py" (
    echo [Cuo wu] Wei zhao dao app.py
    echo Qing que ren fen fa bao wan zheng.
    goto :END
)

if not exist "%BASE%config.json" (
    if exist "%BASE%config.example.json" (
        copy "%BASE%config.example.json" "%BASE%config.json" >nul
        echo [Shou ci yun xing] Yi cong config.example.json fu zhi config.json
        echo Qing zai wang ye she ye zhong tian ru DeepSeek API Key.
        echo.
    )
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [Cuo wu] Wei jian ce dao Python.
    echo Qing xian yun xing An Zhuang Yi Lai.bat,
    echo huo xia zai Python 3.10+ bing gou xuan Add to PATH:
    echo   https://www.python.org/downloads/
    goto :END
)

REM ==== Jian cha yi lai: flask ====
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo [Ti shi] Jian ce dao Python yi lai wei an zhuang.
    echo Jiang zi dong yun xing An Zhuang Yi Lai.bat ...
    echo.
    REM Sheng ji pip
    echo [1/2] Sheng ji pip...
    python -m pip install --upgrade pip
    echo.
    echo [2/2] An zhuang Python yi lai...
    python -m pip install -r "%BASE%requirements.txt"
    if %errorlevel% neq 0 (
        echo.
        echo [Cuo wu] Yi lai an zhuang shi bai. Jie tu shang fang shu chu.
        echo Chang shi shou dong yun xing An Zhuang Yi Lai.bat.
        goto :END
    )
    echo Yi lai an zhuang wan cheng.
    echo.
)

echo Zheng zai qi dong Flask fu wu...
echo ============================================
echo   Ye mian di zhi: http://127.0.0.1:9527/
echo   Ting zhi fu wu: guan bi ben chuang kou
echo ============================================
echo.
python "%BASE%app.py"
echo.
echo Python app.py yi tui chu. Fan hui ma: %errorlevel%

:END
echo.
echo ===== Chuang kou yi bao liu, ke gun dong cha kan shang fang shu chu =====
echo An ren yi jian guan bi ben chuang kou.
pause >nul
endlocal
