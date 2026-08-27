@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ==== 兼容中文路径：用完整路径，不依赖 cd ====
set "BASE=%~dp0"

echo ============================================
echo   启动 MyTool 服务
echo   启动后浏览器访问 http://127.0.0.1:9527/
echo ============================================
echo.
echo 当前目录: %BASE%
echo.

REM 切换到 bat 所在目录（兼容短路径方式）
pushd "%BASE%"

REM 首次运行：从模板创建 config.json
if not exist config.json (
    if exist config.example.json (
        copy config.example.json config.json >nul
        echo [首次运行] 已从模板创建 config.json
        echo 请编辑 config.json 填入你的 DeepSeek API Key，或通过网页设置页填写。
        echo.
    )
)

REM 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python。
    echo 请先运行"安装依赖.bat"，或从 https://www.python.org 下载安装 Python 3.10+
    echo.
    pause
    popd
    exit /b 1
)

python app.py

echo.
echo 服务已停止。按任意键关闭。
pause >nul
popd
endlocal
