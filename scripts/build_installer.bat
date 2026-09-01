@echo off
REM ===========================================================================
REM  Build FileSender.exe installer
REM
REM  Steps:
REM    1. Preflight the Windows build machine
REM    2. Create a clean build virtual environment
REM    3. Install app dependencies + PyInstaller
REM    4. Run the active automated tests
REM    5. Build the FileSender desktop executable
REM    6. Wrap it with Inno Setup as dist_installer\FileSender.exe
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo.
echo ==========================================================
echo  FileSender - installer build
echo ==========================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python was not found on PATH.
    echo        Install Python 3.10+ and tick "Add python.exe to PATH".
    goto :fail
)

echo [1/6] Checking build environment...
python scripts\preflight.py
if errorlevel 1 goto :fail

echo.
echo [2/6] Preparing clean build environment...
if not exist ".venv_build" (
    python -m venv .venv_build || goto :fail
)
call .venv_build\Scripts\activate.bat || goto :fail

echo.
echo [3/6] Installing dependencies...
python -m pip install --upgrade pip >nul || goto :fail
python -m pip install -r requirements.txt || goto :fail
python -m pip install pyinstaller || goto :fail

echo.
echo [4/6] Running automated tests...
python -m unittest discover -s tests -t . || goto :testfail

echo.
echo [5/6] Building FileSender.exe...
if exist "build_app" rmdir /s /q "build_app"
if exist "build_pyi" rmdir /s /q "build_pyi"
pyinstaller --noconfirm --clean ^
    --distpath build_app ^
    --workpath build_pyi ^
    installer\PremiereRenderApp.spec || goto :fail

if not exist "build_app\FileSender\FileSender.exe" (
    echo [FAIL] Expected build_app\FileSender\FileSender.exe was not created.
    goto :fail
)

echo.
echo [6/6] Building installer...
set "ISCC="
where ISCC >nul 2>&1 && set "ISCC=ISCC"
if "!ISCC!"=="" if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" (
    echo [FAIL] Inno Setup compiler ISCC.exe was not found.
    echo        Install Inno Setup 6 and run this script again.
    goto :fail
)

if exist "dist_installer" rmdir /s /q "dist_installer"
"!ISCC!" installer\FileSender.iss || goto :fail

if not exist "dist_installer\FileSender.exe" (
    echo [FAIL] Installer was not created.
    goto :fail
)

echo.
echo ==========================================================
echo  SUCCESS
echo  dist_installer\FileSender.exe
echo ==========================================================
call deactivate >nul 2>&1
pause
exit /b 0

:testfail
echo.
echo [FAIL] Automated tests failed. No installer was produced.
call deactivate >nul 2>&1
pause
exit /b 1

:fail
echo.
echo Build stopped. Fix the failure above and run again.
call deactivate >nul 2>&1
pause
exit /b 1
