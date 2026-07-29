#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$InstallRoot = "C:\EleganceServer",
  [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$TaskName = "Elegance Server"
$Source = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $InstallRoot "app"
$DataDir = Join-Path $InstallRoot "data"
$LogsDir = Join-Path $InstallRoot "logs"
$BackupRoot = Join-Path $InstallRoot "updates"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PreviousApp = Join-Path $BackupRoot "app-$Stamp"

Write-Host "" 
Write-Host "Elegance - Correccion Bloque 8" -ForegroundColor Cyan
Write-Host "Se conservaran datos, imagenes, base y configuracion." -ForegroundColor Gray

New-Item -ItemType Directory -Force -Path $InstallRoot,$DataDir,$LogsDir,$BackupRoot | Out-Null

# Detener la tarea registrada antes de sustituir archivos.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
  Write-Host "Deteniendo servicio anterior..." -ForegroundColor Yellow
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
}

# Detener cualquier proceso que siga escuchando en el puerto indicado.
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
  $pidToStop = $listener.OwningProcess
  if ($pidToStop -and $pidToStop -ne $PID) {
    Write-Host "Cerrando proceso anterior PID $pidToStop en puerto $Port..." -ForegroundColor Yellow
    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
  }
}
Start-Sleep -Seconds 2

# Resguardar solamente el codigo anterior. La carpeta data nunca se toca.
if (Test-Path $AppDir) {
  Write-Host "Guardando copia del programa anterior en $PreviousApp" -ForegroundColor Gray
  New-Item -ItemType Directory -Force -Path $PreviousApp | Out-Null
  Copy-Item -Path (Join-Path $AppDir "*") -Destination $PreviousApp -Recurse -Force
  Remove-Item -Path $AppDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $AppDir -Recurse -Force

# Reutilizar o crear el entorno virtual.
$Venv = Join-Path $InstallRoot ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
  $Python = Get-Command python -ErrorAction Stop
  & $Python.Source -m venv $Venv
}
& $Py -m pip install -r (Join-Path $AppDir "requirements-core.txt")
if ($LASTEXITCODE -ne 0) { throw "No se pudieron validar las dependencias de Python." }

# Conservar configuracion previa; crearla solo si no existe.
$EnvFile = Join-Path $InstallRoot ".env.server"
if (-not (Test-Path $EnvFile)) {
  @(
    "ELEGANCE_SERVER_MODE=home",
    "ELEGANCE_ENV=development",
    "ELEGANCE_DATA_DIR=$DataDir",
    "ELEGANCE_SQLITE_PATH=$(Join-Path $DataDir 'elegance.sqlite3')",
    "ELEGANCE_ALLOWED_ORIGINS=http://127.0.0.1:$Port,http://localhost:$Port",
    "ELEGANCE_ENABLE_BACKUP_SCHEDULER=1",
    "ELEGANCE_TUNNEL_MODE=cloudflared",
    "PORT=$Port"
  ) | Set-Content -Encoding UTF8 $EnvFile
}

$Runner = @"
`$ErrorActionPreference='Stop'
Get-Content '$EnvFile' | ForEach-Object { if (`$_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1],`$matches[2],'Process') } }
Set-Location '$AppDir'
& '$Py' -m uvicorn server:app --host 127.0.0.1 --port $Port *>> '$LogsDir\server.log'
"@
$Runner | Set-Content -Encoding UTF8 (Join-Path $InstallRoot "Iniciar-Elegance.ps1")

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$InstallRoot\Iniciar-Elegance.ps1`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Esperando al servidor nuevo..." -ForegroundColor Gray
$ready = $false
for ($i=0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try {
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
    if ($health.status -eq "ok") { $ready = $true; break }
  } catch {}
}
if (-not $ready) {
  throw "El servidor no respondio. Revisa $LogsDir\server.log"
}

# Comprobar que la version corregida expone realmente las paginas.
$checks = @("/mobile-center", "/server-status")
foreach ($path in $checks) {
  try {
    $response = Invoke-WebRequest "http://127.0.0.1:$Port$path" -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -notin 200,303) { throw "HTTP $($response.StatusCode)" }
  } catch {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -ne 303) { throw "La ruta $path no quedo disponible. Estado: $status" }
  }
}

Write-Host "" 
Write-Host "ACTUALIZACION CORRECTA" -ForegroundColor Green
Write-Host "Datos conservados en: $DataDir" -ForegroundColor Green
Write-Host "Abre: http://127.0.0.1:$Port/mobile-center" -ForegroundColor Cyan
Write-Host "Abre: http://127.0.0.1:$Port/server-status" -ForegroundColor Cyan
Write-Host "No se abrieron puertos del modem." -ForegroundColor Gray
