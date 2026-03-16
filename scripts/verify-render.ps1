$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bridgeUrl = "http://127.0.0.1:5161"
$stdoutPath = Join-Path $projectRoot "storage\cache\verify-render.stdout.log"
$stderrPath = Join-Path $projectRoot "storage\cache\verify-render.stderr.log"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bridgeProcess = $null

function Invoke-BridgeJson {
    param(
        [string]$Uri,
        [string]$Method,
        [string]$Body = ""
    )

    if ($Body) {
        return Invoke-RestMethod -Uri $Uri -Method $Method -ContentType "application/json" -Body $Body -TimeoutSec 60
    }

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec 30
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "storage\cache") | Out-Null

try {
    Write-Host "[verify] start local bridge"
    $bridgeProcess = Start-Process -FilePath $python -ArgumentList "-m worker.bridge.server" -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

    $health = $null
    for ($index = 0; $index -lt 6; $index++) {
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
    $health | ConvertTo-Json -Depth 6

    $renderPayload = @{
        prompt = "30-second cafe promo reel with a warm morning mood"
        budgetMode = "standard"
        projectId = "verify-render-smoke"
        availability = @{
            premiumEnabled = $true
            sora2 = $true
            veo3 = $false
        }
    } | ConvertTo-Json -Depth 4

    Write-Host "[verify] render smoke through bridge"
    $renderResponse = Invoke-BridgeJson -Uri "$bridgeUrl/api/render-smoke" -Method Post -Body $renderPayload
    $renderResponse | ConvertTo-Json -Depth 6

    if (-not (Test-Path $renderResponse.renderResult.outputPath)) {
        throw "Expected render output at $($renderResponse.renderResult.outputPath)"
    }

    if (-not (Test-Path $renderResponse.renderResult.logPath)) {
        throw "Expected ffmpeg log at $($renderResponse.renderResult.logPath)"
    }

    Write-Host "[verify] render output path"
    Write-Host $renderResponse.renderResult.outputPath
}
finally {
    if ($bridgeProcess) {
        Write-Host "[verify] stop local bridge"
        Stop-Process -Id $bridgeProcess.Id -ErrorAction SilentlyContinue
    }
}
