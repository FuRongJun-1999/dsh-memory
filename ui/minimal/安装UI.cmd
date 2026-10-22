@echo off
chcp 65001 >nul
echo 安装前请完全退出 DSH，包括托盘。
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 echo 安装失败。请查看上方错误，切勿分享个人记忆或凭据。
pause
