param([string]$BaseUrl="http://127.0.0.1:8000", [string]$Token="")
$Headers=@{}
if($Token){$Headers.Authorization="Bearer $Token"}
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/admin/home-server/backups/run?kind=daily" -Headers $Headers | ConvertTo-Json -Depth 8
