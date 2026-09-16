@echo off
rem ============================================================
rem update-lingshu.bat - 灵枢插件一键更新（占位：逻辑在 update-lingshu.ps1）
rem ============================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-lingshu.ps1" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo [OK] update finished.) else (echo [FAILED] exit %RC% - see %TEMP%\update-lingshu.log)
pause
endlocal
