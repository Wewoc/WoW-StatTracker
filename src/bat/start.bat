@echo off
rem Start StatTracker from source (needs Python 3.10+ with tkinter). Keeps the window open on errors.
cd /d "%~dp0\..\.."
python src\start.py
if errorlevel 1 pause
