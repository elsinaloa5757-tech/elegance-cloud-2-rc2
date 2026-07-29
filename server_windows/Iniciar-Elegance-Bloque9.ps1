#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$InstallRoot = "C:\EleganceServer",
  [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$AppDir = Join-Path $InstallRoot 'app'
$Py = Join-Path $InstallRoot '.venv\Scripts\python.exe'
$EnvFile = Join-Path $InstallRoot '.env.server'
$LogsDir = Join-Path $InstallRoot 'logs'
$LogFile = Join-Path $LogsDir 'server.log'
$PidFile = Join-Path $InstallRoot 'runtime\server.pid'
New-Item -ItemType Directory -Force -Path $LogsDir,(Split-Path $PidFile -Parent) | Out-Null

if (-not (Test-Path $Py)) { throw "Python virtual no encontrado: $Py" }
if (-not (Test-Path (Join-Path $AppDir 'server.py'))) { throw "Aplicacion no encontrada: $AppDir\server.py" }

if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(),$matches[2],'Process')
    }
  }
}
[Environment]::SetEnvironmentVariable('PORT',[string]$Port,'Process')
Set-Location $AppDir
$PID | Set-Content -Encoding ASCII $PidFile
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -Encoding UTF8 $LogFile "`r`n[$stamp] Iniciando Elegance Bloque 9 en 127.0.0.1:$Port"
try {
  & $Py -m uvicorn server:app --host 127.0.0.1 --port $Port 2>&1 | Tee-Object -FilePath $LogFile -Append
  exit $LASTEXITCODE
} finally {
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
