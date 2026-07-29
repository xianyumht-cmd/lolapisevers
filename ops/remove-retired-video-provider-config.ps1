param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$ServiceName = "LOLDataSystem"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$envFile = Join-Path $ProjectRoot "ops\app_env.local.ps1"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing local environment file: $envFile"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $ProjectRoot ".video-provider-retirement-backups\$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupFile = Join-Path $backupDir "app_env.local.ps1"
Copy-Item -LiteralPath $envFile -Destination $backupFile -Force

$original = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
$riskBefore = [regex]::Match($original, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value
$dynamicBefore = [regex]::Match($original, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value
$updated = [regex]::Replace(
    $original,
    '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=.*(?:\r?\n)?',
    ''
)

if ($updated -eq $original) {
    Write-Host "QUERY_VIDEO_PROVIDERS_JSON is already absent. No file change required."
} else {
    [System.IO.File]::WriteAllText($envFile, $updated, (New-Object System.Text.UTF8Encoding($false)))
}

$after = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
if ($after -match '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=') {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Video provider setting still exists; configuration was rolled back."
}
if ($riskBefore -ne [regex]::Match($after, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value) {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Risk provider setting changed unexpectedly; configuration was rolled back."
}
if ($dynamicBefore -ne [regex]::Match($after, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value) {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Dynamic provider path changed unexpectedly; configuration was rolled back."
}

try {
    Restart-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 3
    $live = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:5001/livez" -TimeoutSec 10
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:5001/health" -TimeoutSec 10
    if ($null -eq $live -or $null -eq $health) {
        throw "Health endpoints returned empty responses."
    }
} catch {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    Restart-Service -Name $ServiceName -Force
    throw "Post-change validation failed and configuration was rolled back: $($_.Exception.Message)"
}

Write-Host "Retired video provider setting removed successfully."
Write-Host "Backup: $backupFile"
