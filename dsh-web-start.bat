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
set DSH_HOME=C:\Users\FuRongJun\.dsh
set NODE_OPTIONS=--max-old-space-size=8192

echo [dsh-web] 启动 DSH web（heap 8GB）...
node "C:\Users\FuRongJun\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js" web
endlocal
