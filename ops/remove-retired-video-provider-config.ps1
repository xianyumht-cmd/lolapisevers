param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Resolve-DynamicCatalogPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$EnvironmentFile
    )

    $hadPrevious = Test-Path Env:DYNAMIC_QUERY_PROVIDERS_PATH
    $previous = $env:DYNAMIC_QUERY_PROVIDERS_PATH
    try {
        . $EnvironmentFile
        $configured = "$($env:DYNAMIC_QUERY_PROVIDERS_PATH)".Trim()
    } finally {
        if ($hadPrevious) {
            $env:DYNAMIC_QUERY_PROVIDERS_PATH = $previous
        } else {
            Remove-Item Env:DYNAMIC_QUERY_PROVIDERS_PATH -ErrorAction SilentlyContinue
        }
    }

    if ($configured) {
        if (-not [System.IO.Path]::IsPathRooted($configured)) {
            $configured = Join-Path $Root $configured
        }
        return [System.IO.Path]::GetFullPath($configured)
    }

    $localPath = Join-Path $Root "config\dynamic-query-providers.json"
    if (Test-Path -LiteralPath $localPath -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($localPath)
    }
    return ""
}

function Wait-ServiceState {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Desired,
        [int]$TimeoutSeconds = 90
    )
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

function Stop-ManagedService {
    param([Parameter(Mandatory = $true)][string]$Name)
    $service = Get-Service -Name $Name -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $Name -Force -ErrorAction Stop
        Wait-ServiceState -Name $Name -Desired "Stopped" -TimeoutSeconds 90
    }
}

function Start-ManagedService {
    param([Parameter(Mandatory = $true)][string]$Name)
    Start-Service -Name $Name -ErrorAction Stop
    Wait-ServiceState -Name $Name -Desired "Running" -TimeoutSeconds 90
}

function Wait-Http200 {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSeconds = 180
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
            if ([int]$response.StatusCode -eq 200) {
                return
            }
            $lastError = "HTTP $([int]$response.StatusCode)"
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 3
    }
    throw "Endpoint did not become ready: $Uri :: $lastError"
}

function Restore-LocalFiles {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentBackup,
        [Parameter(Mandatory = $true)][string]$EnvironmentFile,
        [string]$CatalogBackup,
        [string]$CatalogPath
    )

    Copy-Item -LiteralPath $EnvironmentBackup -Destination $EnvironmentFile -Force
    if ($CatalogBackup -and $CatalogPath -and (Test-Path -LiteralPath $CatalogBackup -PathType Leaf)) {
        Copy-Item -LiteralPath $CatalogBackup -Destination $CatalogPath -Force
    }
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BaseUrl = $BaseUrl.TrimEnd("/")
$envFile = Join-Path $ProjectRoot "ops\app_env.local.ps1"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing local environment file: $envFile"
}

if (-not $BackupRoot) {
    $parent = Split-Path -Parent $ProjectRoot
    $leaf = Split-Path -Leaf $ProjectRoot
    $BackupRoot = Join-Path $parent "$leaf.deploy-backups"
}
if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
}
$BackupRoot = (Resolve-Path -LiteralPath $BackupRoot).Path
if ($BackupRoot.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Retirement backup root must be outside the Git repository: $BackupRoot"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot "$stamp-video-provider-retirement"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupFile = Join-Path $backupDir "app_env.local.ps1"
Copy-Item -LiteralPath $envFile -Destination $backupFile -Force

$catalogPath = Resolve-DynamicCatalogPath -Root $ProjectRoot -EnvironmentFile $envFile
$catalogBackup = ""
$catalogStatus = "not configured"

$original = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
$riskBefore = [regex]::Match($original, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value
$dynamicBefore = [regex]::Match($original, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value
$updated = [regex]::Replace(
    $original,
    '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=.*(?:\r?\n)?',
    ''
)

try {
    if ($updated -eq $original) {
        Write-Host "QUERY_VIDEO_PROVIDERS_JSON is already absent."
    } else {
        [System.IO.File]::WriteAllText(
            $envFile,
            $updated,
            (New-Object System.Text.UTF8Encoding($false))
        )
    }

    $after = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
    if ($after -match '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=') {
        throw "Video provider setting still exists."
    }
    if ($riskBefore -ne [regex]::Match($after, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value) {
        throw "Risk provider setting changed unexpectedly."
    }
    if ($dynamicBefore -ne [regex]::Match($after, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value) {
        throw "Dynamic provider path changed unexpectedly."
    }

    if ($catalogPath) {
        if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
            throw "Configured dynamic provider catalog does not exist: $catalogPath"
        }
        $catalogBackup = Join-Path $backupDir "dynamic-query-providers.json"
        Copy-Item -LiteralPath $catalogPath -Destination $catalogBackup -Force

        $catalog = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ("$($catalog.schema)" -ne "lolapi-dynamic-query-providers.v1") {
            throw "Dynamic provider catalog schema is unsupported: $catalogPath"
        }
        $commandsBefore = @($catalog.commands)
        $nonVideoBefore = @(
            $commandsBefore |
                Where-Object { "$($_.id)".Trim() -ne "video.info" } |
                ForEach-Object { $_ | ConvertTo-Json -Depth 30 -Compress }
        )
        $videoBefore = @(
            $commandsBefore |
                Where-Object { "$($_.id)".Trim() -eq "video.info" }
        )

        if ($videoBefore.Count -gt 0) {
            $catalog.commands = @(
                $commandsBefore |
                    Where-Object { "$($_.id)".Trim() -ne "video.info" }
            )
            $catalogJson = $catalog | ConvertTo-Json -Depth 30
            [System.IO.File]::WriteAllText(
                $catalogPath,
                ($catalogJson + [Environment]::NewLine),
                (New-Object System.Text.UTF8Encoding($false))
            )
            $catalogStatus = "removed video.info"
        } else {
            $catalogStatus = "video.info already absent"
        }

        $catalogAfter = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $commandsAfter = @($catalogAfter.commands)
        if (@($commandsAfter | Where-Object { "$($_.id)".Trim() -eq "video.info" }).Count -ne 0) {
            throw "video.info still exists in the dynamic provider catalog."
        }
        $nonVideoAfter = @(
            $commandsAfter |
                ForEach-Object { $_ | ConvertTo-Json -Depth 30 -Compress }
        )
        if (($nonVideoBefore -join "`n") -ne ($nonVideoAfter -join "`n")) {
            throw "Non-video dynamic command definitions changed unexpectedly."
        }
    }

    Stop-ManagedService -Name $ServiceName
    Start-ManagedService -Name $ServiceName
    Wait-Http200 -Uri "$BaseUrl/livez" -TimeoutSeconds 180
    Wait-Http200 -Uri "$BaseUrl/readyz" -TimeoutSeconds 180
    Wait-Http200 -Uri "$BaseUrl/health" -TimeoutSeconds 180
} catch {
    $failure = $_.Exception.Message
    Restore-LocalFiles `
        -EnvironmentBackup $backupFile `
        -EnvironmentFile $envFile `
        -CatalogBackup $catalogBackup `
        -CatalogPath $catalogPath
    $restoreFailure = ""
    try {
        Stop-ManagedService -Name $ServiceName
        Start-ManagedService -Name $ServiceName
        Wait-Http200 -Uri "$BaseUrl/livez" -TimeoutSeconds 180
        Wait-Http200 -Uri "$BaseUrl/readyz" -TimeoutSeconds 180
    } catch {
        $restoreFailure = $_.Exception.Message
    }
    if ($restoreFailure) {
        throw "Post-change validation failed and configuration was restored, but service recovery also failed: $failure :: $restoreFailure"
    }
    throw "Post-change validation failed and local configuration was restored: $failure"
}

Write-Host "Retired video provider configuration removed successfully."
Write-Host "Dynamic catalog: $catalogStatus"
Write-Host "Backup: $backupDir"
