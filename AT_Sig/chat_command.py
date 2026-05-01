import asyncio
import requests
from trading_engine import TradingEngine
from tel_send import tel_send
from get_setting import update_setting, get_setting
from shared.market_hour import MarketHour
from config import telegram_token

class ChatCommand:
    """
    텔레그램 명령어 처리 및 TradingEngine과의 인터페이스 역할.
    TradingEngine 제어 및 텔레그램 메시지 폴링(Polling) 기능을 담당.
    """
    def __init__(self, ui_callback_func=None):
        # UI Callback: TradingUI 등에서 엔진 이벤트를 받기 위함 (예: 매매 확인 요청)
        self.engine = TradingEngine(ui_callback=self._engine_callback)
        self.external_ui_callback = ui_callback_func
        
        # 텔레그램 폴링 관련
        self.last_update_id = 0
        self.telegram_url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
        self.is_polling = False
        self.polling_task = None

    def _engine_callback(self, type, data):
        """엔진에서 발생한 이벤트를 처리"""
        # 로그는 로거가 파일/콘솔로 처리하므로 무시 (단, 필요시 전달 가능)
        if type == 'log':
            pass
        else:
            # confirm, captured, filter_update 등 모든 이벤트 전달
            if self.external_ui_callback:
                self.external_ui_callback(type, data)
            elif type == 'confirm':
                # UI가 연결되지 않았는데 confirm 요청이 오면 로그만
                print(f"매매 확인 요청 수신 (UI 미연결): {data}")
    
    async def start(self, token=None):
        """start 명령어"""
        return await self.engine.start(token)

    async def stop(self, set_auto_start_false=True):
        """stop 명령어"""
        # 사용자 요청일 때만 설정 변경
        if set_auto_start_false:
            update_setting('auto_start', False)
        return await self.engine.stop()

    async def report(self):
        """report 명령어"""
        token = self.engine.token
        if not token:
             from login import fn_au10001
             token = fn_au10001()
        
        try:
            # 토큰이 갱신되었을 수 있으므로 브로커에 설정
            self.engine.broker.set_token(token)
            
            account_data = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, self.engine.broker.get_holdings),
                timeout=10.0
            )
            
            if not account_data:
                tel_send("📊 계좌평가현황 데이터가 없습니다.")
                return False
            
            message = "📊 [계좌평가현황 보고서]\n\n"
            total_profit_loss = 0
            total_pl_amt = 0
            
            for stock in account_data:
                stock_name = stock.get('stk_nm', 'N/A')
                profit_loss_rate = float(stock.get('pl_rt', 0))
                pl_amt = int(stock.get('pl_amt', 0))
                message += f"[{stock_name}] {profit_loss_rate:+.2f}% ({pl_amt:,}원)\n"
                total_profit_loss += profit_loss_rate
                total_pl_amt += pl_amt
                
            message += f"\n총 평가손익: {total_pl_amt:,}원"
            tel_send(message)
            return True

        except Exception as e:
            tel_send(f"❌ report 오류: {e}")
            return False

    async def process_command(self, text):
        """명령어 처리 분기"""
        command = text.strip().lower()
        
        if command == 'start':
            return await self.start()
        elif command == 'stop':
            return await self.stop(True)
        elif command in ['report', 'r']:
            return await self.report()
        elif command == 'help':
            tel_send("지원 명령어: start, stop, report (상세 설정은 UI 또는 설정파일 이용)")
            return True
        else:
            tel_send(f"알 수 없는 명령어: {command}")
            return False

    # === Telegram Polling Methods ===
    
    def get_updates_sync(self):
        """텔레그램 업데이트 조회 (동기)"""
        try:
            params = {
                'offset': self.last_update_id + 1,
                'timeout': 10
            }
            response = requests.get(self.telegram_url, params=params, timeout=15)
            data = response.json()
            
            if data.get('ok'):
                updates = data.get('result', [])
                for update in updates:
                    self.last_update_id = update['update_id']
                    if 'message' in update and 'text' in update['message']:
                        return update['message']['text']
            return None
        except Exception as e:
            print(f"Telegram polling error: {e}")
            return None

    async def run_polling(self):
        """텔레그램 폴링 태스크 실행"""
        self.is_polling = True
        print("텔레그램 폴링 시작")
        
        while self.is_polling:
            try:
                # 동기 요청을 비동기로 실행
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, self.get_updates_sync)
                
                if text:
                    print(f"텔레그램 명령어 수신: {text}")
                    await self.process_command(text)
                
                await asyncio.sleep(1)
            except Exception as e:
                print(f"폴링 루프 오류: {e}")
                await asyncio.sleep(5)
    
    def stop_polling(self):
        self.is_polling = False
        if self.polling_task:
            self.polling_task.cancel()
