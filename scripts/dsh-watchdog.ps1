# dsh-watchdog.ps1 —— DSH web 看门狗（延时自动重启）
#
# 对齐移动端 APK 的 EngineService 看门狗（5 秒拉起）：监控 DSH web 服务
# （端口监听），若进程退出/崩溃/被杀 → 延时 DelaySec 秒再次确认 → 自动重启。
# 灵枢桥（LingshuBridge）只重连灵枢 python 进程；本看门狗守护 DSH 宿主。
#
# 用法：
#   .\dsh-watchdog.ps1                    # 默认 3080 端口，5 秒延时
#   .\dsh-watchdog.ps1 -DelaySec 10       # 10 秒延时（留出保存/清理时间）
# 停止：Ctrl+C 或 Stop-Process（看门狗自身）
#
# 配合「配置/插件更新后重启」：改完文件 → 直接 kill DSH 进程 → 看门狗
# 延时后自动拉起新版（不再需要手敲启动命令）。

param(
    [int]$Port = 3080,
    [int]$DelaySec = 5,
    [string]$NodeBin = "node",
    [string]$DshBin = "C:\Users\FuRongJun\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js",
    [string]$LogDir = "$env:USERPROFILE\.dsh\logs",
    [switch]$StartNow,
    [switch]$Once
)

# 启动 dsh web（后台，日志重定向）
function Start-DshWeb {
    $ts = Get-Date -Format "yyyyMMdd-HHmmss"
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $out = Join-Path $LogDir "dsh-$ts.out.log"
    $err = Join-Path $LogDir "dsh-$ts.err.log"
    Start-Process -FilePath $NodeBin -ArgumentList @($DshBin, "web") `
        -RedirectStandardOutput $out -RedirectStandardError $err `
        -WindowStyle Hidden
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] dsh web started (out=$out err=$err)"
}

Write-Output "dsh-watchdog: watching port $Port, auto-restart after $DelaySec s (Ctrl+C to stop)"
if ($StartNow) { Start-DshWeb }

# guard: never let the script crash (hidden-window crash still pops an error dialog)
function Test-Port {
    try { return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) }
    catch { return $false }
}

if ($Once) {
    # Once mode: for Windows Task Scheduler (reliable, no resident process)
    try {
        if (-not (Test-Port)) {
            Start-Sleep -Seconds $DelaySec
            if (-not (Test-Port)) {
                Write-Output "[$(Get-Date -Format 'HH:mm:ss')] dsh web is down, restarting..."
                Start-DshWeb
            }
        }
    }
    catch {
        Write-Output "[$(Get-Date -Format 'HH:mm:ss')] once-check error: $_"
    }
    exit 0
}

while ($true) {
    try {
        if (-not (Test-Port)) {
            # Wait, then double-check to avoid false positives
            Start-Sleep -Seconds $DelaySec
            if (-not (Test-Port)) {
                Write-Output "[$(Get-Date -Format 'HH:mm:ss')] dsh web is down, restarting..."
                Start-DshWeb
            }
        }
    }
    catch {
        Write-Output "[$(Get-Date -Format 'HH:mm:ss')] watchdog error: $_"
        Start-Sleep -Seconds 10
    }
    Start-Sleep -Seconds 3
}
