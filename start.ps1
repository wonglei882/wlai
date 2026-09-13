# WLai 一键启动脚本 (Windows PowerShell)
# 功能：检测 Docker -> 初始化 .env（自动生成随机密钥）-> 构建 -> 启动

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  WLai - AI 内容一致性守护平台" -ForegroundColor Cyan
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

# 复制 .env 并自动生成随机密钥
if (-not (Test-Path .env)) {
    Write-Host "[步骤 1/3] 初始化环境配置..." -ForegroundColor Yellow
    Copy-Item backend\.env.example .env
    $secret = [Convert]::ToBase64String((1..64 | ForEach-Object { Get-Random -Maximum 256 }))
    $pgpass = "pg_" + [guid]::NewGuid().ToString("N").Substring(0, 16)
    Add-Content .env ""
    Add-Content .env "# ===== 自动生成（start.ps1 首次运行）====="
    Add-Content .env "SESSION_SECRET_KEY=$secret"
    Add-Content .env "POSTGRES_PASSWORD=$pgpass"
    Write-Host "  已创建 .env 文件（含随机 SESSION_SECRET_KEY / POSTGRES_PASSWORD）" -ForegroundColor Green
    Write-Host "  [重要] 请编辑 .env 填入你的 AI API Key:" -ForegroundColor Yellow
    Write-Host "    - OPENAI_API_KEY  (必需)"
    Write-Host "    - EMBEDDING_PROVIDER (可选, 默认 sentence_transformers)"
    Write-Host ""
    Write-Host "  编辑完成后重新运行此脚本"
    exit 0
} else {
    Write-Host "[步骤 1/3] 环境配置已存在 (.env)" -ForegroundColor Green
    # 缺少 SESSION_SECRET_KEY 时自动补一个
    if (-not (Select-String -Path .env -Pattern '^SESSION_SECRET_KEY=' -Quiet)) {
        $secret = [Convert]::ToBase64String((1..64 | ForEach-Object { Get-Random -Maximum 256 }))
        Add-Content .env "SESSION_SECRET_KEY=$secret"
        Write-Host "  [提示] 已自动补写随机 SESSION_SECRET_KEY" -ForegroundColor Yellow
    }
    # 弱密码提醒
    $line = Select-String -Path .env -Pattern '^LOCAL_AUTH_PASSWORD=' | Select-Object -First 1
    if ($line) {
        $adminPass = ($line.Line -replace '^LOCAL_AUTH_PASSWORD=', '').Trim()
        if ($adminPass -in @('admin123', 'password', '123456', 'admin')) {
            Write-Host "  [安全] LOCAL_AUTH_PASSWORD 为弱密码，请改为强密码" -ForegroundColor Red
        }
    }
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
Write-Host "  默认管理员: 见 .env 中 LOCAL_AUTH_USERNAME / LOCAL_AUTH_PASSWORD" -ForegroundColor Cyan
Write-Host "  [提醒] 若使用初始弱密码登录，系统会要求先修改密码" -ForegroundColor Yellow
Write-Host ""
Write-Host "  查看日志:  docker compose logs -f"
Write-Host "  停止服务:  docker compose down"
Write-Host ""
