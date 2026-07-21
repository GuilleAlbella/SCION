# =====================================================================
# dev.ps1 -- SCION local development runner
#
# Boots backend (FastAPI/uvicorn on :8000) and frontend (Next.js on :3000)
# side-by-side, streams both logs to this window, and kills everything
# cleanly on Ctrl+C. Designed for Windows PowerShell 5.1 -- all-ASCII
# content so encoding quirks never break parsing.
# =====================================================================

$ErrorActionPreference = "Stop"

$root        = $PSScriptRoot
$venvPython  = Join-Path $root ".venv\Scripts\python.exe"
$backendDir  = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

# ---- Helpers for bracketed status lines -----------------------------
function Write-Status {
    param(
        [Parameter(Mandatory)][string]$Tag,
        [Parameter(Mandatory)][string]$Message,
        [ConsoleColor]$TagColor = [ConsoleColor]::Cyan
    )
    Write-Host "  [" -NoNewline -ForegroundColor DarkGray
    Write-Host $Tag.PadRight(4) -NoNewline -ForegroundColor $TagColor
    Write-Host "] " -NoNewline -ForegroundColor DarkGray
    Write-Host $Message -ForegroundColor Gray
}

function Write-Ok    { param([string]$Msg) Write-Status "OK"  $Msg Green  }
function Write-Info  { param([string]$Msg) Write-Status "..." $Msg Cyan   }
function Write-Warn  { param([string]$Msg) Write-Status "!"   $Msg Yellow }
function Write-Fail  { param([string]$Msg) Write-Status "X"   $Msg Red    }

# Read APP_VERSION from the frontend constants so the banner shows the
# same string the UI displays. Fallback to "unknown" on any parse
# failure -- nothing here should block startup over a cosmetic label.
function Get-AppVersion {
    $constantsFile = Join-Path $frontendDir "src\lib\constants.ts"
    if (-not (Test-Path $constantsFile)) { return "unknown" }
    try {
        $line = Select-String -Path $constantsFile -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) {
            return $line.Matches[0].Groups[1].Value
        }
    } catch { }
    return "unknown"
}

# ---- Banner ---------------------------------------------------------
Clear-Host
$version = Get-AppVersion
Write-Host ""
Write-Host "  ===========================================================================" -ForegroundColor DarkCyan
Write-Host "  ||                                                                       ||" -ForegroundColor DarkCyan
Write-Host "  ||    SSSSS  CCCCC  III  OOO   N   N                                     ||" -ForegroundColor Cyan
Write-Host "  ||    S      C       I  O   O  NN  N                                     ||" -ForegroundColor Cyan
Write-Host "  ||    SSSSS  C       I  O   O  N N N                                     ||" -ForegroundColor Cyan
Write-Host "  ||        S  C       I  O   O  N  NN                                     ||" -ForegroundColor Cyan
Write-Host "  ||    SSSSS  CCCCC  III  OOO   N   N                                     ||" -ForegroundColor Cyan
Write-Host "  ||                                                                       ||" -ForegroundColor DarkCyan
Write-Host "  ||    Structural Change Intelligence & Observability Node    " -NoNewline -ForegroundColor White
Write-Host $version.PadRight(12) -NoNewline -ForegroundColor DarkGray
Write-Host "||" -ForegroundColor DarkCyan
Write-Host "  ===========================================================================" -ForegroundColor DarkCyan
Write-Host ""

# ---- Pre-flight checks ---------------------------------------------
Write-Host "  Pre-flight checks" -ForegroundColor White
Write-Host "  -----------------" -ForegroundColor DarkGray

if (-not (Test-Path $venvPython)) {
    Write-Fail "Python venv not found at $venvPython"
    Write-Fail "Create it with:"
    Write-Fail "    python -m venv .venv"
    Write-Fail "    .venv\Scripts\pip install -r backend\requirements\dev.txt"
    exit 1
}
Write-Ok "Python venv found"

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Warn "frontend/node_modules missing -- running 'npm install' (one-time)"
    Push-Location $frontendDir
    try { npm install --silent } finally { Pop-Location }
}
Write-Ok "Node modules ready"

$dbFile = Join-Path $root "kalido_lite.db"
$dbInit = Join-Path $root "backend\tools\db_init.py"
if (-not (Test-Path $dbFile)) {
    Write-Warn "kalido_lite.db not found -- run '.venv\Scripts\python.exe backend\tools\db_init.py reset --with-seed' for a fresh DB + demo data"
} else {
    $dbSize = [math]::Round((Get-Item $dbFile).Length / 1KB, 1)
    Write-Ok "Demo database present (${dbSize} KB)"

    # Bring the schema to HEAD before launching uvicorn -- the same
    # idempotent step the Docker entrypoint runs. Without this, pulling
    # code that adds a migration (e.g. Pipeline 3's dbql_query table)
    # leaves the running DB one revision behind, and the first request
    # that touches the new table dies with "no such table". `init` is a
    # no-op when already current.
    Write-Info "Bringing database schema to HEAD (alembic upgrade)..."
    & $venvPython $dbInit init
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "db_init failed -- the DB may be in a legacy/inconsistent state. See output above."
        exit 1
    }
    Write-Ok "Database schema at HEAD"
}

# Port availability: if either port is busy, kill the occupant and
# continue rather than bailing out. This handles the common case where
# a previous dev session left a stale Next.js or uvicorn process running.
function Clear-Port {
    param([int]$Port, [string]$Label)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { "unknown" }
            Write-Warn "Port $Port busy ($name PID $pid) -- killing stale process"
            & taskkill /PID $pid /T /F 2>$null | Out-Null
        } catch { }
    }
    Start-Sleep -Milliseconds 300
}
Clear-Port 8000 "backend"
Clear-Port 3000 "frontend"
Write-Ok "Ports 8000 and 3000 free"
Write-Host ""

# ---- Launch ---------------------------------------------------------
Write-Host "  Launching services" -ForegroundColor White
Write-Host "  ------------------" -ForegroundColor DarkGray

Write-Info "Starting backend (FastAPI + uvicorn, port 8000)..."

# --reload-dir app : watch only the served FastAPI app, not tools/,
# alembic/, or tests/. Editing seed scripts / migrations / tests during
# a live demo would otherwise trigger a reload. On Windows, WatchFiles'
# reload propagates a signal PowerShell interprets as Ctrl+C on this
# parent script, killing the whole stack silently.
$backend = Start-Process -NoNewWindow -PassThru -FilePath $venvPython `
  -ArgumentList "-m","uvicorn","app.main:app","--reload","--reload-dir","app","--port","8000" `
  -WorkingDirectory $backendDir

Write-Info "Starting frontend (Next.js dev, port 3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "cmd.exe" `
  -ArgumentList "/c","npm run dev" `
  -WorkingDirectory $frontendDir

Start-Sleep -Seconds 1
Write-Ok "Backend PID $($backend.Id)"
Write-Ok "Frontend PID $($frontend.Id)"
Write-Host ""

# ---- URLs + tips ----------------------------------------------------
Write-Host "  Service endpoints" -ForegroundColor White
Write-Host "  -----------------" -ForegroundColor DarkGray
Write-Host "   UI     " -NoNewline -ForegroundColor Gray
Write-Host "http://localhost:3000" -ForegroundColor Blue
Write-Host "   API    " -NoNewline -ForegroundColor Gray
Write-Host "http://localhost:8000" -ForegroundColor Blue
Write-Host "   Docs   " -NoNewline -ForegroundColor Gray
Write-Host "http://localhost:8000/docs" -ForegroundColor Blue
Write-Host ""

Write-Host "  Tips" -ForegroundColor White
Write-Host "  ----" -ForegroundColor DarkGray
Write-Host "   * " -NoNewline -ForegroundColor DarkGray
Write-Host "Press " -NoNewline -ForegroundColor Gray
Write-Host "Ctrl+C" -NoNewline -ForegroundColor Yellow
Write-Host " to stop both services cleanly." -ForegroundColor Gray
Write-Host "   * " -NoNewline -ForegroundColor DarkGray
Write-Host "Edit files under " -NoNewline -ForegroundColor Gray
Write-Host "backend\app\" -NoNewline -ForegroundColor Cyan
Write-Host " -> backend auto-reloads." -ForegroundColor Gray
Write-Host "   * " -NoNewline -ForegroundColor DarkGray
Write-Host "Edit files under " -NoNewline -ForegroundColor Gray
Write-Host "frontend\src\" -NoNewline -ForegroundColor Cyan
Write-Host " -> frontend auto-reloads." -ForegroundColor Gray
Write-Host "   * " -NoNewline -ForegroundColor DarkGray
Write-Host "Reseed demo data: " -NoNewline -ForegroundColor Gray
Write-Host "..\.venv\Scripts\python.exe tools\rich_seed.py" -ForegroundColor Cyan
Write-Host ""

Write-Host "  ------------------ Live logs below ------------------" -ForegroundColor DarkGray
Write-Host ""

# ---- Wait loop ------------------------------------------------------
# Poll every 500ms so Ctrl+C gets picked up quickly. Logs from both
# children stream into this console via -NoNewWindow on Start-Process.
try {
    while (-not $backend.HasExited -and -not $frontend.HasExited) {
        Start-Sleep -Milliseconds 500
    }
    # If we fall out naturally, at least one child died on its own --
    # surface which, to help debugging.
    if ($backend.HasExited) {
        Write-Host ""
        Write-Fail "Backend exited unexpectedly (code $($backend.ExitCode))"
    }
    if ($frontend.HasExited) {
        Write-Host ""
        Write-Fail "Frontend exited unexpectedly (code $($frontend.ExitCode))"
    }
} finally {
    Write-Host ""
    Write-Host "  ------------------ Shutting down ------------------" -ForegroundColor DarkGray

    # taskkill /T /F kills the process AND all its children atomically --
    # needed because npm/uvicorn spawn grandchildren that simple Kill()
    # wouldn't catch.
    if (-not $backend.HasExited) {
        Write-Info "Stopping backend..."
        & taskkill /PID $($backend.Id) /T /F 2>$null | Out-Null
    }
    if (-not $frontend.HasExited) {
        Write-Info "Stopping frontend..."
        & taskkill /PID $($frontend.Id) /T /F 2>$null | Out-Null
    }

    # Safety net: anything still holding the ports (rare, but possible
    # after OneDrive or antivirus delayed a child's SIGTERM handling).
    Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
        ForEach-Object { & taskkill /PID $_.OwningProcess /T /F 2>$null | Out-Null }
    Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
        ForEach-Object { & taskkill /PID $_.OwningProcess /T /F 2>$null | Out-Null }

    Write-Ok "All processes stopped. Bye!"
    Write-Host ""
}
