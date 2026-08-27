@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"

echo ============================================
echo   启动 MyTool 服务
echo   启动后浏览器访问 http://127.0.0.1:9527/
echo ============================================
echo 当前目录: %BASE%
echo.

if not exist "%BASE%app.py" (
    echo [错误] 未找到 app.py
    echo 请确认分发包完整，或移动到纯英文目录重试。
    goto :END
)

if not exist "%BASE%config.json" (
    if exist "%BASE%config.example.json" (
        copy "%BASE%config.example.json" "%BASE%config.json" >nul
        echo [首次运行] 已从 config.example.json 复制 config.json
        echo 请在网页设置中填入 DeepSeek API Key。
        echo.
    )
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python。
    echo 请先运行"安装依赖.bat"，或下载 Python 3.10+ 并勾选 Add to PATH:
    echo   https://www.python.org/downloads/
    goto :END
)

echo 正在启动 Flask 服务...
echo.
python "%BASE%app.py"
echo.
echo Python app.py 已退出。返回码: %errorlevel%

:END
echo.
echo ===== 窗口已保留，可滚动查看上方输出 =====
echo 按任意键关闭本窗口。
pause >nul
endlocal
