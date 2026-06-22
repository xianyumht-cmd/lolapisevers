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

& $pythonExe "app.py"
