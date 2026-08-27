@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ==== 兼容中文路径：不切换目录，用完整路径调用 ====
set "BASE=%~dp0"
set "EXE=%BASE%bin\dreamina.exe"

echo ============================================
echo   即梦账号登录
echo   请按终端提示，在浏览器完成授权
echo ============================================
echo.
echo 当前目录: %BASE%
echo.

REM 检查 dreamina.exe 是否存在（用完整路径）
if not exist "%EXE%" (
    echo [错误] 未找到: %EXE%
    echo 请确认分发包完整，bin 目录下有 dreamina.exe
    echo.
    echo 【常见原因】
    echo   - 解压目录含中文，请把分发包移动到 C:\MyTool 这样的纯英文目录
    echo   - 杀毒软件删除了 exe，请先关闭杀毒再解压
    echo.
    pause
    exit /b 1
)

REM 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 未检测到 Python，请先运行"安装依赖.bat"
    echo.
)

echo 正在启动登录流程...
echo.
"%EXE%" login

if %errorlevel% neq 0 (
    echo.
    echo [错误] dreamina.exe 退出码: %errorlevel%
    echo 可能原因:
    echo   1. 缺少 Visual C++ 运行库 - 下载: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo   2. 解压目录含中文/空格 - 请移动到纯英文短目录，如 C:\MyTool
    echo   3. 杀毒软件拦截 - 请添加白名单
    echo   4. 系统不兼容 - 需要 Windows 10 64位及以上
    echo.
)

echo.
echo 登录流程已结束。按任意键关闭本窗口。
pause >nul
endlocal
