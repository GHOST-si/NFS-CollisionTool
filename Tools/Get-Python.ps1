# Downloads the official Python "embeddable package" into <repo>\Python.
# Run automatically by the build when Python\pythonw.exe is missing; can also be run by hand.
# To change the bundled version, edit $Version (it must exist on python.org).

param([string]$Version = "3.14.7")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "Python"
$zip  = Join-Path ([System.IO.Path]::GetTempPath()) "python-$Version-embed-amd64.zip"
$url  = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"

try {
    Write-Host "Downloading $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Write-Host "Python $Version extracted to $dest"
}
catch {
    Write-Warning "Could not download Python ($($_.Exception.Message)). Download the embeddable package manually and extract it to '$dest' (see README.md)."
    exit 0
}
finally {
    if (Test-Path $zip) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
}
