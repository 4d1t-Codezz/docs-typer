@echo off
rem Launches Docs Typer without a console window.
pushd "%~dp0.."
start "" pythonw -m docstyper
popd
