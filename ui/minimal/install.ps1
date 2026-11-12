param([string]$PluginPath, [switch]$Uninstall, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Read-Text([string]$Path) { [IO.File]::ReadAllText($Path, $utf8) }
function Write-Text([string]$Path, [string]$Text) {
  $parent = Split-Path -Parent $Path
  if (!(Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  [IO.File]::WriteAllText($Path, $Text, $utf8)
}
function Set-Property($Object, [string]$Name, $Value) {
  if ($Object.PSObject.Properties[$Name]) { $Object.$Name = $Value }
  else { $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value }
}
function Assert-Package([string]$Path) {
  $p = Join-Path $Path 'package.json'
  if (!(Test-Path -LiteralPath $p)) { throw '选择目录没有 package.json。请指定灵枢插件根目录。' }
  $pkg = (Read-Text $p) | ConvertFrom-Json
  if ($pkg.name -ne '@furongjun1999/dsh-memory') { throw '目标不是 @furongjun1999/dsh-memory，已停止。' }
  return $pkg
}
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
function Resolve-Plugin {
  if ($PluginPath) { return (Resolve-Path -LiteralPath $PluginPath).Path }
  $homeDir = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE '.dsh' }
  $candidates = @()
  $external = Join-Path $homeDir 'external-plugins\dsh-memory'
  if (Test-Path -LiteralPath (Join-Path $external 'package.json')) { $candidates += $external }
  $profiles = Join-Path $homeDir 'profiles'
  if (Test-Path -LiteralPath $profiles) {
    foreach ($profile in Get-ChildItem -LiteralPath $profiles -Directory) {
      $path = Join-Path $profile.FullName 'node_modules\@furongjun1999\dsh-memory'
      if (Test-Path -LiteralPath (Join-Path $path 'package.json')) { $candidates += $path }
    }
  }
  $unique = @{}
  foreach ($candidate in $candidates) {
    $item = Get-Item -LiteralPath $candidate
    $physical = if ($item.Target) { $item.Target | Select-Object -First 1 } else { $item.FullName }
    if (![IO.Path]::IsPathRooted($physical)) { $physical = [IO.Path]::GetFullPath((Join-Path $item.Parent.FullName $physical)) }
    $unique[$physical.ToLowerInvariant()] = $physical
  }
  $paths = @($unique.Values)
  if ($paths.Count -eq 1) { return $paths[0] }
  Write-Host '未找到唯一灵枢插件目录。请输入已有插件的根目录：'
  foreach ($path in $paths) { Write-Host ('  ' + $path) }
  $inputPath = (Read-Host '路径').Trim().Trim('"')
  if (!$inputPath) { throw '未指定插件路径。请先安装原版灵枢插件。' }
  return (Resolve-Path -LiteralPath $inputPath).Path
}
$target = Resolve-Plugin
$pkg = Assert-Package $target
$stateDir = Join-Path $target '.lingshu-ui-backup-v1'
$statePath = Join-Path $stateDir 'state.json'
if ($Uninstall) {
  if (!(Test-Path -LiteralPath $statePath)) { throw '没有本安装器的备份，拒绝覆盖或删除文件。' }
  $state = (Read-Text $statePath) | ConvertFrom-Json
  if ($state.target -ne $target) { throw '备份目录与安装目标不一致，已停止。' }
  foreach ($record in $state.records) {
    $path = Join-Path $target $record.relative
    if (!(Test-Path -LiteralPath $path) -or (Hash $path) -ne $record.installedHash) {
      throw ('安装后文件已经改变，为避免覆盖你的改动，卸载已停止：' + $record.relative)
    }
    if ($record.existed) {
      $backup = Join-Path $stateDir ('files\' + $record.relative)
      if (!(Test-Path -LiteralPath $backup) -or (Hash $backup) -ne $record.originalHash) { throw '备份校验失败，卸载已停止。' }
    }
  }
  if ($CheckOnly) { Write-Host '卸载检查通过，未修改文件。'; exit 0 }
  foreach ($record in $state.records) {
    $path = Join-Path $target $record.relative
    if ($record.existed) { Copy-Item -LiteralPath (Join-Path $stateDir ('files\' + $record.relative)) -Destination $path -Force }
    else {
      # 删除前确认绝对目标在已校验的插件根下；只删除本安装器新增的已校验文件。
      $absolute = [IO.Path]::GetFullPath($path)
      if (!$absolute.StartsWith($target.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '删除路径越界，已停止。' }
      Remove-Item -LiteralPath $absolute -Force
    }
  }
  $absoluteState = [IO.Path]::GetFullPath($statePath)
  if ($absoluteState -ne [IO.Path]::GetFullPath((Join-Path $target '.lingshu-ui-backup-v1\state.json'))) { throw '状态路径不一致。' }
  Remove-Item -LiteralPath $absoluteState -Force
  Write-Host '已恢复安装前代码。备份副本仍保留；没有删除记忆、凭据或配置。请重新启动 DSH。'
  exit 0
}
$payload = Join-Path $PSScriptRoot 'payload'
$integrity = (Read-Text (Join-Path $PSScriptRoot 'integrity.json')) | ConvertFrom-Json
foreach ($record in $integrity.files) {
  $path = Join-Path $payload $record.path
  if (!(Test-Path -LiteralPath $path) -or (Hash $path) -ne $record.sha256) { throw ('分享包文件缺失或损坏：' + $record.path) }
}
if (Test-Path -LiteralPath $statePath) {
  $state = (Read-Text $statePath) | ConvertFrom-Json
  foreach ($record in $state.records) {
    $path = Join-Path $target $record.relative
    if (!(Test-Path -LiteralPath $path) -or (Hash $path) -ne $record.installedHash) { throw '之前安装的文件发生改变。请手工检查，避免覆盖更新。' }
  }
  Write-Host '此插件已安装本 UI，无需重复安装。'; exit 0
}
$indexPath = Join-Path $target 'lib\index.js'
$index = Read-Text $indexPath
if (!$index.Contains('installRoleplayWeb') -or !$index.Contains('disposers, mdcg')) { throw '此灵枢版本入口不兼容，本包适配 0.8.1 的单桥入口。未修改文件。' }
if (!$index.Contains('installConsoleWeb')) {
  $index = "import { installConsoleWeb } from './lib/console_web.mjs';`n" + $index
  $pattern = '(await\s+installRoleplayWeb\(ctx,\s*capability,\s*config,\s*disposers,\s*mdcg\);)'
  $matches = [regex]::Matches($index, $pattern)
  if ($matches.Count -ne 1) { throw '未找到唯一大脑桥安装位置，已停止。' }
  $index = [regex]::Replace($index, $pattern, '$1' + "`n        installConsoleWeb(ctx, config, disposers, mdcg);")
}
$changes = @{'lib\index.js' = $index}
$sourcePath = Join-Path $target 'src\index.ts'
if (Test-Path -LiteralPath $sourcePath) {
  $source = Read-Text $sourcePath
  if (!$source.Contains('installConsoleWeb')) {
    $source = "// @ts-ignore UI helper is copied by build-ui.mjs`nimport { installConsoleWeb } from './lib/console_web.mjs'`n" + $source
    $pattern = '(await\s+installRoleplayWeb\(ctx,\s*capability,\s*config,\s*disposers,\s*mdcg\))'
    if ([regex]::Matches($source, $pattern).Count -ne 1) { throw 'TypeScript 入口不兼容，已停止。' }
    $source = [regex]::Replace($source, $pattern, '$1' + "`n    installConsoleWeb(ctx, config, disposers, mdcg)")
  }
  $changes['src\index.ts'] = $source
}
if (!$pkg.exports -or !$pkg.dsh) { throw '此插件清单格式不兼容，已停止。' }
Set-Property $pkg.exports './client' './lib/client.js'
Set-Property $pkg.dsh 'client' ([pscustomobject]@{platform='web';immediately=$true;inject=@('@deepseek-ai/dsh-client-ui-renderer','@deepseek-ai/dsh-client-ui-layout','@deepseek-ai/dsh-client-ui-sidebar')})
if ($pkg.scripts) {
  Set-Property $pkg.scripts 'build:ui' 'node build-ui.mjs'
  if ($pkg.scripts.build -and !$pkg.scripts.build.Contains('build-ui.mjs')) { $pkg.scripts.build += ' && node build-ui.mjs' }
}
if ($pkg.files) { $pkg.files = @($pkg.files) + @('web','build-ui.mjs') | Select-Object -Unique }
$changes['package.json'] = ($pkg | ConvertTo-Json -Depth 100) + "`n"
foreach ($record in $integrity.files) { $changes[$record.path.Replace('/','\')] = Read-Text (Join-Path $payload $record.path) }
Write-Host ('目标：' + $target)
Write-Host ('现有灵枢版本：' + $pkg.version)
Write-Host '仅修改 UI 代码和插件清单；不修改 DSH profile、root、记忆、凭据或自动记忆开关。'
if ($CheckOnly) { Write-Host ('兼容性与完整性检查通过，计划修改 ' + $changes.Count + ' 个文件，未修改文件。'); exit 0 }
Write-Host '安装前请完全退出 DSH（包括托盘）。未退出会使用旧模块缓存。'
$records = @()
foreach ($relative in $changes.Keys) {
  $path = Join-Path $target $relative
  $existed = Test-Path -LiteralPath $path
  $originalHash = if ($existed) { Hash $path } else { $null }
  if ($existed) {
    $backup = Join-Path $stateDir ('files\' + $relative)
    New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
    Copy-Item -LiteralPath $path -Destination $backup -Force
  }
  $records += [pscustomobject]@{relative=$relative;existed=$existed;originalHash=$originalHash;installedHash=$null}
}
try {
  foreach ($record in $records) {
    $path = Join-Path $target $record.relative
    Write-Text $path $changes[$record.relative]
    $record.installedHash = Hash $path
  }
  Write-Text $statePath (([pscustomobject]@{target=$target;version='1.0.0';records=$records}) | ConvertTo-Json -Depth 20)
} catch {
  foreach ($record in $records) {
    $path = Join-Path $target $record.relative
    if ($record.existed) { Copy-Item -LiteralPath (Join-Path $stateDir ('files\' + $record.relative)) -Destination $path -Force }
    elseif (Test-Path -LiteralPath $path) {
      $absolute = [IO.Path]::GetFullPath($path)
      if ($absolute.StartsWith($target.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $absolute -Force }
    }
  }
  throw
}
Write-Host '安装完成。重新启动 DSH 后，在左侧点击「灵枢」。'
Write-Host 'UI 复用你原有灵枢的本机大脑桥，因此读取的是你自己的记忆库。'
