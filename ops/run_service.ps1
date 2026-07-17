$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $projectRoot "ops\app_env.ps1"
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

$lanzouProcess = $null
if (Test-Path (Join-Path $projectRoot "lanzou_update_push_api_server\__main__.py")) {
  $env:LANZOU_MONITOR_CONFIG = $lanzouConfig
  $lanzouStdout = Join-Path $logsDir "lanzou_monitor.stdout.log"
  $lanzouStderr = Join-Path $logsDir "lanzou_monitor.stderr.log"
  $lanzouProcess = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList @("-m", "lanzou_update_push_api_server") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $lanzouStdout `
    -RedirectStandardError $lanzouStderr `
    -PassThru
  Write-Output "Started Lanzou monitor PID=$($lanzouProcess.Id)"
}

try {
  & $pythonExe "app.py"
} finally {
  if ($lanzouProcess -and -not $lanzouProcess.HasExited) {
    Stop-Process -Id $lanzouProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
