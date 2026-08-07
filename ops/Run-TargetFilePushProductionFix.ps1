param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$ServiceName = "LOLDataSystem"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ExpectedTargetCommit = "acc6ad2f4e0f47d84d6e9ceb916f400f9782b2a2"
$ExpectedPackagePrefix = "LOLDataSystem-full-bug-repair-safe-deploy-acc6ad2f4e0f-py311-py314-winps51-v3"
$LauncherScriptPath = $PSCommandPath

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-AsAdministrator {
    if (-not $LauncherScriptPath) {
        throw "Unable to resolve launcher script path for administrator elevation."
    }
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $LauncherScriptPath + '"'),
        "-ProjectRoot", ('"' + $ProjectRoot + '"'),
        "-ServiceName", ('"' + $ServiceName + '"')
    )
    $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-Json([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-PendingNames([object]$State) {
    $names = New-Object 'System.Collections.Generic.List[string]'
    if ($State -and $State.pending -and $State.pending.events) {
        foreach ($event in @($State.pending.events)) {
            if ($event.file -and $event.file.name) {
                $names.Add("$($event.file.name)") | Out-Null
            }
        }
    }
    return @($names)
}

function Restore-SafetyFiles {
    param(
        [string]$ConfigBackup,
        [string]$StateBackup,
        [string]$ConfigPath,
        [string]$StatePath,
        [string]$ServiceName
    )

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $wasRunning = $service -and $service.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Running
    if ($wasRunning) {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    }
    try {
        $configParent = Split-Path -Parent $ConfigPath
        $stateParent = Split-Path -Parent $StatePath
        New-Item -ItemType Directory -Path $configParent, $stateParent -Force | Out-Null
        Copy-Item -LiteralPath $ConfigBackup -Destination $ConfigPath -Force
        Copy-Item -LiteralPath $StateBackup -Destination $StatePath -Force
    } finally {
        if ($wasRunning) {
            Start-Service -Name $ServiceName -ErrorAction Stop
        }
    }
}

if (-not (Test-Administrator)) {
    Restart-AsAdministrator
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LOLDataSystem Target File Push Production Fix" -ForegroundColor Cyan
Write-Host "Target: $ExpectedTargetCommit"
Write-Host "============================================================" -ForegroundColor Cyan

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$configPath = Join-Path $ProjectRoot "config\target-file-watch.json"
$statePath = Join-Path $ProjectRoot "data\target-file-watch-state.json"

foreach ($requiredRuntimeFile in @($configPath, $statePath)) {
    if (-not (Test-Path -LiteralPath $requiredRuntimeFile -PathType Leaf)) {
        throw "Required target-file runtime file is missing. Deployment was not started: $requiredRuntimeFile"
    }
}

$config = Read-Json -Path $configPath
$state = Read-Json -Path $statePath
$pendingNames = @(Get-PendingNames -State $state)
Write-Host ("Current target-file config: enabled={0}; token_configured={1}" -f [bool]$config.enabled, (-not [string]::IsNullOrWhiteSpace("$($config.callback_token)")))
Write-Host ("Current pending count: {0}" -f $pendingNames.Count)
if ($pendingNames.Count -gt 0) {
    Write-Host ("Current pending files: " + ($pendingNames -join ", "))
}

$packageZip = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "$ExpectedPackagePrefix.zip" -File)
$metadataFile = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "$ExpectedPackagePrefix.metadata.json" -File)
if ($packageZip.Count -ne 1 -or $metadataFile.Count -ne 1) {
    throw "Expected exactly one validated deployment ZIP and metadata file next to this launcher."
}

$metadata = Read-Json -Path $metadataFile[0].FullName
if ("$($metadata.target_commit)".ToLowerInvariant() -ne $ExpectedTargetCommit) {
    throw "Deployment metadata target commit mismatch."
}
$actualZipHash = Get-Sha256 -Path $packageZip[0].FullName
if ($actualZipHash -ne "$($metadata.zip_sha256)".ToLowerInvariant()) {
    throw "Deployment ZIP SHA-256 mismatch."
}
Write-Host "Deployment ZIP SHA-256 verified."

$parent = Split-Path -Parent $ProjectRoot
$leaf = Split-Path -Leaf $ProjectRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$safetyRoot = Join-Path $parent "$leaf.target-file-safety-backups"
$safetyDirectory = Join-Path $safetyRoot "$timestamp-$($ExpectedTargetCommit.Substring(0,12))"
New-Item -ItemType Directory -Path $safetyDirectory -Force | Out-Null
$configBackup = Join-Path $safetyDirectory "target-file-watch.json"
$stateBackup = Join-Path $safetyDirectory "target-file-watch-state.json"
Copy-Item -LiteralPath $configPath -Destination $configBackup -Force
Copy-Item -LiteralPath $statePath -Destination $stateBackup -Force

$safetyRecord = [ordered]@{
    schema = "target-file-push-predeploy-safety.v1"
    created_at = [DateTime]::UtcNow.ToString("o")
    target_commit = $ExpectedTargetCommit
    production_head = (& git -C $ProjectRoot rev-parse HEAD 2>$null | Select-Object -First 1)
    config_sha256 = Get-Sha256 -Path $configBackup
    state_sha256 = Get-Sha256 -Path $stateBackup
    pending_count = $pendingNames.Count
    pending_names = $pendingNames
}
[System.IO.File]::WriteAllText(
    (Join-Path $safetyDirectory "safety-record.json"),
    ($safetyRecord | ConvertTo-Json -Depth 6),
    (New-Object System.Text.UTF8Encoding($false))
)
Write-Host "Extra target-file safety backup created: $safetyDirectory"

$extractRoot = Join-Path $env:TEMP ("lol-target-file-fix-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
$exitCode = 1
try {
    Expand-Archive -LiteralPath $packageZip[0].FullName -DestinationPath $extractRoot -Force
    $deployScript = Get-ChildItem -LiteralPath $extractRoot -Filter "Deploy-FullBugRepairSafe.ps1" -File -Recurse | Select-Object -First 1
    if (-not $deployScript) {
        throw "Deploy-FullBugRepairSafe.ps1 was not found after extraction."
    }

    Write-Host "Starting validated V3 deployment..." -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $deployScript.FullName `
        -ProjectRoot $ProjectRoot `
        -ServiceName $ServiceName
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Warning "V3 deployment returned exit code $exitCode. Verifying target-file safety files."
        $mustRestore = (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) -or (-not (Test-Path -LiteralPath $statePath -PathType Leaf))
        if (-not $mustRestore) {
            $mustRestore = (Get-Sha256 -Path $configPath) -ne (Get-Sha256 -Path $configBackup) -or
                (Get-Sha256 -Path $statePath) -ne (Get-Sha256 -Path $stateBackup)
        }
        if ($mustRestore) {
            Write-Warning "Target-file runtime files differ after failed deployment. Restoring extra safety backup."
            Restore-SafetyFiles `
                -ConfigBackup $configBackup `
                -StateBackup $stateBackup `
                -ConfigPath $configPath `
                -StatePath $statePath `
                -ServiceName $ServiceName
        }
        exit $exitCode
    }

    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        Write-Warning "Target-file config disappeared after successful deployment. Restoring config only."
        Copy-Item -LiteralPath $configBackup -Destination $configPath -Force
    }

    Write-Host ""
    Write-Host "TARGET FILE PUSH DEPLOYMENT SUCCEEDED." -ForegroundColor Green
    Write-Host "Do NOT rebaseline. Keep the current pending/baseline state." -ForegroundColor Yellow
    Write-Host "Safety backup: $safetyDirectory"
    exit 0
} finally {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
}
