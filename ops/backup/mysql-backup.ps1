param(
  [string]$OutDir = ".\backups",
  [int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"

$hostName = $env:GAMEOPS_MYSQL_HOST
$port = if ($env:GAMEOPS_MYSQL_PORT) { $env:GAMEOPS_MYSQL_PORT } else { "3306" }
$database = $env:GAMEOPS_MYSQL_DATABASE
$user = $env:GAMEOPS_MYSQL_USER
$password = $env:GAMEOPS_MYSQL_PASSWORD

if (-not $hostName -or -not $database -or -not $user -or -not $password) {
  throw "GAMEOPS_MYSQL_HOST, GAMEOPS_MYSQL_DATABASE, GAMEOPS_MYSQL_USER and GAMEOPS_MYSQL_PASSWORD are required."
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $OutDir "$database-$stamp.sql"

$env:MYSQL_PWD = $password
try {
  mysqldump --single-transaction --routines --events --set-gtid-purged=OFF `
    -h $hostName -P $port -u $user $database | Out-File -FilePath $target -Encoding utf8
} finally {
  Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
}

Get-ChildItem -Path $OutDir -Filter "$database-*.sql" |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
  Remove-Item -Force

Write-Host "Backup written to $target"
