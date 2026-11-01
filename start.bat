@echo off
rem Maya Phone Bridge - start
chcp 65001 >nul
title Maya Phone Bridge
cd /d "%~dp0"
python maya.py start
pause
