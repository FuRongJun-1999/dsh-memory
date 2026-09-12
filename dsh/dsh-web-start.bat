@echo off
rem ============================================================
rem dsh-web-start.bat —— 启动 DSH web（带 8GB heap 保护，防启动 OOM）
rem
rem 背景：灵枢 embedding 权重加载 + dsh-bridge + 记忆注入在启动时
rem 同时分配，默认 4GB heap 偶发 OOM。此脚本用 8GB 上限规避。
rem
rem 用法：双击或命令行运行；首次运行后浏览器访问 http://127.0.0.1:3080
rem ============================================================
setlocal
rem 用当前用户环境变量解析，不写死机器/用户名（换台机器 clone 也能直接跑）
set DSH_HOME=%USERPROFILE%\.dsh
set NODE_OPTIONS=--max-old-space-size=8192

echo [dsh-web] 启动 DSH web（heap 8GB）...
node "%APPDATA%\npm\node_modules\@deepseek-ai\dsh\lib\bin.js" web
endlocal
