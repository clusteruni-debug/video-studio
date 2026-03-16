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
        return Invoke-RestMethod -Uri $Uri -Method $Method -ContentType "application/json" -Body $Body -TimeoutSec 10
    }

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec 10
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "storage\cache") | Out-Null

try {
    Write-Host "[verify] start local bridge"
    $bridgeProcess = Start-Process -FilePath $python -ArgumentList "-m worker.bridge.server" -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

    $health = $null
    for ($index = 0; $index -lt 5; $index++) {
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

    if (-not (Test-Path $saveResponse.saveResult.manifestPath)) {
        throw "Bridge save did not create manifest at $($saveResponse.saveResult.manifestPath)"
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
