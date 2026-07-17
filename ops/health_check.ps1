$ErrorActionPreference = "Continue"

$ProjectRoot = "D:\project2\lolapisevers"
$ServiceName = "LOLDataSystem"
$Port = 5001
$HealthUrl = "http://127.0.0.1:$Port/health"
$LanzouPort = 6178
$LanzouHealthUrl = "http://127.0.0.1:$LanzouPort/health"
$LogsDir = Join-Path $ProjectRoot "logs"
$StderrLog = Join-Path $LogsDir "service.stderr.log"
$StdoutLog = Join-Path $LogsDir "service.stdout.log"
$LanzouStderrLog = Join-Path $LogsDir "lanzou_monitor.stderr.log"
$LanzouStdoutLog = Join-Path $LogsDir "lanzou_monitor.stdout.log"

Write-Host "==== lolapisevers health check ====" -ForegroundColor Cyan

function Show-Section([string]$title) {
  Write-Host "`n==== $title ====" -ForegroundColor Yellow
}

Show-Section "HTTP health"
try {
  $res = Invoke-RestMethod $HealthUrl -TimeoutSec 8
  $res | ConvertTo-Json -Depth 5
} catch {
  Write-Host "health request failed: $($_.Exception.Message)" -ForegroundColor Red
}

Show-Section "Lanzou monitor health"
try {
  $res = Invoke-RestMethod $LanzouHealthUrl -TimeoutSec 8
  $res | ConvertTo-Json -Depth 5
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

Write-Host "`n==== health check complete ====" -ForegroundColor Cyan
