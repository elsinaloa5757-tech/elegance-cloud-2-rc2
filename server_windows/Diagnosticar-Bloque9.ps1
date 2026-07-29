#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000)
$items=@()
function Add-Check($Name,$Ok,$Detail){ $script:items += [pscustomobject]@{Comprobacion=$Name;Estado=$(if($Ok){'CORRECTO'}else{'PENDIENTE'});Detalle=$Detail} }
Add-Check 'Aplicacion' (Test-Path "$InstallRoot\app\server.py") "$InstallRoot\app\server.py"
Add-Check 'Python virtual' (Test-Path "$InstallRoot\.venv\Scripts\python.exe") "$InstallRoot\.venv\Scripts\python.exe"
Add-Check 'Datos persistentes' (Test-Path "$InstallRoot\data") "$InstallRoot\data"
Add-Check 'Tarea de servidor' ([bool](Get-ScheduledTask -TaskName 'Elegance Server' -ErrorAction SilentlyContinue)) 'Inicio automatico con Windows'
Add-Check 'Tarea vigilante' ([bool](Get-ScheduledTask -TaskName 'Elegance Server Watchdog' -ErrorAction SilentlyContinue)) 'Revision periodica y recuperacion'
$health=$false
try{$r=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 5;$health=($r.status -eq 'ok')}catch{}
Add-Check 'API local' $health "http://127.0.0.1:$Port/api/health"
$items | Format-Table -AutoSize
if($items.Estado -contains 'PENDIENTE'){ exit 2 } else { exit 0 }
