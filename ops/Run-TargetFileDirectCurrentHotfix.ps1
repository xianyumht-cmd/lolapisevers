param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ExpectedBaseCommit = "af5baa43b484748ffd159e4495f85f8231fb139f"
$TargetCommit = "9f5618bd375f96c217b42672480f01eb4cb26a3e"
$BundleName = "target-file-direct-current-hotfix.bundle"
$MetadataName = "target-file-direct-current-hotfix.metadata.json"
$PackageRef = "refs/heads/package-target-file-direct-current"
$FetchedRef = "refs/remotes/target-file-hotfix/package-target-file-direct-current"
$LauncherScriptPath = $PSCommandPath

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-AsAdministrator {
    if (-not $LauncherScriptPath) {
        throw "Unable to resolve launcher path for administrator elevation."
    }
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $LauncherScriptPath + '"'),
        "-ProjectRoot", ('"' + $ProjectRoot + '"'),
        "-ServiceName", ('"' + $ServiceName + '"'),
        "-BaseUrl", ('"' + $BaseUrl + '"')
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

function Invoke-Git {
    param([string[]]$Arguments)
    $output = & git -C $ProjectRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join ' ')"
    }
    return @($output)
}

function Get-HeadCommit {
    return ((Invoke-Git -Arguments @("rev-parse", "HEAD")) | Select-Object -First 1).Trim().ToLowerInvariant()
}

function Test-Health {
    param([int]$Attempts = 20)
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "$BaseUrl/health" -Method GET -TimeoutSec 10 -UseBasicParsing -Headers @{ Accept = "application/json" }
            if ([int]$response.StatusCode -eq 200) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Stop-LolService {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    }
}

function Start-LolService {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
        Start-Service -Name $ServiceName -ErrorAction Stop
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
    }
}

if (-not (Test-Administrator)) {
    Restart-AsAdministrator
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LOLDataSystem Target File Direct URL Current-History Hotfix" -ForegroundColor Cyan
Write-Host "Expected current HEAD: $ExpectedBaseCommit"
Write-Host "Target HEAD:           $TargetCommit"
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw "Project root does not exist: $ProjectRoot"
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

$bundlePath = Join-Path $PSScriptRoot $BundleName
$metadataPath = Join-Path $PSScriptRoot $MetadataName
if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
    throw "Hotfix bundle is missing: $bundlePath"
}
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "Hotfix metadata is missing: $metadataPath"
}

$metadata = Read-Json -Path $metadataPath
if ("$($metadata.base_commit)".ToLowerInvariant() -ne $ExpectedBaseCommit) {
    throw "Metadata base commit mismatch."
}
if ("$($metadata.target_commit)".ToLowerInvariant() -ne $TargetCommit) {
    throw "Metadata target commit mismatch."
}
if ((Get-Sha256 -Path $bundlePath) -ne "$($metadata.bundle_sha256)".ToLowerInvariant()) {
    throw "Hotfix bundle SHA-256 mismatch."
}
Write-Host "Hotfix bundle SHA-256 verified."

$currentHead = Get-HeadCommit
Write-Host "Actual production HEAD: $currentHead" -ForegroundColor Yellow
if ($currentHead -eq $TargetCommit) {
    Write-Host "Hotfix is already installed. No production change is needed." -ForegroundColor Green
    exit 0
}
if ($currentHead -ne $ExpectedBaseCommit) {
    Write-Host "HEAD DOES NOT MATCH THE RECORDED CURRENT PRODUCTION BASE." -ForegroundColor Red
    Write-Host "Production was not stopped or changed." -ForegroundColor Yellow
    exit 11
}

& git -C $ProjectRoot diff --quiet -- .
if ($LASTEXITCODE -ne 0) {
    throw "Tracked working tree has local changes. Production was not stopped or changed."
}
& git -C $ProjectRoot diff --cached --quiet -- .
if ($LASTEXITCODE -ne 0) {
    throw "Git index has staged changes. Production was not stopped or changed."
}

$configPath = Join-Path $ProjectRoot "config\target-file-watch.json"
$statePath = Join-Path $ProjectRoot "data\target-file-watch-state.json"
foreach ($runtimePath in @($configPath, $statePath)) {
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        throw "Required target-file runtime state is missing: $runtimePath"
    }
}

if (-not (Test-Health -Attempts 3)) {
    throw "Production /health is not HTTP 200 before hotfix. Production was not stopped or changed."
}

$parent = Split-Path -Parent $ProjectRoot
$leaf = Split-Path -Leaf $ProjectRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $parent "$leaf.target-file-direct-hotfix-backups"
$backupDir = Join-Path $backupRoot "$timestamp-$($ExpectedBaseCommit.Substring(0,12))"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item -LiteralPath $configPath -Destination (Join-Path $backupDir "target-file-watch.json") -Force
Copy-Item -LiteralPath $statePath -Destination (Join-Path $backupDir "target-file-watch-state.json") -Force
$configBeforeHash = Get-Sha256 -Path $configPath
$stateBeforeHash = Get-Sha256 -Path $statePath

$record = [ordered]@{
    schema = "target-file-direct-current-hotfix.v1"
    created_at = [DateTime]::UtcNow.ToString("o")
    base_commit = $ExpectedBaseCommit
    target_commit = $TargetCommit
    production_head = $currentHead
    config_sha256 = $configBeforeHash
    state_sha256 = $stateBeforeHash
}
[System.IO.File]::WriteAllText(
    (Join-Path $backupDir "predeploy-record.json"),
    ($record | ConvertTo-Json -Depth 5),
    (New-Object System.Text.UTF8Encoding($false))
)
Write-Host "Target-file config/state safety backup: $backupDir"

Write-Host "Verify bundle prerequisite and fetch target commit while production stays running"
& git -C $ProjectRoot bundle verify $bundlePath
if ($LASTEXITCODE -ne 0) {
    throw "Hotfix bundle prerequisite verification failed. Production was not stopped or changed."
}
& git -C $ProjectRoot fetch $bundlePath "$PackageRef`:$FetchedRef"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to fetch hotfix bundle. Production was not stopped or changed."
}
$fetchedTarget = ((Invoke-Git -Arguments @("rev-parse", $FetchedRef)) | Select-Object -First 1).Trim().ToLowerInvariant()
if ($fetchedTarget -ne $TargetCommit) {
    throw "Fetched hotfix target commit mismatch."
}
& git -C $ProjectRoot merge-base --is-ancestor $ExpectedBaseCommit $TargetCommit
if ($LASTEXITCODE -ne 0) {
    throw "Target commit is not a descendant of the expected current production base."
}

$changedFiles = @((Invoke-Git -Arguments @("diff", "--name-only", $ExpectedBaseCommit, $TargetCommit))) | Where-Object { $_ -and $_.Trim() }
$expectedFiles = @(
    "services/target_file_watch_directory.py",
    "tests/test_target_file_watch_direct_current.py"
)
if (($changedFiles -join "`n") -ne ($expectedFiles -join "`n")) {
    throw "Hotfix commit contains unexpected file changes: $($changedFiles -join ', ')"
}

$candidateRoot = Join-Path $env:TEMP ("lol-target-file-direct-candidate-" + [Guid]::NewGuid().ToString("N"))
try {
    Write-Host "Create isolated candidate and run direct-resolver regression before stopping production"
    & git -C $ProjectRoot worktree add --detach $candidateRoot $TargetCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create candidate worktree. Production was not stopped or changed."
    }

    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Production Python environment is missing: $python"
    }

    Push-Location $candidateRoot
    try {
        & $python -m py_compile "services\target_file_watch_directory.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Candidate target_file_watch_directory.py compile failed."
        }
        & $python -m unittest discover -s tests -p "test_target_file_watch_direct_current.py" -v
        if ($LASTEXITCODE -ne 0) {
            throw "Candidate direct-resolver regression tests failed."
        }
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path -LiteralPath $candidateRoot -PathType Container) {
        & git -C $ProjectRoot worktree remove --force $candidateRoot 2>$null | Out-Null
    }
}

Write-Host "Candidate passed. Stopping only $ServiceName and switching two-file hotfix..." -ForegroundColor Cyan
$switched = $false
try {
    Stop-LolService
    & git -C $ProjectRoot checkout --detach $TargetCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to switch production repository to hotfix commit."
    }
    $switched = $true

    if ((Get-Sha256 -Path $configPath) -ne $configBeforeHash) {
        throw "target-file-watch.json changed unexpectedly during hotfix switch."
    }
    if ((Get-Sha256 -Path $statePath) -ne $stateBeforeHash) {
        throw "target-file-watch-state.json changed unexpectedly during hotfix switch."
    }

    Start-LolService
    if (-not (Test-Health -Attempts 30)) {
        throw "Production /health did not recover after hotfix."
    }
    $afterHead = Get-HeadCommit
    if ($afterHead -ne $TargetCommit) {
        throw "Production HEAD verification failed after hotfix."
    }

    Write-Host ""
    Write-Host "TARGET FILE DIRECT URL HOTFIX SUCCEEDED." -ForegroundColor Green
    Write-Host "Production HEAD: $afterHead"
    Write-Host "Config/state hashes are unchanged." -ForegroundColor Green
    Write-Host "Do NOT rebaseline. Do NOT deploy 6108 or 6178." -ForegroundColor Yellow
    Write-Host "Next action: run exactly one existing target-file immediate check." -ForegroundColor Yellow
    exit 0
} catch {
    $failure = $_
    Write-Warning "Hotfix switch failed: $($failure.Exception.Message)"
    if ($switched) {
        try {
            Stop-LolService
        } catch {
        }
        & git -C $ProjectRoot checkout --detach $ExpectedBaseCommit 2>$null | Out-Null
        Copy-Item -LiteralPath (Join-Path $backupDir "target-file-watch.json") -Destination $configPath -Force
        Copy-Item -LiteralPath (Join-Path $backupDir "target-file-watch-state.json") -Destination $statePath -Force
        try {
            Start-LolService
        } catch {
        }
        if (Test-Health -Attempts 30) {
            Write-Host "ROLLBACK SUCCEEDED. Production returned to $ExpectedBaseCommit." -ForegroundColor Yellow
            exit 2
        }
    }
    Write-Host "Production recovery requires manual inspection. Keep backup: $backupDir" -ForegroundColor Red
    exit 3
}
