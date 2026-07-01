param(
    [string]$BridgeUrl = "http://127.0.0.1:5161",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        return [ordered]@{
            name = $Name
            ready = $false
            path = $null
            detail = "not found on PATH"
        }
    }

    return [ordered]@{
        name = $Name
        ready = $true
        path = $command.Source
        detail = "found"
    }
}

function Read-BridgeStatus {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $response = Invoke-RestMethod -Uri "$Url/api/human-operator/status" -Method Get -TimeoutSec 5
        return [ordered]@{
            ready = $true
            url = $Url
            schema = $response.schema
            setupReady = [bool]$response.setup.criticalReady
            demoPrepared = [bool]$response.demo.prepared
            nextAction = $response.nextAction.label
        }
    } catch {
        return [ordered]@{
            ready = $false
            url = $Url
            error = $_.Exception.Message
        }
    }
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$storage = Join-Path $root "storage"

$report = [ordered]@{
    schema = "video-studio.human-setup-diagnostics.v1"
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    projectRoot = $root.Path
    storageReady = (Test-Path $storage)
    tools = @(
        Test-Command "python"
        Test-Command "node"
        Test-Command "npm"
        Test-Command "ffmpeg"
    )
    bridge = Read-BridgeStatus $BridgeUrl
    note = "Report-only. This script does not install dependencies and does not edit .env files."
}

if ($Json) {
    $report | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "Video Studio human setup diagnostics"
Write-Host "Project: $($report.projectRoot)"
Write-Host "Storage: $($report.storageReady)"
Write-Host ""
foreach ($tool in $report.tools) {
    $state = if ($tool.ready) { "READY" } else { "MISSING" }
    Write-Host ("{0,-8} {1} {2}" -f $tool.name, $state, $tool.path)
}
Write-Host ""
if ($report.bridge.ready) {
    Write-Host "Bridge READY $($report.bridge.url)"
    Write-Host "Setup ready: $($report.bridge.setupReady)"
    Write-Host "Demo prepared: $($report.bridge.demoPrepared)"
    Write-Host "Next action: $($report.bridge.nextAction)"
} else {
    Write-Host "Bridge MISSING $($report.bridge.url)"
    Write-Host $report.bridge.error
}
