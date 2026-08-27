@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "BASE=%~dp0"
pushd "%BASE%"

echo ============================================
echo   安装 Python 依赖（只需执行一次）
echo ============================================
echo.
echo 当前目录: %BASE%
echo.

REM 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python。
    echo 请先下载安装 Python 3.10+: https://www.python.org/downloads/
    echo 安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    popd
    exit /b 1
)

python -m pip install -r requirements.txt

echo.
echo 依赖安装流程结束。按任意键关闭。
pause >nul
popd
endlocal
