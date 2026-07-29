#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot = "C:\EleganceServer", [int]$Port = 8000)
$ErrorActionPreference = "Continue"
function Result($Name,$Ok,$Detail){ [pscustomobject]@{Prueba=$Name;Estado=$(if($Ok){'OK'}else{'ATENCION'});Detalle=$Detail} }
$rows=@()
$rows += Result 'Windows 64 bits' ([Environment]::Is64BitOperatingSystem) ([Environment]::OSVersion.VersionString)
$rows += Result 'PowerShell 5.1+' ($PSVersionTable.PSVersion.Major -ge 5) $PSVersionTable.PSVersion.ToString()
$python=Get-Command python -ErrorAction SilentlyContinue
$rows += Result 'Python disponible' ($null -ne $python) $(if($python){$python.Source}else{'No encontrado'})
$free=(Get-PSDrive -Name C).Free
$rows += Result 'Espacio libre >= 10 GB' ($free -ge 10GB) ("{0:N2} GB libres" -f ($free/1GB))
$pg=Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -First 1
$rows += Result 'Servicio PostgreSQL' ($pg -and $pg.Status -eq 'Running') $(if($pg){"$($pg.Name): $($pg.Status)"}else{'No detectado'})
$cf=Get-Command cloudflared -ErrorAction SilentlyContinue
$rows += Result 'Cloudflared instalado' ($null -ne $cf) $(if($cf){$cf.Source}else{'No encontrado'})
$task=Get-ScheduledTask -TaskName 'Elegance Server' -ErrorAction SilentlyContinue
$rows += Result 'Arranque automático' ($null -ne $task) $(if($task){$task.State}else{'Tarea no creada'})
$portOpen=Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
$rows += Result "Puerto local $Port" $portOpen $(if($portOpen){'Escuchando'}else{'Sin respuesta'})
$envFile=Join-Path $InstallRoot '.env.server'
$rows += Result 'Configuración del servidor' (Test-Path $envFile) $envFile
$rows | Format-Table -AutoSize
$report=Join-Path $env:TEMP 'Elegance_Bloque8_Diagnostico.json'
$rows | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 $report
Write-Host "`nReporte: $report" -ForegroundColor Cyan
if($rows.Estado -contains 'ATENCION'){ exit 2 }
