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
    if ($count -ne 1) {
        throw "$Label patch anchor count was $count, expected 1."
    }
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
$tempRoot = Join-Path $env:RUNNER_TEMP ("lol-v3-groupguard-probe-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $zipFile.FullName -DestinationPath $tempRoot -Force
    $manifestFiles = @(Get-ChildItem -LiteralPath $tempRoot -Filter "manifest.json" -File -Recurse)
    if ($manifestFiles.Count -ne 1) {
        throw "Expected exactly one embedded manifest."
    }
    $manifestFile = $manifestFiles[0]
    $packageRoot = $manifestFile.Directory.FullName
    $verifyPath = Join-Path $packageRoot "Verify-FullBugRepairProduction.ps1"
    if (-not (Test-Path -LiteralPath $verifyPath -PathType Leaf)) {
        throw "Packaged production verifier is missing."
    }
    $verifyText = (Get-Content -LiteralPath $verifyPath -Raw -Encoding UTF8).Replace("`r`n", "`n")

    # Only the GroupGuard functional request is changed. Health, build-info,
    # source-integrity checks and rollback stay strict and independent.
    $helperAnchor = 'function Assert-True {'
    $helper = @'
function Invoke-VerifiedGroupGuardRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][object]$Body,
        [Parameter(Mandatory = $true)][string]$Feature,
        [int]$MaxAttempts = 4,
        [int]$TimeoutSeconds = 20
    )
    if ($MaxAttempts -lt 1 -or $MaxAttempts -gt 4) {
        throw "GroupGuard probe attempts must be between 1 and 4."
    }
    $payloadBytes = [Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $Body -Depth 10 -Compress)
    )
    $started = [Diagnostics.Stopwatch]::StartNew()
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $statusCode = 0
        $errorClass = ""
        $transient = $false
        try {
            $response = Invoke-WebRequest -Uri $Uri -Method POST `
                -TimeoutSec $TimeoutSeconds -UseBasicParsing `
                -DisableKeepAlive -Headers @{ Accept = "application/json" } `
                -ContentType "application/json; charset=utf-8" -Body $payloadBytes
            $statusCode = [int]$response.StatusCode
            if ($statusCode -ne 200) {
                throw "GroupGuard returned unexpected HTTP status $statusCode."
            }
            # HTTP success is insufficient: validate actual delivery data.
            $json = ConvertFrom-Json -InputObject $response.Content -ErrorAction Stop
            if (
                "$($json.protocol)" -ne "groupguard-query-delivery.v1" -or
                $json.ok -ne $true -or
                @($json.delivery.segments).Count -lt 1
            ) {
                throw "GroupGuard delivery envelope is invalid."
            }
            Write-Host ("GroupGuard verified feature={0} attempt={1} elapsed_ms={2}" -f `
                $Feature, $attempt, $started.ElapsedMilliseconds)
            return [pscustomobject]@{ StatusCode = $statusCode; Body = $json }
        } catch {
            $exception = $_.Exception
            $errorClass = $exception.GetType().Name
            if ($exception -is [System.Net.WebException]) {
                $webStatus = $exception.Status.ToString()
                if ($null -ne $exception.Response) {
                    $httpResponse = $exception.Response
                    if ($null -ne $httpResponse.StatusCode) {
                        $statusCode = [int]$httpResponse.StatusCode
                    }
                }
                $transient = ($statusCode -in @(429, 502, 503, 504) -or
                    $webStatus -in @(
                        "ConnectFailure", "ReceiveFailure", "KeepAliveFailure",
                        "ConnectionClosed", "Timeout", "SendFailure"
                    ))
            }
            $listenerPid = "missing"
            try {
                $port = ([uri]$Uri).Port
                $listener = @(Get-NetTCPConnection -State Listen -LocalPort $port `
                    -ErrorAction Stop | Select-Object -First 1)
                if ($listener.Count -gt 0) {
                    $listenerPid = "$($listener[0].OwningProcess)"
                }
            } catch {
                $listenerPid = "unknown"
            }
            Write-Warning ("GroupGuard probe feature={0} attempt={1}/{2} http={3} error_class={4} listener_pid={5} elapsed_ms={6} retryable={7}" -f `
                $Feature, $attempt, $MaxAttempts, $statusCode, $errorClass,
                $listenerPid, $started.ElapsedMilliseconds, $transient)
            if (-not $transient -or $attempt -ge $MaxAttempts) {
                throw ("GroupGuard production verification failed feature={0} http={1} error_class={2} attempts={3}" -f `
                    $Feature, $statusCode, $errorClass, $attempt)
            }
            Start-Sleep -Seconds ([Math]::Min(6, 2 * $attempt))
        }
    }
    throw "GroupGuard probe exceeded its bounded attempts."
}

'@
    $verifyText = Replace-UniqueText -Text $verifyText -Old $helperAnchor `
        -New ($helper + $helperAnchor) -Label "GroupGuard bounded verifier helper"

    $oldCall = '$result = Invoke-JsonRequest -Uri "$BaseUrl/api/v1/groupguard/query" -Method POST -Body $payload'
    $newCall = '$result = Invoke-VerifiedGroupGuardRequest -Uri "$BaseUrl/api/v1/groupguard/query" -Body $payload -Feature $feature'
    $verifyText = Replace-UniqueText -Text $verifyText -Old $oldCall -New $newCall `
        -Label "GroupGuard query replacement"

    foreach ($required in @(
        'function Invoke-VerifiedGroupGuardRequest {',
        '-DisableKeepAlive',
        'listener_pid=',
        'GroupGuard production verification failed',
        'groupguard-query-delivery.v1',
        'Assert-True ($result.Body.protocol -eq "groupguard-query-delivery.v1")',
        'Assert-True ($result.Body.ok -eq $true)',
        'Assert-True (@($result.Body.delivery.segments).Count -ge 1)',
        'Add-Check "delivery_$feature"'
    )) {
        if (-not $verifyText.Contains($required)) {
            throw "Required GroupGuard verification marker missing: $required"
        }
    }

    Write-Utf8NoBom -Path $verifyPath -Text $verifyText
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseInput(
        $verifyText, $verifyPath, [ref]$tokens, [ref]$parseErrors
    ) | Out-Null
    if ($parseErrors -and $parseErrors.Count -gt 0) {
        throw "Patched GroupGuard verifier failed Windows PowerShell parsing: $($parseErrors[0].Message)"
    }

    $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $entries = @($manifest.files | Where-Object { "$($_.path)" -eq "Verify-FullBugRepairProduction.ps1" })
    if ($entries.Count -ne 1) {
        throw "Embedded manifest verifier entry was not unique."
    }
    $entries[0].sha256 = Get-Sha256 $verifyPath
    $entries[0].bytes = [int64](Get-Item -LiteralPath $verifyPath).Length
    $manifest.deployment | Add-Member -NotePropertyName groupguard_bounded_probe -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName groupguard_fresh_connection -NotePropertyValue $true -Force
    $manifest.deployment | Add-Member -NotePropertyName groupguard_probe_diagnostics -NotePropertyValue $true -Force

    $manifestEntries = @($manifest.files | Sort-Object path)
    $contentLines = ($manifestEntries | ForEach-Object {
        "$($_.path)`t$($_.sha256)`t$($_.bytes)"
    }) -join "`n"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $contentDigest = ([BitConverter]::ToString(
            $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($contentLines))
        )).Replace("-", "").ToLowerInvariant()
    } finally { $sha256.Dispose() }
    $manifest.package_content_sha256 = $contentDigest
    Write-Utf8NoBom -Path $manifestFile.FullName -Text (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Remove-Item -LiteralPath $zipFile.FullName -Force
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipFile.FullName -CompressionLevel Optimal -Force

    $metadata = Get-Content -LiteralPath $metadataFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $metadata.zip_sha256 = Get-Sha256 $zipFile.FullName
    $metadata.bytes = [int64](Get-Item -LiteralPath $zipFile.FullName).Length
    $metadata.package_content_sha256 = $contentDigest
    $metadata | Add-Member -NotePropertyName groupguard_bounded_probe -NotePropertyValue $true -Force
    $metadata | Add-Member -NotePropertyName groupguard_fresh_connection -NotePropertyValue $true -Force
    $metadata | Add-Member -NotePropertyName groupguard_probe_diagnostics -NotePropertyValue $true -Force
    Write-Utf8NoBom -Path $metadataFile.FullName -Text (($metadata | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
    Write-Host "Patched V3 artifact for bounded and diagnosed GroupGuard functional verification."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
