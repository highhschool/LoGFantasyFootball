<#
.SYNOPSIS
    Start (or stop) the NGFL Drafter app and confirm it is reachable.

.DESCRIPTION
    One command to bring the site back up after a reboot. The Cloudflare tunnel
    already runs as an automatic Windows service, so this only has to start the
    API behind it -- then it verifies the whole path end to end: the local port,
    the tunnel service, and the public URL.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Stop
    .\start.ps1 -Port 8001 -Season 2025
#>

[CmdletBinding()]
param(
    [switch]$Stop,
    [int]$Port = 8000,
    [string]$Season,
    [string]$PublicUrl = "https://ngfldrafter.com",
    [switch]$SkipPublicCheck
)

$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$LogDir  = Join-Path $Root "logs"
$Service = "Cloudflared"

function Write-Step { param($Text) Write-Host "`n$Text" -ForegroundColor Cyan }
function Write-Ok   { param($Text) Write-Host "  [ok]   $Text" -ForegroundColor Green }
function Write-Warn { param($Text) Write-Host "  [warn] $Text" -ForegroundColor Yellow }
function Write-Bad  { param($Text) Write-Host "  [fail] $Text" -ForegroundColor Red }

function Get-Listener {
    param([int]$OnPort)
    try {
        return Get-NetTCPConnection -LocalPort $OnPort -State Listen -ErrorAction Stop |
               Select-Object -First 1
    } catch {
        return $null
    }
}

function Stop-App {
    param([int]$OnPort)
    $listener = Get-Listener -OnPort $OnPort
    if ($null -eq $listener) {
        Write-Ok "nothing was running on port $OnPort"
        return
    }
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    Write-Ok "stopped PID $($listener.OwningProcess) on port $OnPort"
}

# ---------------------------------------------------------------- stop mode

if ($Stop) {
    Write-Step "Stopping NGFL Drafter"
    Stop-App -OnPort $Port
    Write-Host "`nThe tunnel service is left running; it will serve 502 until the app is back." -ForegroundColor DarkGray
    return
}

# ---------------------------------------------------------------- start

Write-Host "NGFL Drafter" -ForegroundColor White
Write-Host "============" -ForegroundColor White

if (-not (Test-Path $Backend)) {
    Write-Bad "backend not found at $Backend"
    exit 1
}
if ($Season) { $env:SEASON = $Season }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

Write-Step "1. API"

$existing = Get-Listener -OnPort $Port
if ($null -ne $existing) {
    Write-Warn "port $Port already in use by PID $($existing.OwningProcess), restarting it"
    Stop-App -OnPort $Port
}

$stamp   = Get-Date -Format "yyyy-MM-dd"
$outLog  = Join-Path $LogDir "api-$stamp.log"
$errLog  = Join-Path $LogDir "api-$stamp.err.log"

# Bound to loopback deliberately: the tunnel reaches it, the LAN cannot.
$proc = Start-Process python `
    -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$Port" `
    -WorkingDirectory $Backend `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError  $errLog `
    -WindowStyle Hidden `
    -PassThru

Write-Ok "started PID $($proc.Id), logging to logs\api-$stamp.log"

Write-Step "2. Waiting for it to answer"

$health   = $null
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 600
    if ($proc.HasExited) {
        Write-Bad "the API exited immediately (exit code $($proc.ExitCode))"
        Write-Host "`n--- last lines of $errLog ---" -ForegroundColor DarkGray
        if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
        exit 1
    }
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        break
    } catch {
        $health = $null
    }
}

if ($null -eq $health) {
    Write-Bad "no response on http://127.0.0.1:$Port after 30s"
    if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
    exit 1
}

if ($health.status -eq "ok") {
    Write-Ok "$($health.players_loaded) players loaded from $($health.rankings) (season $($health.season))"
} else {
    Write-Warn "API is up but degraded: $($health.error)"
    Write-Warn "run build_rankings.py in FantasyDrafterAI, then .\start.ps1 again"
}

Write-Step "3. Cloudflare tunnel"

$svc = Get-Service -Name $Service -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    Write-Warn "the '$Service' service is not installed; the site will only be reachable locally"
} elseif ($svc.Status -ne "Running") {
    Write-Warn "'$Service' is $($svc.Status), starting it"
    try {
        Start-Service $Service
        Write-Ok "'$Service' started"
    } catch {
        Write-Bad "could not start '$Service' (needs an elevated shell): $($_.Exception.Message)"
    }
} else {
    Write-Ok "'$Service' is running"
}

if (-not $SkipPublicCheck) {
    Write-Step "4. Public URL"

    # Once Cloudflare Access is enabled, an unauthenticated request is bounced
    # to a login page rather than reaching the API. That is the desired state,
    # not a failure, so distinguish "locked down" from "actually broken".
    $protected = $false
    $reached   = $false
    $payload   = $null

    try {
        $resp = Invoke-WebRequest "$PublicUrl/api/health" -UseBasicParsing -TimeoutSec 20 -MaximumRedirection 0
        $reached = $true
        if ($resp.Headers['Content-Type'] -match 'application/json') {
            $payload = $resp.Content | ConvertFrom-Json
        } else {
            $protected = $true
        }
    } catch {
        $code = $null
        if ($null -ne $_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }

        if ($code -in @(301, 302, 303, 307, 308, 401, 403)) {
            $reached   = $true
            $protected = $true
        } else {
            Write-Bad "$PublicUrl did not answer: $($_.Exception.Message)"
            Write-Host "  the tunnel may still be reconnecting; give it a few seconds and retry" -ForegroundColor DarkGray
        }
    }

    if ($reached -and $protected) {
        Write-Ok "$PublicUrl is up and behind Cloudflare Access (login required)"
        Write-Host "  sign in through a browser to use it; this check cannot" -ForegroundColor DarkGray
    } elseif ($null -ne $payload) {
        if ($payload.players_loaded -eq $health.players_loaded) {
            Write-Ok "$PublicUrl is serving this instance"
        } else {
            Write-Warn "$PublicUrl answered, but with different data than the local instance"
        }
        Write-Host "  open to the public (no Access policy) - intended for now" -ForegroundColor DarkGray
    }
}

Write-Host "`n  Local  : http://localhost:$Port" -ForegroundColor White
Write-Host "  Public : $PublicUrl" -ForegroundColor White
Write-Host "  Stop   : .\start.ps1 -Stop`n" -ForegroundColor DarkGray
