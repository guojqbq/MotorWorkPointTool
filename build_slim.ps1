param(
    [string]$BootstrapPython = ".venv\Scripts\python.exe",
    [string]$EnvironmentPath = ".packenv",
    [string]$DistributionPath = "dist_slim",
    [string]$WorkPath = "build_slim"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$environment = Join-Path $projectRoot $EnvironmentPath
$distribution = Join-Path $projectRoot $DistributionPath
$work = Join-Path $projectRoot $WorkPath

if (Test-Path -LiteralPath $environment) {
    throw "Packaging environment already exists: $environment"
}
if (Test-Path -LiteralPath $distribution) {
    throw "Distribution directory already exists: $distribution"
}
if (Test-Path -LiteralPath $work) {
    throw "Build directory already exists: $work"
}

$bootstrap = Join-Path $projectRoot $BootstrapPython
if (-not (Test-Path -LiteralPath $bootstrap)) {
    throw "Bootstrap Python was not found: $bootstrap"
}
& $bootstrap -m venv $environment
$python = Join-Path $environment "Scripts\python.exe"
& $python -m pip install --disable-pip-version-check -r (
    Join-Path $projectRoot "requirements-runtime.txt"
)
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency installation failed with exit code $LASTEXITCODE"
}
& $python -m PyInstaller --noconfirm --clean (
    Join-Path $projectRoot "PMSMPerformanceTool.spec"
) --distpath $distribution --workpath $work
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
