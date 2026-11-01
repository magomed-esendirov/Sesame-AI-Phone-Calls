@echo off
rem Maya Phone Bridge: горячие клавиши Ctrl+Alt+1..4, 0
chcp 65001 >nul
cd /d "%~dp0"
python maya.py hotkeys
pause
