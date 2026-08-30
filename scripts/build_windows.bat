@echo off
REM This project now builds a proper installer (FileSender.exe).
REM This script just forwards to the installer build for convenience.
call "%~dp0build_installer.bat" %*
