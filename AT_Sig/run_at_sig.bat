@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo   Sotdanji AutoTrading System  (AT_Sig)
echo  ==========================================
echo.
echo  Starting AT_Sig...
echo.
pythonw main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] AT_Sig failed to start.
    echo  Please check the error message above.
    echo.
    pause
)
