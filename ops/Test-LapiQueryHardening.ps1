param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedCommit,
    [string]$Hero = "Yasuo",
    [ValidatePattern("^$|^[0-9]{5,11}$")]
    [string]$BanQQ = "",
    [string]$OutputPath = "",
    [int]$Attempts = 3,
    [int]$DelaySeconds = 5
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Invoke-JsonRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [ValidateSet("GET", "POST")][string]$Method = "GET",
        [object]$Body = $null,
        [int]$RetryCount = 3,
        [int]$RetryDelaySeconds = 5
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le [Math]::Max(1, $RetryCount); $attempt++) {
        try {
            $params = @{
                Uri = $Uri
                Method = $Method
                TimeoutSec = 30
                UseBasicParsing = $true
                Headers = @{ Accept = "application/json" }
            }
            if ($Method -eq "POST") {
                $params.ContentType = "application/json; charset=utf-8"
                $params.Body = ($Body | ConvertTo-Json -Depth 10 -Compress)
            }
            $response = Invoke-WebRequest @params
            $parsed = $response.Content | ConvertFrom-Json
            return [pscustomobject]@{
                StatusCode = [int]$response.StatusCode
                Body = $parsed
            }
        } catch {
            $lastError = $_
            if ($attempt -lt $RetryCount) {
                Start-Sleep -Seconds $RetryDelaySeconds
            }
        }
    }
    throw "Request failed after $RetryCount attempt(s): $Uri :: $($lastError.Exception.Message)"
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Get-SnapshotRoot {
    param([string]$Root)
    $configured = "$($env:UPSTREAM_SNAPSHOT_DIR)".Trim()
    if ($configured) {
        if ([System.IO.Path]::IsPathRooted($configured)) {
            return $configured
        }
        return (Join-Path $Root $configured)
    }
    return (Join-Path $Root "data\upstream_snapshots")
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BaseUrl = $BaseUrl.TrimEnd("/")
$envFile = Join-Path $ProjectRoot "ops\app_env.local.ps1"
if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    . $envFile
}

$checks = New-Object System.Collections.Generic.List[object]
function Add-Check {
    param([string]$Name, [string]$Status, [string]$Detail)
    $checks.Add([ordered]@{
        name = $Name
        status = $Status
        detail = $Detail
    }) | Out-Null
}

$live = Invoke-JsonRequest -Uri "$BaseUrl/livez" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($live.StatusCode -eq 200) "livez did not return HTTP 200"
Add-Check "livez" "pass" "HTTP 200"

$ready = Invoke-JsonRequest -Uri "$BaseUrl/readyz" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($ready.StatusCode -eq 200) "readyz did not return HTTP 200"
Add-Check "readyz" "pass" "HTTP 200"

$build = Invoke-JsonRequest -Uri "$BaseUrl/build-info" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
$reportedCommit = "$($build.Body.commit_sha)".ToLowerInvariant()
Assert-True ($reportedCommit -eq $ExpectedCommit.ToLowerInvariant()) "build-info commit mismatch: expected=$ExpectedCommit actual=$reportedCommit"
Assert-True ($build.Body.dirty -eq $false) "build-info reports a dirty release"
Add-Check "build_info" "pass" $reportedCommit

$legacyShard = Invoke-JsonRequest -Uri "$BaseUrl/shard_query?hero=$([uri]::EscapeDataString($Hero))&output=json" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($legacyShard.StatusCode -eq 200) "legacy shard endpoint failed"
Assert-True ([bool]$legacyShard.Body.hero) "legacy shard endpoint returned no hero"
Add-Check "legacy_shard" "pass" "source=$($legacyShard.Body.source)"

$legacyAram = Invoke-JsonRequest -Uri "$BaseUrl/aram_augments?hero=$([uri]::EscapeDataString($Hero))&output=json" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($legacyAram.StatusCode -eq 200) "legacy ARAM endpoint failed"
Assert-True ([bool]$legacyAram.Body.hero) "legacy ARAM endpoint returned no hero"
Add-Check "legacy_aram" "pass" "source=$($legacyAram.Body.source)"

$capabilities = @{ text = $true; image = $false; forward = $true }
$shardRequest = @{
    feature = "shard"
    parameters = @{ hero = $Hero }
    preferred = "text"
    capabilities = $capabilities
    request_id = "deploy-shard"
}
$deliveryShard = Invoke-JsonRequest -Uri "$BaseUrl/api/v1/groupguard/query" -Method POST -Body $shardRequest -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($deliveryShard.Body.protocol -eq "groupguard-query-delivery.v1") "shard delivery protocol mismatch"
Assert-True ($deliveryShard.Body.ok -eq $true) "shard delivery returned failure"
Assert-True (@($deliveryShard.Body.delivery.segments).Count -ge 1) "shard delivery has no segments"
Add-Check "delivery_shard" "pass" "kind=$($deliveryShard.Body.delivery.kind)"

$aramRequest = @{
    feature = "aram"
    parameters = @{ hero = $Hero }
    preferred = "text"
    capabilities = $capabilities
    request_id = "deploy-aram"
}
$deliveryAram = Invoke-JsonRequest -Uri "$BaseUrl/api/v1/groupguard/query" -Method POST -Body $aramRequest -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($deliveryAram.Body.protocol -eq "groupguard-query-delivery.v1") "ARAM delivery protocol mismatch"
Assert-True ($deliveryAram.Body.ok -eq $true) "ARAM delivery returned failure"
Assert-True (@($deliveryAram.Body.delivery.segments).Count -ge 1) "ARAM delivery has no segments"
Add-Check "delivery_aram" "pass" "kind=$($deliveryAram.Body.delivery.kind)"

if ($BanQQ) {
    $banRequest = @{
        feature = "lolban"
        parameters = @{ qq = $BanQQ }
        preferred = "text"
        capabilities = $capabilities
        request_id = "deploy-lolban"
    }
    $deliveryBan = Invoke-JsonRequest -Uri "$BaseUrl/api/v1/groupguard/query" -Method POST -Body $banRequest -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
    Assert-True ($deliveryBan.Body.protocol -eq "groupguard-query-delivery.v1") "lolban delivery protocol mismatch"
    Assert-True (@($deliveryBan.Body.delivery.segments).Count -ge 1) "lolban delivery has no segments"
    Add-Check "delivery_lolban" "pass" "ok=$($deliveryBan.Body.ok)"
} else {
    Add-Check "delivery_lolban" "skipped" "BanQQ was not supplied"
}

$observability = Invoke-JsonRequest -Uri "$BaseUrl/api/v1/operations/query-observability" -RetryCount $Attempts -RetryDelaySeconds $DelaySeconds
Assert-True ($observability.Body.schema_version -eq "query-observability.v1") "observability schema mismatch"
Assert-True ($observability.Body.status -ne "down") "query observability reports down"
Add-Check "observability" "pass" "status=$($observability.Body.status)"

$snapshotRoot = Get-SnapshotRoot -Root $ProjectRoot
Assert-True (Test-Path -LiteralPath $snapshotRoot -PathType Container) "snapshot directory does not exist: $snapshotRoot"
$requiredSnapshots = @("lol-shard-data.json", "lol-hero-list.json")
foreach ($name in $requiredSnapshots) {
    $path = Join-Path $snapshotRoot $name
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "required snapshot missing: $name"
}
$aramSnapshots = @(Get-ChildItem -LiteralPath $snapshotRoot -Filter "aram-mayhem-*.json" -File -ErrorAction SilentlyContinue)
Assert-True ($aramSnapshots.Count -ge 1) "no ARAM payload snapshot was created"
Add-Check "snapshots" "pass" "root=$snapshotRoot aram_count=$($aramSnapshots.Count)"

$result = [ordered]@{
    schema_version = "lapi-query-hardening-verification.v1"
    generated_at = [DateTime]::UtcNow.ToString("o")
    project_root = $ProjectRoot
    base_url = $BaseUrl
    expected_commit = $ExpectedCommit.ToLowerInvariant()
    hero = $Hero
    ban_check = $(if ($BanQQ) { "executed" } else { "skipped" })
    status = "pass"
    checks = $checks
}

if ($OutputPath) {
    $parent = Split-Path -Parent $OutputPath
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText(
        $OutputPath,
        (($result | ConvertTo-Json -Depth 10) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
}

$result | ConvertTo-Json -Depth 10
