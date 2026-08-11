@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo ERROR: .venv was not found. Create it and install requirements.txt first.
    exit /b 1
)

pushd "%PROJECT_ROOT%"
"%VENV_PYTHON%" -m PyInstaller --noconfirm --clean PMSMPerformanceTool.spec
set "BUILD_RESULT=%ERRORLEVEL%"
popd

if not "%BUILD_RESULT%"=="0" (
    echo ERROR: PyInstaller failed with exit code %BUILD_RESULT%.
    exit /b %BUILD_RESULT%
)

echo Build complete: dist\PMSMPerformanceTool.exe
exit /b 0
