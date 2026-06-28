$ErrorActionPreference = "Continue"

$ProjectRoot = "D:\project2\lolapisevers"
$ServiceName = "LOLDataSystem"
$KeepaliveFile = Join-Path $ProjectRoot "ops\keepalive.ps1"
$AppEnvFile = Join-Path $ProjectRoot "ops\app_env.ps1"
$Time = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "==== lolapisevers 一键止血开始 ====" -ForegroundColor Cyan

# 1. 检查管理员权限
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "请用【管理员 PowerShell】运行这个脚本。" -ForegroundColor Red
    exit 1
}

# 2. 检查项目目录
if (!(Test-Path $ProjectRoot)) {
    Write-Host "项目目录不存在：$ProjectRoot" -ForegroundColor Red
    exit 1
}

# 3. 显示当前 5001 监听情况
Write-Host "`n[1] 当前 5001 端口占用：" -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        LocalPort = $_.LocalPort
        PID = $_.OwningProcess
        ProcessName = $p.ProcessName
        Path = $p.Path
    }
} | Format-Table -AutoSize

# 4. 修复 keepalive 默认端口 5000 -> 5001
Write-Host "`n[2] 修复 keepalive 默认端口..." -ForegroundColor Yellow

if (Test-Path $KeepaliveFile) {
    Copy-Item $KeepaliveFile "$KeepaliveFile.bak.$Time" -Force
    $content = Get-Content $KeepaliveFile -Raw
    $newContent = $content -replace 'http://127\.0\.0\.1:5000', 'http://127.0.0.1:5001'
    if ($newContent -ne $content) {
        Set-Content -Path $KeepaliveFile -Value $newContent -Encoding UTF8
        Write-Host "已修复 keepalive.ps1，备份：$KeepaliveFile.bak.$Time" -ForegroundColor Green
    } else {
        Write-Host "keepalive.ps1 里没有发现 5000 默认端口，跳过。" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "未找到 keepalive.ps1，跳过。" -ForegroundColor DarkYellow
}

# 5. 如果 app_env.ps1 里也写死了 5000，也改成 5001
if (Test-Path $AppEnvFile) {
    Copy-Item $AppEnvFile "$AppEnvFile.bak.$Time" -Force
    $envContent = Get-Content $AppEnvFile -Raw
    $newEnvContent = $envContent -replace 'http://127\.0\.0\.1:5000', 'http://127.0.0.1:5001'
    if ($newEnvContent -ne $envContent) {
        Set-Content -Path $AppEnvFile -Value $newEnvContent -Encoding UTF8
        Write-Host "已修复 app_env.ps1 里的 5000，备份：$AppEnvFile.bak.$Time" -ForegroundColor Green
    } else {
        Write-Host "app_env.ps1 未发现 5000，跳过。" -ForegroundColor DarkYellow
    }
}

# 6. 健康检查函数
function Test-LolApiHealth {
    try {
        $res = Invoke-RestMethod "http://127.0.0.1:5001/health" -TimeoutSec 8
        if ($res.status -eq "ok") {
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

Write-Host "`n[3] 停服务前 health 检查..." -ForegroundColor Yellow
$BeforeHealth = Test-LolApiHealth
Write-Host "停服务前接口状态：$BeforeHealth"

# 7. 停止 LOLDataSystem 服务，阻止 NSSM 反复重启
Write-Host "`n[4] 尝试停止 $ServiceName 服务..." -ForegroundColor Yellow
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

if ($svc) {
    if ($svc.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    Write-Host "当前服务状态：$($svc.Status)"

    Write-Host "`n[5] 停服务后 health 检查..." -ForegroundColor Yellow
    $AfterHealth = Test-LolApiHealth
    Write-Host "停服务后接口状态：$AfterHealth"

    if ($AfterHealth) {
        Write-Host "接口仍然正常，说明当前 5001 的 Python 可以继续提供服务。" -ForegroundColor Green
        Set-Service -Name $ServiceName -StartupType Manual -ErrorAction SilentlyContinue
        Write-Host "$ServiceName 已改为手动启动，避免下次开机继续抢 5001。" -ForegroundColor Green
    } else {
        Write-Host "停服务后接口不通，正在把 $ServiceName 服务启动回来..." -ForegroundColor Red
        Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5

        $RecoverHealth = Test-LolApiHealth
        Write-Host "恢复后接口状态：$RecoverHealth"

        if ($RecoverHealth) {
            Write-Host "服务已恢复，接口可用。后续需要再单独整理启动方式。" -ForegroundColor Yellow
        } else {
            Write-Host "恢复后接口仍不可用，需要人工继续排查。" -ForegroundColor Red
        }
    }
} else {
    Write-Host "没有找到 $ServiceName 服务，跳过停止服务。" -ForegroundColor DarkYellow
}

# 8. 显示最终进程状态
Write-Host "`n[6] 当前 Python / PowerShell / NSSM 进程：" -ForegroundColor Yellow
tasklist | findstr /i "python powershell nssm"

Write-Host "`n[7] 当前 5001 端口监听：" -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        LocalPort = $_.LocalPort
        PID = $_.OwningProcess
        ProcessName = $p.ProcessName
        Path = $p.Path
    }
} | Format-Table -AutoSize

Write-Host "`n==== 止血脚本执行完毕 ====" -ForegroundColor Cyan
Write-Host "如果接口状态为 True，说明现在已经先止住了 NSSM 反复重启问题。"
