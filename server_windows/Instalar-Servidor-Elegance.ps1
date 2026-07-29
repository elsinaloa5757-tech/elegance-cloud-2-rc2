#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$InstallRoot = "C:\EleganceServer",
  [int]$Port = 8000,
  [string]$ExternalBackupDir = ""
)
$ErrorActionPreference = "Stop"
$ExistingTask = Get-ScheduledTask -TaskName "Elegance Server" -ErrorAction SilentlyContinue
if ($ExistingTask) { Stop-ScheduledTask -TaskName "Elegance Server" -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { if ($_.OwningProcess -and $_.OwningProcess -ne $PID) { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
$Source = Split-Path -Parent $PSScriptRoot
$Python = Get-Command python -ErrorAction Stop
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$AppDir = Join-Path $InstallRoot "app"
$DataDir = Join-Path $InstallRoot "data"
$LogsDir = Join-Path $InstallRoot "logs"
New-Item -ItemType Directory -Force -Path $AppDir,$DataDir,$LogsDir | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $AppDir -Recurse -Force
& $Python.Source -m venv (Join-Path $InstallRoot ".venv")
$Py = Join-Path $InstallRoot ".venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r (Join-Path $AppDir "requirements-core.txt")
$EnvLines = @(
  "ELEGANCE_SERVER_MODE=home",
  "ELEGANCE_ENV=development",
  "ELEGANCE_DATA_DIR=$DataDir",
  "ELEGANCE_SQLITE_PATH=$(Join-Path $DataDir 'elegance.sqlite3')",
  "ELEGANCE_ALLOWED_ORIGINS=http://127.0.0.1:$Port,http://localhost:$Port",
  "ELEGANCE_ENABLE_BACKUP_SCHEDULER=1",
  "ELEGANCE_TUNNEL_MODE=cloudflared",
  "PORT=$Port"
)
if ($ExternalBackupDir) { $EnvLines += "ELEGANCE_EXTERNAL_BACKUP_DIR=$ExternalBackupDir" }
$EnvLines | Set-Content -Encoding UTF8 (Join-Path $InstallRoot ".env.server")
$Runner = @"
`$ErrorActionPreference='Stop'
Get-Content '$InstallRoot\.env.server' | ForEach-Object { if (`$_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable(`$matches[1],`$matches[2],'Process') } }
Set-Location '$AppDir'
& '$Py' -m uvicorn server:app --host 127.0.0.1 --port $Port *>> '$LogsDir\server.log'
"@
$Runner | Set-Content -Encoding UTF8 (Join-Path $InstallRoot "Iniciar-Elegance.ps1")
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$InstallRoot\Iniciar-Elegance.ps1`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "Elegance Server" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName "Elegance Server"
Write-Host "Servidor instalado. Revisa http://127.0.0.1:$Port/api/health" -ForegroundColor Green
Write-Host "No se abrieron puertos del modem." -ForegroundColor Cyan
