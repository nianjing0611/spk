@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   即梦账号登录
echo   请按终端提示，在浏览器完成授权
echo ============================================
echo.

REM 检查 dreamina.exe 是否存在
if not exist "bin\dreamina.exe" (
    echo [错误] 未找到 bin\dreamina.exe
    echo 请确认分发包完整，bin 目录下有 dreamina.exe
    echo.
    pause
    exit /b 1
)

REM 检查 Python 是否安装（部分功能依赖）
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 未检测到 Python，请先运行"安装依赖.bat"
    echo.
)

echo 正在启动登录流程...
echo.
"bin\dreamina.exe" login

if %errorlevel% neq 0 (
    echo.
    echo [错误] dreamina.exe 退出码: %errorlevel%
    echo 可能原因:
    echo   1. 缺少 Visual C++ 运行库 - 下载: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo   2. 杀毒软件拦截 - 请添加白名单
    echo   3. 系统不兼容 - 需要 Windows 10 64位及以上
    echo.
)

echo.
echo 登录流程已结束。按任意键关闭本窗口。
pause >nul
