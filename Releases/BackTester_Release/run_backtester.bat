@echo off
cd /d "%~dp0"
echo.
echo  ======================================
echo   Sotdanji Backtesting Lab  v1.2.0
echo  ======================================
echo.
echo  Starting BackTester...
echo.
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] BackTester failed to start.
    echo  Check logs\backtester.log for details.
    echo.
    pause
)
