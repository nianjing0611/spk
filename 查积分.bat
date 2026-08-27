@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   查询即梦账号积分余额
echo ============================================
echo.
"bin\dreamina.exe" user_credit
echo.
echo 查询完成。按任意键关闭本窗口。
pause >nul
