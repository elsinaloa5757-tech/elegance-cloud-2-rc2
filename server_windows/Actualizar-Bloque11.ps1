#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000)
$ErrorActionPreference='Stop'
$Source=Split-Path -Parent $PSScriptRoot
$AppDir=Join-Path $InstallRoot 'app';$DataDir=Join-Path $InstallRoot 'data';$LogsDir=Join-Path $InstallRoot 'logs';$UpdatesDir=Join-Path $InstallRoot 'updates';$Stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
Write-Host 'ELEGANCE BLOQUE 11 - RECUPERACION DEFINITIVA Y ESTABILIZACION' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataDir,$LogsDir,$UpdatesDir | Out-Null
Stop-ScheduledTask -TaskName 'Elegance Server' -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue|ForEach-Object{Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue};Start-Sleep 2
if(Test-Path $AppDir){$previous=Join-Path $UpdatesDir "app-pre-bloque11-$Stamp";New-Item -ItemType Directory -Force -Path $previous|Out-Null;Copy-Item (Join-Path $AppDir '*') $previous -Recurse -Force;Remove-Item $AppDir -Recurse -Force}
New-Item -ItemType Directory -Force -Path $AppDir|Out-Null;Copy-Item (Join-Path $Source '*') $AppDir -Recurse -Force
$Py=Join-Path $InstallRoot '.venv\Scripts\python.exe';if(-not(Test-Path $Py)){throw "Python no encontrado: $Py"}
& $Py -m pip install -r (Join-Path $AppDir 'requirements-core.txt');if($LASTEXITCODE-ne 0){throw 'Dependencias incompletas.'}
& $Py (Join-Path $AppDir 'server_windows\Recuperar-Cuenta-Persistente.py') $InstallRoot
$Runner=Join-Path $InstallRoot 'Iniciar-Elegance.cmd'
@"
@echo off
set "ELEGANCE_SERVER_MODE=home"
set "ELEGANCE_ENV=production"
set "ELEGANCE_DATA_DIR=$DataDir"
set "ELEGANCE_SQLITE_PATH=$DataDir\elegance.sqlite3"
set "ELEGANCE_ALLOWED_ORIGINS=http://127.0.0.1:$Port,http://localhost:$Port"
set "ELEGANCE_ENABLE_BACKUP_SCHEDULER=1"
cd /d "$AppDir"
"$Py" -m uvicorn server:app --host 127.0.0.1 --port $Port >> "$LogsDir\server.log" 2>&1
"@|Set-Content -Encoding ASCII $Runner
$action=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$Runner`"";$triggers=@((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -AtLogOn));$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Elegance Server' -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force|Out-Null;Start-ScheduledTask -TaskName 'Elegance Server'
$ready=$false;for($i=0;$i-lt 120;$i++){Start-Sleep 1;try{$h=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3;if($h.status-eq'ok'){$ready=$true;break}}catch{}}
if(-not $ready){throw "Elegance no respondio. Revisa $LogsDir\server.log"}
$status=Invoke-RestMethod "http://127.0.0.1:$Port/api/auth/status" -TimeoutSec 5
Write-Host 'BLOQUE 11 INSTALADO CORRECTAMENTE' -ForegroundColor Green
Write-Host "Configuracion inicial requerida: $($status.setupRequired)" -ForegroundColor Cyan
Write-Host "Verificacion: http://127.0.0.1:$Port/system-check" -ForegroundColor Cyan
Write-Host 'Reinicia Windows y prueba sin abrir PowerShell.' -ForegroundColor Yellow
