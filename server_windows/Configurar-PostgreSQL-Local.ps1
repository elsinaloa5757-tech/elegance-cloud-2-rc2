[CmdletBinding()]
param(
  [string]$InstallRoot="C:\EleganceServer",
  [string]$HostName="127.0.0.1",
  [int]$Port=5432,
  [string]$Database="elegance",
  [string]$User="elegance_admin",
  [Parameter(Mandatory=$true)][SecureString]$Password
)
$ErrorActionPreference="Stop"
$Plain=[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))
try {
  $Encoded=[System.Uri]::EscapeDataString($Plain)
  $Url="postgresql://$User`:$Encoded@$HostName`:$Port/$Database"
  $EnvFile=Join-Path $InstallRoot ".env.server"
  if(-not (Test-Path $EnvFile)){throw "Primero instala Elegance Server."}
  $Lines=Get-Content $EnvFile | Where-Object {$_ -notmatch '^DATABASE_URL='}
  $Lines += "DATABASE_URL=$Url"
  $Lines | Set-Content -Encoding UTF8 $EnvFile
  Write-Host "DATABASE_URL configurada. La contraseña no se imprimió." -ForegroundColor Green
  Write-Host "Ejecuta el migrador desde la carpeta app después de confirmar que PostgreSQL está activo." -ForegroundColor Cyan
} finally {
  $Plain=$null
}
