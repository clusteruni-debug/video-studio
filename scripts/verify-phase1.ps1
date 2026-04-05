$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing project venv python at $python"
}

Write-Host "[verify] python version"
& $python --version

Write-Host "[verify] compile worker package"
& $python -m compileall (Join-Path $projectRoot "worker")

Write-Host "[verify] free-mode sample route"
Push-Location $projectRoot
try {
    & $python -m worker.planner.route_plan --prompt "30-second cafe promo reel with a warm morning mood" --budget-mode free

    Write-Host "[verify] premium-mode sample route"
    & $python -m worker.planner.route_plan --prompt "30-second cafe promo reel with a warm morning mood" --budget-mode premium --veo3
}
finally {
    Pop-Location
}

Write-Host "[verify] optional tools on PATH"
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$hf = Get-Command hf -ErrorAction SilentlyContinue

if ($ffmpeg) {
    Write-Host "ffmpeg: ok"
} else {
    Write-Warning "ffmpeg: not found on PATH in this shell"
}

if ($hf) {
    Write-Host "hf: ok"
} else {
    Write-Warning "hf: not found on PATH in this shell"
}
