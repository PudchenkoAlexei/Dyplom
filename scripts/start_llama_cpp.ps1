param(
    [string]$Model = "Qwen/Qwen3-4B-GGUF:Q4_K_M",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8080,
    [int]$ContextTokens = 8192,
    [int]$PredictTokens = 1200,
    [int]$GpuLayers = 99,
    [int]$Threads = 0,
    [switch]$FlashAttention
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runDir = Join-Path $repoRoot ".run"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$serverCommand = Get-Command llama-server -ErrorAction SilentlyContinue
if (-not $serverCommand) {
    $localServer = Join-Path $repoRoot "tools\llama.cpp\llama-server.exe"
    if (Test-Path $localServer) {
        $serverPath = $localServer
    } else {
        throw "llama-server was not found. Install llama.cpp and make llama-server available in PATH, or place llama-server.exe at tools\llama.cpp\llama-server.exe."
    }
} else {
    $serverPath = $serverCommand.Source
}

$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
    Write-Host "llama-server already appears to be listening on port $Port."
    exit 0
}

$arguments = @(
    "-hf", $Model,
    "--host", $HostName,
    "--port", [string]$Port,
    "--jinja",
    "-c", [string]$ContextTokens,
    "-n", [string]$PredictTokens,
    "--temp", "0",
    "--top-p", "1",
    "--reasoning", "off",
    "--reasoning-format", "none",
    "--reasoning-budget", "0",
    "--parallel", "1",
    "--cache-ram", "0",
    "--no-context-shift"
)

if ($GpuLayers -ge 0) {
    $arguments += @("-ngl", [string]$GpuLayers)
}
if ($Threads -gt 0) {
    $arguments += @("-t", [string]$Threads)
}
if ($FlashAttention) {
    $arguments += @("--flash-attn", "auto")
}

$stdout = Join-Path $runDir "llama-server.out.log"
$stderr = Join-Path $runDir "llama-server.err.log"
$process = Start-Process `
    -FilePath $serverPath `
    -ArgumentList $arguments `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$process.Id | Set-Content -Path (Join-Path $runDir "llama-server.pid")
Write-Host "Started llama-server process: $($process.Id)"
Write-Host "Endpoint: http://$HostName`:$Port/v1"
Write-Host "Logs: $stdout"
