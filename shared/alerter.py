import logging
import requests
import json
import os
from .config import get_data_path

class GlobalAlerter:
    """
    중앙 집중형 알림 시스템.
    - 텔레그램 알림 단일 창구 제공
    - 중요도(Priority)에 따른 채널 분기 (로그만 vs 텔레그램 포함)
    - 중복 알림 방지(Cooldown) 기능 지원
    """
    def __init__(self, token=None, chat_id=None):
        self.logger = logging.getLogger("GlobalAlerter")
        self.token = token
        self.chat_id = chat_id
        self.alert_cache = {} # {msg_key: last_sent_time}
        self.cooldown = 60    # 기본 1분

    def send_alert(self, message, priority="INFO", use_telegram=False):
        """
        통합 알림 발송
        - priority: INFO, WARNING, ERROR, CRITICAL
        """
        # 1. 로깅 (중앙 집중형 로거 활용)
        log_msg = f"[{priority}] {message}"
        if priority in ["ERROR", "CRITICAL"]:
            self.logger.error(log_msg)
        else:
            self.logger.info(log_msg)

        # 2. 텔레그램 발송
        if use_telegram and self.token and self.chat_id:
            # 중복 메시지 체크 (내용 기반)
            import time
            now = time.time()
            msg_key = hash(message)
            if now - self.alert_cache.get(msg_key, 0) < self.cooldown:
                return # 동일 메시지 쿨다운 중
            
            self._send_telegram(message)
            self.alert_cache[msg_key] = now

    def _send_telegram(self, message):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": f"🚀 [KW_AutoTrading] {message}",
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=data, timeout=5)
        except Exception as e:
            self.logger.warning(f"Telegram send failed: {e}")

# 공용 인스턴스 (선택 사항)
_default_alerter = None

def get_alerter(token=None, chat_id=None):
    global _default_alerter
    if _default_alerter is None:
        _default_alerter = GlobalAlerter(token, chat_id)
    return _default_alerter
