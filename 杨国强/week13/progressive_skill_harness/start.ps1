# ============================================================
#   启动脚本（PowerShell）— 加载 .env 并启动指定模式
#   用法：.\start.ps1 cli   或   .\start.ps1 web
# ============================================================

param(
    [Parameter(Position=0)]
    [ValidateSet("cli", "web", "reset", "factory", "smoke")]
    [string]$Mode = "cli"
)

$projectRoot = $PSScriptRoot
Set-Location $projectRoot

# 激活虚拟环境
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
} else {
    Write-Host "[错误] 未找到 .venv，请先运行 setup_env.ps1" -ForegroundColor Red
    exit 1
}

# 加载 .env
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.*?)\s*$' -and $matches[1] -ne "") {
            $key = $matches[1].Trim()
            $val = $matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
    Write-Host "[OK] 已加载 .env（LLM_PROVIDER=$env:LLM_PROVIDER）" -ForegroundColor Green
} else {
    Write-Host "[警告] 未找到 .env，请先运行 setup_env.ps1" -ForegroundColor Yellow
}

# 解决 Windows OpenMP 冲突
$env:KMP_DUPLICATE_LIB_OK = "TRUE"

Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  启动模式：$Mode" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan

switch ($Mode) {
    "cli" {
        Write-Host "  启动 CLI 终端对话..." -ForegroundColor Yellow
        python src/progressive_agent.py
    }
    "web" {
        Write-Host "  启动 Web 服务，浏览器访问 http://localhost:8000" -ForegroundColor Yellow
        uvicorn src.progressive_serve:app --host 0.0.0.0 --port 8000 --reload
    }
    "reset" {
        Write-Host "  重置所有状态..." -ForegroundColor Yellow
        python -c "import requests; r = requests.post('http://localhost:8000/reset'); print(r.json())" 2>$null
        if ($LASTEXITCODE -ne 0) {
            python src/reset_cli.py factory
        }
    }
    "factory" {
        Write-Host "  [警告] 即将恢复到出厂状态（删除所有用户记忆与 Skill 调用记录）" -ForegroundColor Red
        $conf = Read-Host "  确认？(y/N)"
        if ($conf -eq "y" -or $conf -eq "Y") {
            python src/reset_cli.py factory
        } else {
            Write-Host "  已取消" -ForegroundColor Gray
        }
    }
    "smoke" {
        Write-Host "  冒烟测试：验证 Skill 注册表 / 加载器 / 选择器..." -ForegroundColor Yellow
        python run_smoke_test.py
    }
}