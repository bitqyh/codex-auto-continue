# Normalize Windows release assets after the optional SignPath step.
#
# When SignPath signed the installer, copy the signed copy over the unsigned
# one. When signing was skipped, keep the installer but mark it "-unsigned" so
# the download page never implies a signature that does not exist.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$SignedDir = "signed",
    [string]$DistDir = "dist"
)

$ErrorActionPreference = "Stop"
$setupName = "CodexContinue-Setup-$Version.exe"

$signedExe = $null
if (Test-Path $SignedDir) {
    $signedExe = Get-ChildItem -Path $SignedDir -Recurse -File -Filter "CodexContinue-Setup-*.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
}
if (-not $signedExe -and (Test-Path $SignedDir)) {
    $signedExe = Get-ChildItem -Path $SignedDir -Recurse -File -Filter "*.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

$status = "unsigned"
if ($signedExe) {
    Copy-Item -Path $signedExe.FullName -Destination (Join-Path $DistDir $setupName) -Force
    $status = "signed"
    Write-Host "signed installer: $($signedExe.FullName)"
}
else {
    $unsigned = Get-ChildItem -Path $DistDir -File -Filter "CodexContinue-Setup-*.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike "*-unsigned.exe" } |
        Select-Object -First 1
    if ($unsigned) {
        $target = Join-Path $DistDir ("CodexContinue-Setup-$Version-unsigned.exe")
        Move-Item -Path $unsigned.FullName -Destination $target -Force
        Write-Host "installer left unsigned: $target"
    }
}

if ($env:GITHUB_OUTPUT) {
    "signed=$status" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}
Write-Host "windows installer: $status"
