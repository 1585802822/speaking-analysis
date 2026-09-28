@echo off
rem 日常录音分析工具一键启动入口（双击即用）
rem 切换到项目根目录（config.yaml 与 data/ 为相对路径），再交给 Python 启动器
cd /d "%~dp0\.."
uv run python scripts\launcher.py %*
if errorlevel 1 pause
