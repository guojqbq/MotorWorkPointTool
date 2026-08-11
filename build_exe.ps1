$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "未找到 .venv。请先按 README 创建虚拟环境并安装 requirements.txt。"
}

Push-Location $projectRoot
try {
    & $venvPython -m PyInstaller --noconfirm --clean PMSMPerformanceTool.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败，退出代码：$LASTEXITCODE"
    }
    Write-Host "构建完成：dist\PMSMPerformanceTool.exe"
}
finally {
    Pop-Location
}
