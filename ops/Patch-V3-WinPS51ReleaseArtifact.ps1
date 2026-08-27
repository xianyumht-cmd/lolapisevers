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
    [System.IO.File]::WriteAllText(
        $Path,
        $Text,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

$DistRoot = [IO.Path]::GetFullPath($DistRoot)
$zipFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.zip" -File)
$metadataFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.metadata.json" -File)
if ($zipFiles.Count -ne 1 -or $metadataFiles.Count -ne 1) {
    throw "Expected exactly one V3 ZIP and one metadata file."
}
$zipFile = $zipFiles[0]
$metadataFile = $metadataFiles[0]

$tempRoot = Join-Path $env:RUNNER_TEMP ("lol-v3-winps51-native-git-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $zipFile.FullName -DestinationPath $tempRoot -Force
    $manifestFiles = @(Get-ChildItem -LiteralPath $tempRoot -Filter "manifest.json" -File -Recurse)
    if ($manifestFiles.Count -ne 1) {
        throw "Expected exactly one embedded manifest."
    }
    $manifestFile = $manifestFiles[0]
    $packageRoot = $manifestFile.Directory.FullName
    $deployPath = Join-Path $packageRoot "Deploy-FullBugRepairSafe.ps1"
    if (-not (Test-Path -LiteralPath $deployPath -PathType Leaf)) {
        throw "V3 deployment script is missing."
    }

    $deployText = (Get-Content -LiteralPath $deployPath -Raw -Encoding UTF8).Replace("`r`n", "`n")
    $unsafeAnchor = @'
    & (Resolve-GitExecutable) -C $ProjectRoot bundle verify $bundlePath
    if ($LASTEXITCODE -ne 0) {
        throw "Release bundle verification failed."
    }
    $candidateRepository = Join-Path $candidateDirectory "repository"
    & (Resolve-GitExecutable) clone --no-checkout $bundlePath $candidateRepository
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate clone from release bundle failed."
    }
'@
    $safeReplacement = @'
    Invoke-Git -WorkingDirectory $ProjectRoot -Arguments @("bundle", "verify", $bundlePath) | Out-Null
    $candidateRepository = Join-Path $candidateDirectory "repository"
    Invoke-Git -WorkingDirectory $ProjectRoot -Arguments @("clone", "--no-checkout", $bundlePath, $candidateRepository) | Out-Null
'@
    $unsafeText = $unsafeAnchor.Replace("`r`n", "`n").TrimEnd()
    $safeText = $safeReplacement.Replace("`r`n", "`n").TrimEnd()
    if ([regex]::Matches($deployText, [regex]::Escape($unsafeText)).Count -ne 1) {
        throw "Native Git stderr safety patch anchor was not unique."
    }
    $deployText = $deployText.Replace($unsafeText, $safeText)
    if ($deployText.Contains('& (Resolve-GitExecutable) -C $ProjectRoot bundle verify')) {
        throw "Unsafe native bundle verify command remains after patch."
    }
    if ($deployText.Contains('& (Resolve-GitExecutable) clone --no-checkout')) {
        throw "Unsafe native clone command remains after patch."
    }
    Write-Utf8NoBom -Path $deployPath -Text $deployText

    $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $deployEntry = @($manifest.files | Where-Object { "$( $_.path )" -eq "Deploy-FullBugRepairSafe.ps1" })
    if ($deployEntry.Count -ne 1) {
        throw "Embedded manifest deployment entry was not unique."
    }
    $deployEntry[0].sha256 = Get-Sha256 $deployPath
    $deployEntry[0].bytes = [int64](Get-Item -LiteralPath $deployPath).Length
    $manifest.deployment | Add-Member -NotePropertyName winps51_native_git_stderr_safe -NotePropertyValue $true -Force

    $entries = @($manifest.files | Sort-Object path)
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
    Write-Utf8NoBom -Path $manifestFile.FullName -Text (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Remove-Item -LiteralPath $zipFile.FullName -Force
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipFile.FullName -CompressionLevel Optimal -Force

    $metadata = Get-Content -LiteralPath $metadataFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $metadata.zip_sha256 = Get-Sha256 $zipFile.FullName
    $metadata.bytes = [int64](Get-Item -LiteralPath $zipFile.FullName).Length
    $metadata.package_content_sha256 = $contentDigest
    $metadata | Add-Member -NotePropertyName winps51_native_git_stderr_safe -NotePropertyValue $true -Force
    Write-Utf8NoBom -Path $metadataFile.FullName -Text (($metadata | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Write-Host "Patched V3 artifact for Windows PowerShell 5.1 native Git stderr safety."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
