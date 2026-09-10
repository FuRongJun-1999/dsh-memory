' bootstrap-watchdog-launcher.vbs - hidden launcher for bootstrap_watchdog.py
' WScript.Shell.Run with window style 0 = fully hidden (no console flash).
' Used by Windows Task Scheduler (task: lingshu-bootstrap-watchdog, every 10 min).
' NOTE: keep this file ASCII-only. cscript reads .vbs as ANSI, so non-ASCII
' comments can shift byte pairing and swallow the next line's leading quote.
Dim fso, ws, here, py, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
' Prefer the interpreter that has the loop's deps; fall back to PATH.
py = ws.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\python.exe")
If Not fso.FileExists(py) Then py = "python"
cmd = """" & py & """ """ & here & "\bootstrap_watchdog.py"""
ws.Run cmd, 0, False
