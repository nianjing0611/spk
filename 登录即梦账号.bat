@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   即梦账号登录
echo   请按终端提示，在浏览器完成授权
echo ============================================
echo.
"bin\dreamina.exe" login
echo.
echo 登录流程已结束。按任意键关闭本窗口。
pause >nul
