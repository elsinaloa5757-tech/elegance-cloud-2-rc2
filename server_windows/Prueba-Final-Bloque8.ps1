[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000)
$ErrorActionPreference='Stop'
$base="http://127.0.0.1:$Port"
$health=Invoke-RestMethod "$base/api/health" -TimeoutSec 10
$home=Invoke-RestMethod "$base/api/system/home-server" -TimeoutSec 10
Write-Host "Health: $($health.status)" -ForegroundColor Green
Write-Host "Base: $($home.database.engine); respaldos: $($home.backup.count); libre: $($home.storage.freePercent)%"
Write-Host 'Prueba local aprobada. Ahora abre la URL pública desde el S26 Ultra con Wi-Fi apagado.' -ForegroundColor Cyan
