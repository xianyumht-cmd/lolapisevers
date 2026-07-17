$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Config = Join-Path $Root "lanzou_update_push_api_server\config.json"
$Example = Join-Path $Root "lanzou_update_push_api_server\config.example.json"

if (-not (Test-Path $Config)) {
  Copy-Item $Example $Config
  Write-Host "Created local config: $Config"
}

$env:LANZOU_MONITOR_CONFIG = $Config
Set-Location $Root
python -m lanzou_update_push_api_server
