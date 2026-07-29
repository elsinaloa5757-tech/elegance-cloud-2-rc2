#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000)
$ErrorActionPreference='SilentlyContinue'
$TaskName='Elegance Server'
$WatchLog=Join-Path $InstallRoot 'logs\watchdog.log'
$healthy=$false
try {
  $r=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 8
  $healthy=($r.status -eq 'ok')
} catch {}
if (-not $healthy) {
  $stamp=Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  Add-Content -Encoding UTF8 $WatchLog "[$stamp] Servidor sin respuesta; solicitando reinicio."
  $listeners=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach($listener in $listeners){ if($listener.OwningProcess -and $listener.OwningProcess -ne $PID){ Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue } }
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
