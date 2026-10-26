# Rename the Inno Setup installer to make its unsigned status explicit.
#
# The project does not sign Windows installers (SignPath Foundation application
# was rejected). Publishing "-unsigned.exe" avoids implying a signature.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$DistDir = "dist"
)

$ErrorActionPreference = "Stop"

$unsigned = Get-ChildItem -Path $DistDir -File -Filter "CodexContinue-Setup-*.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike "*-unsigned.exe" } |
    Select-Object -First 1
if (-not $unsigned) { throw "no installer found in $DistDir" }

$target = Join-Path $DistDir ("CodexContinue-Setup-$Version-unsigned.exe")
Move-Item -Path $unsigned.FullName -Destination $target -Force
Write-Host "installer marked unsigned: $target"

if ($env:GITHUB_OUTPUT) {
    "signed=unsigned" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}
