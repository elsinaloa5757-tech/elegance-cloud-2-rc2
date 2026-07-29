#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000)
$ErrorActionPreference='Stop'
$ServerTask='Elegance Server'
$WatchTask='Elegance Server Watchdog'
$Source=Split-Path -Parent $PSScriptRoot
$AppDir=Join-Path $InstallRoot 'app'
$DataDir=Join-Path $InstallRoot 'data'
$LogsDir=Join-Path $InstallRoot 'logs'
$RuntimeDir=Join-Path $InstallRoot 'runtime'
$UpdatesDir=Join-Path $InstallRoot 'updates'
$Stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$PreviousApp=Join-Path $UpdatesDir "app-$Stamp"

Write-Host ''; Write-Host 'ELEGANCE BLOQUE 9' -ForegroundColor Cyan
Write-Host 'Instalacion definitiva y administracion segura' -ForegroundColor Cyan
Write-Host 'La carpeta data no se eliminara ni sustituira.' -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataDir,$LogsDir,$RuntimeDir,$UpdatesDir | Out-Null

foreach($name in @($ServerTask,$WatchTask)){ Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue }
$listeners=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach($listener in $listeners){ if($listener.OwningProcess -and $listener.OwningProcess -ne $PID){ Write-Host "Deteniendo PID $($listener.OwningProcess)..." -ForegroundColor Yellow; Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue } }
Start-Sleep -Seconds 2

if(Test-Path $AppDir){
  Write-Host "Resguardando programa anterior: $PreviousApp" -ForegroundColor Gray
  New-Item -ItemType Directory -Force -Path $PreviousApp | Out-Null
  Copy-Item (Join-Path $AppDir '*') $PreviousApp -Recurse -Force
  Remove-Item $AppDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item (Join-Path $Source '*') $AppDir -Recurse -Force

$Venv=Join-Path $InstallRoot '.venv'; $Py=Join-Path $Venv 'Scripts\python.exe'
if(-not(Test-Path $Py)){ $Python=Get-Command python -ErrorAction Stop; & $Python.Source -m venv $Venv }
& $Py -m pip install -r (Join-Path $AppDir 'requirements-core.txt')
if($LASTEXITCODE -ne 0){ throw 'No se pudieron instalar o validar las dependencias.' }

$EnvFile=Join-Path $InstallRoot '.env.server'
if(-not(Test-Path $EnvFile)){
  @(
    'ELEGANCE_SERVER_MODE=home',
    'ELEGANCE_ENV=production',
    "ELEGANCE_DATA_DIR=$DataDir",
    "ELEGANCE_SQLITE_PATH=$(Join-Path $DataDir 'elegance.sqlite3')",
    "ELEGANCE_ALLOWED_ORIGINS=http://127.0.0.1:$Port,http://localhost:$Port",
    'ELEGANCE_ENABLE_BACKUP_SCHEDULER=1',
    'ELEGANCE_TUNNEL_MODE=cloudflared',
    "PORT=$Port"
  ) | Set-Content -Encoding UTF8 $EnvFile
}

$RunnerSource=Join-Path $AppDir 'server_windows\Iniciar-Elegance-Bloque9.ps1'
$WatchSource=Join-Path $AppDir 'server_windows\Vigilar-Elegance-Bloque9.ps1'
Copy-Item $RunnerSource (Join-Path $InstallRoot 'Iniciar-Elegance.ps1') -Force
Copy-Item $WatchSource (Join-Path $InstallRoot 'Vigilar-Elegance.ps1') -Force

$serverAction=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$InstallRoot\Iniciar-Elegance.ps1`" -InstallRoot `"$InstallRoot`" -Port $Port"
$serverTriggers=@((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -AtLogOn))
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $ServerTask -Action $serverAction -Trigger $serverTriggers -Principal $principal -Settings $settings -Description 'Servidor local de Elegance; inicia con Windows y se recupera si falla.' -Force | Out-Null

$watchAction=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$InstallRoot\Vigilar-Elegance.ps1`" -InstallRoot `"$InstallRoot`" -Port $Port"
$watchTrigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $WatchTask -Action $watchAction -Trigger $watchTrigger -Principal $principal -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew) -Description 'Comprueba Elegance cada cinco minutos y reinicia el servicio si deja de responder.' -Force | Out-Null

Start-ScheduledTask -TaskName $ServerTask
Write-Host 'Esperando respuesta del servidor...' -ForegroundColor Gray
$ready=$false
for($i=0;$i -lt 60;$i++){
  Start-Sleep -Seconds 1
  try{$health=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 4;if($health.status -eq 'ok'){$ready=$true;break}}catch{}
}
if(-not $ready){
  Write-Host 'Intentando arranque interactivo de recuperacion...' -ForegroundColor Yellow
  Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$InstallRoot\Iniciar-Elegance.ps1`" -InstallRoot `"$InstallRoot`" -Port $Port"
  for($i=0;$i -lt 30;$i++){ Start-Sleep 1; try{$health=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 4;if($health.status -eq 'ok'){$ready=$true;break}}catch{} }
}
if(-not $ready){ throw "Elegance no respondio. Revisa $LogsDir\server.log y ejecuta Diagnosticar-Bloque9.ps1" }

foreach($path in @('/mobile-center','/server-status','/admin')){
  try{$r=Invoke-WebRequest "http://127.0.0.1:$Port$path" -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop;if($r.StatusCode -notin 200,303){throw "HTTP $($r.StatusCode)"}}
  catch{$status=$_.Exception.Response.StatusCode.value__;if($status -notin 302,303){throw "Ruta no disponible: $path (HTTP $status)"}}
}

Write-Host ''; Write-Host 'BLOQUE 9 INSTALADO CORRECTAMENTE' -ForegroundColor Green
Write-Host 'Elegance arrancara automaticamente con Windows.' -ForegroundColor Green
Write-Host 'El vigilante revisara el servidor cada 5 minutos.' -ForegroundColor Green
Write-Host "Datos conservados: $DataDir" -ForegroundColor Cyan
Write-Host "Panel: http://127.0.0.1:$Port/admin" -ForegroundColor Cyan
Write-Host "Centro movil: http://127.0.0.1:$Port/mobile-center" -ForegroundColor Cyan
Write-Host 'Reinicia la computadora para realizar la prueba definitiva.' -ForegroundColor Yellow
