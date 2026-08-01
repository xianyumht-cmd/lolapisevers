param(
  [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
  [string]$ServiceName = "LOLDataSystem",
  [int]$Port = 5001,
  [int]$LanzouPort = 6178
)

$ErrorActionPreference = "Continue"

$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$HealthUrl = "http://127.0.0.1:$Port/health"
$LanzouHealthUrl = "http://127.0.0.1:$LanzouPort/health"
$LogsDir = Join-Path $ProjectRoot "logs"
$StderrLog = Join-Path $LogsDir "main_api.stderr.log"
$StdoutLog = Join-Path $LogsDir "main_api.stdout.log"
$LanzouStderrLog = Join-Path $LogsDir "lanzou_monitor.stderr.log"
$LanzouStdoutLog = Join-Path $LogsDir "lanzou_monitor.stdout.log"
$MainApiReady = $false
$LanzouHealthy = $false

Write-Host "==== lolapisevers health check ====" -ForegroundColor Cyan

function Show-Section([string]$title) {
  Write-Host "`n==== $title ====" -ForegroundColor Yellow
}

Show-Section "HTTP health"
try {
  $res = Invoke-RestMethod $HealthUrl -TimeoutSec 8
  $res | ConvertTo-Json -Depth 5
  $MainApiReady = (
    $res.status -eq "ok" -and
    $res.ready -eq $true -and
    $res.mysql -eq "up" -and
    $res.so1_browser -eq "up"
  )
  if ($MainApiReady) {
    Write-Host "main API readiness: ready" -ForegroundColor Green
  } else {
    Write-Host "main API readiness: not ready (the process may still be live)" -ForegroundColor Red
  }
} catch {
  Write-Host "health request failed: $($_.Exception.Message)" -ForegroundColor Red
}

Show-Section "Lanzou monitor health"
try {
  $res = Invoke-RestMethod $LanzouHealthUrl -TimeoutSec 8
  $res | ConvertTo-Json -Depth 5
  $LanzouHealthy = ($res.ok -eq $true -and $res.running -eq $true)
  if ($LanzouHealthy) {
    Write-Host "lanzou monitor health: ready" -ForegroundColor Green
  } else {
    Write-Host "lanzou monitor health: not ready" -ForegroundColor Red
  }
} catch {
  Write-Host "lanzou health request failed: $($_.Exception.Message)" -ForegroundColor Red
}

Show-Section "Windows service"
Get-Service $ServiceName -ErrorAction SilentlyContinue | Format-List Name,Status,StartType
sc.exe queryex $ServiceName

Show-Section "Port $Port listener"
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
  [PSCustomObject]@{
    LocalPort = $_.LocalPort
    PID = $_.OwningProcess
    ProcessName = $p.ProcessName
    Path = $p.Path
  }
} | Format-Table -AutoSize

Show-Section "Port $LanzouPort listener"
Get-NetTCPConnection -LocalPort $LanzouPort -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
  [PSCustomObject]@{
    LocalPort = $_.LocalPort
    PID = $_.OwningProcess
    ProcessName = $p.ProcessName
    Path = $p.Path
  }
} | Format-Table -AutoSize

Show-Section "Python / PowerShell / NSSM processes"
tasklist | findstr /i "python powershell nssm"

Show-Section "app.py process command lines"
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -like "python*" -and $_.CommandLine -match "app\.py"
} | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | Format-List

Show-Section "Lanzou monitor process command lines"
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -like "python*" -and $_.CommandLine -match "lanzou_update_push_api_server"
} | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | Format-List

Show-Section "Recent stderr"
if (Test-Path $StderrLog) {
  Get-Content $StderrLog -Tail 40
} else {
  Write-Host "stderr log not found: $StderrLog"
}

Show-Section "Recent stdout"
if (Test-Path $StdoutLog) {
  Get-Content $StdoutLog -Tail 20
} else {
  Write-Host "stdout log not found: $StdoutLog"
}

Show-Section "Recent Lanzou stderr"
if (Test-Path $LanzouStderrLog) {
  Get-Content $LanzouStderrLog -Tail 40
} else {
  Write-Host "lanzou stderr log not found: $LanzouStderrLog"
}

Show-Section "Recent Lanzou stdout"
if (Test-Path $LanzouStdoutLog) {
  Get-Content $LanzouStdoutLog -Tail 20
} else {
  Write-Host "lanzou stdout log not found: $LanzouStdoutLog"
}

if ($MainApiReady -and $LanzouHealthy) {
  Write-Host "`n==== health check complete: ready ====" -ForegroundColor Cyan
  exit 0
}

Write-Host "`n==== health check complete: one or more services are not ready ====" -ForegroundColor Red
exit 1
