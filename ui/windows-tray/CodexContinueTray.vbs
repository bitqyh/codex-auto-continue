' Launch CodexContinueTray.ps1 without a console window.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = base & "\CodexContinueTray.ps1"
q = Chr(34)
cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & q & ps1 & q
CreateObject("WScript.Shell").Run cmd, 0, False
