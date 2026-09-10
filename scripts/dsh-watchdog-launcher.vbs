' dsh-watchdog-launcher.vbs - hidden launcher for dsh-watchdog.ps1
' WScript.Shell.Run with window style 0 = fully hidden (no flash).
' Usage:
'   wscript.exe dsh-watchdog-launcher.vbs           -> once mode (for Task Scheduler)
'   wscript.exe dsh-watchdog-launcher.vbs -loop     -> resident loop mode
' NOTE: keep this file ASCII-only. cscript reads .vbs as ANSI, so non-ASCII
' comments can shift byte pairing and swallow the next line's leading quote.
Dim args, mode, ws, fso, here, ps
Set args = WScript.Arguments
mode = "-Once"
If args.Count > 0 Then mode = args(0)
' Resolve dsh-watchdog.ps1 from this script's own folder, so the repo works
' wherever it is cloned (no hard-coded absolute path).
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set ws = CreateObject("WScript.Shell")
ps = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & here & "\dsh-watchdog.ps1"" " & mode
ws.Run ps, 0, False
