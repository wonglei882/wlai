# WLai 一键启动脚本 (Windows PowerShell)

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  WLai — AI 内容一致性守护平台" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Docker
try {
    $null = Get-Command docker -ErrorAction Stop
} catch {
    Write-Host "[错误] 未检测到 Docker，请先安装 Docker Desktop" -ForegroundColor Red
    Write-Host "  https://www.docker.com/products/docker-desktop/"
    exit 1
}

try {
    $null = docker compose version
} catch {
    Write-Host "[错误] Docker Compose 不可用，请确保 Docker Desktop 版本 >= 2.0" -ForegroundColor Red
    exit 1
}

# 复制 .env
if (-not (Test-Path .env)) {
    Write-Host "[步骤 1/3] 初始化环境配置..." -ForegroundColor Yellow
    Copy-Item backend\.env.example .env
    Write-Host "  已创建 .env 文件"
    Write-Host "  [重要] 请编辑 .env 填入你的 AI API Key:" -ForegroundColor Yellow
    Write-Host "    - OPENAI_API_KEY  (必需)"
    Write-Host "    - EMBEDDING_PROVIDER (可选, 默认 sentence_transformers)"
    Write-Host ""
    Write-Host "  编辑完成后重新运行此脚本"
    exit 0
} else {
    Write-Host "[步骤 1/3] 环境配置已存在 (.env)" -ForegroundColor Green
}

# 构建并启动
Write-Host "[步骤 2/3] 构建 Docker 镜像（首次可能需要 5-10 分钟）..." -ForegroundColor Yellow
docker compose build

Write-Host "[步骤 3/3] 启动服务..." -ForegroundColor Yellow
docker compose up -d

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  WLai 已启动！" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  前端界面:  http://localhost:3000" -ForegroundColor Cyan
Write-Host "  后端 API:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "  API 文档:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "  查看日志:  docker compose logs -f"
Write-Host "  停止服务:  docker compose down"
Write-Host ""
