param(
    [switch]$UsePollinationsFlux
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$bridgeUrl = "http://127.0.0.1:5161"
$stdoutPath = Join-Path $projectRoot "storage\cache\verify-render.stdout.log"
$stderrPath = Join-Path $projectRoot "storage\cache\verify-render.stderr.log"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bridgeProcess = $null
$bodyTimeoutSec = if ($UsePollinationsFlux) { 720 } else { 60 }

function Enable-PollinationsFluxCommand {
    $wrapperPath = Join-Path $projectRoot "scripts\pollinations_flux.py"
    if (-not (Test-Path $wrapperPath)) {
        throw "Pollinations wrapper script was not found at $wrapperPath"
    }

    $authMode = "anonymous"
    if ($env:VIDEO_STUDIO_POLLINATIONS_API_KEY) {
        if ($env:VIDEO_STUDIO_POLLINATIONS_API_KEY.StartsWith("sk_")) {
            $authMode = "secret-key"
        }
        elseif ($env:VIDEO_STUDIO_POLLINATIONS_API_KEY.StartsWith("pk_")) {
            $authMode = "publishable-key"
        }
        else {
            $authMode = "custom-key"
        }
    }

    $env:VIDEO_STUDIO_FLUX_MODE = "command"
    $env:VIDEO_STUDIO_FLUX_COMMAND = (@(
        $python,
        $wrapperPath,
        "--prompt-path",
        "{prompt_path}",
        "--output-path",
        "{output_path}",
        "--timeout-sec",
        "45",
        "--max-attempts",
        "4",
        "--endpoint-mode",
        "auto",
        "--min-request-gap-sec",
        "90",
        "--initial-backoff-sec",
        "8",
        "--backoff-jitter-sec",
        "4",
        "--max-backoff-sec",
        "45"
    ) | ConvertTo-Json -Compress)

    if (-not $env:VIDEO_STUDIO_MEDIA_TIMEOUT_SEC) {
        $env:VIDEO_STUDIO_MEDIA_TIMEOUT_SEC = "360"
    }

    Write-Host "[verify] enabled Pollinations FLUX command adapter"
    Write-Host "[verify] Pollinations auth mode: $authMode"
    Write-Host $env:VIDEO_STUDIO_FLUX_COMMAND
}

function Invoke-BridgeJson {
    param(
        [string]$Uri,
        [string]$Method,
        [string]$Body = ""
    )

    if ($Body) {
        return Invoke-RestMethod -Uri $Uri -Method $Method -ContentType "application/json" -Body $Body -TimeoutSec $bodyTimeoutSec
    }

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec 30
}

function New-SilenceWavBase64 {
    param(
        [int]$Milliseconds = 800
    )

    $sampleRate = 16000
    $channels = 1
    $bitsPerSample = 16
    $bytesPerSample = $bitsPerSample / 8
    $sampleCount = [Math]::Max(1, [int]($sampleRate * $Milliseconds / 1000))
    $dataSize = $sampleCount * $channels * $bytesPerSample

    $stream = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.BinaryWriter($stream)
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("RIFF"))
    $writer.Write([int](36 + $dataSize))
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("WAVE"))
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("fmt "))
    $writer.Write([int]16)
    $writer.Write([int16]1)
    $writer.Write([int16]$channels)
    $writer.Write([int]$sampleRate)
    $writer.Write([int]($sampleRate * $channels * $bytesPerSample))
    $writer.Write([int16]($channels * $bytesPerSample))
    $writer.Write([int16]$bitsPerSample)
    $writer.Write([System.Text.Encoding]::ASCII.GetBytes("data"))
    $writer.Write([int]$dataSize)
    $writer.Write((New-Object byte[] $dataSize))
    $writer.Flush()

    return [Convert]::ToBase64String($stream.ToArray())
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "storage\cache") | Out-Null

if ($UsePollinationsFlux) {
    Enable-PollinationsFluxCommand
}

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

    if ($health.planner.backend -ne "ollama") {
        throw "Expected Ollama planner backend, got $($health.planner.backend)"
    }

    if (-not $health.media.flux -or -not $health.media.wan) {
        throw "Expected local media adapter diagnostics for flux and wan in bridge health"
    }

    Write-Host "[verify] local media adapters"
    $health.media | ConvertTo-Json -Depth 6

    if ($UsePollinationsFlux) {
        if ($health.media.flux.mode -ne "command") {
            throw "Expected FLUX adapter mode=command when -UsePollinationsFlux is set, got $($health.media.flux.mode)"
        }

        if (-not $health.media.flux.ready) {
            throw "Expected FLUX adapter to be ready when -UsePollinationsFlux is set"
        }
    }

    $sampleImageBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1QAAAAASUVORK5CYII="
    $sampleAudioBase64 = New-SilenceWavBase64 -Milliseconds 900

    $renderPayloadObject = @{
        prompt = "30-second cafe promo reel with a warm morning mood"
        budgetMode = "standard"
        projectId = "verify-render-draft"
        availability = @{
            premiumEnabled = $true
            veo3 = $true
        }
        sceneAssets = @(
            @{
                sceneId = "scene-01"
                role = "visual"
                fileName = "scene-01.png"
                mimeType = "image/png"
                base64 = $sampleImageBase64
            },
            @{
                sceneId = "scene-02"
                role = "audio"
                fileName = "scene-02.wav"
                mimeType = "audio/wav"
                base64 = $sampleAudioBase64
            }
        )
    }

    if ($UsePollinationsFlux) {
        $renderPayloadObject.plannerMode = "sample"
    }

    $renderPayload = $renderPayloadObject | ConvertTo-Json -Depth 4

    Write-Host "[verify] draft render through bridge"
    $renderResponse = Invoke-BridgeJson -Uri "$bridgeUrl/api/render-smoke" -Method Post -Body $renderPayload
    $renderResponse | ConvertTo-Json -Depth 6

    if (-not (Test-Path $renderResponse.renderResult.outputPath)) {
        throw "Expected render output at $($renderResponse.renderResult.outputPath)"
    }

    if (-not (Test-Path $renderResponse.renderResult.logPath)) {
        throw "Expected ffmpeg log at $($renderResponse.renderResult.logPath)"
    }

    if (-not $renderResponse.renderResult.localMediaPlanPath) {
        throw "Expected local media plan path in render response"
    }

    if (-not (Test-Path $renderResponse.renderResult.localMediaPlanPath)) {
        throw "Expected local media plan at $($renderResponse.renderResult.localMediaPlanPath)"
    }

    if (-not $renderResponse.renderResult.localMediaReportPath) {
        throw "Expected local media report path in render response"
    }

    if (-not (Test-Path $renderResponse.renderResult.localMediaReportPath)) {
        throw "Expected local media report at $($renderResponse.renderResult.localMediaReportPath)"
    }

    $localMediaSummary = $renderResponse.renderResult.localMediaSummary
    if (-not $localMediaSummary) {
        throw "Expected local media summary in render response"
    }

    $resolvedSceneCount = [int]$localMediaSummary.uploaded + [int]$localMediaSummary.generated + [int]$localMediaSummary.placeholder
    if ($resolvedSceneCount -ne [int]$localMediaSummary.totalScenes) {
        throw "Expected uploaded + generated + placeholder scenes to match total scenes"
    }

    if (-not $renderResponse.renderResult.localMedia) {
        throw "Expected per-scene local media results in render response"
    }

    Write-Host "[verify] local media summary"
    $localMediaSummary | ConvertTo-Json -Depth 4

    if ($UsePollinationsFlux) {
        $fluxResults = @($renderResponse.renderResult.localMedia | Where-Object { $_.adapterKey -eq "flux" })
        if (-not $fluxResults.Count) {
            throw "Expected at least one FLUX-backed local media result when -UsePollinationsFlux is set"
        }

        $attemptedFluxResults = @($fluxResults | Where-Object { $_.attempted -eq $true })
        if (-not $attemptedFluxResults.Count) {
            throw "Expected the Pollinations FLUX command path to be attempted at least once"
        }

        if ([int]$localMediaSummary.generated -lt 1) {
            Write-Warning "Pollinations FLUX command path was attempted but did not generate an image; render fallback remained active"
        }
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
