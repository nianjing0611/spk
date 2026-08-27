@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   启动 MyTool 服务
echo   启动后浏览器访问 http://127.0.0.1:9527/
echo ============================================
echo.

REM 首次运行：从模板创建 config.json（含 base_url/model，api_key 留空）
if not exist config.json (
    copy config.example.json config.json >nul
    echo [首次运行] 已从模板创建 config.json
    echo 请编辑 config.json 填入你的 DeepSeek API Key，或通过网页设置页填写。
    echo.
)

python app.py
echo.
echo 服务已停止。按任意键关闭。
pause >nul
