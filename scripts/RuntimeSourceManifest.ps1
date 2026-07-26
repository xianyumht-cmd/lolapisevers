$ErrorActionPreference = "Stop"

function Invoke-ManifestGit {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& git -C $RepositoryRoot @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $detail = ($output | Select-Object -First 5) -join [Environment]::NewLine
        throw "Git command failed while preparing the runtime source manifest: $detail"
    }
    return @($output | ForEach-Object { "$_" })
}

function Sort-Ordinal {
    param([string[]]$Values)

    $copy = [string[]]@($Values)
    [Array]::Sort($copy, [StringComparer]::Ordinal)
    return $copy
}

function Get-RuntimeSourcePaths {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $topLevelFiles = @(
        "app.py",
        "cache.py",
        "db.py",
        "requirements.txt",
        "so1_client.py",
        "ops/run_service.ps1",
        "scripts/RuntimeSourceManifest.ps1"
    )
    $runtimePrefixes = @(
        "core/",
        "lanzou_update_push_api_server/",
        "renderers/",
        "routers/",
        "services/"
    )
    $runtimeExtensions = @(".py", ".json")

    $tracked = Invoke-ManifestGit -RepositoryRoot $RepositoryRoot -Arguments @("ls-files")
    $selected = foreach ($rawPath in $tracked) {
        $relativePath = "$rawPath".Replace("\", "/")
        if ($topLevelFiles -contains $relativePath) {
            $relativePath
            continue
        }

        $hasRuntimePrefix = $false
        foreach ($prefix in $runtimePrefixes) {
            if ($relativePath.StartsWith($prefix, [StringComparison]::Ordinal)) {
                $hasRuntimePrefix = $true
                break
            }
        }
        if (-not $hasRuntimePrefix) {
            continue
        }

        $extension = [IO.Path]::GetExtension($relativePath).ToLowerInvariant()
        if ($runtimeExtensions -contains $extension) {
            $relativePath
        }
    }

    $paths = Sort-Ordinal -Values @($selected | Select-Object -Unique)
    if ($paths.Count -eq 0) {
        throw "No tracked runtime source files were found."
    }
    return $paths
}

function Get-UntrackedExecutableSourcePaths {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot)

    $executableExtensions = @(
        ".bat", ".bash", ".cjs", ".cmd", ".dll", ".exe", ".js", ".mjs",
        ".ps1", ".psd1", ".psm1", ".py", ".pyd", ".pyw", ".sh", ".so",
        ".ts", ".tsx", ".vbs", ".zsh"
    )
    $executableNames = @("Dockerfile")
    $untracked = Invoke-ManifestGit -RepositoryRoot $RepositoryRoot -Arguments @(
        "ls-files",
        "--others",
        "--exclude-standard"
    )
    $selected = foreach ($rawPath in $untracked) {
        $relativePath = "$rawPath".Replace("\", "/")
        $extension = [IO.Path]::GetExtension($relativePath).ToLowerInvariant()
        if (
            $executableExtensions -contains $extension -or
            $executableNames -contains [IO.Path]::GetFileName($relativePath)
        ) {
            $relativePath
        }
    }
    return Sort-Ordinal -Values @($selected | Select-Object -Unique)
}

function Get-RuntimeTrackedChanges {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string[]]$RuntimePaths
    )

    $arguments = @("status", "--porcelain", "--untracked-files=no", "--")
    $arguments += $RuntimePaths
    return Invoke-ManifestGit -RepositoryRoot $RepositoryRoot -Arguments $arguments
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($Bytes)
    } finally {
        $sha256.Dispose()
    }
    return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
}

function New-RuntimeSourceManifest {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [switch]$AllowTrackedRuntimeChanges
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
    $runtimePaths = @(Get-RuntimeSourcePaths -RepositoryRoot $resolvedRoot)
    $untrackedExecutableSources = @(
        Get-UntrackedExecutableSourcePaths -RepositoryRoot $resolvedRoot
    )
    if ($untrackedExecutableSources.Count -gt 0) {
        throw "Untracked executable source files are not allowed in a release: $($untrackedExecutableSources -join ', ')"
    }

    $trackedChanges = @(
        Get-RuntimeTrackedChanges -RepositoryRoot $resolvedRoot -RuntimePaths $runtimePaths
    )
    if ($trackedChanges.Count -gt 0 -and -not $AllowTrackedRuntimeChanges) {
        throw "Tracked runtime source files are dirty. Commit the runtime changes before generating release metadata."
    }

    $entries = foreach ($relativePath in $runtimePaths) {
        $nativePath = $relativePath.Replace("/", [IO.Path]::DirectorySeparatorChar)
        $absolutePath = Join-Path $resolvedRoot $nativePath
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "Tracked runtime source file is missing: $relativePath"
        }
        [pscustomobject][ordered]@{
            path = $relativePath
            sha256 = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
            size_bytes = (Get-Item -LiteralPath $absolutePath).Length
        }
    }

    $aggregateText = ($entries | ForEach-Object {
        "$($_.path)`0$($_.sha256)`0$($_.size_bytes)`n"
    }) -join ""
    $aggregateBytes = [Text.UTF8Encoding]::new($false).GetBytes($aggregateText)

    return [pscustomobject][ordered]@{
        algorithm = "sha256"
        aggregate_sha256 = Get-Sha256Hex -Bytes $aggregateBytes
        file_count = @($entries).Count
        files = @($entries)
        tracked_runtime_dirty = $trackedChanges.Count -gt 0
    }
}

function Assert-RuntimeSourceManifest {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)]$ExpectedManifest
    )

    if ("$($ExpectedManifest.algorithm)" -ne "sha256") {
        throw "Runtime source manifest algorithm must be sha256."
    }
    if ("$($ExpectedManifest.aggregate_sha256)" -notmatch "^[0-9a-fA-F]{64}$") {
        throw "Runtime source manifest aggregate_sha256 is missing or invalid."
    }
    if ($ExpectedManifest.tracked_runtime_dirty -ne $false) {
        throw "Runtime source manifest is dirty or unverified."
    }

    $expectedEntries = @($ExpectedManifest.files)
    if ($expectedEntries.Count -eq 0 -or [int]$ExpectedManifest.file_count -ne $expectedEntries.Count) {
        throw "Runtime source manifest file list is empty or inconsistent."
    }

    # Validation is content-based. A docs-only commit (or harmless Git metadata
    # change) must not invalidate a release whose runtime bytes are unchanged.
    $current = New-RuntimeSourceManifest `
        -RepositoryRoot $RepositoryRoot `
        -AllowTrackedRuntimeChanges
    if (
        $current.file_count -eq [int]$ExpectedManifest.file_count -and
        $current.aggregate_sha256 -eq "$($ExpectedManifest.aggregate_sha256)".ToLowerInvariant()
    ) {
        return $current
    }

    $expectedByPath = @{}
    foreach ($entry in $expectedEntries) {
        $path = "$($entry.path)".Replace("\", "/")
        $hash = "$($entry.sha256)".ToLowerInvariant()
        if (-not $path -or $hash -notmatch "^[0-9a-f]{64}$" -or $expectedByPath.ContainsKey($path)) {
            throw "Runtime source manifest contains an invalid or duplicate file entry."
        }
        $expectedByPath[$path] = "$hash|$($entry.size_bytes)"
    }
    $currentByPath = @{}
    foreach ($entry in @($current.files)) {
        $currentByPath["$($entry.path)"] = "$($entry.sha256)|$($entry.size_bytes)"
    }
    $allPaths = Sort-Ordinal -Values @(
        @($expectedByPath.Keys) + @($currentByPath.Keys) | Select-Object -Unique
    )
    foreach ($path in $allPaths) {
        if (
            -not $expectedByPath.ContainsKey($path) -or
            -not $currentByPath.ContainsKey($path) -or
            $expectedByPath[$path] -ne $currentByPath[$path]
        ) {
            throw "Runtime source manifest mismatch: $path"
        }
    }
    throw "Runtime source manifest aggregate does not match the deployed files."
}
