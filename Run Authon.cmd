@echo off
cd /d "%~dp0"
python authon.py
if errorlevel 1 pause
