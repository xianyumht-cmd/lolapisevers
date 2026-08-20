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
$TopologyWarningCount = 0
$TopologyHelperAvailable = $false
$RuntimeTopologyScript = Join-Path $ProjectRoot "ops\runtime_topology.ps1"
if (Test-Path -LiteralPath $RuntimeTopologyScript -PathType Leaf) {
  . $RuntimeTopologyScript
  $TopologyHelperAvailable = $true
}

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
$WindowsService = Get-Service $ServiceName -ErrorAction SilentlyContinue
$WindowsService | Format-List Name,Status,StartType
sc.exe queryex $ServiceName

Show-Section "Runtime topology"
if (-not $TopologyHelperAvailable) {
  $TopologyWarningCount += 1
  Write-Host "runtime topology helper not found: $RuntimeTopologyScript" -ForegroundColor Red
} else {
  $supervisors = @(Get-LolDataSupervisorProcesses -ProjectRoot $ProjectRoot -ServiceName $ServiceName)
  $legacyStartupEntries = @(Get-LolDataLegacyStartupEntries -ProjectRoot $ProjectRoot)

  if ($supervisors.Count -gt 0) {
    $supervisors |
      Select-Object ProcessId,ParentProcessId,ParentName,IsServiceChild,ServiceProcessId,ExecutablePath,CommandLine |
      Format-List
  } else {
    Write-Host "No run_service.ps1 supervisor process found."
  }

  if ($WindowsService -and $WindowsService.Status -eq "Running") {
    $serviceSupervisors = @($supervisors | Where-Object { $_.IsServiceChild })
    $nonServiceSupervisors = @($supervisors | Where-Object { -not $_.IsServiceChild })

    if ($serviceSupervisors.Count -eq 1 -and $nonServiceSupervisors.Count -eq 0) {
      Write-Host "runtime supervisor topology: healthy (exactly one service-owned supervisor)" -ForegroundColor Green
    } else {
      $TopologyWarningCount += 1
      Write-Host "runtime supervisor topology: WARNING" -ForegroundColor Red
      Write-Host "expected exactly one service-owned supervisor; service=$($serviceSupervisors.Count), non-service=$($nonServiceSupervisors.Count)" -ForegroundColor Red
    }
  } elseif ($supervisors.Count -gt 0) {
    $TopologyWarningCount += 1
    Write-Host "runtime supervisor topology: service is not running but project supervisor process still exists" -ForegroundColor Red
  } else {
    Write-Host "runtime supervisor topology: service is not running and no supervisor exists"
  }

  if ($legacyStartupEntries.Count -gt 0) {
    $TopologyWarningCount += 1
    Write-Host "legacy Startup entries detected for this project: $($legacyStartupEntries.Count)" -ForegroundColor Red
    $legacyStartupEntries |
      Select-Object EntryPath,Kind,TargetPath,Arguments,MatchedValue |
      Format-List
    Write-Host "Run ops\install_persistence.ps1 -Apply to retire these entries safely into logs\retired-startup." -ForegroundColor Yellow
  } else {
    Write-Host "legacy Startup entries: none" -ForegroundColor Green
  }
}

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

if ($TopologyWarningCount -gt 0) {
  Write-Host "`nRuntime topology warnings: $TopologyWarningCount" -ForegroundColor Yellow
  Write-Host "Topology warnings are reported separately and do not change the HTTP readiness exit code." -ForegroundColor Yellow
}

if ($MainApiReady -and $LanzouHealthy) {
  Write-Host "`n==== health check complete: ready ====" -ForegroundColor Cyan
  exit 0
}

Write-Host "`n==== health check complete: one or more services are not ready ====" -ForegroundColor Red
exit 1
