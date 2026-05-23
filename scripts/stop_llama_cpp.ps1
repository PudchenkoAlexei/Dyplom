$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pidPath = Join-Path $repoRoot ".run\llama-server.pid"

if (Test-Path $pidPath) {
    $processId = [int](Get-Content -Path $pidPath -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -Force
        Write-Host "Stopped llama-server process: $processId"
    }
    Remove-Item -LiteralPath $pidPath -Force
    exit 0
}

$processes = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "^llama-server(\.exe)?$" }

foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force
    Write-Host "Stopped llama-server process: $($process.ProcessId)"
}

if (-not $processes) {
    Write-Host "No llama-server process found."
}
