# ============================================================
# WLai PostgreSQL 备份脚本（Windows / PowerShell）
#
# 用法:
#   .\scripts\backup_pg.ps1               # 备份到 .\backups，保留 14 天
#   .\scripts\backup_pg.ps1 -Keep 30      # 保留 30 天
#   .\scripts\backup_pg.ps1 -OutputDir D:\backups
#
# 恢复:
#   docker compose exec -T db pg_restore -U wlai -d wlai --clean --if-exists backups\wlai_*.dump
# ============================================================
param(
  [int]$Keep = 14,
  [string]$OutputDir = ".\backups"
)

$ErrorActionPreference = "Stop"

# 环境变量（与 docker-compose.yml 默认值保持一致）
$dbUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "wlai" }
$dbName = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "wlai" }

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $OutputDir "wlai_$stamp.dump"

Write-Host "[1/2] 导出数据库 $dbName -> $dest" -ForegroundColor Yellow
docker compose exec -T db pg_dump -U $dbUser -d $dbName -Fc | Set-Content -Path $dest -AsByteStream

Write-Host "[2/2] 清理超过 $Keep 天的旧备份" -ForegroundColor Yellow
Get-ChildItem $OutputDir -Filter "wlai_*.dump" | Where-Object {
  $_.LastWriteTime -lt (Get-Date).AddDays(-$Keep)
} | Remove-Item -Force

$size = (Get-Item $dest).Length / 1MB
Write-Host "备份完成: $dest (${size} MB)" -ForegroundColor Green
