param(
    [string]$Release = "",
    [string]$ContractVersion = "groupguard-lol-api.v2",
    [string]$ConfigSchemaVersion = "5",
    [string]$OutputPath = "",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$manifestScript = Join-Path $PSScriptRoot "RuntimeSourceManifest.ps1"
if (-not (Test-Path -LiteralPath $manifestScript -PathType Leaf)) {
    throw "Runtime source manifest helper is missing: $manifestScript"
}
. $manifestScript

if (-not $OutputPath) {
    $OutputPath = Join-Path $repositoryRoot "build-info.json"
}

$commitSha = (& git -C $repositoryRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve the release Git commit."
}
if ($commitSha -notmatch "^[0-9a-fA-F]{40}$") {
    throw "A full 40-character Git commit SHA is required."
}
if (-not $Release) {
    $Release = "build-$($commitSha.Substring(0, 12).ToLowerInvariant())"
}

$sourceManifest = New-RuntimeSourceManifest `
    -RepositoryRoot $repositoryRoot `
    -AllowTrackedRuntimeChanges:$AllowDirty
$dirty = $sourceManifest.tracked_runtime_dirty

$payload = [ordered]@{
    schema_version = "1"
    service = "lolapisevers"
    release = $Release
    commit_sha = $commitSha.ToLowerInvariant()
    build_time_utc = [DateTime]::UtcNow.ToString("o")
    contract_version = $ContractVersion
    config_schema_version = $ConfigSchemaVersion
    dirty = $dirty
    source_manifest = $sourceManifest
}

$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$json = ($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine
[System.IO.File]::WriteAllText(
    $OutputPath,
    $json,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "build_info_written=$OutputPath"
Write-Output "commit_sha=$commitSha"
Write-Output "dirty=$dirty"
Write-Output "source_manifest_files=$($sourceManifest.file_count)"
Write-Output "source_manifest_sha256=$($sourceManifest.aggregate_sha256)"
