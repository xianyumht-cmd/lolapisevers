$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $projectRoot "ops\app_env.ps1"
if (Test-Path $envFile) {
  . $envFile
}

Set-Location $projectRoot
$pythonExe = (Get-Command python).Source
& $pythonExe "app.py"
