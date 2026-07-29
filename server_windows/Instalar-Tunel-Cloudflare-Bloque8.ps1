#requires -RunAsAdministrator
[CmdletBinding()]
param([string]$InstallRoot='C:\EleganceServer',[int]$Port=8000,[string]$TunnelToken='')
$ErrorActionPreference='Stop'
if(-not(Get-Command cloudflared -ErrorAction SilentlyContinue)){
 if(Get-Command winget -ErrorAction SilentlyContinue){winget install --id Cloudflare.cloudflared --exact --accept-package-agreements --accept-source-agreements}
}
$cf=Get-Command cloudflared -ErrorAction Stop
if($TunnelToken){
 & $cf.Source service install $TunnelToken
 if($LASTEXITCODE -ne 0){throw 'No fue posible instalar el servicio del túnel.'}
 Write-Host 'Túnel permanente instalado como servicio de Windows.' -ForegroundColor Green
}else{
 Write-Host 'Modo de prueba: se abrirá una URL temporal. Para una URL fija necesitas crear un túnel en Cloudflare y volver con su token.' -ForegroundColor Yellow
 & $cf.Source tunnel --url "http://127.0.0.1:$Port"
}
