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

$ToolsZipSha256 = "30266c26bc21b4600d7e2cf63a27978f486958fa7c1e65a11e19484587a54237"
$SupportedPythonVersions = @("3.11", "3.12", "3.13", "3.14")
$BinaryPackages = @("pillow", "pydantic_core", "cffi", "greenlet", "charset_normalizer")

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-LastExitCode([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Message ExitCode=$LASTEXITCODE"
    }
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText(
        $Path,
        $Text,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

if ($TargetCommit -notmatch '^[0-9a-f]{40}$') {
    throw "TargetCommit must be a full lowercase SHA-1 commit id."
}

$workRoot = Join-Path $env:RUNNER_TEMP ("lol-safe-deploy-v3-" + [Guid]::NewGuid().ToString("N"))
$toolsRoot = Join-Path $workRoot "tools"
$baseOutput = Join-Path $workRoot "base-output"
$staging = Join-Path $workRoot "staging"
New-Item -ItemType Directory -Path $toolsRoot, $baseOutput, $staging -Force | Out-Null

try {
    Write-Host "Reconstruct deployment tools"
    $chunkRoot = Join-Path $RepositoryRoot ".deployment-package\full-bug-repair-20260801"
    $chunks = @(Get-ChildItem -LiteralPath $chunkRoot -Filter "chunk-*.txt" -File | Sort-Object Name)
    if ($chunks.Count -ne 4) {
        throw "Expected exactly four deployment tool chunks."
    }

    $encoded = ""
    foreach ($chunk in $chunks) {
        $encoded += (Get-Content -LiteralPath $chunk.FullName -Raw -Encoding ASCII).Trim()
    }

    $toolsZip = Join-Path $workRoot "package-tools.zip"
    [System.IO.File]::WriteAllBytes($toolsZip, [Convert]::FromBase64String($encoded))
    if ((Get-Sha256 $toolsZip) -ne $ToolsZipSha256) {
        throw "Deployment tools archive SHA-256 mismatch."
    }
    Expand-Archive -LiteralPath $toolsZip -DestinationPath $toolsRoot -Force

    $toolNames = @(
        "Deploy-FullBugRepairSafe.ps1",
        "Rollback-FullBugRepairSafe.ps1",
        "Verify-FullBugRepairProduction.ps1",
        "Build-FullBugRepairPackage.ps1"
    )
    foreach ($toolName in $toolNames) {
        $sourceTool = Join-Path $toolsRoot "ops\$toolName"
        $targetTool = Join-Path $RepositoryRoot "ops\$toolName"
        if (-not (Test-Path -LiteralPath $sourceTool -PathType Leaf)) {
            throw "Reconstructed deployment tool is missing: $toolName"
        }
        Copy-Item -LiteralPath $sourceTool -Destination $targetTool -Force
    }

    $baseBuilder = Join-Path $RepositoryRoot "ops\Build-FullBugRepairPackage.ps1"
    if (-not (Test-Path -LiteralPath $baseBuilder -PathType Leaf)) {
        throw "Base package builder is missing."
    }

    Write-Host "Build immutable base package"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $baseBuilder `
        -RepositoryRoot $RepositoryRoot `
        -TargetCommit $TargetCommit `
        -OutputRoot $baseOutput
    Assert-LastExitCode "Base deployment package build failed."

    $baseZip = Get-ChildItem -LiteralPath $baseOutput -Filter "*.zip" -File | Select-Object -First 1
    if (-not $baseZip) {
        throw "Base deployment ZIP is missing."
    }
    Expand-Archive -LiteralPath $baseZip.FullName -DestinationPath $staging -Force

    $expandedRoot = Get-ChildItem -LiteralPath $staging -Directory | Select-Object -First 1
    if (-not $expandedRoot) {
        throw "Expanded package root is missing."
    }

    $shortCommit = $TargetCommit.Substring(0, 12)
    $packageName = "LOLDataSystem-full-bug-repair-safe-deploy-$shortCommit-py311-py314-winps51-v3"
    $packageRoot = Join-Path $staging $packageName
    Rename-Item -LiteralPath $expandedRoot.FullName -NewName $packageName

    $wheelhouse = Join-Path $packageRoot "payload\wheelhouse"
    $requirements = Join-Path $packageRoot "payload\requirements.txt"
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "Packaged requirements.txt is missing."
    }

    foreach ($pythonVersion in $SupportedPythonVersions) {
        $abi = "cp" + $pythonVersion.Replace(".", "")
        Write-Host "Download Windows wheels for Python $pythonVersion ($abi)"
        & python -m pip download `
            --disable-pip-version-check `
            --dest $wheelhouse `
            --only-binary=:all: `
            --platform win_amd64 `
            --implementation cp `
            --python-version $pythonVersion `
            --abi $abi `
            -r $requirements
        Assert-LastExitCode "Offline wheel download failed for Python $pythonVersion."
    }

    foreach ($pythonVersion in $SupportedPythonVersions) {
        $tag = "cp" + $pythonVersion.Replace(".", "")
        foreach ($package in $BinaryPackages) {
            $match = Get-ChildItem -LiteralPath $wheelhouse -File | Where-Object {
                $_.Name -like "$package-*-$tag-$tag-win_amd64.whl"
            } | Select-Object -First 1
            if (-not $match) {
                throw "Missing $package wheel for Python $pythonVersion."
            }
        }
    }

    Write-Host "Patch deployment script for explicit UTF-8 parsing"
    $deployPath = Join-Path $packageRoot "Deploy-FullBugRepairSafe.ps1"
    $deployText = (Get-Content -LiteralPath $deployPath -Raw -Encoding UTF8).Replace("`r`n", "`n")

    $bootstrapAnchor = '    $bootstrapPython = Resolve-BootstrapPython -Root $ProjectRoot'
    if ([regex]::Matches($deployText, [regex]::Escape($bootstrapAnchor)).Count -ne 1) {
        throw "Bootstrap Python patch anchor was not unique."
    }
    $bootstrapReplacement = @'
    $bootstrapPython = Resolve-BootstrapPython -Root $ProjectRoot
    $bootstrapVersion = (& $bootstrapPython -c "import sys; print(str(sys.version_info[0]) + str(sys.version_info[1]))").Trim()
    if ($LASTEXITCODE -ne 0 -or $bootstrapVersion -notin @("311", "312", "313", "314")) {
        throw "Production Python must be 3.11, 3.12, 3.13, or 3.14 for this offline package."
    }
    Write-Host ("Candidate Python: {0} (Python {1}.{2})" -f $bootstrapPython, $bootstrapVersion.Substring(0, 1), $bootstrapVersion.Substring(1))
'@
    $deployText = $deployText.Replace($bootstrapAnchor, $bootstrapReplacement.TrimEnd())

    $parseFilePattern = '(?ms)(?<indent>^[ \t]*)\[System\.Management\.Automation\.Language\.Parser\]::ParseFile\(\s*\$file\.FullName,\s*\[ref\]\$tokens,\s*\[ref\]\$errors\s*\)\s*\|\s*Out-Null'
    $parseMatches = [regex]::Matches($deployText, $parseFilePattern)
    if ($parseMatches.Count -ne 1) {
        throw "Candidate PowerShell parser patch anchor count was $($parseMatches.Count), expected 1."
    }
    $parseMatch = $parseMatches[0]
    $indent = $parseMatch.Groups["indent"].Value
    $parseInputBlock = @(
        ('{0}$scriptText = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8' -f $indent),
        ('{0}[System.Management.Automation.Language.Parser]::ParseInput(' -f $indent),
        ('{0}    $scriptText,' -f $indent),
        ('{0}    $file.FullName,' -f $indent),
        ('{0}    [ref]$tokens,' -f $indent),
        ('{0}    [ref]$errors' -f $indent),
        ('{0}) | Out-Null' -f $indent)
    ) -join "`n"
    $deployText = $deployText.Substring(0, $parseMatch.Index) +
        $parseInputBlock +
        $deployText.Substring($parseMatch.Index + $parseMatch.Length)
    Write-Utf8NoBom -Path $deployPath -Text $deployText

    $syntaxCommand = @'
$tokens = $null
$errors = $null
$text = Get-Content -LiteralPath $env:DEPLOY_SCRIPT_PATH -Raw -Encoding UTF8
[System.Management.Automation.Language.Parser]::ParseInput(
    $text,
    $env:DEPLOY_SCRIPT_PATH,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors -and $errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_.Message }
    exit 1
}
'@
    $oldDeployPath = $env:DEPLOY_SCRIPT_PATH
    try {
        $env:DEPLOY_SCRIPT_PATH = $deployPath
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $syntaxCommand
        Assert-LastExitCode "Patched deployment script failed Windows PowerShell syntax validation."
    } finally {
        $env:DEPLOY_SCRIPT_PATH = $oldDeployPath
    }

    $manifestPath = Join-Path $packageRoot "manifest.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.package_id = "LOLAPI-FULL-BUG-REPAIR-SAFE-DEPLOY-$shortCommit-WINPS51-V3"
    $manifest.built_at = [DateTime]::UtcNow.ToString("o")
    $manifest.ci.python = "3.11, 3.12, 3.13, 3.14"
    $manifest.deployment | Add-Member -NotePropertyName supported_python_versions -NotePropertyValue $SupportedPythonVersions -Force
    $manifest.deployment | Add-Member -NotePropertyName bootstrap_python_version_logged -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName powershell_utf8_parse_input -NotePropertyValue $true -Force
    $manifest | Add-Member -NotePropertyName package_revision -NotePropertyValue 3 -Force

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
        supported_python_versions = $SupportedPythonVersions
        package_revision = 3
        powershell_utf8_parse_input = $true
    }
    $metadataPath = Join-Path $OutputRoot "$packageName.metadata.json"
    Write-Utf8NoBom -Path $metadataPath -Text (($metadata | ConvertTo-Json -Depth 10) + [Environment]::NewLine)

    Write-Host "V3 deployment package created successfully."
    Write-Host "ZIP: $finalZip"
    Write-Host "SHA256: $($metadata.zip_sha256)"
} finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
