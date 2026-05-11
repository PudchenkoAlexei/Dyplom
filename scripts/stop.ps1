$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$RunDir = Join-Path $RootDir ".run"

function Stop-PidFile($Name) {
    $pidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return
    }

    $processId = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($processId) {
        Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Name process: $processId"
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-PortListener($Port) {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        if ($listener.OwningProcess -ne 0) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped listener on port ${Port}: $($listener.OwningProcess)"
        }
    }
}

Set-Location $RootDir

Stop-PidFile "backend"
Stop-PidFile "frontend"

Stop-PortListener 8000
Stop-PortListener 3000

if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose down
}

Write-Host ""
Write-Host "Stopped local project services." -ForegroundColor Green
