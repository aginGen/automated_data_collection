@echo off
chcp 65001 >nul
python "%~dp0launch.py" %*
if errorlevel 1 pause
