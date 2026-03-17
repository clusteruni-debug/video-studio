$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bridgeUrl = "http://127.0.0.1:5161"
$stdoutPath = Join-Path $projectRoot "storage\cache\verify-bridge.stdout.log"
$stderrPath = Join-Path $projectRoot "storage\cache\verify-bridge.stderr.log"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bridgeProcess = $null

function Invoke-BridgeJson {
    param(
        [string]$Uri,
        [string]$Method,
        [string]$Body = ""
    )

    if ($Body) {
        return Invoke-RestMethod -Uri $Uri -Method $Method -ContentType "application/json" -Body $Body -TimeoutSec 90
    }

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec 30
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "storage\cache") | Out-Null

try {
    Write-Host "[verify] start local bridge"
    $bridgeProcess = Start-Process -FilePath $python -ArgumentList "-m worker.bridge.server" -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

    $health = $null
    for ($index = 0; $index -lt 8; $index++) {
        Start-Sleep -Milliseconds 800
        try {
            $health = Invoke-BridgeJson -Uri "$bridgeUrl/api/health" -Method Get
            break
        }
        catch {
            $health = $null
        }
    }

    if (-not $health) {
        $stderr = if (Test-Path $stderrPath) { Get-Content $stderrPath -Raw } else { "" }
        throw "Bridge did not become healthy. $stderr"
    }

    Write-Host "[verify] bridge health"
    $health | ConvertTo-Json -Depth 4

    if (-not $health.planner) {
        throw "Bridge health did not expose planner runtime metadata"
    }

    if (-not $health.media.flux -or -not $health.media.wan) {
        throw "Bridge health did not expose local media adapter metadata"
    }

    Write-Host "[verify] route plan through bridge"
    $routePayload = @{
        prompt = "30-second cafe promo reel with a warm morning mood"
        budgetMode = "premium"
        availability = @{
            premiumEnabled = $true
            sora2 = $true
            veo3 = $false
        }
    } | ConvertTo-Json -Depth 4
    $routeResponse = Invoke-BridgeJson -Uri "$bridgeUrl/api/route-plan" -Method Post -Body $routePayload
    $routeResponse | ConvertTo-Json -Depth 5

    if (-not $routeResponse.planner) {
        throw "Bridge route response did not include planner metadata"
    }

    Write-Host "[verify] save project through bridge"
    $savePayload = @{
        prompt = "30-second cafe promo reel with a warm morning mood"
        budgetMode = "premium"
        projectId = "verify-bridge-save"
        availability = @{
            premiumEnabled = $true
            sora2 = $true
            veo3 = $false
        }
    } | ConvertTo-Json -Depth 4
    $saveResponse = Invoke-BridgeJson -Uri "$bridgeUrl/api/save-project" -Method Post -Body $savePayload
    $saveResponse | ConvertTo-Json -Depth 5

    if (-not $saveResponse.planner) {
        throw "Bridge save response did not include planner metadata"
    }

    if (-not (Test-Path $saveResponse.saveResult.manifestPath)) {
        throw "Bridge save did not create manifest at $($saveResponse.saveResult.manifestPath)"
    }

    if (-not $saveResponse.saveResult.localMediaPlanPath) {
        throw "Bridge save response did not include local media plan path"
    }

    if (-not (Test-Path $saveResponse.saveResult.localMediaPlanPath)) {
        throw "Bridge save did not create local media plan at $($saveResponse.saveResult.localMediaPlanPath)"
    }

    if (-not $saveResponse.saveResult.localMediaSummary) {
        throw "Bridge save response did not include local media summary"
    }

    Write-Host "[verify] bridge manifest path"
    Write-Host $saveResponse.saveResult.manifestPath
}
finally {
    if ($bridgeProcess) {
        Write-Host "[verify] stop local bridge"
        Stop-Process -Id $bridgeProcess.Id -ErrorAction SilentlyContinue
    }
}
