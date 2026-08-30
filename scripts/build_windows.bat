@echo off
REM Build PremiereRenderApp.exe on Windows.
setlocal
cd /d "%~dp0.."

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv || goto :failed
)
call .venv\Scripts\activate.bat || goto :failed

echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :failed
python -m pip install pyinstaller || goto :failed

echo Running tests...
python -m unittest discover -s tests -t . || goto :failed

echo Building executable...
pyinstaller --noconfirm --clean scripts\PremiereRenderApp.spec || goto :failed

echo.
echo Build complete: dist\PremiereRenderApp\PremiereRenderApp.exe
goto :eof

:failed
echo.
echo BUILD FAILED
exit /b 1
