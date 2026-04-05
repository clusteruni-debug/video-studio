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

Push-Location $projectRoot
try {
    Write-Host "[verify] save sample plan to storage/"
    & $python -m worker.planner.save_plan --prompt "30-second cafe promo reel with a warm morning mood" --budget-mode premium --project-id verify-project-save --veo3

    Write-Host "[verify] emit render manifest preview"
    & $python -m worker.render.render_manifest --prompt "30-second cafe promo reel with a warm morning mood" --budget-mode premium --project-id verify-project --veo3

    $manifestPath = Join-Path $projectRoot "storage\inputs\verify-project-save\render-manifest.json"
    if (-not (Test-Path $manifestPath)) {
        throw "Missing render manifest at $manifestPath"
    }

    Write-Host "[verify] saved manifest location"
    Write-Host $manifestPath
}
finally {
    Pop-Location
}
