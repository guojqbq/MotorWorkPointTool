param(
    [string]$BootstrapPython = ".venv\Scripts\python.exe",
    [string]$TestPython = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$version = (Get-Content -LiteralPath (Join-Path $projectRoot "VERSION.txt") -Raw).Trim()
if ($version -notmatch "^\d+\.\d+\.\d+$") {
    throw "VERSION.txt must contain X.Y.Z"
}

$releaseRoot = Join-Path $projectRoot "release"
$packageName = "PMSM_Performance_Tool_v$version"
$packageDirectory = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"
$releaseEnvironment = Join-Path $projectRoot ".release-venv"
$releaseWork = Join-Path $projectRoot ".release-build"
$releaseDist = Join-Path $projectRoot ".release-dist"
$releaseSmoke = Join-Path $projectRoot ".release-smoke"
$releaseTestTemp = Join-Path $projectRoot ".release-test-temp"
$bootstrap = Join-Path $projectRoot $BootstrapPython
$testInterpreter = Join-Path $projectRoot $TestPython
$userReadmeName = "README_$([char]0x7528)$([char]0x6237)$([char]0x8BF4)$([char]0x660E).md"

function Remove-OwnedPath {
    param(
        [string]$Target,
        [string]$ExpectedParent
    )
    if (-not (Test-Path -LiteralPath $Target)) {
        return
    }
    $resolvedTarget = (Resolve-Path -LiteralPath $Target).Path
    $resolvedParent = (Resolve-Path -LiteralPath $ExpectedParent).Path
    if ([IO.Path]::GetDirectoryName($resolvedTarget) -ne $resolvedParent) {
        throw "Unsafe cleanup target: $resolvedTarget"
    }
    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
}

if (-not (Test-Path -LiteralPath $bootstrap)) {
    throw "Bootstrap Python was not found: $bootstrap"
}
if (-not (Test-Path -LiteralPath $testInterpreter)) {
    throw "Test Python was not found: $testInterpreter"
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
foreach ($temporaryPath in @(
    $releaseEnvironment,
    $releaseWork,
    $releaseDist,
    $releaseSmoke,
    $releaseTestTemp
)) {
    Remove-OwnedPath $temporaryPath $projectRoot
}
Remove-OwnedPath $packageDirectory $releaseRoot
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $releaseTestTemp -Force | Out-Null
& $testInterpreter -m pytest -q -p no:cacheprovider --basetemp $releaseTestTemp
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed with exit code $LASTEXITCODE"
}

& $bootstrap -m venv $releaseEnvironment
if ($LASTEXITCODE -ne 0) {
    throw "Release environment creation failed with exit code $LASTEXITCODE"
}
$releasePython = Join-Path $releaseEnvironment "Scripts\python.exe"
& $releasePython -m pip install --disable-pip-version-check -r (
    Join-Path $projectRoot "requirements-runtime.txt"
)
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency installation failed with exit code $LASTEXITCODE"
}

& $releasePython -m PyInstaller --noconfirm --clean (
    Join-Path $projectRoot "PMSMPerformanceTool.spec"
) --distpath $releaseDist --workpath $releaseWork
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$builtDirectory = Join-Path $releaseDist "PMSMPerformanceTool"
$builtExecutable = Join-Path $builtDirectory "PMSMPerformanceTool.exe"
if (-not (Test-Path -LiteralPath $builtExecutable)) {
    throw "Built executable was not found: $builtExecutable"
}

$previousQpaPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
$smokeProcess = Start-Process `
    -FilePath $builtExecutable `
    -ArgumentList @("--smoke-test", $releaseSmoke) `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
$env:QT_QPA_PLATFORM = $previousQpaPlatform
if ($smokeProcess.ExitCode -ne 0) {
    throw "Packaged smoke test failed with exit code $($smokeProcess.ExitCode)"
}

Copy-Item -LiteralPath $builtDirectory -Destination $packageDirectory -Recurse
Copy-Item -LiteralPath (
    Join-Path $projectRoot $userReadmeName
) -Destination (Join-Path $releaseRoot $userReadmeName) -Force
Copy-Item -LiteralPath (
    Join-Path $projectRoot "CHANGELOG.md"
) -Destination (Join-Path $releaseRoot "CHANGELOG.md") -Force
Copy-Item -LiteralPath (
    Join-Path $projectRoot "VERSION.txt"
) -Destination (Join-Path $releaseRoot "VERSION.txt") -Force

$prohibited = Get-ChildItem -LiteralPath $packageDirectory -Recurse -Force |
    Where-Object {
        $_.Name -in @(
            "tests",
            ".git",
            "build",
            "__pycache__",
            ".pytest_cache",
            ".venv"
        ) -or $_.Extension -eq ".py"
    }
if ($prohibited) {
    throw "Release package contains prohibited source/build content."
}

Compress-Archive `
    -LiteralPath $packageDirectory `
    -DestinationPath $zipPath `
    -CompressionLevel Optimal `
    -Force

$hashTargets = @(
    $zipPath,
    (Join-Path $packageDirectory "PMSMPerformanceTool.exe"),
    (Join-Path $releaseRoot $userReadmeName),
    (Join-Path $releaseRoot "CHANGELOG.md"),
    (Join-Path $releaseRoot "VERSION.txt")
)
$hashLines = foreach ($target in $hashTargets) {
    $hash = Get-FileHash -LiteralPath $target -Algorithm SHA256
    $relative = $hash.Path.Substring($releaseRoot.Length + 1)
    "$($hash.Hash)  $relative"
}
Set-Content `
    -LiteralPath (Join-Path $releaseRoot "SHA256.txt") `
    -Value $hashLines `
    -Encoding utf8

$packageFiles = Get-ChildItem -LiteralPath $packageDirectory -Recurse -File
$packageBytes = ($packageFiles | Measure-Object Length -Sum).Sum
$zipBytes = (Get-Item -LiteralPath $zipPath).Length
$largestFile = $packageFiles | Sort-Object Length -Descending | Select-Object -First 1
Write-Output "Release: $packageDirectory"
Write-Output "Folder bytes: $packageBytes"
Write-Output "ZIP bytes: $zipBytes"
Write-Output "Largest file: $($largestFile.FullName) ($($largestFile.Length) bytes)"

foreach ($temporaryPath in @(
    $releaseEnvironment,
    $releaseWork,
    $releaseDist,
    $releaseSmoke,
    $releaseTestTemp
)) {
    Remove-OwnedPath $temporaryPath $projectRoot
}
