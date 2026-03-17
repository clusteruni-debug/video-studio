$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

Write-Host "[verify] route plan through planner CLI"
$raw = & $python -m worker.planner.route_plan --prompt "Warm cafe promo reel, 20 seconds, hero opening shot" --budget-mode premium --sora2

if ($LASTEXITCODE -ne 0) {
    throw "Planner CLI exited with code $LASTEXITCODE"
}

$payload = $raw | ConvertFrom-Json

if (-not $payload.plan) {
    throw "Planner payload did not include a plan"
}

if (-not $payload.planner) {
    throw "Planner payload did not include planner metadata"
}

if ($payload.plan.scenes.Count -lt 4) {
    throw "Planner returned fewer than 4 scenes"
}

Write-Host "[verify] planner backend"
Write-Host $payload.planner.backend

Write-Host "[verify] planner detail"
Write-Host $payload.planner.detail

Write-Host "[verify] first scene"
$payload.plan.scenes[0] | ConvertTo-Json -Depth 4
