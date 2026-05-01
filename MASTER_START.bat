@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

:: ── 관리자 권한 확인 및 자동 재실행 ───────────────────────────────
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [KW_AutoTrading] 관리자 권한이 필요합니다. 권한 승격 중...
    powershell -Command "Start-Process cmd -ArgumentList '/c, \"%~f0\"' -Verb RunAs"
    exit /b
)

:: ── Python 버전 확인 (3.11+ 권장) ──────────────────────────────────
python --version >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo       https://www.python.org 에서 Python 3.11 이상을 설치하세요.
    pause
    exit /b 1
)

:: ── 의존성 확인 ─────────────────────────────────────────────────────
python -c "import dotenv" >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [설치] python-dotenv가 없습니다. 설치 중...
    pip install -r requirements.txt -q
)

:: ── .env 파일 존재 확인 ─────────────────────────────────────────────
if not exist ".env" (
    echo.
    echo [경고] .env 파일이 없습니다. API 키가 설정되지 않았습니다.
    echo        지금 setup_keys.py를 실행하여 API 키를 등록하세요.
    echo.
    set /p RUN_SETUP="지금 setup_keys.py를 실행하시겠습니까? (Y/N): "
    if /i "%RUN_SETUP%"=="Y" (
        python setup_keys.py
    ) else (
        echo [중단] API 키 없이는 실행할 수 없습니다.
        pause
        exit /b 1
    )
)

:: ── 시스템 실행 ─────────────────────────────────────────────────────
echo.
echo ==========================================================
echo [Sotdanji Lab] KW_AutoTrading Center
echo ==========================================================
echo.

echo Launching Master_Control.py...
start "" pythonw Master_Control.py

timeout /t 2 >nul
exit
