@echo off
chcp 65001 >nul
echo 卸载前请完全退出 DSH，包括托盘。
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall
if errorlevel 1 echo 卸载停止。文件可能已有新改动，请不要强制覆盖。
pause
