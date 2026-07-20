param(
  [string]$ServiceName = "LOLDataSystem",
  [string]$TaskName = "LOLDataSystem-KeepAlive",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Please run PowerShell as Administrator"
  }
}

function Ensure-Nssm([string]$projectRoot) {
  $toolsDir = Join-Path $projectRoot "tools"
  if (!(Test-Path $toolsDir)) {
    New-Item -Path $toolsDir -ItemType Directory | Out-Null
  }
  $nssmRoot = Join-Path $toolsDir "nssm-2.24"
  $nssmExe = Join-Path $nssmRoot "win64\nssm.exe"
  if (Test-Path $nssmExe) {
    return $nssmExe
  }
  $zipPath = Join-Path $toolsDir "nssm-2.24.zip"
  Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
  Expand-Archive -Path $zipPath -DestinationPath $toolsDir -Force
  if (!(Test-Path $nssmExe)) {
    throw "nssm executable not found after download: $nssmExe"
  }
  return $nssmExe
}

function Install-ServiceWithNssm([string]$projectRoot, [string]$serviceName) {
  $nssmExe = Ensure-Nssm $projectRoot
  $runScript = Join-Path $projectRoot "ops\run_service.ps1"
  $logsDir = Join-Path $projectRoot "logs"
  if (!(Test-Path $logsDir)) {
    New-Item -Path $logsDir -ItemType Directory | Out-Null
  }
  $stdoutLog = Join-Path $logsDir "service.stdout.log"
  $stderrLog = Join-Path $logsDir "service.stderr.log"

  $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
  if ($svc) {
    try {
      Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    } catch {}
    & $nssmExe remove $serviceName confirm | Out-Null
    for ($i = 0; $i -lt 12; $i++) {
      $checkSvc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
      if (-not $checkSvc) { break }
      Start-Sleep -Milliseconds 500
    }
  }
  $installed = $false
  for ($i = 0; $i -lt 12; $i++) {
    & $nssmExe install $serviceName "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`""
    $checkSvc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($checkSvc) {
      $installed = $true
      break
    }
    Start-Sleep -Milliseconds 500
  }
  if (-not $installed) {
    throw "service install failed: $serviceName"
  }
  & $nssmExe set $serviceName AppDirectory $projectRoot
  & $nssmExe set $serviceName Start SERVICE_AUTO_START
  & $nssmExe set $serviceName AppExit Default Restart
  & $nssmExe set $serviceName AppStdout $stdoutLog
  & $nssmExe set $serviceName AppStderr $stderrLog
  & $nssmExe set $serviceName AppRotateFiles 1
  & $nssmExe set $serviceName AppRotateOnline 1
  & $nssmExe set $serviceName AppRotateBytes 10485760
  try {
    Start-Service -Name $serviceName -ErrorAction Stop
  } catch {
    $svcNow = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $svcNow -or $svcNow.Status -ne 'Running') {
      throw
    }
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

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not $Apply) {
  Write-Output "Validation passed. Planned persistent setup:"
  Write-Output "1) Windows service: $ServiceName"
  Write-Output "2) Keepalive task: $TaskName (every 10 minutes)"
  Write-Output "Run command:"
  Write-Output "powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Apply"
  exit 0
}

Assert-Admin
Ensure-PlaywrightRuntime -projectRoot $projectRoot
Install-ServiceWithNssm -projectRoot $projectRoot -serviceName $ServiceName
Install-KeepAliveTask -projectRoot $projectRoot -taskName $TaskName

Write-Output "Persistence setup completed"
Write-Output "Service: $ServiceName"
Write-Output "Task: $TaskName"
