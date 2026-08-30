@echo off
REM ===========================================================================
REM  Build FileSender.exe  (the Premiere Render App installer)
REM
REM  What this does, in order:
REM    1. Checks your machine is ready (preflight)
REM    2. Creates a clean Python environment
REM    3. Installs the app's dependencies
REM    4. Runs the automated tests
REM    5. Builds the app with PyInstaller
REM    6. Wraps it into the installer with Inno Setup
REM
REM  You run this ONCE. The finished installer appears at:
REM    dist_installer\FileSender.exe
REM
REM  Just double-click this file, or run it from a terminal. If anything is
REM  missing it stops and tells you exactly what to fix.
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo.
echo ==========================================================
echo  Premiere Render App - installer build
echo ==========================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python was not found on PATH.
    echo        Install Python 3.10+ and tick "Add python.exe to PATH".
    goto :fail
)

echo [1/6] Checking your machine is ready...
python scripts\preflight.py
if errorlevel 1 goto :fail

echo.
echo [2/6] Preparing a clean build environment...
if not exist ".venv_build" python -m venv .venv_build || goto :fail
call .venv_build\Scripts\activate.bat || goto :fail

echo.
echo [3/6] Installing dependencies (this can take a few minutes)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :fail
python -m pip install pyinstaller || goto :fail

echo.
echo [4/6] Running automated tests...
python -m unittest discover -s tests -t . || goto :testfail

echo.
echo [5/6] Building the application...
if exist "build_app" rmdir /s /q "build_app"
if exist "build_pyi" rmdir /s /q "build_pyi"
pyinstaller --noconfirm --clean --distpath build_app --workpath build_pyi installer\PremiereRenderApp.spec || goto :fail
if not exist "build_app\PremiereRenderApp\PremiereRenderApp.exe" (
    echo [FAIL] PyInstaller did not produce the expected executable.
    goto :fail
)

echo.
echo [6/6] Building the installer (FileSender.exe)...
set "ISCC="
where ISCC >nul 2>&1 && set "ISCC=ISCC"
if "!ISCC!"=="" if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    echo [FAIL] Inno Setup compiler ^(ISCC^) not found.
    echo        Install Inno Setup 6.
    goto :fail
)
if exist "dist_installer" rmdir /s /q "dist_installer"
"!ISCC!" installer\FileSender.iss || goto :fail
if not exist "dist_installer\FileSender.exe" (
    echo [FAIL] Inno Setup did not produce FileSender.exe.
    goto :fail
)

echo.
echo ==========================================================
echo  SUCCESS
echo.
echo  Your installer is ready:
echo      dist_installer\FileSender.exe
echo.
echo  Copy that one file to any Windows PC and run it to install
echo  the app. No Python needed on those PCs.
echo ==========================================================
call deactivate >nul 2>&1
pause
exit /b 0

:testfail
echo.
echo [FAIL] Automated tests did not pass. The build was stopped so you do not
more ship a broken app. Send the messages above to your developer.
call deactivate >nul 2>&1
pause
exit /b 1

:fail
echo.
echo Build stopped. See the message above for what to fix.
call deactivate >nul 2>&1
pause
exit /b 1
