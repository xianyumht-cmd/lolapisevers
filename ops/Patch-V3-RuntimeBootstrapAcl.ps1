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

function Replace-UniqueText {
    param(
        [string]$Text,
        [string]$Old,
        [string]$New,
        [string]$Label
    )
    $normalizedOld = $Old.Replace("`r`n", "`n")
    $normalizedNew = $New.Replace("`r`n", "`n")
    $count = [regex]::Matches($Text, [regex]::Escape($normalizedOld)).Count
    if ($count -ne 1) {
        throw "$Label patch anchor count was $count, expected 1."
    }
    return $Text.Replace($normalizedOld, $normalizedNew)
}

$DistRoot = [IO.Path]::GetFullPath($DistRoot)
$zipFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.zip" -File)
$metadataFiles = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.metadata.json" -File)
if ($zipFiles.Count -ne 1 -or $metadataFiles.Count -ne 1) {
    throw "Expected exactly one V3 ZIP and one metadata file."
}

$zipFile = $zipFiles[0]
$metadataFile = $metadataFiles[0]
$tempRoot = Join-Path $env:RUNNER_TEMP ("lol-v3-runtime-bootstrap-acl-" + [Guid]::NewGuid().ToString("N"))
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

    $oldResolver = @'
function Resolve-BootstrapPython {
    param([string]$Root)
    $productionPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $productionPython -PathType Leaf) {
        return $productionPython
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }
    return (Get-Command python.exe -ErrorAction Stop).Source
}
'@

    $newResolver = @'
function Resolve-BootstrapPython {
    param(
        [string]$Root,
        [string]$BaseUrl = ""
    )

    # Prefer the actual Python executable that owns the live HTTP listener.
    # This keeps candidate creation independent from the production .venv ACL.
    $listenerPort = 5001
    if ($BaseUrl) {
        try {
            $uri = [Uri]$BaseUrl
            if ($uri.Port -gt 0) {
                $listenerPort = [int]$uri.Port
            }
        } catch {
            Write-Warning "Unable to parse BaseUrl for bootstrap listener discovery; using port 5001."
        }
    }

    try {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $listenerPort -ErrorAction Stop)
        foreach ($listener in $listeners) {
            try {
                $listenerProcess = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$listener.OwningProcess) -ErrorAction Stop
                $listenerExecutable = "$($listenerProcess.ExecutablePath)".Trim()
                if ($listenerExecutable -and ([IO.Path]::GetFileName($listenerExecutable) -match '^(?i)pythonw?\.exe$')) {
                    Write-Host ("Bootstrap Python resolved from active listener PID {0}: {1}" -f $listener.OwningProcess, $listenerExecutable)
                    return $listenerExecutable
                }
            } catch {
                Write-Warning ("Unable to inspect listener PID {0} for bootstrap Python: {1}" -f $listener.OwningProcess, $_.Exception.Message)
            }
        }
    } catch {
        Write-Warning ("Unable to resolve bootstrap Python from active listener on port {0}: {1}" -f $listenerPort, $_.Exception.Message)
    }

    # Preserve the historical production-venv fallback, but ACL denial is not fatal.
    $productionPython = Join-Path $Root ".venv\Scripts\python.exe"
    try {
        $productionPythonItem = Get-Item -LiteralPath $productionPython -ErrorAction Stop
        if (-not $productionPythonItem.PSIsContainer) {
            return $productionPythonItem.FullName
        }
    } catch {
        Write-Warning ("Production venv bootstrap is not readable; continuing with system Python discovery: {0}" -f $_.Exception.Message)
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }

    throw "Unable to resolve a bootstrap Python interpreter without depending on the production .venv."
}
'@

    $deployText = Replace-UniqueText -Text $deployText -Old $oldResolver.TrimEnd() -New $newResolver.TrimEnd() -Label "Runtime bootstrap resolver"

    $oldCall = '    $bootstrapPython = Resolve-BootstrapPython -Root $ProjectRoot'
    $newCall = '    $bootstrapPython = Resolve-BootstrapPython -Root $ProjectRoot -BaseUrl $BaseUrl'
    $deployText = Replace-UniqueText -Text $deployText -Old $oldCall -New $newCall -Label "Runtime bootstrap call"

    foreach ($requiredMarker in @(
        'Get-NetTCPConnection -State Listen -LocalPort $listenerPort',
        'Get-CimInstance Win32_Process',
        'Production venv bootstrap is not readable; continuing with system Python discovery',
        'Resolve-BootstrapPython -Root $ProjectRoot -BaseUrl $BaseUrl'
    )) {
        if (-not $deployText.Contains($requiredMarker)) {
            throw "Runtime bootstrap ACL marker is missing: $requiredMarker"
        }
    }

    foreach ($forbiddenMarker in @(
        'if (Test-Path -LiteralPath $productionPython -PathType Leaf)',
        'Resolve-BootstrapPython -Root $ProjectRoot`n'
    )) {
        if ($deployText.Contains($forbiddenMarker)) {
            throw "Runtime bootstrap ACL unsafe marker remains: $forbiddenMarker"
        }
    }

    Write-Utf8NoBom -Path $deployPath -Text $deployText

    $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $deployEntry = @($manifest.files | Where-Object { "$($_.path)" -eq "Deploy-FullBugRepairSafe.ps1" })
    if ($deployEntry.Count -ne 1) {
        throw "Embedded manifest deployment entry was not unique."
    }

    $deployEntry[0].sha256 = Get-Sha256 $deployPath
    $deployEntry[0].bytes = [int64](Get-Item -LiteralPath $deployPath).Length
    $manifest.deployment | Add-Member -NotePropertyName runtime_bootstrap_acl_safe -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName runtime_listener_bootstrap_discovery -NotePropertyValue $true -Force

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
    $metadata | Add-Member -NotePropertyName runtime_bootstrap_acl_safe -NotePropertyValue $true -Force
    $metadata | Add-Member -NotePropertyName runtime_listener_bootstrap_discovery -NotePropertyValue $true -Force
    Write-Utf8NoBom -Path $metadataFile.FullName -Text (($metadata | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Write-Host "Patched V3 artifact for runtime bootstrap ACL safety."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
