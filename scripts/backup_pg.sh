#!/usr/bin/env bash
# ============================================================
# WLai PostgreSQL 备份脚本（Docker Compose 环境）
#
# 用法:
#   ./scripts/backup_pg.sh                 # 备份到 ./backups，保留 14 天
#   ./scripts/backup_pg.sh --keep 30       # 保留 30 天
#   ./scripts/backup_pg.sh --output /mnt/backup
#
# 恢复:
#   docker compose exec -T db pg_restore -U wlai -d wlai \
#     --clean --if-exists backups/wlai_YYYYMMDD_HHMMSS.dump
#   （数据库名/用户按 .env 中 POSTGRES_* 调整）
# ============================================================
set -euo pipefail

# ── 参数解析 ─────────────────────────────────────────────────
KEEP=14
OUTPUT_DIR="${WLai_BACKUP_DIR:-./backups}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# 环境变量（与 docker-compose.yml 默认值保持一致）
DB_USER="${POSTGRES_USER:-wlai}"
DB_NAME="${POSTGRES_DB:-wlai}"

mkdir -p "$OUTPUT_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="${OUTPUT_DIR}/wlai_${STAMP}.dump"

echo "[1/2] 导出数据库 ${DB_NAME} → ${DEST}"
docker compose exec -T db \
  pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DEST"

echo "[2/2] 清理超过 ${KEEP} 天的旧备份"
find "$OUTPUT_DIR" -name 'wlai_*.dump' -mtime "+${KEEP}" -delete 2>/dev/null || true

echo "✅ 备份完成: ${DEST} ($(du -h "$DEST" | cut -f1))"
ls -1t "${OUTPUT_DIR}"/wlai_*.dump | head -5
