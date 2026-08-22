' dsh-watchdog-launcher.vbs - hidden launcher for dsh-watchdog.ps1
' WScript.Shell.Run with window style 0 = fully hidden (no flash).
' Usage:
'   wscript.exe dsh-watchdog-launcher.vbs           -> once mode (for Task Scheduler)
'   wscript.exe dsh-watchdog-launcher.vbs -loop     -> resident loop mode
Dim args, mode, ws, ps
Set args = WScript.Arguments
mode = "-Once"
If args.Count > 0 Then mode = args(0)
Set ws = CreateObject("WScript.Shell")
ps = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\Program Files\2_ai\dsh-memory\scripts\dsh-watchdog.ps1"" " & mode
ws.Run ps, 0, False
