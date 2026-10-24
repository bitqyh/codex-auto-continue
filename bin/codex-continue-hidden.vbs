' Runs codex-continue.cmd without opening a console window.
'
' The command is launched through cmd.exe explicitly: WScript.Shell.Run on the
' .cmd file itself goes through ShellExecute, which can raise the Windows
' "Open File - Security Warning" dialog when the repository lives in a folder
' that Windows treats as untrusted (observed on a real Windows 11 box). The
' dialog blocks the scheduled task forever because it runs without a visible
' window. cmd.exe /d /c starts the batch file through CreateProcess instead.
Option Explicit

Dim fso, shell, base, script, quote, command, argument

Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(base, "codex-continue.cmd")
quote = Chr(34)

command = "cmd.exe /d /c " & quote & quote & script & quote
For Each argument In WScript.Arguments
  command = command & " " & quote & argument & quote
Next
command = command & quote

Set shell = CreateObject("WScript.Shell")
shell.Run command, 0, False
