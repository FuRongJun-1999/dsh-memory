# Register nightly hot-tier sync: rebuild _hot/ + write daily digest into the main brain (idempotent, soft-deletable).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/register_hot_sync_task.ps1 [-BrainRoot D:\program\AEIS\data\mdcg] [-Time 02:30]
param(
  [string]$BrainRoot = 'D:\program\AEIS\data\mdcg',
  [string]$Time = '02:30',
  [string]$TaskName = 'LingshuHotTierNightly'
)
$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$script = Join-Path $repo 'scripts\sync_hot_tier.py'
$pyArgs = "-X utf8 `"$script`" --root `"$BrainRoot`" --write"
$action = New-ScheduledTaskAction -Execute $python -Argument $pyArgs -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Lingshu: nightly rebuild local hot tier + daily digest (idempotent)' -Force | Out-Null
Write-Host ('Registered: ' + $TaskName + ' daily ' + $Time + ' -> ' + $python + ' ' + $pyArgs)
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State | Format-List