$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $projectRoot "ops\app_env.local.ps1"
if (Test-Path $envFile) {
  . $envFile
}

Set-Location $projectRoot

if (-not $env:PYTHONIOENCODING) {
  $env:PYTHONIOENCODING = "utf-8"
}
if (-not $env:APP_PORT) {
  $env:APP_PORT = "5001"
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  $pythonExe = $venvPython
} else {
  $pythonExe = (Get-Command python -ErrorAction Stop).Source
}

$logsDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory | Out-Null
}

$lanzouConfig = Join-Path $projectRoot "lanzou_update_push_api_server\config.json"
$lanzouExample = Join-Path $projectRoot "lanzou_update_push_api_server\config.example.json"
if ((-not (Test-Path $lanzouConfig)) -and (Test-Path $lanzouExample)) {
  Copy-Item $lanzouExample $lanzouConfig
}
$env:LANZOU_MONITOR_CONFIG = $lanzouConfig

$mainStdout = Join-Path $logsDir "service.stdout.log"
$mainStderr = Join-Path $logsDir "service.stderr.log"
$lanzouStdout = Join-Path $logsDir "lanzou_monitor.stdout.log"
$lanzouStderr = Join-Path $logsDir "lanzou_monitor.stderr.log"

function Rotate-Log([string]$Path) {
  if (-not (Test-Path $Path)) {
    return
  }
  $previousPath = "$Path.previous"
  Move-Item -Path $Path -Destination $previousPath -Force
}

function Start-ManagedPythonProcess(
  [string[]]$ProcessArguments,
  [string]$StdoutPath,
  [string]$StderrPath
) {
  Rotate-Log $StdoutPath
  Rotate-Log $StderrPath
  return Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $ProcessArguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdoutPath `
    -RedirectStandardError $StderrPath `
    -PassThru
}

function Stop-ManagedProcess($Process, [string]$Name) {
  if ($null -eq $Process) {
    return
  }
  try {
    $Process.Refresh()
    if (-not $Process.HasExited) {
      Write-Output "Stopping $Name PID=$($Process.Id)"
      Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
      $Process.WaitForExit(5000) | Out-Null
    }
  } catch {
    Write-Warning "Failed to stop $Name cleanly: $($_.Exception.Message)"
  }
}

$mainProcess = $null
$lanzouProcess = $null
$exitCode = 0
$monitorRestartCount = 0
$lanzouStartedAt = $null
$lanzouModuleExists = Test-Path (Join-Path $projectRoot "lanzou_update_push_api_server\__main__.py")

try {
  $mainProcess = Start-ManagedPythonProcess @("app.py") $mainStdout $mainStderr
  Write-Output "Started main API PID=$($mainProcess.Id)"

  if ($lanzouModuleExists) {
    $lanzouProcess = Start-ManagedPythonProcess @("-m", "lanzou_update_push_api_server") $lanzouStdout $lanzouStderr
    $lanzouStartedAt = Get-Date
    Write-Output "Started Lanzou monitor PID=$($lanzouProcess.Id)"
  } else {
    Write-Warning "Lanzou monitor module not found; 6178 will not be started."
  }

  while ($true) {
    Start-Sleep -Seconds 5

    $mainProcess.Refresh()
    if ($mainProcess.HasExited) {
      $exitCode = $mainProcess.ExitCode
      if ($exitCode -eq 0) {
        $exitCode = 1
      }
      Write-Error "Main API exited unexpectedly with code $($mainProcess.ExitCode)."
      break
    }

    if ($null -ne $lanzouProcess) {
      $lanzouProcess.Refresh()
      if ($lanzouProcess.HasExited) {
        $monitorRestartCount += 1
        $delaySeconds = [Math]::Min(60, 5 * [Math]::Pow(2, [Math]::Min($monitorRestartCount - 1, 3)))
        Write-Warning "Lanzou monitor exited with code $($lanzouProcess.ExitCode). Restarting in $delaySeconds seconds."
        Start-Sleep -Seconds $delaySeconds
        $lanzouProcess = Start-ManagedPythonProcess @("-m", "lanzou_update_push_api_server") $lanzouStdout $lanzouStderr
        $lanzouStartedAt = Get-Date
        Write-Output "Restarted Lanzou monitor PID=$($lanzouProcess.Id), attempt=$monitorRestartCount"
      } elseif ($null -ne $lanzouStartedAt -and ((Get-Date) - $lanzouStartedAt).TotalMinutes -ge 5) {
        $monitorRestartCount = 0
      }
    }
  }
} finally {
  Stop-ManagedProcess $lanzouProcess "Lanzou monitor"
  Stop-ManagedProcess $mainProcess "main API"
}

exit $exitCode
