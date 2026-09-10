param(
    [Parameter(Mandatory = $true)]
    [string]$DistRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Replace-UniqueText {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $oldNormalized = $Old.Replace("`r`n", "`n")
    $newNormalized = $New.Replace("`r`n", "`n")
    $count = [regex]::Matches($Text, [regex]::Escape($oldNormalized)).Count
    if ($count -ne 1) { throw "$Label patch anchor count was $count, expected 1." }
    return $Text.Replace($oldNormalized, $newNormalized)
}

$DistRoot = [IO.Path]::GetFullPath($DistRoot)
$zipFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.zip" -File)
$metadataFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.metadata.json" -File)
if ($zipFiles.Count -ne 1 -or $metadataFiles.Count -ne 1) {
    throw "Expected exactly one V3 ZIP and one metadata file."
}
$zipFile = $zipFiles[0]
$metadataFile = $metadataFiles[0]
$tempRoot = Join-Path $env:RUNNER_TEMP ("lol-v3-production-venv-acl-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $zipFile.FullName -DestinationPath $tempRoot -Force
    $manifestFiles = @(Get-ChildItem -LiteralPath $tempRoot -Filter "manifest.json" -File -Recurse)
    if ($manifestFiles.Count -ne 1) { throw "Expected exactly one embedded manifest." }
    $manifestFile = $manifestFiles[0]
    $packageRoot = $manifestFile.Directory.FullName
    $deployPath = Join-Path $packageRoot "Deploy-FullBugRepairSafe.ps1"
    if (-not (Test-Path -LiteralPath $deployPath -PathType Leaf)) { throw "V3 deployment script is missing." }
    $deployText = (Get-Content -LiteralPath $deployPath -Raw -Encoding UTF8).Replace("`r`n", "`n")

    $helperAnchor = 'function Invoke-CandidateTests {'
    $helperBlock = @'
function Test-DirectoryEntryFromParent {
    param([string]$Path)
    $parent = Split-Path -Parent $Path
    $leaf = Split-Path -Leaf $Path
    if (-not $parent -or -not (Test-Path -LiteralPath $parent -PathType Container)) {
        return $false
    }
    $entries = @(Get-ChildItem -LiteralPath $parent -Force -Directory -ErrorAction Stop | Where-Object { $_.Name -ieq $leaf })
    return ($entries.Count -gt 0)
}

function Ensure-ManagedVenvAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-DirectoryEntryFromParent -Path $Path)) { return $false }

    Write-Host ("Normalize {0} ACL for Administrators and SYSTEM: {1}" -f $Label, $Path)
    $takeown = Join-Path $env:SystemRoot "System32\takeown.exe"
    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"

    # A .venv moved from a protected candidate directory can retain the ACL of
    # the identity that performed the previous deployment. Repair it only after
    # production is stopped. Well-known SIDs avoid localized Windows names.
    $ownerResult = Invoke-NativeProcess -FilePath $takeown -Arguments @("/F", $Path, "/A") -AllowFailure -Quiet
    if ($ownerResult.ExitCode -ne 0) {
        Write-Warning ("takeown returned ExitCode={0}; attempting icacls because the current token may already own the directory." -f $ownerResult.ExitCode)
    }

    $rootGrant = Invoke-NativeProcess -FilePath $icacls -Arguments @(
        $Path, "/inheritance:e", "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"
    ) -AllowFailure -Quiet
    if ($rootGrant.ExitCode -ne 0) { throw "Unable to repair root ACL for $Label." }

    $treeGrant = Invoke-NativeProcess -FilePath $icacls -Arguments @(
        $Path, "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
        "/T", "/C", "/Q"
    ) -AllowFailure -Quiet
    if ($treeGrant.ExitCode -ne 0) { throw "Unable to propagate maintainable ACL through $Label." }

    try { Get-Item -LiteralPath $Path -Force -ErrorAction Stop | Out-Null }
    catch { throw "ACL normalization completed but $Label is still unreadable: $($_.Exception.Message)" }
    Write-Host ("ACL READY: {0}" -f $Label) -ForegroundColor Green
    return $true
}

'@
    $deployText = Replace-UniqueText -Text $deployText -Old $helperAnchor -New ($helperBlock + $helperAnchor) -Label "Production venv ACL helper"

    $oldSwap = @'
    $oldVenv = Join-Path $ProjectRoot ".venv"
    $backupVenv = Join-Path $backupDirectory "venv.previous"
    if (Test-Path -LiteralPath $oldVenv -PathType Container) {
        Move-Item -LiteralPath $oldVenv -Destination $backupVenv
        $record.previous_venv = "venv.previous"
    }
'@
    $newSwap = @'
    $oldVenv = Join-Path $ProjectRoot ".venv"
    $backupVenv = Join-Path $backupDirectory "venv.previous"
    if (Ensure-ManagedVenvAcl -Path $oldVenv -Label "existing production venv") {
        Move-Item -LiteralPath $oldVenv -Destination $backupVenv
        $record.previous_venv = "venv.previous"
    }
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $oldSwap.TrimEnd() -New $newSwap.TrimEnd() -Label "Existing production venv swap"

    $oldInstall = '    Move-Item -LiteralPath $candidateVenv -Destination (Join-Path $ProjectRoot ".venv")'
    $newInstall = @'
    $installedVenv = Join-Path $ProjectRoot ".venv"
    Move-Item -LiteralPath $candidateVenv -Destination $installedVenv
    if (-not (Ensure-ManagedVenvAcl -Path $installedVenv -Label "installed production venv")) {
        throw "Installed production venv is missing after candidate move."
    }
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $oldInstall -New $newInstall.TrimEnd() -Label "Installed production venv ACL normalization"

    foreach ($marker in @(
        'function Ensure-ManagedVenvAcl {',
        '"*S-1-5-32-544:(OI)(CI)F"',
        '"*S-1-5-18:(OI)(CI)F"',
        'Ensure-ManagedVenvAcl -Path $oldVenv -Label "existing production venv"',
        'Ensure-ManagedVenvAcl -Path $installedVenv -Label "installed production venv"'
    )) {
        if (-not $deployText.Contains($marker)) { throw "Production venv ACL marker is missing: $marker" }
    }
    if ($deployText.Contains('if (Test-Path -LiteralPath $oldVenv -PathType Container)')) {
        throw "Unsafe old production venv Test-Path remains."
    }
    Write-Utf8NoBom -Path $deployPath -Text $deployText

    $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $deployEntry = @($manifest.files | Where-Object { "$($_.path)" -eq "Deploy-FullBugRepairSafe.ps1" })
    if ($deployEntry.Count -ne 1) { throw "Embedded manifest deployment entry was not unique." }
    $deployEntry[0].sha256 = Get-Sha256 $deployPath
    $deployEntry[0].bytes = [int64](Get-Item -LiteralPath $deployPath).Length
    $manifest.deployment | Add-Member -NotePropertyName production_venv_acl_recovery -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName installed_venv_acl_normalized -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName venv_acl_well_known_sids -NotePropertyValue $true -Force

    $entries = @($manifest.files | Sort-Object path)
    $contentLines = ($entries | ForEach-Object { "$($_.path)`t$($_.sha256)`t$($_.bytes)" }) -join "`n"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $contentDigest = ([BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($contentLines)))).Replace("-", "").ToLowerInvariant()
    } finally { $sha256.Dispose() }
    $manifest.package_content_sha256 = $contentDigest
    Write-Utf8NoBom -Path $manifestFile.FullName -Text (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Remove-Item -LiteralPath $zipFile.FullName -Force
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipFile.FullName -CompressionLevel Optimal -Force

    $metadata = Get-Content -LiteralPath $metadataFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $metadata.zip_sha256 = Get-Sha256 $zipFile.FullName
    $metadata.bytes = [int64](Get-Item -LiteralPath $zipFile.FullName).Length
    $metadata.package_content_sha256 = $contentDigest
    $metadata | Add-Member -NotePropertyName production_venv_acl_recovery -NotePropertyValue $true -Force
    $metadata | Add-Member -NotePropertyName installed_venv_acl_normalized -NotePropertyValue $true -Force
    $metadata | Add-Member -NotePropertyName venv_acl_well_known_sids -NotePropertyValue $true -Force
    Write-Utf8NoBom -Path $metadataFile.FullName -Text (($metadata | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
    Write-Host "Patched V3 artifact for production venv ACL recovery and future maintainability."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
