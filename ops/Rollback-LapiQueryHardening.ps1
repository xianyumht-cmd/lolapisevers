param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [Parameter(Mandatory = $true)]
    [string]$BackupDirectory,
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Administrator privileges are required."
    }
}

function Invoke-Git {
    param([string[]]$Arguments)
    $output = & git -C $ProjectRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Wait-ServiceState {
    param([string]$Name, [string]$Desired, [int]$TimeoutSeconds = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $service = Get-Service -Name $Name -ErrorAction Stop
        if ($service.Status.ToString() -eq $Desired) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Service $Name did not reach state $Desired within $TimeoutSeconds seconds."
}

function Stop-ReleaseService {
    param([string]$Name)
    $service = Get-Service -Name $Name -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $Name -Force -ErrorAction Stop
        Wait-ServiceState -Name $Name -Desired "Stopped"
    }
}

function Start-ReleaseService {
    param([string]$Name)
    Start-Service -Name $Name -ErrorAction Stop
    Wait-ServiceState -Name $Name -Desired "Running" -TimeoutSeconds 60
}

function Restore-BackupItems {
    param([object[]]$Items)
    foreach ($item in $Items) {
        $relative = "$($item.relative_path)"
        if (-not $relative) {
            continue
        }
        $source = Join-Path $BackupDirectory (Join-Path "files" $relative)
        $destination = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $source)) {
            continue
        }
        $parent = Split-Path -Parent $destination
        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        if ((Get-Item -LiteralPath $source).PSIsContainer) {
            if (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination -Recurse -Force
            }
            Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
        } else {
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
    }
}

function Resolve-Python {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }
    return (Get-Command python -ErrorAction Stop).Source
}

function Wait-HttpReady {
    param([string]$Uri, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
            if ([int]$response.StatusCode -eq 200) {
                return
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "Endpoint did not become ready: $Uri :: $lastError"
}

Assert-Administrator
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BackupDirectory = (Resolve-Path -LiteralPath $BackupDirectory).Path
$recordPath = Join-Path $BackupDirectory "deployment-record.json"
if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
    throw "Deployment record not found: $recordPath"
}
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding utf8 | ConvertFrom-Json
$previousCommit = "$($record.previous_commit)".Trim().ToLowerInvariant()
if ($previousCommit -notmatch "^[0-9a-f]{40}$") {
    throw "Deployment record does not contain a valid previous_commit."
}
if ($record.service_name) {
    $ServiceName = "$($record.service_name)"
}
if ($record.base_url) {
    $BaseUrl = "$($record.base_url)".TrimEnd("/")
}

Write-Output "Rolling back $ProjectRoot to $previousCommit"
Stop-ReleaseService -Name $ServiceName

Invoke-Git -Arguments @("checkout", "--detach", $previousCommit) | Out-Null
Restore-BackupItems -Items @($record.backup_items)

$pythonExe = Resolve-Python
$requirements = Join-Path $ProjectRoot "requirements.txt"
if (Test-Path -LiteralPath $requirements -PathType Leaf) {
    & $pythonExe -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency restoration failed during rollback."
    }
}

$buildInfoPath = Join-Path $ProjectRoot "build-info.json"
if (-not (Test-Path -LiteralPath $buildInfoPath -PathType Leaf)) {
    $generator = Join-Path $ProjectRoot "scripts\Generate-BuildInfo.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $generator -Release "rollback-$($previousCommit.Substring(0, 12))"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to regenerate build-info during rollback."
    }
}

Start-ReleaseService -Name $ServiceName
Wait-HttpReady -Uri "$BaseUrl/livez"
Wait-HttpReady -Uri "$BaseUrl/readyz"
$build = Invoke-RestMethod -Uri "$BaseUrl/build-info" -Method Get -TimeoutSec 15
$reported = "$($build.commit_sha)".ToLowerInvariant()
if ($reported -ne $previousCommit) {
    throw "Rollback build-info mismatch: expected=$previousCommit actual=$reported"
}

$rollbackResult = [ordered]@{
    status = "completed"
    completed_at = [DateTime]::UtcNow.ToString("o")
    restored_commit = $previousCommit
}
$record | Add-Member -NotePropertyName rollback -NotePropertyValue $rollbackResult -Force
[System.IO.File]::WriteAllText(
    $recordPath,
    (($record | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "Rollback completed. commit=$previousCommit service=$ServiceName"
