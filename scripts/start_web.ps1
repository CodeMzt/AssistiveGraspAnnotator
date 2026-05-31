param(
    [string]$DataRoot = "D:\AssistiveGraspAnnotatorData",
    [int]$Port = 8000,
    [string]$HostAddress = "0.0.0.0",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "Repository: $RepoRoot"

$DataRoot = (New-Item -ItemType Directory -Force -Path $DataRoot).FullName
$DatasetsRoot = (New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "datasets")).FullName
$StateDir = (New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "state")).FullName
$LogDir = (New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot "logs")).FullName

$PidFile = Join-Path $LogDir "web_server.pid"
if (Test-Path -LiteralPath $PidFile) {
    $OldPid = [int](Get-Content -LiteralPath $PidFile)
    $OldProcess = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
    if ($OldProcess) {
        Write-Host "Stopping previous service process $OldPid..."
        Stop-Process -Id $OldPid -Force
        Start-Sleep -Milliseconds 700
    }
}

$ExistingListeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ListenerPid in $ExistingListeners) {
    $ListenerProcess = Get-Process -Id $ListenerPid -ErrorAction SilentlyContinue
    if ($ListenerProcess) {
        Write-Host "Stopping existing listener on port $Port, process $ListenerPid..."
        Stop-Process -Id $ListenerPid -Force
    }
}
if ($ExistingListeners) {
    Start-Sleep -Milliseconds 700
}

$FrontendDist = Join-Path $RepoRoot "web_frontend\dist"
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDist "index.html"))) {
    throw "Frontend build not found. Run: cd web_frontend; npm install; npm run build"
}

$env:AGA_HOST = $HostAddress
$env:AGA_PORT = [string]$Port
$env:AGA_DATASET_ROOTS = $DatasetsRoot
$env:AGA_UPLOAD_ROOT = $DatasetsRoot
$env:AGA_STATE_DB = Join-Path $StateDir "aga_state.sqlite3"
$env:AGA_FRONTEND_DIST = $FrontendDist

$OutLog = Join-Path $LogDir "web_server_$Port.out.log"
$ErrLog = Join-Path $LogDir "web_server_$Port.err.log"
Write-Host "Starting service on $HostAddress`:$Port..."
$Process = Start-Process -FilePath $PythonExe `
    -ArgumentList @("-m", "assistive_grasp_annotator.web.server") `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WindowStyle Hidden `
    -PassThru

$Ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 250
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
        if ($Response.StatusCode -eq 200) {
            $Ready = $true
            break
        }
    } catch {
    }
}

if (-not $Ready) {
    $Tail = Get-Content -LiteralPath $ErrLog -ErrorAction SilentlyContinue | Select-Object -Last 30
    throw "Web server did not become ready. stderr:`n$($Tail -join "`n")"
}

$ReadyListenerPid = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -First 1
if ($ReadyListenerPid) {
    $ReadyListenerPid | Set-Content -LiteralPath $PidFile
} else {
    $Process.Id | Set-Content -LiteralPath $PidFile
}

Write-Host ""
Write-Host "Service is ready."
Write-Host "Local:   http://127.0.0.1:$Port/"
$LanAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -notlike "127.*" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
    } |
    Select-Object -ExpandProperty IPAddress -Unique
foreach ($Address in $LanAddresses) {
    Write-Host "LAN:     http://$Address`:$Port/"
}
Write-Host "Data:    $DatasetsRoot"
Write-Host "Logs:    $LogDir"
Write-Host ""

[pscustomobject]@{
    pid = if ($ReadyListenerPid) { $ReadyListenerPid } else { $Process.Id }
    url = "http://127.0.0.1:$Port/"
    data_root = $DataRoot
    datasets_root = $DatasetsRoot
    state_db = $env:AGA_STATE_DB
    stdout_log = $OutLog
    stderr_log = $ErrLog
}
