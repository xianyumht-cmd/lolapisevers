function Get-LolDataStartupDirectories {
    [CmdletBinding()]
    param()

    $paths = New-Object System.Collections.Generic.List[string]

    foreach ($specialFolder in @(
        [Environment+SpecialFolder]::Startup,
        [Environment+SpecialFolder]::CommonStartup
    )) {
        try {
            $path = [Environment]::GetFolderPath($specialFolder)
            if (-not [string]::IsNullOrWhiteSpace($path)) {
                $paths.Add($path)
            }
        } catch {}
    }

    try {
        Get-CimInstance Win32_UserProfile -ErrorAction Stop | Where-Object {
            $_.LocalPath -and -not $_.Special
        } | ForEach-Object {
            $candidate = Join-Path ([string]$_.LocalPath) "AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
            $paths.Add($candidate)
        }
    } catch {}

    return @(
        $paths |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique |
            Where-Object { Test-Path -LiteralPath $_ -PathType Container }
    )
}

function Get-LolDataLegacyStartupEntries {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )

    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $legacyNeedles = @(
        [IO.Path]::GetFullPath((Join-Path $root "start_hidden.vbs")),
        [IO.Path]::GetFullPath((Join-Path $root "run_server.bat")),
        [IO.Path]::GetFullPath((Join-Path $root "ops\run_service.ps1"))
    )

    $shell = $null
    try {
        $shell = New-Object -ComObject WScript.Shell
    } catch {}

    foreach ($startupDir in @(Get-LolDataStartupDirectories)) {
        foreach ($item in @(Get-ChildItem -LiteralPath $startupDir -Force -File -ErrorAction SilentlyContinue)) {
            $targetPath = ""
            $arguments = ""
            $matchedValue = ""
            $kind = ""

            if ($item.Extension -ieq ".lnk" -and $null -ne $shell) {
                try {
                    $shortcut = $shell.CreateShortcut($item.FullName)
                    $targetPath = [Environment]::ExpandEnvironmentVariables([string]$shortcut.TargetPath)
                    $arguments = [Environment]::ExpandEnvironmentVariables([string]$shortcut.Arguments)
                    $combined = "$targetPath`n$arguments"
                    foreach ($needle in $legacyNeedles) {
                        if ($combined.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                            $matchedValue = $needle
                            $kind = "shortcut"
                            break
                        }
                    }
                } catch {}
            } elseif ($item.Extension -in @(".vbs", ".bat", ".cmd", ".ps1")) {
                try {
                    $raw = Get-Content -LiteralPath $item.FullName -Raw -ErrorAction Stop
                    foreach ($needle in $legacyNeedles) {
                        if ($raw.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                            $raw.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                            $matchedValue = $needle
                            $kind = "script"
                            break
                        }
                    }
                } catch {}
            }

            if (-not [string]::IsNullOrWhiteSpace($matchedValue)) {
                [pscustomobject]@{
                    EntryPath = $item.FullName
                    StartupDirectory = $startupDir
                    Kind = $kind
                    TargetPath = $targetPath
                    Arguments = $arguments
                    MatchedValue = $matchedValue
                }
            }
        }
    }
}

function Get-LolDataSupervisorProcesses {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$ServiceName = "LOLDataSystem"
    )

    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $runScript = [IO.Path]::GetFullPath((Join-Path $root "ops\run_service.ps1"))
    $serviceProcessId = 0

    try {
        $service = Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {
            $_.Name -eq $ServiceName
        } | Select-Object -First 1
        if ($service) {
            $serviceProcessId = [int]$service.ProcessId
        }
    } catch {}

    $processes = @()
    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.Name -in @("powershell.exe", "pwsh.exe") -and
            $_.CommandLine -and
            ([string]$_.CommandLine).IndexOf($runScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
    } catch {}

    foreach ($process in $processes) {
        $parent = $null
        try {
            $parent = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$process.ParentProcessId) -ErrorAction Stop
        } catch {}

        [pscustomobject]@{
            ProcessId = [int]$process.ProcessId
            ParentProcessId = [int]$process.ParentProcessId
            ParentName = if ($parent) { [string]$parent.Name } else { "" }
            ParentCommandLine = if ($parent) { [string]$parent.CommandLine } else { "" }
            CommandLine = [string]$process.CommandLine
            ExecutablePath = [string]$process.ExecutablePath
            ServiceProcessId = $serviceProcessId
            IsServiceChild = ($serviceProcessId -gt 0 -and [int]$process.ParentProcessId -eq $serviceProcessId)
        }
    }
}

function Restore-LolDataLegacyStartupEntries {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object[]]$RetiredEntries
    )

    foreach ($entry in @($RetiredEntries)) {
        $backupPath = [string]$entry.BackupPath
        $originalPath = [string]$entry.OriginalPath
        if ([string]::IsNullOrWhiteSpace($backupPath) -or [string]::IsNullOrWhiteSpace($originalPath)) {
            continue
        }
        if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
            continue
        }
        if (Test-Path -LiteralPath $originalPath) {
            Write-Warning "Legacy startup restore skipped because destination already exists: $originalPath"
            continue
        }

        $destinationDirectory = Split-Path -Parent $originalPath
        if (-not (Test-Path -LiteralPath $destinationDirectory -PathType Container)) {
            New-Item -Path $destinationDirectory -ItemType Directory -Force | Out-Null
        }
        Move-Item -LiteralPath $backupPath -Destination $originalPath -Force -ErrorAction Stop
        Write-Output "Restored legacy startup entry: $originalPath"
    }
}

function Move-LolDataLegacyStartupEntries {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )

    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $entries = @(Get-LolDataLegacyStartupEntries -ProjectRoot $root)
    if ($entries.Count -eq 0) {
        return
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = Join-Path $root ("logs\retired-startup\" + $stamp)
    New-Item -Path $backupDir -ItemType Directory -Force | Out-Null

    # Creating List[object] through New-Object can trigger PowerShell's array
    # subexpression binder bug when @($retired) is evaluated. The CLR
    # constructor avoids that wrapper while preserving the same list type.
    $retired = [System.Collections.Generic.List[object]]::new()
    try {
        $index = 0
        foreach ($entry in $entries) {
            $index += 1
            $fileName = [IO.Path]::GetFileName([string]$entry.EntryPath)
            $backupPath = Join-Path $backupDir ("{0:D2}_{1}" -f $index, $fileName)
            Move-Item -LiteralPath $entry.EntryPath -Destination $backupPath -Force -ErrorAction Stop

            $retired.Add([pscustomobject]@{
                OriginalPath = [string]$entry.EntryPath
                BackupPath = $backupPath
                Kind = [string]$entry.Kind
                TargetPath = [string]$entry.TargetPath
                Arguments = [string]$entry.Arguments
                MatchedValue = [string]$entry.MatchedValue
            })
        }
    } catch {
        $failure = $_
        Restore-LolDataLegacyStartupEntries -RetiredEntries @($retired) | Out-Null
        throw $failure
    }

    $manifestPath = Join-Path $backupDir "manifest.json"
    @($retired) | ConvertTo-Json -Depth 5 | Out-File -LiteralPath $manifestPath -Encoding UTF8
    return @($retired)
}
