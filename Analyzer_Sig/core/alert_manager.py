import time
from datetime import datetime
from core.logger import get_logger

logger = get_logger(__name__)

class AlertManager:
    """
    관심 종목에 대한 실시간 이벤트(VI 임박, 거래대금 폭발 등)를 감지하고 
    중복 알림을 방지하기 위한 관리 클래스입니다.
    """
    def __init__(self):
        # 중복 알람을 막기 위한 캐시: { code: last_alert_time }
        self.alert_cache = {}
        # 같은 종목에 대해 최소 10분간 알람을 보내지 않음
        self.cooldown_seconds = 600

    def check_and_alert(self, stock_info, vi_vol_data):
        """
        data_fetcher에서 받아온 VI 및 거래량 폭발 여부 데이터를 확인합니다.
        조건에 맞으면 알람 메시지를 반환합니다.
        
        stock_info: {'code': '005930', 'name': '삼성전자', 'price': 50000}
        vi_vol_data: {'is_vi_near': True, 'is_vol_spike': True, 'vol_ratio': 600.0}
        """
        code = stock_info.get('code')
        name = stock_info.get('name')
        
        is_vi = vi_vol_data.get('is_vi_near', False)
        is_spike = vi_vol_data.get('is_vol_spike', False)
        vol_ratio = vi_vol_data.get('vol_ratio', 0.0)
        
        alerts = []
        if is_vi:
            alerts.append("🔔 VI 임박")
        if is_spike:
            alerts.append(f"💥 거래량 폭증({vol_ratio:.0f}%)")
            
        if not alerts:
            return None
            
        now = time.time()
        last_alert = self.alert_cache.get(code, 0)
        
        # Cooldown check
        if now - last_alert < self.cooldown_seconds:
            return None
            
        # Register new alert
        self.alert_cache[code] = now
        
        alert_msg = f"[🔥 초기폭발 감지] {name}({code}) | " + ", ".join(alerts)
        logger.info(alert_msg)
        return alert_msg
