import asyncio
import sys
import os
import traceback

# Add project root and local directory to sys.path at the very beginning
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime
from chat_command import ChatCommand
from get_setting import get_setting
from shared.market_hour import MarketHour

# GUI 모드로 실행 (기본)
def main():
    """
    main.py를 실행하면 GUI 모드로 자동매매 프로그램이 시작됩니다.
    텔레그램 기반 모드를 사용하려면 main_telegram()을 호출하세요.
    """
    # trading_ui 임포트 및 실행
    try:
        import trading_ui
        from tel_send import tel_send
        
        # Global Exception Hook Setting
        def exception_hook(exctype, value, tb):
            print("Unhandled Exception:")
            traceback.print_exception(exctype, value, tb)
            error_msg = "".join(traceback.format_exception(exctype, value, tb))
            
            # 1. Send Telegram Alert (Async)
            try:
                tel_send(f"🚨 [CRITICAL ERROR]\n{error_msg}", threaded=True)
            except:
                pass
            
            # 2. UI Message Box
            try:
                from PyQt6.QtWidgets import QApplication, QMessageBox
                if QApplication.instance():
                    QMessageBox.critical(None, "치명적 오류", f"프로그램 실행 중 오류가 발생했습니다:\n{error_msg}")
            except:
                pass

        sys.excepthook = exception_hook
        
        trading_ui.main()
    except Exception as e:
        print(f"UI 실행 중 오류 발생: {e}")
        traceback.print_exc()

# 텔레그램 기반 모드 (CLI)
async def main_telegram():
    """텔레그램 기반 명령어 모드로 실행 (GUI 없음)"""
    print("텔레그램 봇 모드를 시작합니다...")
    
    # ChatCommand 인스턴스 생성
    chat_cmd = ChatCommand()
    
    # 텔레그램 폴링 태스크 시작
    polling_task = asyncio.create_task(chat_cmd.run_polling())
    
    # 자동매매 스케줄링 변수
    last_check_date = None
    today_started = False
    today_stopped = False
    
    try:
        while True:
            # 스케줄링 로직
            auto_start = get_setting('auto_start', False)
            today = datetime.now().date()
            
            if last_check_date != today:
                today_started = False
                today_stopped = False
                last_check_date = today
                
            if MarketHour.is_market_start_time() and auto_start and not today_started:
                print(f"장 시작 시간입니다. 자동매매를 시작합니다.")
                await chat_cmd.start()
                today_started = True
                
            elif MarketHour.is_market_end_time() and not today_stopped:
                print(f"장 종료 시간입니다. 자동매매를 종료합니다.")
                await chat_cmd.stop(False)
                print("자동으로 계좌평가 보고서를 발송합니다.")
                await chat_cmd.report()
                today_stopped = True
                
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다...")
        chat_cmd.stop_polling()
        # polling_task 취소 대기
        polling_task.cancel()
        try:
             await polling_task
        except asyncio.CancelledError:
             pass
             
        await chat_cmd.engine.stop()
        chat_cmd.engine.shutdown()

if __name__ == '__main__':
    # GUI 모드로 실행
    main()
    
    # 텔레그램 모드로 실행하려면 아래 주석을 해제하세요
    # asyncio.run(main_telegram())
