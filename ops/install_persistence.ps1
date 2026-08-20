param(
  [string]$ServiceName = "LOLDataSystem",
  [string]$TaskName = "LOLDataSystem-KeepAlive",
  [string]$NssmZipSha256 = $env:NSSM_ZIP_SHA256,
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeTopologyScript = Join-Path $projectRoot "ops\runtime_topology.ps1"
if (!(Test-Path -LiteralPath $runtimeTopologyScript -PathType Leaf)) {
  throw "runtime topology helper not found: $runtimeTopologyScript"
}
. $runtimeTopologyScript

function Assert-Admin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Please run PowerShell as Administrator"
  }
}

function Ensure-Nssm([string]$projectRoot, [string]$expectedZipSha256) {
  $toolsDir = Join-Path $projectRoot "tools"
  if (!(Test-Path $toolsDir)) {
    New-Item -Path $toolsDir -ItemType Directory | Out-Null
  }
  $nssmRoot = Join-Path $toolsDir "nssm-2.24"
  $nssmExe = Join-Path $nssmRoot "win64\nssm.exe"
  if (Test-Path $nssmExe) {
    return $nssmExe
  }
  $expected = ([string]$expectedZipSha256).Trim().ToLowerInvariant()
  if ($expected -notmatch '^[a-f0-9]{64}$') {
    throw "NSSM_ZIP_SHA256 (or -NssmZipSha256) must contain the verified SHA-256 for nssm-2.24.zip"
  }
  $zipPath = Join-Path $toolsDir "nssm-2.24.zip"
  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
  $actual = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) {
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    throw "NSSM archive SHA-256 mismatch. Expected $expected but received $actual"
  }
  Expand-Archive -Path $zipPath -DestinationPath $toolsDir -Force
  if (!(Test-Path $nssmExe)) {
    throw "nssm executable not found after verified download: $nssmExe"
  }
  return $nssmExe
}

function Install-ServiceWithNssm([string]$projectRoot, [string]$serviceName, [string]$expectedZipSha256) {
  $nssmExe = Ensure-Nssm $projectRoot $expectedZipSha256
  $runScript = Join-Path $projectRoot "ops\run_service.ps1"
  if (!(Test-Path $runScript)) {
    throw "service entry script not found: $runScript"
  }
  $powershellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
  $logsDir = Join-Path $projectRoot "logs"
  if (!(Test-Path $logsDir)) {
    New-Item -Path $logsDir -ItemType Directory | Out-Null
  }
  $stdoutLog = Join-Path $logsDir "supervisor.stdout.log"
  $stderrLog = Join-Path $logsDir "supervisor.stderr.log"
  $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`""

  # Validate the complete candidate before stopping or changing the active service.
  foreach ($requiredPath in @($projectRoot, $runScript, $powershellExe, $nssmExe, $logsDir)) {
    if (!(Test-Path $requiredPath)) { throw "service preflight path missing: $requiredPath" }
  }

  $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
  $serviceExisted = $null -ne $svc
  $wasRunning = $serviceExisted -and $svc.Status -eq 'Running'
  $created = $false
  $saved = @{}
  $keys = @('Application','AppParameters','AppDirectory','Start','AppExit','AppStdout','AppStderr','AppRotateFiles','AppRotateOnline','AppRotateBytes')
  if ($serviceExisted) {
    foreach ($key in $keys) {
      $saved[$key] = ((& $nssmExe get $serviceName $key 2>$null) -join "`n").Trim()
    }
  }

  try {
    if ($serviceExisted) {
      Stop-Service -Name $serviceName -Force -ErrorAction Stop
    } else {
      & $nssmExe install $serviceName $powershellExe $arguments | Out-Null
      if ($LASTEXITCODE -ne 0 -or -not (Get-Service -Name $serviceName -ErrorAction SilentlyContinue)) {
        throw "service install failed: $serviceName"
      }
      $created = $true
    }

    & $nssmExe set $serviceName Application $powershellExe | Out-Null
    & $nssmExe set $serviceName AppParameters $arguments | Out-Null
    & $nssmExe set $serviceName AppDirectory $projectRoot | Out-Null
    & $nssmExe set $serviceName Start SERVICE_AUTO_START | Out-Null
    & $nssmExe set $serviceName AppExit Default Restart | Out-Null
    & $nssmExe set $serviceName AppStdout $stdoutLog | Out-Null
    & $nssmExe set $serviceName AppStderr $stderrLog | Out-Null
    & $nssmExe set $serviceName AppRotateFiles 1 | Out-Null
    & $nssmExe set $serviceName AppRotateOnline 1 | Out-Null
    & $nssmExe set $serviceName AppRotateBytes 10485760 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "NSSM service configuration failed" }

    Start-Service -Name $serviceName -ErrorAction Stop
    $running = $false
    for ($i = 0; $i -lt 20; $i++) {
      $current = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
      if ($current -and $current.Status -eq 'Running') { $running = $true; break }
      Start-Sleep -Milliseconds 500
    }
    if (-not $running) { throw "service failed to reach Running state: $serviceName" }
  } catch {
    $failure = $_
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    if ($created) {
      & $nssmExe remove $serviceName confirm | Out-Null
    } elseif ($serviceExisted) {
      foreach ($key in $keys) {
        $oldValue = [string]$saved[$key]
        if ([string]::IsNullOrWhiteSpace($oldValue)) {
          & $nssmExe reset $serviceName $key | Out-Null
        } elseif ($key -eq 'AppExit') {
          & $nssmExe set $serviceName AppExit Default $oldValue | Out-Null
        } else {
          & $nssmExe set $serviceName $key $oldValue | Out-Null
        }
      }
      if ($wasRunning) { Start-Service -Name $serviceName -ErrorAction SilentlyContinue }
    }
    throw $failure
  }
}

function Ensure-PlaywrightRuntime([string]$projectRoot) {
  $envFile = Join-Path $projectRoot "ops\app_env.local.ps1"
  if (Test-Path $envFile) {
    . $envFile
  }
  if (-not $env:PLAYWRIGHT_BROWSERS_PATH) {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot "ms-playwright"
  }
  if (!(Test-Path $env:PLAYWRIGHT_BROWSERS_PATH)) {
    New-Item -Path $env:PLAYWRIGHT_BROWSERS_PATH -ItemType Directory | Out-Null
  }
  Push-Location $projectRoot
  try {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
      $pythonExe = $venvPython
    } else {
      $pythonExe = (Get-Command python -ErrorAction Stop).Source
    }
    & $pythonExe -m playwright install chromium | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "playwright browser install failed"
    }
  } finally {
    Pop-Location
  }
}

function Install-KeepAliveTask([string]$projectRoot, [string]$taskName) {
  $keepaliveScript = Join-Path $projectRoot "ops\keepalive.ps1"
  $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$keepaliveScript`""
  schtasks /Delete /TN $taskName /F | Out-Null
  schtasks /Create /SC MINUTE /MO 10 /TN $taskName /TR $command /RU SYSTEM /F | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "scheduled task create failed: $taskName"
  }
  schtasks /Query /TN $taskName | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "scheduled task query failed after create: $taskName"
  }
}

function Assert-NoNonServiceSupervisor([string]$projectRoot, [string]$serviceName) {
  $conflicts = @(Get-LolDataSupervisorProcesses -ProjectRoot $projectRoot -ServiceName $serviceName | Where-Object { -not $_.IsServiceChild })
  if ($conflicts.Count -eq 0) {
    return
  }

  $details = @($conflicts | ForEach-Object {
    "PID=$($_.ProcessId) parent=$($_.ParentName)($($_.ParentProcessId))"
  }) -join "; "
  throw "Non-service run_service.ps1 supervisor already exists for this project: $details. Stop the manual/legacy instance before applying persistence."
}

function Assert-SingleServiceSupervisor([string]$projectRoot, [string]$serviceName) {
  for ($i = 0; $i -lt 20; $i++) {
    $supervisors = @(Get-LolDataSupervisorProcesses -ProjectRoot $projectRoot -ServiceName $serviceName)
    $serviceOwned = @($supervisors | Where-Object { $_.IsServiceChild })
    $nonService = @($supervisors | Where-Object { -not $_.IsServiceChild })
    if ($serviceOwned.Count -eq 1 -and $nonService.Count -eq 0) {
      return
    }
    Start-Sleep -Milliseconds 500
  }

  $final = @(Get-LolDataSupervisorProcesses -ProjectRoot $projectRoot -ServiceName $serviceName)
  $summary = @($final | ForEach-Object {
    "PID=$($_.ProcessId) serviceChild=$($_.IsServiceChild) parent=$($_.ParentName)($($_.ParentProcessId))"
  }) -join "; "
  if ([string]::IsNullOrWhiteSpace($summary)) { $summary = "none" }
  throw "Managed runtime topology validation failed. Expected exactly one service-owned run_service.ps1 supervisor; observed: $summary"
}

if (-not $Apply) {
  $legacyEntries = @(Get-LolDataLegacyStartupEntries -ProjectRoot $projectRoot)
  $supervisors = @(Get-LolDataSupervisorProcesses -ProjectRoot $projectRoot -ServiceName $ServiceName)
  Write-Output "Validation passed. Planned persistent setup:"
  Write-Output "1) Windows service: $ServiceName"
  Write-Output "2) Keepalive task: $TaskName (every 10 minutes)"
  Write-Output "3) Validate exactly one service-owned run_service.ps1 supervisor"
  Write-Output "4) Retire legacy Startup entries for this project: $($legacyEntries.Count)"
  foreach ($entry in $legacyEntries) {
    Write-Output "   - $($entry.EntryPath) -> $($entry.MatchedValue)"
  }
  Write-Output "Current supervisors: $($supervisors.Count)"
  foreach ($supervisor in $supervisors) {
    Write-Output "   - PID=$($supervisor.ProcessId) serviceChild=$($supervisor.IsServiceChild) parent=$($supervisor.ParentName)"
  }
  Write-Output "Run command:"
  Write-Output "powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Apply"
  exit 0
}

Assert-Admin
Assert-NoNonServiceSupervisor -projectRoot $projectRoot -serviceName $ServiceName
Ensure-PlaywrightRuntime -projectRoot $projectRoot
Install-ServiceWithNssm -projectRoot $projectRoot -serviceName $ServiceName -expectedZipSha256 $NssmZipSha256
Install-KeepAliveTask -projectRoot $projectRoot -taskName $TaskName
Assert-SingleServiceSupervisor -projectRoot $projectRoot -serviceName $ServiceName

# Retire old login-startup routes only after the managed service and keepalive
# task are established successfully. Entries are moved, not deleted, and the
# helper rolls back partial moves if the retirement itself fails.
$retiredStartupEntries = @(Move-LolDataLegacyStartupEntries -ProjectRoot $projectRoot)
foreach ($entry in $retiredStartupEntries) {
  Write-Output "Retired legacy Startup entry: $($entry.OriginalPath)"
  Write-Output "Backup: $($entry.BackupPath)"
}

$remainingLegacyEntries = @(Get-LolDataLegacyStartupEntries -ProjectRoot $projectRoot)
if ($remainingLegacyEntries.Count -gt 0) {
  throw "Persistence setup finished but legacy Startup entries still exist for this project. Run ops\health_check.ps1 and inspect Runtime topology."
}

Write-Output "Persistence setup completed"
Write-Output "Service: $ServiceName"
Write-Output "Task: $TaskName"
Write-Output "Retired legacy Startup entries: $($retiredStartupEntries.Count)"
