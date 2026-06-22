$ErrorActionPreference = "Continue"

$ProjectRoot = "D:\project2\lolapisevers"
$ServiceName = "LOLDataSystem"
$Port = 5001
$HealthUrl = "http://127.0.0.1:$Port/health"
$LogsDir = Join-Path $ProjectRoot "logs"
$StderrLog = Join-Path $LogsDir "service.stderr.log"
$StdoutLog = Join-Path $LogsDir "service.stdout.log"

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

Show-Section "Python / PowerShell / NSSM processes"
tasklist | findstr /i "python powershell nssm"

Show-Section "app.py process command lines"
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -like "python*" -and $_.CommandLine -match "app\.py"
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

Write-Host "`n==== health check complete ====" -ForegroundColor Cyan
