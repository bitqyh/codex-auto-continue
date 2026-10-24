' Runs codex-continue.cmd without opening a console window.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = """" & base & "\codex-continue.cmd"" "
For Each arg In WScript.Arguments
  cmd = cmd & """" & arg & """ "
Next
CreateObject("WScript.Shell").Run cmd, 0, False
