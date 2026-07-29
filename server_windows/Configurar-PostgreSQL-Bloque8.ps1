#requires -RunAsAdministrator
#requires -Version 5.1
[CmdletBinding()]
param(
 [string]$InstallRoot='C:\EleganceServer',
 [string]$Database='elegance',
 [string]$User='elegance_app',
 [string]$Password=''
)
$ErrorActionPreference='Stop'
if(-not $Password){
  $Password=[System.Web.Security.Membership]::GeneratePassword(28,4).Replace('"','A').Replace("'",'B').Replace(' ','C')
}
$psql=Get-ChildItem 'C:\Program Files\PostgreSQL' -Filter psql.exe -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
if(-not $psql){
  if(Get-Command winget -ErrorAction SilentlyContinue){
    Write-Host 'PostgreSQL no está instalado. Se abrirá la instalación oficial mediante winget.' -ForegroundColor Yellow
    winget install --id PostgreSQL.PostgreSQL --exact --accept-package-agreements --accept-source-agreements
    $psql=Get-ChildItem 'C:\Program Files\PostgreSQL' -Filter psql.exe -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  }
}
if(-not $psql){ throw 'No se encontró psql.exe. Instala PostgreSQL y vuelve a ejecutar este script.' }
$admin=Read-Host 'Usuario administrador de PostgreSQL' 
if(-not $admin){$admin='postgres'}
$env:PGPASSWORD=Read-Host 'Contraseña del usuario administrador'
$sql=@"
DO `$`$
BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$User') THEN
   CREATE ROLE $User LOGIN PASSWORD '$($Password.Replace("'","''"))';
 ELSE
   ALTER ROLE $User WITH LOGIN PASSWORD '$($Password.Replace("'","''"))';
 END IF;
END `$`$;
SELECT 'CREATE DATABASE $Database OWNER $User' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$Database')\gexec
GRANT ALL PRIVILEGES ON DATABASE $Database TO $User;
"@
$tmp=Join-Path $env:TEMP 'elegance_pg_setup.sql'; $sql | Set-Content -Encoding UTF8 $tmp
& $psql.FullName -U $admin -h 127.0.0.1 -d postgres -f $tmp
if($LASTEXITCODE -ne 0){throw 'PostgreSQL rechazó la configuración.'}
$envFile=Join-Path $InstallRoot '.env.server'
if(-not(Test-Path $envFile)){New-Item -ItemType Directory -Force $InstallRoot|Out-Null; New-Item -ItemType File $envFile|Out-Null}
$lines=@(Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object {$_ -notmatch '^DATABASE_URL='})
$encoded=[uri]::EscapeDataString($Password)
$lines += "DATABASE_URL=postgresql://$User`:$encoded@127.0.0.1:5432/$Database"
$lines | Set-Content -Encoding UTF8 $envFile
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host "PostgreSQL configurado. Credenciales guardadas únicamente en $envFile" -ForegroundColor Green
Write-Host 'Conserva una copia segura de la contraseña generada:' -ForegroundColor Yellow
Write-Host $Password
