# Build the Windows portable bundle (embeddable Python + repo + tray).
#
# Output:
#   dist/CodexContinue-<version>-win-x64/      (folder, used by Inno Setup)
#   dist/CodexContinue-<version>-win-x64.zip   (portable release asset)
#
# The embeddable Python ignores PYTHONPATH, so "..\src" is appended to its ._pth.
[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$PythonVersion = "3.12.10",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Version) {
    $match = Select-String -Path (Join-Path $repo "pyproject.toml") -Pattern '^version = "([^"]+)"' | Select-Object -First 1
    if (-not $match) { throw "cannot read version from pyproject.toml" }
    $Version = $match.Matches[0].Groups[1].Value
}
if (-not $OutDir) { $OutDir = Join-Path $repo "dist" }

$bundleName = "CodexContinue-$Version-win-x64"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("cac-bundle-" + [guid]::NewGuid().ToString("N"))
$bundle = Join-Path $tempRoot $bundleName

try {
    New-Item -ItemType Directory -Path $bundle -Force | Out-Null

    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    $pyZip = Join-Path $tempRoot "python-embed.zip"
    Write-Host "downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $pyZip -UseBasicParsing

    $pythonDir = Join-Path $bundle "python"
    Expand-Archive -Path $pyZip -DestinationPath $pythonDir -Force

    $pth = Get-ChildItem -Path $pythonDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { throw "no python*._pth in the embeddable distribution" }
    Add-Content -Path $pth.FullName -Value "..\src" -Encoding ASCII

    Copy-Item -Recurse -Path (Join-Path $repo "src") -Destination (Join-Path $bundle "src")
    Copy-Item -Recurse -Path (Join-Path $repo "bin") -Destination (Join-Path $bundle "bin")
    $trayParent = Join-Path $bundle "ui"
    New-Item -ItemType Directory -Path $trayParent -Force | Out-Null
    Copy-Item -Recurse -Path (Join-Path $repo "ui\windows-tray") -Destination (Join-Path $trayParent "windows-tray")

    foreach ($file in @("LICENSE", "README.md")) {
        Copy-Item -Path (Join-Path $repo $file) -Destination $bundle
    }
    $docsDir = Join-Path $bundle "docs"
    New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
    Copy-Item -Path (Join-Path $repo "docs\WINDOWS-TESTING.md") -Destination $docsDir
    $scriptsDir = Join-Path $bundle "scripts"
    New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
    Copy-Item -Path (Join-Path $repo "scripts\windows-diagnostics.ps1") -Destination $scriptsDir

    Get-ChildItem -Path $bundle -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $bundle -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $notices = @"
Codex Auto Continue bundles the Python runtime from python.org (embeddable package).

Python is licensed under the Python Software Foundation License.
See https://docs.python.org/3/license.html

Codex Auto Continue itself is MIT licensed; see LICENSE.
"@
    Set-Content -Path (Join-Path $bundle "THIRD_PARTY_NOTICES.txt") -Value $notices -Encoding UTF8

    $embedded = Join-Path $pythonDir "python.exe"
    $imported = & $embedded -c "import codex_auto_continue; print(codex_auto_continue.__version__)" 2>&1
    if ($LASTEXITCODE -ne 0 -or "$imported".Trim() -ne $Version) {
        throw "embedded Python cannot import codex_auto_continue (got: $imported)"
    }

    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $final = Join-Path $OutDir $bundleName
    if (Test-Path $final) { Remove-Item -Recurse -Force $final }
    Copy-Item -Recurse -Path $bundle -Destination $final

    $zipPath = "$final.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Compress-Archive -Path (Join-Path $final "*") -DestinationPath $zipPath

    Write-Host "bundle: $final"
    Write-Host "zip: $zipPath"
}
finally {
    Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
}
