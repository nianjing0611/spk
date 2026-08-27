@echo off
REM ========== 防止闪退：双击时用 cmd /k 重启本脚本 ==========
if "%~1"=="" (
    start "MyTool" cmd /k ""%~f0" _inner_run_"
    exit /b
)
if "%~1"=="_inner_run_" shift

setlocal
set "BASE=%~dp0"
set "EXE=%BASE%bin\dreamina.exe"

echo ============================================
echo   即梦账号登录
echo   请按终端提示，在浏览器完成授权
echo ============================================
echo 当前目录: %BASE%
echo.

if not exist "%EXE%" (
    echo [错误] 未找到 dreamina.exe
    echo 期望路径: %EXE%
    echo.
    echo 常见原因:
    echo   1. 解压路径含中文/特殊字符 - 请移到 C:\MyTool 这样的纯英文目录
    echo   2. 杀毒软件删除了 exe - 请关闭杀毒后重新解压
    goto :END
)

echo 正在启动登录流程...
echo.
"%EXE%" login
set "RET=%errorlevel%"

if %RET% neq 0 (
    echo.
    echo [错误] dreamina.exe 退出码: %RET%
    echo.
    echo 可能原因:
    echo   1. 缺少 VC++ 运行库: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo   2. 杀毒拦截 - 请添加白名单
    echo   3. 系统版本低于 Windows 10 x64
)

:END
echo.
echo ===== 窗口已保留，可滚动查看上方输出 =====
echo 按任意键关闭本窗口。
pause >nul
endlocal
