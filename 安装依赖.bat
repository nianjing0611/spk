@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   安装 Python 依赖（只需执行一次）
echo ============================================
echo.
pip install -r requirements.txt
echo.
echo 依赖安装流程结束。按任意键关闭。
pause >nul
