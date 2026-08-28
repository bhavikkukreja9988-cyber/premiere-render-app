@echo off
setlocal
cd /d "%~dp0.."
python -m pip install -r requirements.txt
pyinstaller --noconfirm --clean --windowed --name PremiereRenderApp --paths src src/main.py
endlocal