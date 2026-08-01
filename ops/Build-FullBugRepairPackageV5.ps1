param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [Parameter(Mandatory = $true)]
    [string]$TargetCommit,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText(
        $Path,
        $Text,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

if ($TargetCommit -notmatch '^[0-9a-f]{40}$') {
    throw "TargetCommit must be a full lowercase SHA-1 commit id."
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$workRoot = Join-Path $env:RUNNER_TEMP ("lol-safe-deploy-v5-" + [Guid]::NewGuid().ToString("N"))
$v3Output = Join-Path $workRoot "v3-output"
$extractRoot = Join-Path $workRoot "extract"
New-Item -ItemType Directory -Path $v3Output, $extractRoot -Force | Out-Null

try {
    $v3Builder = Join-Path $RepositoryRoot "ops\Build-FullBugRepairPackageV3.ps1"
    if (-not (Test-Path -LiteralPath $v3Builder -PathType Leaf)) {
        throw "V3 builder is missing."
    }

    Write-Host "Build verified V3 base package for the P009-integrated target"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $v3Builder `
        -RepositoryRoot $RepositoryRoot `
        -TargetCommit $TargetCommit `
        -OutputRoot $v3Output
    if ($LASTEXITCODE -ne 0) {
        throw "V3 base package build failed. ExitCode=$LASTEXITCODE"
    }

    $v3Zip = Get-ChildItem -LiteralPath $v3Output -Filter "*.zip" -File | Select-Object -First 1
    if (-not $v3Zip) {
        throw "V3 base ZIP is missing."
    }
    Expand-Archive -LiteralPath $v3Zip.FullName -DestinationPath $extractRoot -Force

    $oldRoot = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
    if (-not $oldRoot) {
        throw "Expanded V3 package root is missing."
    }

    $shortCommit = $TargetCommit.Substring(0, 12)
    $packageName = "LOLDataSystem-full-bug-repair-safe-deploy-$shortCommit-py311-py314-winps51-p009-integrated-v5"
    Rename-Item -LiteralPath $oldRoot.FullName -NewName $packageName
    $packageRoot = Join-Path $extractRoot $packageName

    $manifestPath = Join-Path $packageRoot "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Embedded manifest is missing."
    }

    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ("$($manifest.target_commit)" -ne $TargetCommit) {
        throw "Embedded target commit mismatch."
    }

    $manifest.package_id = "LOLAPI-FULL-BUG-REPAIR-SAFE-DEPLOY-$shortCommit-P009-INTEGRATED-V5"
    $manifest.built_at = [DateTime]::UtcNow.ToString("o")
    $manifest | Add-Member -NotePropertyName package_revision -NotePropertyValue 5 -Force
    $manifest.deployment | Add-Member -NotePropertyName p009_lineage_preserved -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName parser_center_present -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName full_bug_repair_integrated -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName ancestry_guard_preserved -NotePropertyValue $true -Force

    $entries = @(
        Get-ChildItem -LiteralPath $packageRoot -Recurse -File |
            Where-Object { $_.FullName -ne $manifestPath } |
            ForEach-Object {
                $relative = $_.FullName.Substring($packageRoot.Length).TrimStart("\") -replace "\\", "/"
                [ordered]@{
                    path = $relative
                    sha256 = Get-Sha256 $_.FullName
                    bytes = [int64]$_.Length
                }
            } |
            Sort-Object path
    )

    $contentLines = ($entries | ForEach-Object {
        "$($_.path)`t$($_.sha256)`t$($_.bytes)"
    }) -join "`n"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $contentDigest = ([BitConverter]::ToString(
            $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($contentLines))
        )).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }

    $manifest.package_content_sha256 = $contentDigest
    $manifest.files = $entries
    Write-Utf8NoBom -Path $manifestPath -Text (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    $finalZip = Join-Path $OutputRoot "$packageName.zip"
    if (Test-Path -LiteralPath $finalZip) {
        Remove-Item -LiteralPath $finalZip -Force
    }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $finalZip -CompressionLevel Optimal -Force

    $metadata = [ordered]@{
        schema_version = "lolapisevers-safe-deployment-artifact.v1"
        filename = [IO.Path]::GetFileName($finalZip)
        target_commit = $TargetCommit
        zip_sha256 = Get-Sha256 $finalZip
        bytes = [int64](Get-Item -LiteralPath $finalZip).Length
        package_content_sha256 = $contentDigest
        supported_python_versions = @("3.11", "3.12", "3.13", "3.14")
        package_revision = 5
        powershell_utf8_parse_input = $true
        p009_lineage_preserved = $true
        parser_center_present = $true
        full_bug_repair_integrated = $true
        ancestry_guard_preserved = $true
    }
    $metadataPath = Join-Path $OutputRoot "$packageName.metadata.json"
    Write-Utf8NoBom -Path $metadataPath -Text (($metadata | ConvertTo-Json -Depth 10) + [Environment]::NewLine)

    Write-Host "V5 P009-integrated deployment package created successfully."
    Write-Host "ZIP: $finalZip"
    Write-Host "SHA256: $($metadata.zip_sha256)"
} finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
