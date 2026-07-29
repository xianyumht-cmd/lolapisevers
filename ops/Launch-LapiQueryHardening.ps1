param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedCommit,
    [string]$ReleaseBranch = "release/lapi-query-hardening-20260729",
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [string]$Hero = "Yasuo",
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

function Assert-PowerShellSyntax {
    param([string]$Path)
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

function Patch-WindowsPowerShellGitStderr {
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
        $newBlock = @'
function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $ProjectRoot @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
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
        $newBlock = @'
function Invoke-Git {
    param([string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $ProjectRoot @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($code -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}
'@
    }

    $oldBlock = $oldBlock.Replace("`r`n", "`n")
    $newBlock = $newBlock.Replace("`r`n", "`n")
    if ($text.IndexOf($oldBlock, [System.StringComparison]::Ordinal) -lt 0) {
        throw "Expected Invoke-Git block was not found in $Path"
    }

    $patched = $text.Replace($oldBlock, $newBlock)
    [System.IO.File]::WriteAllText($Path, $patched, [System.Text.Encoding]::ASCII)
}

if (-not (Test-Administrator)) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"' + $PSCommandPath + '"'),
        "-ProjectRoot", ('"' + $ProjectRoot + '"'),
        "-ExpectedCommit", $ExpectedCommit,
        "-ReleaseBranch", $ReleaseBranch,
        "-ServiceName", $ServiceName,
        "-BaseUrl", $BaseUrl,
        "-Hero", $Hero
    )
    if ($BanQQ) {
        $arguments += @("-BanQQ", $BanQQ)
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList ($arguments -join " ")
    exit
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$ExpectedCommit = $ExpectedCommit.ToLowerInvariant()
$gitExe = (Get-Command git -ErrorAction Stop).Source

& $gitExe -C $ProjectRoot fetch --no-tags origin $ReleaseBranch
if ($LASTEXITCODE -ne 0) {
    throw "Failed to fetch release branch."
}

& $gitExe -C $ProjectRoot cat-file -e "$ExpectedCommit`^{commit}"
if ($LASTEXITCODE -ne 0) {
    throw "Pinned release commit is not available locally: $ExpectedCommit"
}

& $gitExe -C $ProjectRoot merge-base --is-ancestor $ExpectedCommit "origin/$ReleaseBranch"
if ($LASTEXITCODE -ne 0) {
    throw "Pinned release commit is not contained in the remote release branch."
}

$tempRoot = Join-Path $env:TEMP "lapi-query-hardening-$($ExpectedCommit.Substring(0, 12))"
if (Test-Path -LiteralPath $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

$archivePath = Join-Path $tempRoot "release-scripts.zip"
& $gitExe -C $ProjectRoot archive `
    --format=zip `
    --output=$archivePath `
    $ExpectedCommit `
    ops/Deploy-LapiQueryHardening.ps1 `
    ops/Rollback-LapiQueryHardening.ps1 `
    ops/Test-LapiQueryHardening.ps1
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Failed to export pinned release scripts with git archive."
}

$extractRoot = Join-Path $tempRoot "extracted"
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force

$deployScript = Join-Path $extractRoot "ops\Deploy-LapiQueryHardening.ps1"
$rollbackScript = Join-Path $extractRoot "ops\Rollback-LapiQueryHardening.ps1"
$verifyScript = Join-Path $extractRoot "ops\Test-LapiQueryHardening.ps1"
foreach ($scriptPath in @($deployScript, $rollbackScript, $verifyScript)) {
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Pinned release script is missing: $scriptPath"
    }
    $bytes = [System.IO.File]::ReadAllBytes($scriptPath)
    if (@($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) {
        throw "Release script is not ASCII-safe: $scriptPath"
    }
}

Patch-WindowsPowerShellGitStderr -Path $deployScript -Kind "deploy"
Patch-WindowsPowerShellGitStderr -Path $rollbackScript -Kind "rollback"
foreach ($scriptPath in @($deployScript, $rollbackScript, $verifyScript)) {
    Assert-PowerShellSyntax -Path $scriptPath
}

$deployArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $deployScript,
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
exit $LASTEXITCODE
