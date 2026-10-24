# Collect diagnostics for Codex Auto Continue on Windows.
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$data = Join-Path $env:APPDATA "codex-auto-continue"
$out = Join-Path $env:TEMP ("codex-auto-continue-diag-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Section($title, $body) {
    Add-Content -Path $out -Value ("`r`n===== {0} =====" -f $title) -Encoding UTF8
    Add-Content -Path $out -Value ($body | Out-String) -Encoding UTF8
}

Section "time" (Get-Date)
Section "os" (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber)
Section "powershell" $PSVersionTable
Section "python" (& python --version 2>&1)
Section "python-path" (& where.exe python 2>&1)
Section "codex" (& where.exe codex 2>&1; & codex --version 2>&1)
Section "repo" (git -C $repo log -1 --oneline 2>&1; git -C $repo status --short 2>&1)
Section "task" (schtasks /Query /TN CodexAutoContinue /V /FO LIST 2>&1)
$xml = Join-Path $data "task-scheduler.xml"
if (Test-Path $xml) { Section "task-xml" (Get-Content $xml -Raw) }
Section "data-dir" (Get-ChildItem $data -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime)
foreach ($log in @("run.log", "tray.log")) {
    $path = Join-Path $data $log
    if (Test-Path $path) { Section $log (Get-Content $path -Tail 60) }
}
Section "powercfg" (powercfg /a 2>&1; powercfg /lastwake 2>&1)
Write-Host "diagnostics written to: $out"
