@echo off
rem One-click launcher for the daily speaking analysis tool.
rem Switch to the project root (config.yaml and data/ are relative paths).
cd /d "%~dp0.."
uv run python "%~dp0launcher.py" %*
if errorlevel 1 pause
