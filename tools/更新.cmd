@echo off
rem 大肥鱼桌宠：更新补丁的双击启动器
rem
rem 存在的意义：让用户不用手敲 PowerShell 命令，也不用记 -ExecutionPolicy Bypass。
rem 双击本文件即可更新；结束时暂停，好让人看清结果。
rem
rem 想预演（不实际改动）就在命令行里跑：
rem     update.ps1 -DryRun

setlocal
cd /d "%~dp0"

echo.
echo  大肥鱼桌宠 - 更新补丁
echo.

where powershell >nul 2>nul
if errorlevel 1 (
    echo  [错误] 找不到 powershell，请手动在本目录运行：
    echo      powershell -ExecutionPolicy Bypass -File .\update.ps1
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
set CODE=%ERRORLEVEL%

echo.
if "%CODE%"=="0" (
    echo  更新完成。请双击桌面上的「大肥鱼」重新启动桌宠。
) else (
    echo  更新未完全成功（退出码 %CODE%）。请把上面的输出发给提供者。
)
echo.
pause
exit /b %CODE%
