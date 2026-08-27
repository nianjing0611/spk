@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"

echo ============================================
echo   安装 Python 依赖（只需执行一次）
echo ============================================
echo 当前目录: %BASE%
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python。
    echo 请下载安装 Python 3.10+，安装时勾选 "Add Python to PATH":
    echo   https://www.python.org/downloads/
    goto :END
)

echo [1/2] 升级 pip...
python -m pip install --upgrade pip
echo.
echo [2/2] 安装 requirements.txt 中的依赖...
python -m pip install -r "%BASE%requirements.txt"
echo.
echo ===== 依赖安装完成 =====
echo 如果上面有红色错误，把错误截图发出来。

:END
echo.
echo ===== 窗口已保留，可滚动查看上方输出 =====
echo 按任意键关闭本窗口。
pause >nul
endlocal
