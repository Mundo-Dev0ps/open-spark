# Boot OBS in --portable mode against .\.portable-obs\ so dev work doesn't
# touch your real OBS config. Windows / PowerShell.
#
# Usage: pwsh ./scripts/run_portable_obs.ps1

$ErrorActionPreference = "Stop"

$PortableDir = Join-Path (Split-Path -Parent $PSScriptRoot) ".portable-obs"
New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null

$Candidates = @(
  "C:\Program Files\obs-studio\bin\64bit\obs64.exe",
  "C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"
)

$Obs = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Obs) {
    Write-Error "OBS not found. Install from https://obsproject.com/."
    exit 1
}

Write-Host "Launching $Obs in portable mode at $PortableDir"
Push-Location $PortableDir
try {
    & $Obs --portable --multi
} finally {
    Pop-Location
}
