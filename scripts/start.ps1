param(
    [switch]$SkipInstall,
    [switch]$SkipPbx,
    [switch]$SkipLlama,
    [switch]$NoOpen,
    [string]$LlamaModel = "Qwen/Qwen3-4B-GGUF:Q4_K_M",
    [string]$LlamaAlias = "Qwen3-4B-KPI-Assistant-Q4_K_M",
    [int]$LlamaPort = 8080,
    [int]$LlamaContextTokens = 8192,
    [int]$LlamaPredictTokens = 1200,
    [int]$LlamaGpuLayers = 99,
    [int]$LlamaThreads = 0,
    [switch]$LlamaFlashAttention
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$RunDir = Join-Path $RootDir ".run"
$BackendLog = Join-Path $RunDir "backend.out.log"
$BackendErr = Join-Path $RunDir "backend.err.log"
$FrontendLog = Join-Path $RunDir "frontend.out.log"
$FrontendErr = Join-Path $RunDir "frontend.err.log"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortFree($Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -eq $listener
}

function Test-UdpPortFree($Port) {
    $listener = Get-NetUDPEndpoint -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -eq $listener
}

function Wait-HttpOk($Url, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Wait-LlamaReady($Port, $TimeoutSeconds) {
    $url = "http://127.0.0.1:$Port/v1/models"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $url -TimeoutSec 3
            if ($response.data -or $response.object -eq "list") {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Wait-DockerReady {
    try {
        docker info *> $null
    } catch {
        $global:LASTEXITCODE = 1
    }
    if ($LASTEXITCODE -eq 0) {
        return
    }

    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path -LiteralPath $dockerDesktop) {
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    } else {
        throw "Docker is not running and Docker Desktop was not found at $dockerDesktop"
    }

    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        try {
            docker info *> $null
        } catch {
            $global:LASTEXITCODE = 1
        }
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 5
    }
    throw "Docker did not become ready in time."
}

function Wait-PostgresHealthy {
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect -f "{{.State.Health.Status}}" kpi-helpdesk-postgres 2>$null
        if ($status -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 3
    }
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    throw "PostgreSQL container did not become healthy in time."
}

function Resolve-Python {
    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    if (Test-Command "python") {
        return "python"
    }
    throw "Python was not found. Install Python 3.11+ or create backend\.venv."
}

function Ensure-BackendDependencies($PythonExe) {
    if ($SkipInstall) {
        return $PythonExe
    }

    & $PythonExe -c "import fastapi, sqlalchemy, asyncpg, alembic" *> $null
    if ($LASTEXITCODE -eq 0) {
        return $PythonExe
    }

    Write-Host "Backend dependencies are missing. Creating backend virtual environment..."
    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        python -m venv (Join-Path $BackendDir ".venv")
    }

    & $venvPython -m pip install --upgrade pip
    Push-Location $BackendDir
    try {
        & $venvPython -m pip install -e ".[dev]"
    } finally {
        Pop-Location
    }
    return $venvPython
}

function Ensure-FrontendDependencies {
    if ($SkipInstall) {
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Frontend dependencies are missing. Running npm install..."
        Push-Location $FrontendDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }
}

function Start-Backend($PythonExe) {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000") `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErr `
        -PassThru
    Set-Content -Path (Join-Path $RunDir "backend.pid") -Value $process.Id
}

function Start-Frontend {
    $process = Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000") `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError $FrontendErr `
        -PassThru
    Set-Content -Path (Join-Path $RunDir "frontend.pid") -Value $process.Id
}

function Start-LlamaServer {
    $scriptPath = Join-Path $ScriptDir "start_llama_cpp.ps1"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "start_llama_cpp.ps1 was not found."
    }

    $arguments = @{
        Model = $LlamaModel
        Alias = $LlamaAlias
        Port = $LlamaPort
        ContextTokens = $LlamaContextTokens
        PredictTokens = $LlamaPredictTokens
        GpuLayers = $LlamaGpuLayers
        Threads = $LlamaThreads
    }
    if ($LlamaFlashAttention) {
        $arguments["FlashAttention"] = $true
    }

    & $scriptPath @arguments
}

Set-Location $RootDir
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

Write-Step "Checking local environment"
if (-not (Test-Command "docker")) {
    throw "Docker CLI was not found. Install Docker Desktop."
}
if (-not (Test-Command "npm")) {
    throw "npm was not found. Install Node.js."
}
if (-not (Test-Path -LiteralPath (Join-Path $RootDir ".env"))) {
    Copy-Item -LiteralPath (Join-Path $RootDir ".env.example") -Destination (Join-Path $RootDir ".env")
    Write-Host "Created .env from .env.example"
}

if (-not (Test-PortFree 8000)) {
    throw "Port 8000 is already busy. Run .\scripts\stop.ps1 first."
}
if (-not (Test-PortFree 3000)) {
    throw "Port 3000 is already busy. Run .\scripts\stop.ps1 first."
}
if (-not $SkipPbx -and -not (Test-UdpPortFree 5060)) {
    throw "UDP port 5060 is already busy. Close the other SIP/PBX service or run with -SkipPbx."
}
if (-not $SkipPbx -and -not (Test-PortFree 8088)) {
    throw "Port 8088 is already busy. Close the other PBX WebSocket service or run with -SkipPbx."
}

$PythonExe = Resolve-Python
$PythonExe = Ensure-BackendDependencies $PythonExe
Ensure-FrontendDependencies

Write-Step "Starting PostgreSQL and PBX"
Wait-DockerReady
if ($SkipPbx) {
    docker compose up -d postgres
} else {
    docker compose up -d --build postgres asterisk
}
Wait-PostgresHealthy

Write-Step "Preparing database"
Push-Location $BackendDir
try {
    & $PythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed."
    }
    & $PythonExe -m app.db.seed
    if ($LASTEXITCODE -ne 0) {
        throw "Database seed failed."
    }
} finally {
    Pop-Location
}

if (-not $SkipLlama) {
    Write-Step "Starting local LLM inference"
    Start-LlamaServer
    $llamaReady = Wait-LlamaReady $LlamaPort 180
    if (-not $llamaReady) {
        Write-Host "llama-server did not answer in time. See .run\llama-server.err.log" -ForegroundColor Yellow
    }
}

Write-Step "Starting backend and frontend"
Start-Backend $PythonExe
Start-Frontend

$backendReady = Wait-HttpOk "http://127.0.0.1:8000/health" 90
$frontendReady = Wait-HttpOk "http://127.0.0.1:3000/login" 90

if (-not $backendReady) {
    Write-Host "Backend did not answer in time. See $BackendErr" -ForegroundColor Yellow
}
if (-not $frontendReady) {
    Write-Host "Frontend did not answer in time. See $FrontendErr" -ForegroundColor Yellow
}

Write-Step "Project is running"
Write-Host "Site:     http://127.0.0.1:3000/login" -ForegroundColor Green
Write-Host "API:      http://127.0.0.1:8000/health" -ForegroundColor Green
if (-not $SkipPbx) {
    Write-Host "PBX:      SIP 127.0.0.1:5060, WebRTC ws://127.0.0.1:8088/ws, call 7000" -ForegroundColor Green
}
if (-not $SkipLlama) {
    Write-Host "LLM:      http://127.0.0.1:$LlamaPort/v1 ($LlamaAlias)" -ForegroundColor Green
}
Write-Host ""
Write-Host "Users:"
Write-Host "  student@kpi.ua   / StudentPassword123!"
Write-Host "  teacher@kpi.ua   / TeacherPassword123!"
Write-Host "  operator1@kpi.ua / OperatorPassword123!"
Write-Host "  operator2@kpi.ua / OperatorPassword123!"
Write-Host "  admin@kpi.ua     / AdminPassword123!"
Write-Host ""
Write-Host "Stop command: .\scripts\stop.ps1"

if (-not $NoOpen -and $frontendReady) {
    Start-Process "http://127.0.0.1:3000/login"
}
