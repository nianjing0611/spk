@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   启动 MyTool 服务
echo   启动后浏览器访问 http://127.0.0.1:9527/
echo ============================================
echo.
python app.py
echo.
echo 服务已停止。按任意键关闭。
pause >nul
