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

$tempRoot = Join-Path $env:RUNNER_TEMP ("lol-v3-winps51-native-process-" + [Guid]::NewGuid().ToString("N"))
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

    $nativeHelperAnchor = 'function Invoke-CandidateTests {'
    $nativeHelper = @'
function Invoke-NativeProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = "",
        [switch]$AllowFailure,
        [switch]$Quiet
    )
    $quoted = @()
    foreach ($argument in $Arguments) {
        $value = "$argument"
        if ($value -match '[\r\n"]') {
            throw "Unsupported native process argument: $value"
        }
        if ($value.Length -eq 0) {
            $quoted += '""'
        } elseif ($value -match '\s') {
            $quoted += ('"' + $value + '"')
        } else {
            $quoted += $value
        }
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    if ($WorkingDirectory) {
        $startInfo.WorkingDirectory = $WorkingDirectory
    } else {
        $startInfo.WorkingDirectory = (Get-Location).Path
    }
    $startInfo.Arguments = ($quoted -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Failed to start native process: $FilePath"
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

    if (-not $Quiet) {
        if ($stdout) {
            Write-Host ($stdout.TrimEnd())
        }
        if ($stderr) {
            # Keep stderr in the deployment transcript without converting it to
            # a PowerShell ErrorRecord. WinPS 5.1 + ErrorActionPreference=Stop
            # otherwise treats benign Python/unittest warnings as fatal.
            Write-Host ($stderr.TrimEnd())
        }
    }

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "Native process failed with ExitCode=${exitCode}: $FilePath $($Arguments -join ' ')`n$stderr"
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $stdout
        Error = $stderr
    }
}

'@
    $deployText = Replace-UniqueText -Text $deployText -Old $nativeHelperAnchor -New ($nativeHelper + $nativeHelperAnchor) -Label "Native process helper"

    $old = @'
    & $BootstrapPython -m venv $CandidateVenv
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate virtual environment creation failed."
    }
'@
    $new = @'
    Invoke-NativeProcess -FilePath $BootstrapPython -Arguments @("-m", "venv", $CandidateVenv) | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate venv"

    $old = @'
    & $candidatePython -m pip install --disable-pip-version-check --no-index --find-links $Wheelhouse -r (Join-Path $CandidateRepository "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Offline candidate dependency installation failed."
    }
'@
    $new = @'
    Invoke-NativeProcess -FilePath $candidatePython -Arguments @(
        "-m", "pip", "install",
        "--disable-pip-version-check",
        "--no-index",
        "--find-links", $Wheelhouse,
        "-r", (Join-Path $CandidateRepository "requirements.txt")
    ) | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate pip install"

    $old = @'
    & $candidatePython -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate dependency consistency check failed."
    }
'@
    $new = @'
    Invoke-NativeProcess -FilePath $candidatePython -Arguments @("-m", "pip", "check") | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate pip check"

    $old = @'
        & $candidatePython -m compileall -q .
        if ($LASTEXITCODE -ne 0) {
            throw "Candidate Python compileall failed."
        }
'@
    $new = @'
        Invoke-NativeProcess -FilePath $candidatePython -Arguments @("-m", "compileall", "-q", ".") | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate compileall"

    $old = @'
        & $candidatePython -m unittest discover -s tests -p "test_*.py" -v
        if ($LASTEXITCODE -ne 0) {
            throw "Candidate full unit tests failed."
        }
'@
    $new = @'
        Invoke-NativeProcess -FilePath $candidatePython -Arguments @(
            "-m", "unittest", "discover",
            "-s", "tests",
            "-p", "test_*.py",
            "-v"
        ) | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate unit tests"

    $old = @'
        & $candidatePython tests\check_ui_assets.py
        if ($LASTEXITCODE -ne 0) {
            throw "Candidate WebUI generation failed."
        }
'@
    $new = @'
        Invoke-NativeProcess -FilePath $candidatePython -Arguments @("tests\check_ui_assets.py") | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate WebUI generation"

    $old = @'
            & $node.Source --check $generatedJs
            if ($LASTEXITCODE -ne 0) {
                throw "Candidate generated JavaScript syntax check failed."
            }
'@
    $new = @'
            Invoke-NativeProcess -FilePath $node.Source -Arguments @("--check", $generatedJs) | Out-Null
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Candidate Node syntax check"

    $old = @'
    $bootstrapVersion = (& $bootstrapPython -c "import sys; print(str(sys.version_info[0]) + str(sys.version_info[1]))").Trim()
    if ($LASTEXITCODE -ne 0 -or $bootstrapVersion -notin @("311", "312", "313", "314")) {
        throw "Production Python must be 3.11, 3.12, 3.13, or 3.14 for this offline package."
    }
'@
    $new = @'
    $bootstrapVersionResult = Invoke-NativeProcess -FilePath $bootstrapPython -Arguments @(
        "-c",
        "import sys; print(str(sys.version_info[0]) + str(sys.version_info[1]))"
    ) -Quiet
    $bootstrapVersion = $bootstrapVersionResult.Output.Trim()
    if ($bootstrapVersion -notin @("311", "312", "313", "314")) {
        throw "Production Python must be 3.11, 3.12, 3.13, or 3.14 for this offline package."
    }
'@
    $deployText = Replace-UniqueText -Text $deployText -Old $old.TrimEnd() -New $new.TrimEnd() -Label "Bootstrap Python version"

    foreach ($unsafeNative in @(
        '& $BootstrapPython -m venv',
        '& $candidatePython',
        '& $node.Source --check',
        '$bootstrapVersion = (& $bootstrapPython -c'
    )) {
        if ($deployText.Contains($unsafeNative)) {
            throw "Unsafe direct native invocation remains after patch: $unsafeNative"
        }
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
    $manifest.deployment | Add-Member -NotePropertyName winps51_native_process_stderr_safe -NotePropertyValue $true -Force

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
    $metadata | Add-Member -NotePropertyName winps51_native_process_stderr_safe -NotePropertyValue $true -Force
    Write-Utf8NoBom -Path $metadataFile.FullName -Text (($metadata | ConvertTo-Json -Depth 20) + [Environment]::NewLine)

    Write-Host "Patched V3 artifact for Windows PowerShell 5.1 native process stderr safety."
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
