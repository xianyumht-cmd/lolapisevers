param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$TargetRef = "origin/release/lapi-query-hardening-20260729",
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedCommit,
    [string]$RequiredAncestor = "bbc8ea2d2687820e4c4a3b400c7568a771f10519",
    [string]$ServiceName = "LOLDataSystem",
    [string]$BaseUrl = "http://127.0.0.1:5001",
    [string]$Hero = "Yasuo",
    [ValidatePattern("^$|^[0-9]{5,11}$")]
    [string]$BanQQ = "",
    [string]$BackupRoot = "",
    [switch]$SkipDependencyInstall,
    [switch]$SkipFullTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "请右键 PowerShell，选择‘以管理员身份运行’后重新执行。"
    }
}

function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $output = & git -C $ProjectRoot @Arguments 2>&1
    $code = $LASTEXITCODE
    if (-not $AllowFailure -and $code -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return [pscustomobject]@{ ExitCode = $code; Output = @($output) }
}

function Resolve-ServiceName {
    param([string]$RequestedName)
    if (Get-Service -Name $RequestedName -ErrorAction SilentlyContinue) {
        return $RequestedName
    }
    $matches = @(
        Get-CimInstance Win32_Service -ErrorAction Stop |
            Where-Object {
                $path = "$($_.PathName)"
                $path -and $path.IndexOf($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                    $path.IndexOf("run_service.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
    if ($matches.Count -eq 1) {
        return "$($matches[0].Name)"
    }
    if ($matches.Count -gt 1) {
        throw "检测到多个指向本项目的 Windows 服务，请用 -ServiceName 明确指定。"
    }
    throw "未找到 Windows 服务 '$RequestedName'，也无法从服务 PathName 自动识别本项目。"
}

function Wait-ServiceState {
    param([string]$Name, [string]$Desired, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $service = Get-Service -Name $Name -ErrorAction Stop
        if ($service.Status.ToString() -eq $Desired) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "服务 $Name 未在 $TimeoutSeconds 秒内进入 $Desired 状态。"
}

function Stop-ReleaseService {
    param([string]$Name)
    $service = Get-Service -Name $Name -ErrorAction Stop
    if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
        Stop-Service -Name $Name -Force -ErrorAction Stop
        Wait-ServiceState -Name $Name -Desired "Stopped"
    }
}

function Start-ReleaseService {
    param([string]$Name)
    Start-Service -Name $Name -ErrorAction Stop
    Wait-ServiceState -Name $Name -Desired "Running"
}

function Resolve-Python {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }
    return (Get-Command python -ErrorAction Stop).Source
}

function Protect-BackupDirectory {
    param([string]$Path)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path /inheritance:r /grant:r "$identity`:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "无法限制备份目录 ACL，已停止发布：$Path"
    }
}

function Add-BackupItem {
    param(
        [string]$RelativePath,
        [System.Collections.Generic.List[object]]$Manifest
    )
    $source = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        return
    }
    $destination = Join-Path $script:BackupDirectory (Join-Path "files" $RelativePath)
    $parent = Split-Path -Parent $destination
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ((Get-Item -LiteralPath $source).PSIsContainer) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
        $kind = "directory"
    } else {
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $kind = "file"
    }
    $Manifest.Add([ordered]@{ relative_path = $RelativePath; kind = $kind }) | Out-Null
}

function Write-DeploymentRecord {
    param([object]$Record)
    [System.IO.File]::WriteAllText(
        $script:RecordPath,
        (($Record | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Invoke-ReleaseTests {
    param([string]$PythonExe)
    if ($SkipFullTests) {
        Write-Warning "已按参数跳过完整单元测试。"
        return
    }
    & $PythonExe -m unittest discover -s (Join-Path $ProjectRoot "tests") -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
        throw "完整 Python 单元测试失败。"
    }
}

Assert-Administrator
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BaseUrl = $BaseUrl.TrimEnd("/")
$ExpectedCommit = $ExpectedCommit.ToLowerInvariant()
$RequiredAncestor = $RequiredAncestor.ToLowerInvariant()

$remoteUrlResult = Invoke-Git -Arguments @("remote", "get-url", "origin")
$remoteUrl = ($remoteUrlResult.Output -join "").Trim()
if ($remoteUrl -notmatch "github\.com[/:]xianyumht-cmd/lolapisevers(?:\.git)?$") {
    throw "origin 不是预期仓库：$remoteUrl"
}

$dirty = Invoke-Git -Arguments @("status", "--porcelain", "--untracked-files=no")
if (($dirty.Output -join "").Trim()) {
    throw "检测到已跟踪文件未提交改动。为防止覆盖本地代码，发布已停止。"
}

Write-Output "Fetching release branch..."
Invoke-Git -Arguments @("fetch", "--no-tags", "origin", "release/lapi-query-hardening-20260729") | Out-Null
$resolvedTarget = ((Invoke-Git -Arguments @("rev-parse", "$TargetRef^{commit}")).Output -join "").Trim().ToLowerInvariant()
if ($resolvedTarget -ne $ExpectedCommit) {
    throw "目标提交不匹配：expected=$ExpectedCommit resolved=$resolvedTarget"
}

$ancestorCheck = Invoke-Git -Arguments @("merge-base", "--is-ancestor", $RequiredAncestor, $ExpectedCommit) -AllowFailure
if ($ancestorCheck.ExitCode -ne 0) {
    throw "目标提交不包含必需生产祖先 $RequiredAncestor。"
}

$previousCommit = ((Invoke-Git -Arguments @("rev-parse", "HEAD")).Output -join "").Trim().ToLowerInvariant()
$currentAncestorCheck = Invoke-Git -Arguments @("merge-base", "--is-ancestor", $previousCommit, $ExpectedCommit) -AllowFailure
if ($currentAncestorCheck.ExitCode -ne 0) {
    throw "当前本地提交 $previousCommit 不是目标发布的祖先。请先确认本地仓库来源。"
}

$previousBranchResult = Invoke-Git -Arguments @("symbolic-ref", "--short", "-q", "HEAD") -AllowFailure
$previousBranch = ($previousBranchResult.Output -join "").Trim()
$ServiceName = Resolve-ServiceName -RequestedName $ServiceName
$serviceBefore = Get-Service -Name $ServiceName -ErrorAction Stop
$wasRunning = $serviceBefore.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Running

if (-not $BackupRoot) {
    $parent = Split-Path -Parent $ProjectRoot
    $leaf = Split-Path -Leaf $ProjectRoot
    $BackupRoot = Join-Path $parent "$leaf.deploy-backups"
}
if (-not (Test-Path -LiteralPath $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$script:BackupDirectory = Join-Path $BackupRoot "$timestamp-lapi-query-hardening"
New-Item -ItemType Directory -Path $script:BackupDirectory -Force | Out-Null
Protect-BackupDirectory -Path $script:BackupDirectory
$script:RecordPath = Join-Path $script:BackupDirectory "deployment-record.json"

$backupItems = New-Object 'System.Collections.Generic.List[object]'
Add-BackupItem -RelativePath "ops\app_env.local.ps1" -Manifest $backupItems
Add-BackupItem -RelativePath "build-info.json" -Manifest $backupItems
Add-BackupItem -RelativePath "lanzou_update_push_api_server\config.json" -Manifest $backupItems
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "lanzou_update_push_api_server") -Filter "state*.json" -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        $relative = "lanzou_update_push_api_server\$($_.Name)"
        Add-BackupItem -RelativePath $relative -Manifest $backupItems
    }
Add-BackupItem -RelativePath "data\upstream_snapshots" -Manifest $backupItems

$record = [ordered]@{
    schema_version = "lapi-query-hardening-deployment.v1"
    deployment_id = "$timestamp-lapi-query-hardening"
    started_at = [DateTime]::UtcNow.ToString("o")
    status = "prepared"
    project_root = $ProjectRoot
    remote_url = $remoteUrl
    previous_commit = $previousCommit
    previous_branch = $previousBranch
    target_commit = $ExpectedCommit
    target_ref = $TargetRef
    required_ancestor = $RequiredAncestor
    service_name = $ServiceName
    service_was_running = $wasRunning
    base_url = $BaseUrl
    hero = $Hero
    ban_check = $(if ($BanQQ) { "enabled" } else { "skipped" })
    backup_items = @($backupItems)
    verification_report = "verification-report.json"
    failure = $null
    rollback = $null
}
Write-DeploymentRecord -Record $record

$deploymentStarted = $false
try {
    Write-Output "Stopping service $ServiceName..."
    Stop-ReleaseService -Name $ServiceName
    $deploymentStarted = $true
    $record.status = "service_stopped"
    Write-DeploymentRecord -Record $record

    Write-Output "Checking out release commit $ExpectedCommit..."
    Invoke-Git -Arguments @("checkout", "--detach", $ExpectedCommit) | Out-Null
    $record.status = "source_updated"
    Write-DeploymentRecord -Record $record

    $pythonExe = Resolve-Python
    if (-not $SkipDependencyInstall) {
        & $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
        if ($LASTEXITCODE -ne 0) {
            throw "依赖安装失败。"
        }
    }

    Invoke-ReleaseTests -PythonExe $pythonExe

    $generator = Join-Path $ProjectRoot "scripts\Generate-BuildInfo.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $generator -Release "lapi-query-hardening-20260729"
    if ($LASTEXITCODE -ne 0) {
        throw "build-info 生成失败。"
    }

    $record.status = "validated_before_start"
    Write-DeploymentRecord -Record $record

    Write-Output "Starting service $ServiceName..."
    Start-ReleaseService -Name $ServiceName
    $record.status = "service_started"
    Write-DeploymentRecord -Record $record

    $verificationScript = Join-Path $ProjectRoot "ops\Test-LapiQueryHardening.ps1"
    $verificationPath = Join-Path $script:BackupDirectory "verification-report.json"
    $verifyArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $verificationScript,
        "-ProjectRoot", $ProjectRoot,
        "-BaseUrl", $BaseUrl,
        "-ExpectedCommit", $ExpectedCommit,
        "-Hero", $Hero,
        "-OutputPath", $verificationPath
    )
    if ($BanQQ) {
        $verifyArgs += @("-BanQQ", $BanQQ)
    }
    & powershell.exe @verifyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "生产验收脚本失败。"
    }

    $record.status = "completed"
    $record.completed_at = [DateTime]::UtcNow.ToString("o")
    Write-DeploymentRecord -Record $record
    Write-Output "============================================================"
    Write-Output "LAPI query hardening deployment completed successfully."
    Write-Output "Commit : $ExpectedCommit"
    Write-Output "Service: $ServiceName"
    Write-Output "Backup : $script:BackupDirectory"
    Write-Output "Report : $verificationPath"
    Write-Output "============================================================"
} catch {
    $message = $_.Exception.Message
    Write-Error "发布失败：$message"
    $record.status = "failed"
    $record.failure = [ordered]@{
        at = [DateTime]::UtcNow.ToString("o")
        message = $message
        type = $_.Exception.GetType().FullName
    }
    Write-DeploymentRecord -Record $record

    if ($deploymentStarted) {
        Write-Warning "开始自动回滚到 $previousCommit"
        $rollbackScript = Join-Path $ProjectRoot "ops\Rollback-LapiQueryHardening.ps1"
        if (-not (Test-Path -LiteralPath $rollbackScript -PathType Leaf)) {
            $rollbackScript = Join-Path $script:BackupDirectory "Rollback-LapiQueryHardening.ps1"
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rollbackScript `
            -ProjectRoot $ProjectRoot `
            -BackupDirectory $script:BackupDirectory `
            -ServiceName $ServiceName `
            -BaseUrl $BaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "发布失败且自动回滚也失败。请保留备份目录：$script:BackupDirectory"
        }
    }
    throw
}
