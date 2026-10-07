@echo off
REM ===========================================================================
REM  Builds dist_tools\FileSender-ConnectionTest.exe - ONE file that can be
REM  copied to any Windows PC and double-clicked (no Python needed there).
REM ===========================================================================
setlocal
cd /d "%~dp0.."

echo.
echo Building the FileSender connection test...
set "PY=python"
if exist ".venv_build\Scripts\python.exe" set "PY=.venv_build\Scripts\python.exe"

"%PY%" -m pip install --quiet pyinstaller || goto :fail
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console ^
    --name FileSender-ConnectionTest ^
    --distpath dist_tools --workpath build_tools --specpath build_tools ^
    tools\connection_test.py || goto :fail
if not exist "dist_tools\FileSender-ConnectionTest.exe" goto :fail

echo.
echo ==========================================================
echo  [ ok ] Built: dist_tools\FileSender-ConnectionTest.exe
echo.
echo  Copy that ONE file to both PCs and double-click it.
echo  See docs\CONNECTION_TEST_GUIDE.txt
echo ==========================================================
pause
exit /b 0

:fail
echo.
echo [FAIL] Could not build the connection test. See the messages above.
pause
exit /b 1
