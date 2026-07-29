#requires -Version 5.1
#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\EleganceServer',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Source = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $InstallRoot 'app'
$DataDir = Join-Path $InstallRoot 'data'
$LogsDir = Join-Path $InstallRoot 'logs'
$UpdatesDir = Join-Path $InstallRoot 'updates'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$TaskNames = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Text) {
    Write-Host "`n==> $Text" -ForegroundColor Cyan
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-EleganceTasks {
    $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskName -like '*Elegance*' -or
        ($_.Actions | Where-Object {
            ($_.Execute -like '*EleganceServer*') -or ($_.Arguments -like '*EleganceServer*') -or
            ($_.Arguments -like '*uvicorn*server:app*')
        })
    }
    return @($tasks)
}

function Stop-EleganceTasks {
    Write-Step 'Deteniendo tareas automaticas de Elegance'
    foreach ($task in Get-EleganceTasks) {
        $TaskNames.Add($task.TaskName) | Out-Null
        try { Stop-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue } catch {}
        try { Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue | Out-Null } catch {}
        Write-Host "Tarea detenida: $($task.TaskPath)$($task.TaskName)"
    }
}

function Stop-EleganceProcesses {
    Write-Step "Liberando el puerto $Port y la carpeta de la aplicacion"
    $pids = New-Object System.Collections.Generic.HashSet[int]

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.OwningProcess -gt 0) { [void]$pids.Add([int]$_.OwningProcess) }
    }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and (
            $_.CommandLine -like "*$InstallRoot*" -or
            $_.CommandLine -like '*uvicorn*server:app*'
        )
    } | ForEach-Object { [void]$pids.Add([int]$_.ProcessId) }

    foreach ($processId in $pids) {
        try {
            & taskkill.exe /PID $processId /T /F | Out-Null
            Write-Host "Proceso detenido: $processId"
        } catch {
            try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch {
                throw "No fue posible detener el proceso $processId. Reinicia Windows y ejecuta este actualizador antes de abrir Elegance. Detalle: $($_.Exception.Message)"
            }
        }
    }

    for ($i = 0; $i -lt 20; $i++) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $listener) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "El puerto $Port continua ocupado despues de detener Elegance."
}

function Replace-AppSafely {
    Write-Step 'Guardando la version anterior y actualizando la aplicacion'
    if (Test-Path $AppDir) {
        $previous = Join-Path $UpdatesDir "app-pre-bloque12-corregido-$Stamp"
        Copy-Item $AppDir $previous -Recurse -Force

        $removed = $false
        for ($i = 1; $i -le 10; $i++) {
            try {
                Remove-Item $AppDir -Recurse -Force -ErrorAction Stop
                $removed = $true
                break
            } catch {
                Write-Host "La carpeta sigue ocupada. Reintento $i de 10..." -ForegroundColor Yellow
                Stop-EleganceProcesses
                Start-Sleep -Seconds 1
            }
        }
        if (-not $removed) {
            throw "No se pudo reemplazar $AppDir. Se conservo una copia en $previous."
        }
    }

    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    Copy-Item (Join-Path $Source '*') $AppDir -Recurse -Force
}

if (-not (Test-Administrator)) {
    throw 'El actualizador debe ejecutarse como administrador.'
}

Write-Host 'ELEGANCE BLOQUE 12 CORREGIDO - ACTUALIZACION AUTOMATICA SEGURA' -ForegroundColor Green
Write-Host 'No elimina la carpeta data, imagenes ni respaldos.' -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $InstallRoot, $DataDir, $LogsDir, $UpdatesDir | Out-Null

try {
    Stop-EleganceTasks
    Stop-EleganceProcesses
    Replace-AppSafely

    $Py = Join-Path $InstallRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $Py)) { throw "Python no encontrado: $Py" }

    Write-Step 'Comprobando dependencias'
    & $Py -m pip install -r (Join-Path $AppDir 'requirements-core.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No fue posible completar las dependencias.' }

    Write-Step 'Recuperando cuenta y datos historicos de forma segura'
    & $Py (Join-Path $AppDir 'server_windows\Recuperar-Cuenta-Persistente.py') $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw 'La recuperacion de cuenta no termino correctamente.' }

    $env:ELEGANCE_DATA_DIR = $DataDir
    $env:ELEGANCE_SQLITE_PATH = Join-Path $DataDir 'elegance.sqlite3'
    Push-Location $AppDir
    try {
        & $Py -c "from services.legacy_recovery import recover_empty_business_data; print(recover_empty_business_data())"
        if ($LASTEXITCODE -ne 0) { throw 'La recuperacion integral no termino correctamente.' }
    } finally { Pop-Location }

    Write-Step 'Configurando arranque automatico estable'
    $Runner = Join-Path $InstallRoot 'Iniciar-Elegance.cmd'
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
"@ | Set-Content -Encoding ASCII $Runner

    foreach ($name in $TaskNames | Select-Object -Unique) {
        try { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    }
    try { Unregister-ScheduledTask -TaskName 'Elegance Server' -Confirm:$false -ErrorAction SilentlyContinue } catch {}

    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$Runner`""
    $triggers = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn))
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 20 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'Elegance Server' -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Out-Null
    Enable-ScheduledTask -TaskName 'Elegance Server' | Out-Null
    Start-ScheduledTask -TaskName 'Elegance Server'

    Write-Step 'Comprobando que Elegance responda'
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) { throw "Elegance no respondio. Revisa $LogsDir\server.log" }

    Write-Host "`nBLOQUE 12 CORREGIDO INSTALADO CORRECTAMENTE" -ForegroundColor Green
    Write-Host "Datos conservados: $DataDir" -ForegroundColor Green
    Write-Host "Centro de recuperacion: http://127.0.0.1:$Port/recovery-center" -ForegroundColor Cyan
    Write-Host "Panel: http://127.0.0.1:$Port/admin" -ForegroundColor Cyan
    Write-Host 'Reinicia Windows y prueba sin abrir PowerShell.' -ForegroundColor Yellow
    exit 0
} catch {
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Tus datos permanecen en $DataDir" -ForegroundColor Yellow
    exit 1
}
