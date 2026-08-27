@echo off
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"
set "EXE=%BASE%bin\dreamina.exe"

echo ============================================
echo   查询即梦账号积分余额
echo ============================================
echo 当前目录: %BASE%
echo.

if not exist "%EXE%" (
    echo [错误] 未找到 dreamina.exe
    echo 请移动分发包到纯英文目录重试。
    goto :END
)

"%EXE%" user_credit
echo.
echo 查询返回码: %errorlevel%

:END
echo.
echo ===== 窗口已保留，可滚动查看上方输出 =====
echo 按任意键关闭本窗口。
pause >nul
endlocal
