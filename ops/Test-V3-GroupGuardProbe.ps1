param(
    [Parameter(Mandatory = $true)][string]$DistRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$zipFile = @(Get-ChildItem -LiteralPath $DistRoot -Filter "*.zip" -File)
if ($zipFile.Count -ne 1) { throw "Expected one final V3 ZIP." }

$tempRoot = Join-Path $env:RUNNER_TEMP ("groupguard-verifier-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $zipFile[0].FullName -DestinationPath $tempRoot
    $verifiers = @(Get-ChildItem -LiteralPath $tempRoot -Filter "Verify-FullBugRepairProduction.ps1" -File -Recurse)
    if ($verifiers.Count -ne 1) { throw "Expected one packaged verifier." }
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $verifiers[0].FullName, [ref]$tokens, [ref]$errors
    )
    if ($errors.Count -gt 0) { throw "Packaged verifier has syntax errors." }
    $functions = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-VerifiedGroupGuardRequest"
    }, $true))
    if ($functions.Count -ne 1) { throw "Packaged verifier helper is not unique." }
    . ([scriptblock]::Create($functions[0].Extent.Text))

    $script:Scenario = ""
    $script:Calls = 0
    $script:FreshConnections = 0
    $valid = '{"protocol":"groupguard-query-delivery.v1","ok":true,"delivery":{"segments":[{"type":"text","text":"ready"}]}}'

    # Mock only the transport; the shipped verifier helper is real.
    function Invoke-WebRequest {
        param(
            [string]$Uri, [string]$Method,
            [switch]$UseBasicParsing, [switch]$DisableKeepAlive,
            [hashtable]$Headers, [string]$ContentType, [byte[]]$Body,
            [int]$TimeoutSec
        )
        $script:Calls++
        if (-not $DisableKeepAlive) {
            throw "Disabled keep-alive is mandatory for the post-switch probe."
        }
        $script:FreshConnections++
        if ($script:Scenario -eq "transient" -and $script:Calls -eq 1) {
            throw ([System.Net.WebException]::new(
                "connection closed",
                [System.Net.WebExceptionStatus]::ConnectionClosed
            ))
        }
        if ($script:Scenario -eq "permanent") {
            throw ([System.InvalidOperationException]::new("permanent"))
        }
        if ($script:Scenario -eq "invalid") {
            return [pscustomobject]@{
                StatusCode = 200
                Content = '{"protocol":"unexpected","ok":false,"delivery":{"segments":[]}}'
            }
        }
        return [pscustomobject]@{ StatusCode = 200; Content = $valid }
    }
    function Start-Sleep { param([int]$Seconds) }

    $payload = @{
        feature = "shard"
        parameters = @{ hero = "Yasuo" }
        preferred = "text"
        capabilities = @{ text = $true; image = $false; forward = $true }
    }
    $url = "http://127.0.0.1:5001/api/v1/groupguard/query"

    $script:Scenario = "success"
    $script:Calls = 0
    $success = Invoke-VerifiedGroupGuardRequest -Uri $url -Body $payload -Feature shard
    if ($script:Calls -ne 1 -or $success.StatusCode -ne 200 -or $success.Body.ok -ne $true) {
        throw "Healthy delivery was not accepted."
    }

    $script:Scenario = "transient"
    $script:Calls = 0
    $success = Invoke-VerifiedGroupGuardRequest -Uri $url -Body $payload -Feature shard
    if ($script:Calls -ne 2 -or $success.Body.ok -ne $true) {
        throw "Transient failure must retry and then verify a real successful delivery."
    }

    $script:Scenario = "invalid"
    $script:Calls = 0
    $rejected = $false
    try {
        Invoke-VerifiedGroupGuardRequest -Uri $url -Body $payload -Feature shard | Out-Null
    } catch { $rejected = $true }
    if (-not $rejected -or $script:Calls -ne 1) {
        throw "Invalid protocol or delivery must fail closed without retry."
    }

    $script:Scenario = "permanent"
    $script:Calls = 0
    $rejected = $false
    try {
        Invoke-VerifiedGroupGuardRequest -Uri $url -Body $payload -Feature shard | Out-Null
    } catch { $rejected = $true }
    if (-not $rejected -or $script:Calls -ne 1) {
        throw "Permanent error must not retry."
    }

    if ($script:FreshConnections -ne 5) {
        throw "Every HTTP attempt must disable persistent connection reuse."
    }
    Write-Host "GroupGuard verification smoke tests passed."
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
