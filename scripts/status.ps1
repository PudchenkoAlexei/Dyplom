$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

Set-Location $RootDir

Write-Host "Ports:" -ForegroundColor Cyan
$ports = Get-NetTCPConnection -LocalPort 3000,8000,8088,5432 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, State, OwningProcess
if ($ports) {
    $ports | Format-Table -AutoSize
} else {
    Write-Host "  No listeners on 3000, 8000, 8088 or 5432."
}

$udpPorts = Get-NetUDPEndpoint -LocalPort 5060 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
if ($udpPorts) {
    Write-Host ""
    Write-Host "UDP:" -ForegroundColor Cyan
    $udpPorts | Format-Table -AutoSize
}

Write-Host ""
Write-Host "Docker:" -ForegroundColor Cyan
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker ps --filter "name=kpi-helpdesk" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
} else {
    Write-Host "  Docker CLI not found."
}

Write-Host ""
Write-Host "HTTP:" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
    Write-Host "  Backend:  OK ($($health.status))" -ForegroundColor Green
} catch {
    Write-Host "  Backend:  not responding"
}

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/login" -UseBasicParsing -TimeoutSec 3
    Write-Host "  Frontend: OK ($($response.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  Frontend: not responding"
}
