#!/usr/bin/env bash
# WLai 一键启动脚本 (Linux/macOS)
# 功能：检测 Docker -> 初始化 .env（自动生成随机密钥）-> 构建 -> 启动
set -euo pipefail

echo "========================================="
echo "  WLai - AI 内容一致性守护平台"
echo "========================================="
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "[错误] 未检测到 Docker，请先安装 Docker" >&2
  exit 1
fi

gen_secret() { head -c 48 /dev/urandom | base64 | tr -d '\n'; }

if [ ! -f .env ]; then
  echo "[步骤 1/3] 初始化环境配置..."
  cp backend/.env.example .env
  {
    echo ""
    echo "# ===== 自动生成（start.sh 首次运行）====="
    echo "SESSION_SECRET_KEY=$(gen_secret)"
    echo "POSTGRES_PASSWORD=pg_$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 16)"
  } >> .env
  echo "  已创建 .env 文件（含随机 SESSION_SECRET_KEY / POSTGRES_PASSWORD）"
  echo "  [重要] 请编辑 .env 填入你的 AI API Key:"
  echo "    - OPENAI_API_KEY  (必需)"
  echo "    - EMBEDDING_PROVIDER (可选, 默认 sentence_transformers)"
  echo ""
  echo "  编辑完成后重新运行此脚本"
  exit 0
else
  echo "[步骤 1/3] 环境配置已存在 (.env)"
  if ! grep -q '^SESSION_SECRET_KEY=' .env; then
    echo "SESSION_SECRET_KEY=$(gen_secret)" >> .env
    echo "  [提示] 已自动补写随机 SESSION_SECRET_KEY"
  fi
  if grep -q '^LOCAL_AUTH_PASSWORD=\(admin123\|password\|123456\|admin\)$' .env; then
    echo "  [安全] LOCAL_AUTH_PASSWORD 为弱密码，请改为强密码" >&2
  fi
fi

echo "[步骤 2/3] 构建 Docker 镜像（首次可能需要 5-10 分钟）..."
docker compose build

echo "[步骤 3/3] 启动服务..."
docker compose up -d

echo ""
echo "========================================="
echo "  WLai 已启动！"
echo "========================================="
echo ""
echo "  前端界面:  http://localhost:3000"
echo "  后端 API:  http://localhost:8000"
echo "  API 文档:  http://localhost:8000/docs"
echo ""
echo "  默认管理员: 见 .env 中 LOCAL_AUTH_USERNAME / LOCAL_AUTH_PASSWORD"
echo "  查看日志:  docker compose logs -f"
echo "  停止服务:  docker compose down"
echo ""
