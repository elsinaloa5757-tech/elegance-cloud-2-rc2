#requires -Version 5.1
[CmdletBinding()]
param([string]$InstallRoot="C:\EleganceServer", [int]$Port=8000)
$ErrorActionPreference="Stop"
$Winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $Winget) { throw "winget no está disponible. Instala cloudflared manualmente desde Cloudflare." }
winget install --id Cloudflare.cloudflared --exact --accept-source-agreements --accept-package-agreements
Write-Host "Cloudflared instalado." -ForegroundColor Green
Write-Host "Para una URL temporal gratuita ejecuta:" -ForegroundColor Cyan
Write-Host "cloudflared tunnel --url http://127.0.0.1:$Port"
Write-Host "Para una URL permanente con dominio propio, inicia sesión con 'cloudflared tunnel login' y crea un túnel nombrado." -ForegroundColor Yellow
