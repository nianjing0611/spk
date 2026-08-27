@echo off
REM ======================================================
REM  MyTool 自动更新脚本（在 Flask 退出后独立执行）
REM  流程：等待5s让前端收完响应 → 杀 Flask 占用进程 →
REM         python apply_update.py → 成功则重启 启动.bat
REM ======================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ======================================================
echo   MyTool 自动更新中，请等待（不要关闭此窗口）...
echo ======================================================
echo.

REM 1) 等待 5 秒，确保 Flask 已把响应发给前端，避免 TCP 连接中断
echo [1/4] 等待前端响应 (5s)...
timeout /t 5 /nobreak >nul

REM 2) 杀掉占用 9527 端口的 python 进程（即正在跑 app.py 的 Flask）
echo [2/4] 停止旧版 Flask 服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9527 ^| findstr LISTENING') do (
    echo    发现 PID=%%a，终止...
    taskkill /F /PID %%a >nul 2>nul
)
timeout /t 2 /nobreak >nul

REM 3) 执行 apply_update.py（备份 + 解压覆盖 + 校验）
echo [3/4] 应用更新包...
python "%~dp0apply_update.py"
set RC=%ERRORLEVEL%

if %RC% NEQ 0 (
    echo.
    echo [错误] 应用更新失败，错误码 %RC%。
    echo   详情请查看 _updates\apply_*.log。
    echo   软件已尽量自动回滚，请手动打开 启动.bat 重试。
    echo.
    pause
    exit /b %RC%
)

REM 4) 成功：启动新的 启动.bat 并退出本窗口
echo [4/4] 重启应用...
timeout /t 2 /nobreak >nul
start "" "%~dp0启动.bat"
exit /b 0
