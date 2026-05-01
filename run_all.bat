@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo [KW_AutoTrading Ecosystem Launcher]
echo Initializing Shared Core and Data...
echo ==========================================
echo.

:: 1. Analyzer_Sig (Integrated Theme/Leader Finder)
echo [1/2] Starting Analyzer_Sig...
start /d "Analyzer_Sig" pythonw main.py

:: 2. AT_Sig (Trading Execution)
echo [2/2] Starting AT_Sig...
start /d "AT_Sig" pythonw trading_ui.py

echo.
echo ==========================================
echo Analyzer_Sig and AT_Sig launched.
echo ==========================================
timeout /t 5
