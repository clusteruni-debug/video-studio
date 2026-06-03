param(
    [string]$ProjectId = "",
    [string]$SceneId = "scene-01",
    [string]$BridgeUrl = "http://127.0.0.1:5161",
    [switch]$OpenGuide,
    [switch]$CopyToClipboard,
    [switch]$OpenObservedPost,
    [switch]$CopyObservedPostConsole,
    [switch]$OpenProofMonitor,
    # Deprecated for regular Chrome 137+ branded builds. Kept for callers, but
    # the script now guides the operator to chrome://extensions Load unpacked.
    [switch]$RelaunchChromeWithCompanion,
    [switch]$CloseChromeApproved,
    [switch]$StartCdpChrome,
    [switch]$StartAuthWait,
    [string]$ChromeProfileDirectory = "Default",
    [int]$RemoteDebuggingPort = 9222,
    [string]$DownloadDir = "",
    [int]$OperatorReadyTimeoutSeconds = 7200,
    [int]$DownloadClickTimeoutSeconds = 240,
    [int]$WatchTimeoutSeconds = 420
)

$ErrorActionPreference = "Stop"

function Get-ProjectRoot {
    $scriptRoot = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

function Resolve-DefaultProjectId([string]$ProjectRoot) {
    $handoffRoot = Join-Path $ProjectRoot "storage\grok-handoffs"
    if (-not (Test-Path -LiteralPath $handoffRoot)) {
        throw "Grok handoff root not found. Create a Grok handoff packet first: $handoffRoot"
    }

    $candidates = @()
    foreach ($dir in Get-ChildItem -LiteralPath $handoffRoot -Directory) {
        $manifestPath = Join-Path $dir.FullName "handoff.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            continue
        }

        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            continue
        }

        $score = 0
        if ($manifest.mode -and [string]$manifest.mode -like "*grok*") {
            $score += 10
        }
        if ($manifest.grokMainSourceRequired -eq $true) {
            $score += 100
        }
        if ($dir.Name -like "grok-main*") {
            $score += 5
        }

        $candidates += [pscustomobject]@{
            ProjectId = $dir.Name
            Score = $score
            LastWriteTime = (Get-Item -LiteralPath $manifestPath).LastWriteTime
        }
    }

    if ($candidates.Count -eq 0) {
        throw "No Grok handoff packet with handoff.json was found under $handoffRoot"
    }

    $selected = $candidates |
        Sort-Object -Property @{Expression = "Score"; Descending = $true}, @{Expression = "LastWriteTime"; Descending = $true} |
        Select-Object -First 1
    return $selected.ProjectId
}

function Get-ChromePath {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    throw "Google Chrome executable was not found."
}

function Get-BridgeJson([string]$Uri) {
    return Invoke-RestMethod -Uri $Uri -TimeoutSec 15
}

function Post-BridgeJson([string]$Uri, [hashtable]$Payload, [int]$TimeoutSeconds = 30) {
    $json = $Payload | ConvertTo-Json -Depth 12
    $body = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec $TimeoutSeconds
}

function Quote-ProcessArgument([string]$Argument) {
    if ($null -eq $Argument) {
        return '""'
    }
    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }

    $result = '"'
    $backslashCount = 0
    foreach ($char in $Argument.ToCharArray()) {
        if ($char -eq '\') {
            $backslashCount += 1
            continue
        }
        if ($char -eq '"') {
            if ($backslashCount -gt 0) {
                $result += ('\' * ($backslashCount * 2))
                $backslashCount = 0
            }
            $result += '\"'
            continue
        }
        if ($backslashCount -gt 0) {
            $result += ('\' * $backslashCount)
            $backslashCount = 0
        }
        $result += $char
    }
    if ($backslashCount -gt 0) {
        $result += ('\' * ($backslashCount * 2))
    }
    $result += '"'
    return $result
}

function ConvertTo-ProcessArgumentString([string[]]$Arguments) {
    return (($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " ")
}

function Start-ChromeProcess([string]$ChromePath, [string[]]$Arguments) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $ChromePath
    $startInfo.UseShellExecute = $false
    if ($null -ne $startInfo.ArgumentList) {
        foreach ($argument in $Arguments) {
            [void]$startInfo.ArgumentList.Add($argument)
        }
    } else {
        $startInfo.Arguments = ConvertTo-ProcessArgumentString $Arguments
    }
    [void][System.Diagnostics.Process]::Start($startInfo)
}

function Open-ChromeUrl([string]$ChromePath, [string]$Url) {
    Start-ChromeProcess $ChromePath @($Url)
}

function Test-CdpPort([int]$Port) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Get-CdpChromeCommandLine([int]$Port) {
    $pattern = "--remote-debugging-port=$Port"
    $processes = @(Get-CimInstance Win32_Process -Filter "name = 'chrome.exe'" -ErrorAction SilentlyContinue)
    foreach ($process in $processes) {
        $commandLine = [string]$process.CommandLine
        if ($commandLine -and $commandLine.Contains($pattern)) {
            return $commandLine
        }
    }
    return ""
}

function Get-UserDataDirFromCommandLine([string]$CommandLine) {
    if (-not $CommandLine) {
        return ""
    }
    $quoted = [regex]::Match($CommandLine, '--user-data-dir="([^"]+)"')
    if ($quoted.Success) {
        return $quoted.Groups[1].Value
    }
    $bare = [regex]::Match($CommandLine, '--user-data-dir=([^\s]+)')
    if ($bare.Success) {
        return $bare.Groups[1].Value
    }
    return ""
}

function Test-SamePathText([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) {
        return $false
    }
    try {
        $leftFull = [System.IO.Path]::GetFullPath($Left.Trim('"')).TrimEnd('\')
        $rightFull = [System.IO.Path]::GetFullPath($Right.Trim('"')).TrimEnd('\')
        return [string]::Equals($leftFull, $rightFull, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return [string]::Equals($Left.Trim('"'), $Right.Trim('"'), [System.StringComparison]::OrdinalIgnoreCase)
    }
}

function Start-CdpChromeProfile([string]$ChromePath, [string]$ProfileDirectory, [int]$Port, [string]$Url) {
    $userDataDir = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
    if (Test-CdpPort $Port) {
        $commandLine = Get-CdpChromeCommandLine $Port
        $detectedUserDataDir = Get-UserDataDirFromCommandLine $commandLine
        if ($detectedUserDataDir -and -not (Test-SamePathText $detectedUserDataDir $userDataDir)) {
            if (-not $CloseChromeApproved) {
                throw "CDP is already listening on 127.0.0.1:$Port, but that Chrome process uses user-data-dir '$detectedUserDataDir' instead of '$userDataDir'. Close that Chrome instance or rerun with -StartCdpChrome -CloseChromeApproved so Video Studio can launch the signed-in Chrome profile with the correctly quoted User Data path."
            }
            Write-Warning "Closing Chrome because CDP on $Port is using the wrong user-data-dir: $detectedUserDataDir"
            Close-ChromeGracefully
        } else {
            Write-Host "CDP already listening on 127.0.0.1:$Port"
            Open-ChromeUrl $ChromePath $Url
            return
        }
    }

    $runningChrome = @(Get-Process chrome -ErrorAction SilentlyContinue)
    if ($runningChrome.Count -gt 0) {
        if (-not $CloseChromeApproved) {
            throw "Chrome is already running and CDP is not listening on $Port. Rerun with -StartCdpChrome -CloseChromeApproved after saving browser work, or launch Chrome with --remote-debugging-port=$Port yourself."
        }
        Close-ChromeGracefully
    }

    Start-ChromeProcess $ChromePath @(
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=$Port",
        "--profile-directory=$ProfileDirectory",
        "--user-data-dir=$userDataDir",
        $Url
    )

    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        if (Test-CdpPort $Port) {
            Write-Host "Started Chrome profile '$ProfileDirectory' with CDP on 127.0.0.1:$Port"
            return
        }
        Start-Sleep -Milliseconds 500
    }
    $commandLine = Get-CdpChromeCommandLine $Port
    $detectedUserDataDir = Get-UserDataDirFromCommandLine $commandLine
    if ($detectedUserDataDir -and (Test-SamePathText $detectedUserDataDir $userDataDir)) {
        throw "Chrome launched with the correctly quoted user-data-dir '$userDataDir', but CDP did not become reachable on 127.0.0.1:$Port. This is consistent with Chrome 136+ default-profile remote-debugging restrictions. Use the Video Studio Grok Companion extension or manual Grok MP4 batch upload in the signed-in Chrome profile, or use an isolated handoff profile and sign in there once."
    }
    throw "Chrome started but CDP did not become available on 127.0.0.1:$Port"
}

function Write-HandoffText([string]$ProjectRoot, [string]$ProjectId, [string]$SceneId, [string]$Text) {
    $handoffDir = Join-Path $ProjectRoot "storage\grok-handoffs\$ProjectId"
    New-Item -Path $handoffDir -ItemType Directory -Force | Out-Null
    $handoffPath = Join-Path $handoffDir "operator-handoff-$SceneId.txt"
    Set-Content -LiteralPath $handoffPath -Value $Text -Encoding UTF8
    return $handoffPath
}

function Close-ChromeGracefully {
    $chrome = @(Get-Process chrome -ErrorAction SilentlyContinue)
    if ($chrome.Count -eq 0) {
        return
    }
    foreach ($process in $chrome) {
        if ($process.MainWindowHandle -ne 0) {
            [void]$process.CloseMainWindow()
        }
    }
    $deadline = (Get-Date).AddSeconds(12)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process chrome -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Chrome is still running. Close Chrome manually, then rerun with -RelaunchChromeWithCompanion. This script does not force-close Chrome."
}

function Write-Chrome137ExtensionNote {
    Write-Warning "Chrome 137+ branded Chrome no longer reliably loads unpacked extensions via --load-extension."
    Write-Host "Use the signed-in Chrome profile: chrome://extensions -> Developer mode -> Load unpacked -> $extensionPath"
    Write-Host "Official note: https://groups.google.com/a/chromium.org/g/chromium-extensions/c/1-g8EFx2BBY"
}

function Start-GrokBackgroundAuthWait(
    [string]$BaseUrl,
    [string]$ProjectId,
    [string]$SceneId,
    [string]$ProfileDirectory,
    [int]$Port,
    [string]$DownloadDirectory
) {
    if ([string]::IsNullOrWhiteSpace($DownloadDirectory)) {
        $DownloadDirectory = Join-Path $env:USERPROFILE "Downloads"
    }
    $payload = @{
        sceneId = $SceneId
        operatorApproved = $true
        browserAutomationApproved = $true
        useDefaultChromeProfile = $true
        attachDefaultChromeApproved = $true
        browserProfileMode = "default-chrome-cdp-attach"
        browserProfileDirectory = $ProfileDirectory
        launchBrowserApproved = $false
        profileApproved = $false
        remoteDebuggingPort = $Port
        waitForOperatorReadyApproved = $true
        operatorReadyTimeoutSeconds = $OperatorReadyTimeoutSeconds
        operatorReadyPollIntervalSeconds = 2
        authKickoffApproved = $true
        authProviderKickoffApproved = $true
        authProviderPreference = "google"
        cookieRejectApproved = $true
        generatePromptApproved = $true
        downloadResultApproved = $true
        watchDownloadsApproved = $true
        downloadDir = $DownloadDirectory
        downloadClickTimeoutSeconds = $DownloadClickTimeoutSeconds
        watchTimeoutSeconds = $WatchTimeoutSeconds
        watchPollIntervalSeconds = 2
        allowNewestFallback = $true
        sinceHandoff = $true
        preserveCandidates = $true
        supersedeActiveJobApproved = $true
    }

    $url = "$BaseUrl/api/grok-handoff/$ProjectId/background-automation"
    $result = Post-BridgeJson $url $payload 30
    Write-Host "Started Grok CDP auth-wait job: scene=$($result.sceneId) expected=$($result.expectedFileName)"
    if ($result.automationJob) {
        Write-Host "Job status: $($result.automationJob.status)"
        Write-Host "Operator next: $($result.automationJob.operatorNextAction)"
        Write-Host "Wait deadline: $($result.automationJob.operatorWaitDeadlineAt)"
    }
    return $result
}

$projectRoot = Get-ProjectRoot
if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    $ProjectId = Resolve-DefaultProjectId $projectRoot
    Write-Host "Auto-selected latest Grok handoff packet: $ProjectId"
}

$extensionPath = Join-Path $projectRoot "tools\chrome-grok-companion"
if (-not (Test-Path -LiteralPath $extensionPath)) {
    throw "Video Studio Grok companion extension path not found: $extensionPath"
}

$base = $BridgeUrl.TrimEnd("/")
$statusUrl = "$base/api/grok-handoff/$ProjectId/status"
$commandUrl = "$base/api/grok-handoff/$ProjectId/extension-command?operatorApproved=true&sceneId=$SceneId"
$guideUrl = "$base/api/grok-handoff/$ProjectId/chrome-extension?sceneId=$SceneId"

$status = Get-BridgeJson $statusUrl
$command = Get-BridgeJson $commandUrl
$chromePath = Get-ChromePath
$observedPostPlan = $status.observedPostImportPlan

$companionStatus = $status.companionConnection.status
$connected = $status.companionConnection.connected
$companionAction = [string]$status.companionConnection.operatorAction
$mainGate = $status.mainSourceGate.status
$ready = "$($status.readyScenes)/$($status.totalScenes)"
$profileProbe = $status.chromeCompanionExtension.profileProbe
$recommendedProfile = [string]$profileProbe.recommendedProfileDirectory
$replayProfile = [string]$profileProbe.automationReplayProfileDirectory
$profileMismatch = [bool]$profileProbe.profileMismatch
$reviewPacketUrl = "$base/api/grok-handoff/$ProjectId/review-packet"
$productionQueueUrl = "$base/api/grok-handoff/$ProjectId/production-queue"
$statusImportUrl = "$base/api/grok-handoff/$ProjectId/status"
$proofMonitorUrl = "$base/api/grok-handoff/$ProjectId/direct-import-proof?sceneId=$SceneId"

Write-Host "Project: $ProjectId"
Write-Host "Scene: $SceneId"
Write-Host "Ready scenes: $ready"
Write-Host "Companion: $companionStatus connected=$connected"
if (-not [string]::IsNullOrWhiteSpace($companionAction)) {
    Write-Host "Companion action: $companionAction"
}
Write-Host "Main source gate: $mainGate"
Write-Host "Extension path: $extensionPath"
Write-Host "Guide URL: $guideUrl"
Write-Host "Direct import proof monitor: $proofMonitorUrl"
Write-Host "Prep+Generate URL: $($command.prepGenerateAutostartUrl)"
Write-Host "Fallback bookmarklets: included in the handoff file/clipboard runbook."
Write-Host "Expected MP4: $($command.expectedFileName)"
Write-Host "CDP profile: $ChromeProfileDirectory port=$RemoteDebuggingPort"
Write-Host "Recommended Chrome profile: $recommendedProfile; saved CDP replay profile: $replayProfile; mismatch=$profileMismatch"
Write-Host "Chrome 137+ note: regular Chrome ignores --load-extension for unpacked extensions; use Load unpacked in chrome://extensions."

$observedPostSection = ""
if ($null -ne $observedPostPlan -and -not [string]::IsNullOrWhiteSpace([string]$observedPostPlan.observedPostDownloadConsoleSnippet)) {
    $observedPostSection = @"

Fallback route C - observed-post direct import:
Use this when a Grok post is already open and a 720p+ MP4 is visible, but Chrome Download opens an approval dialog. Open the observed Grok post tab, paste this console snippet, and it will fetch the MP4 inside the signed-in tab and post it to the local uploadEndpoint without Chrome Download approval dialog.

Observed post:
$($observedPostPlan.postUrl)

Upload endpoint:
$($observedPostPlan.uploadEndpoint)

Console snippet:
$($observedPostPlan.observedPostDownloadConsoleSnippet)
"@
    Write-Host "Observed-post direct import snippet: included in the handoff file/clipboard runbook."
}

$handoffText = @"
Current Grok-main state:
- project: $ProjectId
- scene: $SceneId
- ready scenes: $ready
- main gate: $mainGate
- companion: $companionStatus connected=$connected
- companion action: $companionAction
- recommended Chrome profile: $recommendedProfile
- saved CDP replay profile: $replayProfile
- profile mismatch: $profileMismatch
- expected MP4: $($command.expectedFileName)

Extension path:
$extensionPath

Chrome 137+ setup:
Regular Google Chrome no longer reliably loads unpacked extensions from --load-extension.
Use the existing signed-in Chrome profile:
1. Open chrome://extensions
2. Enable Developer mode
3. Click Load unpacked
4. Select the Extension path above

Guide URL:
$guideUrl

Scene $SceneId Prep+Generate URL:
$($command.prepGenerateAutostartUrl)

Fallback route A - self-contained bookmarklet:
If Companion stays bookmarklet-only/not connected, open Grok Imagine in the signed-in Chrome tab and use this bookmarklet URL from the bookmarks bar. It embeds the prompt directly, so it does not need the unpacked extension.

Fill + Generate bookmarklet:
$($command.bookmarkletGenerateInlineUrl)

Fallback route B - queue bookmarklet:
Use this from the Grok tab when Grok clips should be the main source for all missing scenes. It fills the next missing scene, clicks Generate, waits for a download control, and imports the newest MP4 from Downloads.

Queue Fill+Generate+Import bookmarklet:
$($command.bookmarkletQueueInlineUrl)
$observedPostSection

Audit/script URLs:
- status: $statusImportUrl
- direct import proof monitor: $proofMonitorUrl
- production queue: $productionQueueUrl
- review packet: $reviewPacketUrl
- import endpoint: $($command.bookmarkletImportEndpoint)
- command URL: $commandUrl

Minimum accept rule:
Generate at least two takes for the scene. Reject clips with no first-second motion, baked-in text/logo/watermark/UI, face/hand/body morphing, weak continuity, or unsafe lower/right composition. Do not render around a bad Grok take.
"@
$handoffFile = ""
if ($CopyToClipboard -or $OpenGuide -or $OpenObservedPost -or $CopyObservedPostConsole -or $OpenProofMonitor -or $RelaunchChromeWithCompanion) {
    $handoffFile = Write-HandoffText $projectRoot $ProjectId $SceneId $handoffText
    Write-Host "Handoff file: $handoffFile"
}

if ($CopyToClipboard) {
    try {
        Set-Clipboard -Value $handoffText
        Write-Host "Copied Grok companion setup, fallback bookmarklets, queue runbook, and expected MP4 name to clipboard."
    } catch {
        Write-Warning "Clipboard copy failed: $($_.Exception.Message)"
        Write-Host "Use the handoff file instead: $handoffFile"
    }
}

if ($CopyObservedPostConsole) {
    $observedConsole = ""
    if ($null -ne $observedPostPlan) {
        $observedConsole = [string]$observedPostPlan.observedPostDownloadConsoleSnippet
    }
    if ([string]::IsNullOrWhiteSpace($observedConsole)) {
        Write-Warning "Observed-post console snippet is not available for project '$ProjectId'."
    } else {
        try {
            Set-Clipboard -Value $observedConsole
            Write-Host "Copied observed-post direct-import console snippet to clipboard."
        } catch {
            Write-Warning "Clipboard copy failed: $($_.Exception.Message)"
            Write-Host "Use the handoff file instead: $handoffFile"
        }
    }
}

if ($OpenGuide) {
    Open-ChromeUrl $chromePath $guideUrl
    Open-ChromeUrl $chromePath "chrome://extensions/"
    Write-Host "Opened the Video Studio companion guide and Chrome Extension Manager in Chrome."
}

if ($OpenObservedPost) {
    $observedPostUrl = ""
    if ($null -ne $observedPostPlan) {
        $observedPostUrl = [string]$observedPostPlan.postUrl
    }
    if ([string]::IsNullOrWhiteSpace($observedPostUrl)) {
        Write-Warning "Observed Grok post URL is not available for project '$ProjectId'."
    } else {
        Open-ChromeUrl $chromePath $observedPostUrl
        Write-Host "Opened observed Grok post in Chrome. Run the copied console snippet from that signed-in Grok post tab."
    }
}

if ($OpenProofMonitor) {
    Open-ChromeUrl $chromePath $proofMonitorUrl
    Write-Host "Opened the direct import proof monitor in Chrome."
}

if ($RelaunchChromeWithCompanion) {
    Write-Chrome137ExtensionNote
    Open-ChromeUrl $chromePath "chrome://extensions/"
    Open-ChromeUrl $chromePath $guideUrl
    Open-ChromeUrl $chromePath $command.prepGenerateAutostartUrl
    Write-Host "Opened Grok/guide/Extension Manager instead of using the deprecated --load-extension path."
    if ($CloseChromeApproved) {
        Write-Host "-CloseChromeApproved was ignored because this script no longer closes Chrome for the deprecated relaunch path."
    }
}

if ($StartCdpChrome) {
    Start-CdpChromeProfile $chromePath $ChromeProfileDirectory $RemoteDebuggingPort $command.prepGenerateAutostartUrl
}

if ($StartAuthWait) {
    $null = Start-GrokBackgroundAuthWait $base $ProjectId $SceneId $ChromeProfileDirectory $RemoteDebuggingPort $DownloadDir
}

Write-Host "Next check: $statusUrl"
