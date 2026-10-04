@echo off
chcp 65001 >nul
rem 启动大肥鱼桌宠（无控制台窗口）。双击本文件即可。
rem
rem 这里**不再"先杀掉旧进程"**：那样会把用户正在跑的那只一起杀掉（我之前就是这么
rem 弄丢过一次）。程序自己会按显示服务端口判断是否已有实例，已有就安静退出，
rem 见 main.py 的 existing_instance()。
setlocal
set HERE=%~dp0

rem 优先用本目录下的虚拟环境（推荐做法，依赖装在 .venv 里不污染系统）
set PY=%HERE%.venv\Scripts\pythonw.exe
if not exist "%PY%" set PY=pythonw.exe

rem 先探一次：已经在跑就不重复启动
powershell -NoProfile -Command "try{ $r=Invoke-RestMethod 'http://127.0.0.1:8899/health' -TimeoutSec 2; Write-Host ('已经有一只大肥鱼在跑了（mood=' + $r.mood + '），不重复启动。'); exit 0 }catch{ exit 1 }"
if not errorlevel 1 (
    timeout /t 3 >nul
    goto :eof
)

start "" "%PY%" -X utf8 "%HERE%main.py"
echo 已启动大肥鱼桌宠。
echo   右键宠物：动作点播 / 聊天 / 碎碎念 / 大小 / 模式
echo   托盘图标：显示隐藏 / 退出
timeout /t 3 >nul
