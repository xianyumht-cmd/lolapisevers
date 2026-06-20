$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $projectRoot "ops\app_env.ps1"
if (Test-Path $envFile) {
  . $envFile
}

$baseUrl = if ($env:KEEPALIVE_BASE_URL) { $env:KEEPALIVE_BASE_URL } else { "http://127.0.0.1:5000" }
$name = if ($env:KEEPALIVE_TEST_NAME) { $env:KEEPALIVE_TEST_NAME } else { "testplayer#12345" }
$region = if ($env:KEEPALIVE_TEST_REGION) { $env:KEEPALIVE_TEST_REGION } else { "HN1" }

$logsDir = Join-Path $projectRoot "logs"
if (!(Test-Path $logsDir)) {
  New-Item -Path $logsDir -ItemType Directory | Out-Null
}
$logFile = Join-Path $logsDir "keepalive.log"

function Write-Log([string]$text) {
  $line = "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $text"
  Add-Content -Path $logFile -Value $line
}

try {
  $health = Invoke-RestMethod -Uri "$baseUrl/health" -Method GET -TimeoutSec 8
  if ($health.status -ne "ok") {
    Write-Log "health_status_not_ok: $($health | ConvertTo-Json -Compress)"
    exit 1
  }

  $uri = "$baseUrl/cross_query?output=pretty&name=$([uri]::EscapeDataString($name))&region=$([uri]::EscapeDataString($region))"
  $res = Invoke-RestMethod -Uri $uri -Method GET -TimeoutSec 60
  if ($null -eq $res) {
    Write-Log "cross_query_empty_response"
    exit 1
  }

  if ($res.error) {
    Write-Log "cross_query_error: $($res.error)"
    exit 1
  }

  $okFlag = $false
  if ($res.raw_ok -eq $true) {
    $okFlag = $true
  } elseif ($res.recent_matches -and $res.recent_matches.Count -gt 0) {
    $okFlag = $true
  } elseif ($res.name) {
    $okFlag = $true
  }

  if ($okFlag) {
    $matchCount = if ($res.recent_matches) { [int]$res.recent_matches.Count } else { 0 }
    Write-Log "ok name=$($res.name) region=$($res.region) matches=$matchCount"
    exit 0
  }

  Write-Log "cross_query_no_valid_data: $($res | ConvertTo-Json -Compress -Depth 4)"
  exit 1
} catch {
  $detail = $_.Exception.Message
  try {
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream) {
      $stream = $_.Exception.Response.GetResponseStream()
      if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        if ($body) {
          $detail = "$detail | body=$body"
        }
      }
    }
  } catch {}
  Write-Log "exception: $detail"
  exit 1
}
