@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "BASE=%~dp0"
set "EXE=%BASE%bin\dreamina.exe"

echo ============================================
echo   查询即梦账号积分余额
echo ============================================
echo.

if not exist "%EXE%" (
    echo [错误] 未找到: %EXE%
    echo 请移动分发包到纯英文目录，如 C:\MyTool
    pause
    exit /b 1
)

"%EXE%" user_credit

echo.
echo 查询完成。按任意键关闭本窗口。
pause >nul
endlocal
