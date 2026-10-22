@echo off
rem Double-click this file to install Docs Typer on Windows.
rem It adds Docs Typer to the Start menu and desktop, then opens it.
rem Afterwards you can delete this folder: Docs Typer keeps its own copy.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "install.ps1"
echo.
pause
