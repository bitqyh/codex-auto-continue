# Collect diagnostics for Codex Auto Continue on Windows.
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$data = Join-Path $env:APPDATA "codex-auto-continue"
$out = Join-Path $env:TEMP ("codex-auto-continue-diag-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Section($title, $body) {
    Add-Content -Path $out -Value ("`r`n===== {0} =====" -f $title) -Encoding UTF8
    Add-Content -Path $out -Value ($body | Out-String) -Encoding UTF8
}

function Find-Codex {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:USERPROFILE ".codex\.sandbox-bin\codex.exe"),
        (Join-Path $env:USERPROFILE ".codex\bin\codex.exe"),
        (Join-Path $env:APPDATA "npm\codex.cmd"),
        (Join-Path $env:LOCALAPPDATA "Programs\Codex\codex.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

Section "time" (Get-Date)
Section "os" (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber)
Section "powershell" $PSVersionTable
Section "python" (& python --version 2>&1)
Section "python-path" (& where.exe python 2>&1)
$codex = Find-Codex
if ($codex) {
    Section "codex" ("path: {0}`nversion: {1}" -f $codex, (& $codex --version 2>&1))
    Section "codex-login" (& $codex login status 2>&1)
} else {
    Section "codex" "codex CLI not found on PATH or in a known install location"
}
$repoInfo = @()
$repoInfo += git -C $repo log -1 --oneline 2>&1
$repoInfo += git -C $repo status --short 2>&1
Section "repo" ($repoInfo -join "`n")

$taskInfo = @()
$taskInfo += schtasks /Query /TN CodexAutoContinue /V /FO LIST 2>&1
$taskInfo += schtasks /Query /TN CodexAutoContinue /XML 2>&1
Section "task" ($taskInfo -join "`n")

$xml = Join-Path $data "task-scheduler.xml"
if (Test-Path $xml) { Section "task-xml-file" (Get-Content $xml -Raw -Encoding Unicode) }

Section "data-dir" (Get-ChildItem $data -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime)
foreach ($log in @("run.log", "tray.log")) {
    $path = Join-Path $data $log
    if (Test-Path $path) { Section $log (Get-Content $path -Tail 60 -Encoding UTF8) }
}

$powerInfo = @()
$powerInfo += powercfg /a 2>&1
$powerInfo += powercfg /lastwake 2>&1
$powerInfo += powercfg /waketimers 2>&1
Section "powercfg" ($powerInfo -join "`n")
Write-Host "diagnostics written to: $out"
