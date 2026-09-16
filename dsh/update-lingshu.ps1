#Requires -Version 5.1
<#
  update-lingshu.ps1 —— 灵枢大脑（@furongjun1999/dsh-memory）一键更新

  为什么需要它（2026-09-16 实测得到的三条教训）：
    1) 目录锁：pnpm 装新版本的最后一步是把 dsh-memory_tmp_NNN 重命名成 dsh-memory。
       只要 DSH 主进程还活着（工作目录锚在这个包内），Windows 就拒绝重命名，
       报 EPERM ... rename ... dsh-memory_tmp_NNN。所以更新前必须先停 DSH。
    2) 发布龄闸门：pnpm 有供应链 minimumReleaseAge 策略，刚发布的版本默认解析不进来，
       必须在 pnpm-workspace.yaml 的 minimumReleaseAgeExclude 里显式放行，
       否则 pnpm 会安静地"更新成功"，版本号却一动不动。
    3) 慢网：本机到 registry.npmjs.org 可能只有几十 KB/s，27MB 的包会撞上 pnpm 默认
       60s 下载超时。本脚本改用 curl 断点续传 + sha512 校验，再按文件覆盖安装
       （不重命名目录），最后逐文件哈希核对与发布包是否一致。

  用法：
    update-lingshu.bat                            双击：更新到 npm 最新版并重启 DSH
    powershell -File update-lingshu.ps1 -DryRun   只看要做什么，不落任何修改
    powershell -File update-lingshu.ps1 -NoRestart
    powershell -File update-lingshu.ps1 -UsePnpm  走 pnpm 官方安装路线（慢网可能超时）
    powershell -File update-lingshu.ps1 -Tarball C:\path\dsh-memory-0.4.9.tgz
    powershell -File update-lingshu.ps1 -Force    已是最新也重装一遍

  日志：%TEMP%\update-lingshu.log
#>
[CmdletBinding()]
param(
  [string]$Profile = 'web',
  [switch]$NoRestart,
  [switch]$DryRun,
  [switch]$Force,
  [switch]$UsePnpm,
  [string]$Tarball = ''
)

$ErrorActionPreference = 'Stop'

$Pkg         = '@furongjun1999/dsh-memory'
$ProfileDir  = Join-Path $env:USERPROFILE ('.dsh\profiles\' + $Profile)
$PluginDir   = Join-Path $ProfileDir 'node_modules\@furongjun1999\dsh-memory'
$WsFile      = Join-Path $ProfileDir 'pnpm-workspace.yaml'
$PkgJson     = Join-Path $ProfileDir 'package.json'
$LogFile     = Join-Path $env:TEMP 'update-lingshu.log'
$Stamp       = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:TargetVersion = ''
$script:Stopped       = $false

function Log {
  param([string]$m, [string]$c = 'Gray')
  $line = '[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $m
  Write-Host $line -ForegroundColor $c
  try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch { }
}

function Get-InstalledVersion {
  $p = Join-Path $PluginDir 'package.json'
  if (-not (Test-Path $p)) { return '' }
  $m = [regex]::Match((Get-Content $p -Raw -Encoding UTF8), '"version"\s*:\s*"([^"]+)"')
  if ($m.Success) { return $m.Groups[1].Value }
  return ''
}

function Get-LatestVersion {
  $v = (& npm view $Pkg version 2>$null | Out-String).Trim()
  if ($v -notmatch '^\d+\.\d+\.\d+') { throw ('无法从 npm 取到最新版本（返回: ' + $v + '）') }
  return $v
}

function Get-NpmIntegrity {
  param([string]$Version)
  $v = (& npm view ($Pkg + '@' + $Version) dist.integrity 2>$null | Out-String).Trim()
  if ($v -notmatch '^sha512-') { throw ('无法取到 ' + $Version + ' 的 dist.integrity，拒绝在无法校验的情况下覆盖安装') }
  return $v
}

function Get-FileSha512 {
  param([string]$Path)
  $hex = (Get-FileHash $Path -Algorithm SHA512).Hash
  $bytes = New-Object byte[] ($hex.Length / 2)
  for ($i = 0; $i -lt $hex.Length; $i += 2) { $bytes[$i / 2] = [Convert]::ToByte($hex.Substring($i, 2), 16) }
  return 'sha512-' + [Convert]::ToBase64String($bytes)
}

function Set-ReleaseGate {
  param([string]$Version)
  $text = Get-Content $WsFile -Raw -Encoding UTF8
  $pattern = "(?m)^(\s*-\s*'?)" + [regex]::Escape($Pkg) + "@([^'\r\n]*)('?)\s*$"
  $m = [regex]::Match($text, $pattern)
  if ($m.Success) {
    $list = $m.Groups[2].Value
    $has = $false
    foreach ($v in ($list -split '\|\|')) { if ($v.Trim() -eq $Version) { $has = $true } }
    if ($has) {
      Log ('发布龄闸门已放行 ' + $Version)
    } elseif ($DryRun) {
      Log ('[dry-run] 将把 ' + $Version + ' 追加进 minimumReleaseAgeExclude')
    } else {
      $new = $m.Groups[1].Value + $Pkg + '@' + $list.Trim() + ' || ' + $Version + $m.Groups[3].Value
      $text = $text.Replace($m.Value, $new)
      Log ('已放行发布龄闸门: ' + $Pkg + '@' + $Version)
    }
  } else {
    if ($text -match '(?m)^minimumReleaseAgeExclude:') {
      throw 'pnpm-workspace.yaml 的 minimumReleaseAgeExclude 不是单行列表，请手动把最新版本加进去'
    }
    if ($DryRun) {
      Log '[dry-run] 将新增 minimumReleaseAgeExclude 段落'
    } else {
      $text = $text.TrimEnd() + [Environment]::NewLine + 'minimumReleaseAgeExclude:' + [Environment]::NewLine + "  - '" + $Pkg + '@' + $Version + "'" + [Environment]::NewLine
      Log '已新增 minimumReleaseAgeExclude 放行条目'
    }
  }
  if ($text -notmatch '(?m)^fetchTimeout:') {
    if ($DryRun) {
      Log '[dry-run] 将把 pnpm 下载超时放宽到 900s（慢网必需）'
    } else {
      $text = $text.TrimEnd() + [Environment]::NewLine + 'fetchTimeout: 900000' + [Environment]::NewLine
      Log '已把 pnpm 下载超时放宽到 900s（慢网必需）'
    }
  }
  if (-not $DryRun) { [System.IO.File]::WriteAllText($WsFile, $text, (New-Object System.Text.UTF8Encoding($false))) }
}

function Set-ProfileRange {
  param([string]$Version)
  $text = Get-Content $PkgJson -Raw -Encoding UTF8
  $pattern = '("' + [regex]::Escape($Pkg) + '"\s*:\s*")(?<v>[^"]*)(")'
  $m = [regex]::Match($text, $pattern)
  if (-not $m.Success) { throw ('profile package.json 里没有 ' + $Pkg + '，请先用 dsh plugin --profile ' + $Profile + ' add 安装') }
  $old = $m.Groups['v'].Value
  $newRange = '^' + $Version
  if ($old -eq $newRange) {
    Log ('依赖区间已是 ' + $newRange)
    return
  }
  if ($DryRun) {
    Log ('[dry-run] 将把依赖区间 ' + $old + ' 改成 ' + $newRange)
    return
  }
  $text = $text.Replace($m.Value, $m.Groups[1].Value + $newRange + $m.Groups[3].Value)
  [System.IO.File]::WriteAllText($PkgJson, $text, (New-Object System.Text.UTF8Encoding($false)))
  Log ('依赖区间 ' + $old + ' → ' + $newRange)
}

function Sync-Lockfile {
  if ($DryRun) { Log '[dry-run] 将执行 pnpm install --lockfile-only'; return }
  Push-Location $ProfileDir
  try {
    $o = (& pnpm install --lockfile-only 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0) {
      Log 'lockfile 已同步到目标版本'
    } else {
      Log 'lockfile 同步失败（不致命，稍后由安装步骤兜底）' 'Yellow'
    }
  } catch {
    Log ('lockfile 同步异常: ' + $_.Exception.Message) 'Yellow'
  } finally { Pop-Location }
}

function Get-Tarball {
  param([string]$Version, [string]$Hint, [string]$Integrity)
  if ($Hint -ne '') {
    if (-not (Test-Path $Hint)) { throw ('指定的 tarball 不存在: ' + $Hint) }
    $full = (Get-Item $Hint).FullName
    if ((Get-FileSha512 $full) -ne $Integrity) { throw ('本地 tarball 的 sha512 与 registry 不一致: ' + $full) }
    Log ('使用本地 tarball: ' + $full + '（sha512 校验通过）')
    return $full
  }
  $out = Join-Path $env:TEMP ('lingshu-' + $Version + '.tgz')
  if (Test-Path $out) {
    if ((Get-FileSha512 $out) -eq $Integrity) { Log ('复用已缓存且校验通过的 tarball: ' + $out); return $out }
    Remove-Item $out -Force
  }
  $short = $Pkg.Substring($Pkg.IndexOf('/') + 1)
  $url = 'https://registry.npmjs.org/' + $Pkg + '/-/' + $short + '-' + $Version + '.tgz'
  if ($DryRun) {
    Log ('[dry-run] 将断点续传下载 ' + $url + ' 并校验 sha512')
    return $out
  }
  for ($i = 1; $i -le 15; $i++) {
    & curl.exe -sS -L -C - -o $out --retry 3 --retry-delay 3 --max-time 900 --connect-timeout 30 $url 2>$null
    $sz = 0
    if (Test-Path $out) { $sz = (Get-Item $out).Length }
    if ((Test-Path $out) -and ((Get-FileSha512 $out) -eq $Integrity)) {
      Log ('tarball 下载完成并校验通过: ' + [math]::Round($sz / 1MB, 2) + ' MB')
      return $out
    }
    Log ('  第 ' + $i + ' 次下载未完（' + [math]::Round($sz / 1MB, 2) + ' MB），继续断点续传…')
    Start-Sleep -Seconds 3
  }
  throw '下载 tarball 失败（网络过慢）。可手动下载后用 -Tarball 指定本地文件'
}

function Stop-Holders {
  param([bool]$IncludeDsh)
  $n = 0
  $procs = Get-CimInstance Win32_Process -Filter "name='node.exe' or name='python.exe' or name='pythonw.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $procs) {
    $cl = [string]$p.CommandLine
    if ($cl -eq '') { continue }
    $kill = $false
    if ($cl -match 'md_cg') { $kill = $true }
    if ($IncludeDsh -and ($cl -match '@deepseek-ai[\\/]dsh')) { $kill = $true }
    if ($kill) {
      try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Log ('  已结束 pid=' + $p.ProcessId)
        $n++
      } catch {
        Log ('  pid=' + $p.ProcessId + ' 结束失败（可能已退出）')
      }
    }
  }
  return $n
}

function Install-Overlay {
  param([string]$Tgz, [string]$Version)
  $stage = Join-Path $env:TEMP ('lingshu-stage-' + $Version)
  if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  Log '  解包发布包…'
  & tar.exe -xzf $Tgz -C $stage
  $src = Join-Path $stage 'package'
  if (-not (Test-Path (Join-Path $src 'package.json'))) { throw '解包结果缺少 package/package.json' }
  $m = [regex]::Match((Get-Content (Join-Path $src 'package.json') -Raw -Encoding UTF8), '"version"\s*:\s*"([^"]+)"')
  if (-not $m.Success -or $m.Groups[1].Value -ne $Version) { throw ('发布包内版本不是 ' + $Version) }
  $suspect = Get-ChildItem $src -Recurse -File -Force | Where-Object { $_.Name -in @('_keys.json', '_audit.jsonl', '_index.json', '_refindex.json') }
  if ($suspect) { throw ('发布包内出现不应发布的运行时文件: ' + $suspect[0].FullName) }
  Log '  覆盖写入插件目录（不重命名目录，DSH 开着也能装）…'
  & robocopy $src $PluginDir /E /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
  Log '  逐文件哈希核对…'
  $bad = New-Object System.Collections.ArrayList
  $all = Get-ChildItem $src -Recurse -File -Force
  foreach ($f in $all) {
    $rel = $f.FullName.Substring($src.Length + 1)
    $dst = Join-Path $PluginDir $rel
    if (-not (Test-Path $dst)) { [void]$bad.Add('缺失 ' + $rel); continue }
    if ((Get-Item $dst).Length -ne $f.Length) { [void]$bad.Add('大小不符 ' + $rel); continue }
    if ((Get-FileHash $dst -Algorithm SHA256).Hash -ne (Get-FileHash $f.FullName -Algorithm SHA256).Hash) { [void]$bad.Add('内容不符 ' + $rel) }
  }
  if ($bad.Count -gt 0) { throw ('覆盖后核对失败 ' + $bad.Count + ' 个文件，例如: ' + $bad[0]) }
  Log ('  核对通过: ' + $all.Count + ' 个文件与发布包逐字节一致')
}

function Install-WithPnpm {
  Push-Location $ProfileDir
  try {
    for ($i = 1; $i -le 6; $i++) {
      Log ('  pnpm update（第 ' + $i + ' 次）…')
      $o = (& pnpm update 2>&1 | Out-String)
      $v = Get-InstalledVersion
      if ($v -eq $script:TargetVersion) { return $true }
      Log ('  本轮结果仍为 ' + $v + '，重试前再清一次占锁子进程…')
      [void](Stop-Holders -IncludeDsh:$false)
      Start-Sleep -Seconds 3
    }
    return $false
  } finally { Pop-Location }
}

function Start-Dsh {
  $bat = Join-Path $PluginDir 'dsh\dsh-web-start.bat'
  if (-not (Test-Path $bat)) { Log ('找不到启动脚本: ' + $bat) 'Yellow'; return }
  Log '启动 DSH…'
  Start-Process -FilePath $bat -WorkingDirectory (Split-Path $bat) | Out-Null
  Log 'DSH 已在新窗口启动；浏览器访问 http://127.0.0.1:3080'
}

# ============================ 主流程 ============================
Log '===== 灵枢一键更新 ====='
Log ('profile 目录: ' + $ProfileDir)
if ($DryRun) { Log '运行模式: DryRun（不落任何修改）' 'Yellow' }

try {
  if (-not (Test-Path $PluginDir)) { throw ('找不到插件目录: ' + $PluginDir) }
  $cur = Get-InstalledVersion
  $script:TargetVersion = Get-LatestVersion
  Log ('当前版本 ' + $cur + '  →  npm 最新 ' + $script:TargetVersion)

  if ($cur -eq $script:TargetVersion -and -not $Force -and $Tarball -eq '') {
    Log '已经是最新版本，未做任何修改。' 'Green'
    exit 0
  }

  if (-not $DryRun) {
    Copy-Item $WsFile ($WsFile + '.pre-update-' + $Stamp) -Force
    Copy-Item $PkgJson ($PkgJson + '.pre-update-' + $Stamp) -Force
    Log ('已备份 profile 配置（后缀 pre-update-' + $Stamp + '）')
  }

  Log '--- 1/5 放行发布龄闸门 + 声明目标版本 ---'
  Set-ReleaseGate -Version $script:TargetVersion
  Set-ProfileRange -Version $script:TargetVersion

  Log '--- 2/5 同步 lockfile（只写 lockfile，不动目录）---'
  Sync-Lockfile

  Log '--- 3/5 准备发布包（sha512 校验）---'
  $integrity = Get-NpmIntegrity $script:TargetVersion
  $tgz = Get-Tarball -Version $script:TargetVersion -Hint $Tarball -Integrity $integrity
  if ($DryRun) {
    Log '--- DryRun 结束：以上动作均未执行 ---' 'Yellow'
    Log ('完整日志: ' + $LogFile)
    exit 0
  }

  Log '--- 4/5 停 DSH 与 md_cg 子进程（释放目录锁）---'
  $killed = Stop-Holders -IncludeDsh:$true
  $script:Stopped = $killed -gt 0
  Log ('共结束 ' + $killed + ' 个进程；等待文件句柄释放…')
  Start-Sleep -Seconds 3

  Log '--- 5/5 安装 ---'
  $ok = $false
  if ($UsePnpm) {
    $ok = Install-WithPnpm
    if (-not $ok) { Log 'pnpm 路线未成功，改用发布包覆盖安装…' 'Yellow' }
  }
  if (-not $ok) { Install-Overlay -Tgz $tgz -Version $script:TargetVersion }
  $final = Get-InstalledVersion
  if ($final -ne $script:TargetVersion) { throw ('安装后版本仍为 ' + $final + '，预期 ' + $script:TargetVersion) }
  Log ('安装完成: ' + $cur + ' → ' + $final) 'Green'

  if ($NoRestart) {
    Log '按 -NoRestart 未重启 DSH，请手动运行 dsh\dsh-web-start.bat' 'Yellow'
  } else {
    Start-Dsh
  }
  Log ('完整日志: ' + $LogFile)
  exit 0
} catch {
  Log ('[失败] ' + $_.Exception.Message) 'Red'
  Log ('完整日志: ' + $LogFile) 'Red'
  if ($script:Stopped -and -not $NoRestart) { Log '尝试把 DSH 重新拉起来…' 'Yellow'; Start-Dsh }
  exit 1
}
