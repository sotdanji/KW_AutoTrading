@echo off
setlocal
cd /d "%~dp0"

title KW_AutoTrading Master Control Debugger

echo ==========================================================
echo [디버그 모드] KW_AutoTrading 통합 관제 시스템
echo 오류 원인을 파악하기 위해 콘솔 모드로 기동합니다.
echo ==========================================================
echo.

:: Python 설치 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
	echo [오류] Python이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
	pause
	exit /b 1
)

echo [기동] Master_Control.py 실행 중... (콘솔 창 유지)
echo.
:: pythonw 대신 python을 사용하여 에러 메시지를 화면에 출력
python Master_Control.py

echo.
echo ==========================================================
echo 프로그램이 종료되었습니다. 
echo 위 에러 메시지를 확인하신 후 아무 키나 눌러주세요.
echo ==========================================================
pause
