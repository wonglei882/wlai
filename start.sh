#!/bin/bash
# WLai 一键启动脚本 (Linux/Mac)
set -e

echo "========================================="
echo "  WLai — AI 内容一致性守护平台"
echo "========================================="
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "[错误] 未检测到 Docker，请先安装 Docker Desktop"
    echo "  https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "[错误] Docker Compose 不可用，请确保 Docker Desktop 版本 >= 2.0"
    exit 1
fi

# 复制 .env
if [ ! -f .env ]; then
    echo "[步骤 1/3] 初始化环境配置..."
    cp backend/.env.example .env
    echo "  已创建 .env 文件"
    echo "  [重要] 请编辑 .env 填入你的 AI API Key:"
    echo "    - OPENAI_API_KEY  (必需)"
    echo "    - EMBEDDING_PROVIDER (可选, 默认 sentence_transformers)"
    echo ""
    echo "  编辑完成后重新运行此脚本"
    exit 0
else
    echo "[步骤 1/3] 环境配置已存在 (.env)"
fi

# 构建并启动
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
echo "  查看日志:  docker compose logs -f"
echo "  停止服务:  docker compose down"
echo ""
