$ErrorActionPreference = "Continue"

$ProjectRoot = "D:\project2\lolapisevers"
$ServiceName = "LOLDataSystem"
$HealthUrl = "http://127.0.0.1:5001/health"
$Port = 5001
$Time = Get-Date -Format "yyyyMMdd-HHmmss"
$LogsDir = Join-Path $ProjectRoot "logs"
$BackupFile = Join-Path $LogsDir "formal_takeover_backup_$Time.txt"

Write-Host "==== lolapisevers 正式接管开始 ====" -ForegroundColor Cyan

function Write-Step([string]$text) {
    Write-Host "`n$text" -ForegroundColor Yellow
}

function Test-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Health {
    try {
        $res = Invoke-RestMethod $HealthUrl -TimeoutSec 8
        return (
            $res.status -eq "ok" -and
            $res.ready -eq $true -and
            $res.mysql -eq "up" -and
            $res.so1_browser -eq "up"
        )
    } catch {
        return $false
    }
}

function Show-PortOwner {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            LocalPort = $_.LocalPort
            PID = $_.OwningProcess
            ProcessName = $p.ProcessName
            Path = $p.Path
        }
    } | Format-Table -AutoSize
}

function Get-NssmPath {
    $localNssm = Join-Path $ProjectRoot "tools\nssm-2.24\win64\nssm.exe"
    if (Test-Path $localNssm) {
        return $localNssm
    }
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Save-Diagnostics([string]$path, [string]$nssmExe) {
    "==== time ====" | Out-File $path -Encoding UTF8
    Get-Date | Out-File $path -Append -Encoding UTF8

    "`n==== sc queryex $ServiceName ====" | Out-File $path -Append -Encoding UTF8
    sc.exe queryex $ServiceName | Out-File $path -Append -Encoding UTF8

    "`n==== sc qc $ServiceName ====" | Out-File $path -Append -Encoding UTF8
    sc.exe qc $ServiceName | Out-File $path -Append -Encoding UTF8

    if ($nssmExe) {
        "`n==== nssm config ====" | Out-File $path -Append -Encoding UTF8
        foreach ($key in @("Application","AppParameters","AppDirectory","AppStdout","AppStderr","AppEnvironmentExtra","Start","AppExit")) {
            "`n[$key]" | Out-File $path -Append -Encoding UTF8
            & $nssmExe get $ServiceName $key 2>&1 | Out-File $path -Append -Encoding UTF8
        }
    }

    "`n==== 5001 owner ====" | Out-File $path -Append -Encoding UTF8
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            LocalPort = $_.LocalPort
            PID = $_.OwningProcess
            ProcessName = $p.ProcessName
            Path = $p.Path
        }
    } | Format-Table -AutoSize | Out-String | Out-File $path -Append -Encoding UTF8

    "`n==== app.py python processes ====" | Out-File $path -Append -Encoding UTF8
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like "python*" -and $_.CommandLine -match "app\.py"
    } | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | Format-List | Out-String | Out-File $path -Append -Encoding UTF8
}

function Stop-AppPyConsoleProcesses {
    Write-Step "[4] 停止当前手动/控制台 app.py 进程..."

    $appPyProcesses = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -like "python*" -and $_.CommandLine -match "app\.py"
    } | Sort-Object ProcessId -Descending

    if (-not $appPyProcesses) {
        Write-Host "没有找到 app.py Python 进程，跳过。"
        return
    }

    foreach ($proc in $appPyProcesses) {
        Write-Host "准备停止 PID=$($proc.ProcessId) CMD=$($proc.CommandLine)" -ForegroundColor DarkYellow
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Host "停止 PID=$($proc.ProcessId) 失败：$($_.Exception.Message)" -ForegroundColor Red
        }
    }

    Start-Sleep -Seconds 3
}

function Start-FallbackConsole {
    Write-Step "[回滚] 尝试恢复为控制台后台 Python 启动..."

    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $pythonExe = $venvPython
    } else {
        $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    }

    if (-not $pythonExe) {
        Write-Host "找不到 Python，无法回滚启动。" -ForegroundColor Red
        return $false
    }

    Start-Process -FilePath $pythonExe -ArgumentList "app.py" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
    Start-Sleep -Seconds 8
    return (Test-Health)
}

# 1. 管理员检查
if (-not (Test-Admin)) {
    Write-Host "请用【管理员 PowerShell】运行这个脚本。" -ForegroundColor Red
    exit 1
}

if (!(Test-Path $ProjectRoot)) {
    Write-Host "项目目录不存在：$ProjectRoot" -ForegroundColor Red
    exit 1
}

if (!(Test-Path $LogsDir)) {
    New-Item -Path $LogsDir -ItemType Directory | Out-Null
}

$nssmExe = Get-NssmPath
if (-not $nssmExe) {
    Write-Host "未找到 nssm.exe，无法正式接管服务。" -ForegroundColor Red
    exit 1
}

Write-Step "[1] 当前 5001 端口占用"
Show-PortOwner

Write-Step "[2] 当前接口健康检查"
$beforeHealth = Test-Health
Write-Host "接管前接口状态：$beforeHealth"

Write-Step "[3] 备份服务与进程诊断信息"
Save-Diagnostics -path $BackupFile -nssmExe $nssmExe
Write-Host "已备份到：$BackupFile" -ForegroundColor Green

# 确保服务先停住
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "没有找到服务：$ServiceName，无法接管。" -ForegroundColor Red
    exit 1
}

if ($svc.Status -ne "Stopped") {
    Write-Host "先停止 $ServiceName 服务..."
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# 停掉当前所有 app.py Python，避免 5001 被占用
Stop-AppPyConsoleProcesses

Write-Step "[5] 确认 5001 是否已释放"
$stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($stillListening) {
    Write-Host "5001 仍被占用，暂不启动服务，避免继续冲突。" -ForegroundColor Red
    Show-PortOwner
    Write-Host "脚本停止。你把上面 5001 占用信息发给我。" -ForegroundColor Red
    exit 1
}
Write-Host "5001 已释放。" -ForegroundColor Green

Write-Step "[6] 启动 $ServiceName 服务接管接口"
Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 12

$svcAfter = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
Write-Host "服务状态：$($svcAfter.Status)"

Write-Step "[7] 服务接管后 health 检查"
$afterHealth = Test-Health
Write-Host "服务接管后接口状态：$afterHealth"

if ($afterHealth) {
    Write-Host "正式接管成功：以后由 LOLDataSystem 服务负责运行接口。" -ForegroundColor Green

    Set-Service -Name $ServiceName -StartupType Automatic -ErrorAction SilentlyContinue
    & $nssmExe set $ServiceName Start SERVICE_AUTO_START | Out-Null

    Write-Host "已恢复 $ServiceName 为开机自启。" -ForegroundColor Green

    Write-Step "[8] 当前 5001 端口监听"
    Show-PortOwner

    Write-Step "[9] 当前 Python / PowerShell / NSSM 进程"
    tasklist | findstr /i "python powershell nssm"

    Write-Host "`n==== 正式接管完成 ====" -ForegroundColor Cyan
    exit 0
}

Write-Host "服务接管失败，准备回滚，避免接口长时间不可用。" -ForegroundColor Red

Write-Step "[失败诊断] service.stderr.log 最近 80 行"
$stderr = Join-Path $LogsDir "service.stderr.log"
if (Test-Path $stderr) {
    Get-Content $stderr -Tail 80
} else {
    Write-Host "未找到 service.stderr.log"
}

Write-Step "[回滚] 停止服务并改回手动"
Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
Set-Service -Name $ServiceName -StartupType Manual -ErrorAction SilentlyContinue

$fallbackOk = Start-FallbackConsole
Write-Host "回滚后接口状态：$fallbackOk"

Write-Step "[最终状态] 当前 5001 端口监听"
Show-PortOwner

Write-Step "[最终状态] 当前 Python / PowerShell / NSSM 进程"
tasklist | findstr /i "python powershell nssm"

if ($fallbackOk) {
    Write-Host "`n服务接管失败，但已经回滚到 Python 后台运行，接口仍可用。" -ForegroundColor Yellow
    exit 2
} else {
    Write-Host "`n服务接管失败，回滚也失败，需要人工继续排查。" -ForegroundColor Red
    exit 3
}
