param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedCommit,
    [string]$BundlePath = "",
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [string]$Hero = "Kalista",
    [ValidatePattern("^$|^[0-9]{5,11}$")]
    [string]$BanQQ = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-GitProcess {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $gitExe = (Get-Command git.exe -ErrorAction Stop).Source
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $gitExe
    $startInfo.WorkingDirectory = $WorkingDirectory
    $quoted = @()
    foreach ($argument in $Arguments) {
        $value = "$argument"
        if ($value.Contains('"')) {
            throw "Unsupported quote in Git argument."
        }
        if ($value -match '\s') {
            $value = '"' + $value + '"'
        }
        $quoted += $value
    }
    $startInfo.Arguments = $quoted -join " "
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Failed to start Git."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = "$($stdoutTask.Result)"
        $stderr = "$($stderrTask.Result)"
        $exitCode = [int]$process.ExitCode
    } finally {
        $process.Dispose()
    }

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "Git failed with exit code $exitCode`: $stderr"
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $stdout
        Error = $stderr
    }
}

function Assert-PowerShellSyntax {
    param([Parameter(Mandatory = $true)][string]$Path)
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $Path,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        $messages = @($errors | ForEach-Object { $_.Message }) -join [Environment]::NewLine
        throw "PowerShell syntax validation failed for $Path`n$messages"
    }
}

function Patch-WindowsPowerShellCompatibility {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet("deploy", "rollback")][string]$Kind
    )

    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::ASCII).Replace("`r`n", "`n")

    if ($Kind -eq "deploy") {
        $oldBlock = @'
function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $output = & git -C $ProjectRoot @Arguments 2>&1
    $code = $LASTEXITCODE
    if (-not $AllowFailure -and $code -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return [pscustomobject]@{ ExitCode = $code; Output = @($output) }
}
'@
    } else {
        $oldBlock = @'
function Invoke-Git {
    param([string[]]$Arguments)
    $output = & git -C $ProjectRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}
'@
    }

    $newBlock = @'
function Resolve-GitExecutable {
    $configured = "$($env:LAPI_GIT_EXE)".Trim()
    if ($configured) {
        if (-not (Test-Path -LiteralPath $configured -PathType Leaf)) {
            throw "Configured Git executable does not exist: $configured"
        }
        return (Resolve-Path -LiteralPath $configured).Path
    }
    return (Get-Command git.exe -ErrorAction Stop).Source
}

function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)

    foreach ($argument in $Arguments) {
        if ("$argument" -match '[\s"]') {
            throw "Unsupported whitespace or quote in Git argument: $argument"
        }
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = Resolve-GitExecutable
    $startInfo.WorkingDirectory = $ProjectRoot
    $startInfo.Arguments = ($Arguments -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Failed to start Git process."
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = "$($stdoutTask.Result)"
        $stderr = "$($stderrTask.Result)"
        $code = [int]$process.ExitCode
    } finally {
        $process.Dispose()
    }

    if (-not $AllowFailure -and $code -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $code`: $stderr"
    }
    return [pscustomobject]@{
        ExitCode = $code
        Output = $stdout
        Error = $stderr
    }
}
'@

    $oldBlock = $oldBlock.Replace("`r`n", "`n")
    $newBlock = $newBlock.Replace("`r`n", "`n")
    if ($text.IndexOf($oldBlock, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Expected Invoke-Git block was not found in $Path"
    }
    $text = $text.Replace($oldBlock, $newBlock)

    if ($Kind -eq "deploy") {
        $oldManifest = '    backup_items = @($backupItems)'
        $newManifest = '    backup_items = $backupItems.ToArray()'
        if ($text.IndexOf($oldManifest, [System.StringComparison]::Ordinal) -lt 0) {
            throw "Expected backup manifest conversion was not found in $Path"
        }
        $text = $text.Replace($oldManifest, $newManifest)

        $oldFetch = @'
Write-Output "Fetching release branch..."
Invoke-Git -Arguments @("fetch", "--no-tags", "origin", "release/lapi-query-hardening-20260729") | Out-Null
'@.Replace("`r`n", "`n")
        $newFetch = @'
Write-Output "Using imported offline release commit..."
'@.Replace("`r`n", "`n")
        if ($text.IndexOf($oldFetch, [System.StringComparison]::Ordinal) -lt 0) {
            throw "Expected online fetch block was not found in $Path"
        }
        $text = $text.Replace($oldFetch, $newFetch)
    }

    [System.IO.File]::WriteAllText($Path, $text, [System.Text.Encoding]::ASCII)
}

function Find-DeploymentBackup {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Commit
    )
    $parent = Split-Path -Parent $Root
    $leaf = Split-Path -Leaf $Root
    $backupRoot = Join-Path $parent "$leaf.deploy-backups"
    if (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) {
        throw "Deployment backup root was not created: $backupRoot"
    }
    foreach ($recordPath in @(Get-ChildItem -LiteralPath $backupRoot -Filter "deployment-record.json" -File -Recurse | Sort-Object LastWriteTimeUtc -Descending)) {
        try {
            $record = Get-Content -LiteralPath $recordPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ("$($record.target_commit)".ToLowerInvariant() -eq $Commit -and "$($record.status)" -eq "completed") {
                return $recordPath.Directory.FullName
            }
        } catch {
        }
    }
    throw "Completed deployment record for $Commit was not found."
}

function Invoke-DeploymentRollback {
    param(
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url
    )
    $rollbackPath = Join-Path $BackupDirectory "Rollback-LapiQueryHardening.ps1"
    if (-not (Test-Path -LiteralPath $rollbackPath -PathType Leaf)) {
        throw "Rollback script is missing from backup: $rollbackPath"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rollbackPath `
        -ProjectRoot $Root `
        -BackupDirectory $BackupDirectory `
        -ServiceName $Name `
        -BaseUrl $Url
    if ($LASTEXITCODE -ne 0) {
        throw "Automatic rollback failed. Keep backup directory: $BackupDirectory"
    }
}

if (-not (Test-Administrator)) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $PSCommandPath + '"'),
        "-ProjectRoot", ('"' + $ProjectRoot + '"'),
        "-ExpectedCommit", $ExpectedCommit,
        "-ServiceName", $ServiceName,
        "-BaseUrl", $BaseUrl,
        "-Hero", $Hero
    )
    if ($BundlePath) {
        $arguments += @("-BundlePath", ('"' + $BundlePath + '"'))
    }
    if ($BanQQ) {
        $arguments += @("-BanQQ", $BanQQ)
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList ($arguments -join " ")
    exit
}

$ExpectedCommit = $ExpectedCommit.ToLowerInvariant()
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BaseUrl = $BaseUrl.TrimEnd("/")
if (-not $BundlePath) {
    $BundlePath = Join-Path $PSScriptRoot "lapi-video-free-offline.bundle"
}
$BundlePath = (Resolve-Path -LiteralPath $BundlePath).Path
$manifestPath = Join-Path $PSScriptRoot "PACKAGE-MANIFEST.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Package manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ("$($manifest.schema)" -ne "lapi-video-free-offline-deploy.v1") {
    throw "Unsupported package manifest schema."
}
if ("$($manifest.target_commit)".ToLowerInvariant() -ne $ExpectedCommit) {
    throw "Package target commit mismatch."
}
$bundleHash = (Get-FileHash -LiteralPath $BundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($bundleHash -ne "$($manifest.bundle_sha256)".ToLowerInvariant()) {
    throw "Offline bundle SHA-256 mismatch."
}

$remoteUrl = (Invoke-GitProcess -WorkingDirectory $ProjectRoot -Arguments @("remote", "get-url", "origin")).Output.Trim()
if ($remoteUrl -notmatch "github\.com[/:]xianyumht-cmd/lolapisevers(?:\.git)?$") {
    throw "origin is not the expected repository: $remoteUrl"
}
$dirty = (Invoke-GitProcess -WorkingDirectory $ProjectRoot -Arguments @("status", "--porcelain", "--untracked-files=no")).Output.Trim()
if ($dirty) {
    throw "Tracked files have local changes. Deployment stopped."
}

Write-Output "Importing fixed video-free release commit from offline Git bundle..."
Invoke-GitProcess -WorkingDirectory $ProjectRoot -Arguments @(
    "fetch",
    $BundlePath,
    "refs/heads/lapi-video-free-target:refs/remotes/offline/lapi-video-free-target"
) | Out-Null
$resolved = (Invoke-GitProcess -WorkingDirectory $ProjectRoot -Arguments @("rev-parse", "refs/remotes/offline/lapi-video-free-target^{commit}")).Output.Trim().ToLowerInvariant()
if ($resolved -ne $ExpectedCommit) {
    throw "Imported commit mismatch: expected=$ExpectedCommit actual=$resolved"
}

$tempRoot = Join-Path $env:TEMP "lapi-video-free-$($ExpectedCommit.Substring(0, 12))"
if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$archivePath = Join-Path $tempRoot "release-scripts.zip"
Invoke-GitProcess -WorkingDirectory $ProjectRoot -Arguments @(
    "archive",
    "--format=zip",
    "--output=$archivePath",
    $ExpectedCommit,
    "ops/Deploy-LapiQueryHardening.ps1",
    "ops/Rollback-LapiQueryHardening.ps1",
    "ops/Test-LapiQueryHardening.ps1",
    "ops/remove-retired-video-provider-config.ps1"
) | Out-Null

$extractRoot = Join-Path $tempRoot "extracted"
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force
$deployPath = Join-Path $extractRoot "ops\Deploy-LapiQueryHardening.ps1"
$rollbackPath = Join-Path $extractRoot "ops\Rollback-LapiQueryHardening.ps1"
$verifyPath = Join-Path $extractRoot "ops\Test-LapiQueryHardening.ps1"
$cleanupPath = Join-Path $extractRoot "ops\remove-retired-video-provider-config.ps1"
foreach ($required in @($deployPath, $rollbackPath, $verifyPath, $cleanupPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Pinned release script is missing: $required"
    }
}

Patch-WindowsPowerShellCompatibility -Path $deployPath -Kind "deploy"
Patch-WindowsPowerShellCompatibility -Path $rollbackPath -Kind "rollback"
foreach ($scriptPath in @($deployPath, $rollbackPath, $verifyPath, $cleanupPath)) {
    Assert-PowerShellSyntax -Path $scriptPath
}

Write-Output "Running candidate tests and safe deployment before retiring video configuration..."
$deployArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $deployPath,
    "-ProjectRoot", $ProjectRoot,
    "-TargetRef", $ExpectedCommit,
    "-ExpectedCommit", $ExpectedCommit,
    "-ServiceName", $ServiceName,
    "-BaseUrl", $BaseUrl,
    "-Hero", $Hero
)
if ($BanQQ) {
    $deployArgs += @("-BanQQ", $BanQQ)
}
& powershell.exe @deployArgs
if ($LASTEXITCODE -ne 0) {
    throw "Video-free service deployment failed."
}

$backupDirectory = Find-DeploymentBackup -Root $ProjectRoot -Commit $ExpectedCommit
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleanupPath `
        -ProjectRoot $ProjectRoot `
        -ServiceName $ServiceName
    if ($LASTEXITCODE -ne 0) {
        throw "Retired video provider cleanup returned exit code $LASTEXITCODE."
    }

    $videoBody = @{
        feature = "video"
        parameters = @{ category = "popular" }
        preferred = "text"
        capabilities = @{ text = $true; image = $false; forward = $false }
        request_id = "video-retired-$([Guid]::NewGuid().ToString('N'))"
        client = "windows-offline-deploy"
    } | ConvertTo-Json -Depth 8
    try {
        Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/groupguard/query" -ContentType "application/json" -Body $videoBody -TimeoutSec 15 | Out-Null
        throw "Retired video feature unexpectedly returned success."
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response -or [int]$response.StatusCode -ne 400) {
            throw "Retired video feature did not return expected HTTP 400."
        }
    }
} catch {
    $cleanupFailure = $_.Exception.Message
    Write-Warning "Post-deployment video retirement validation failed: $cleanupFailure"
    Write-Warning "Rolling back the full service deployment."
    Invoke-DeploymentRollback -BackupDirectory $backupDirectory -Root $ProjectRoot -Name $ServiceName -Url $BaseUrl
    throw "Video-free deployment was rolled back: $cleanupFailure"
}

Write-Output "============================================================"
Write-Output "LOLDataSystem VIDEO-FREE offline deployment completed successfully."
Write-Output "Commit : $ExpectedCommit"
Write-Output "Service: $ServiceName"
Write-Output "Backup : $backupDirectory"
Write-Output "Video  : retired and provider configuration removed"
Write-Output "============================================================"
