import os
import json
import time
from typing import Any, Dict, Optional
import config as secret_config  # 기존 config.py에서 시크릿 가져오기

class ConfigManager:
    _instance = None
    _settings_cache: Dict[str, Any] = {}
    _last_load_time = 0
    CACHE_DURATION = 5  # 캐시 유효 시간 (초)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_settings()
        return cls._instance

    def _get_settings_path(self) -> str:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, 'settings.json')

    def _load_settings(self, force: bool = False):
        """설정 파일 로드 (캐시 적용)"""
        now = time.time()
        if not force and (now - self._last_load_time < self.CACHE_DURATION) and self._settings_cache:
            return

        try:
            path = self._get_settings_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    self._settings_cache = json.load(f)
            else:
                self._settings_cache = {}
            self._last_load_time = now
        except Exception as e:
            print(f"Error loading settings: {e}") # 로거가 초기화되기 전일 수 있으므로 print 사용

    def get(self, key: str, default: Any = None) -> Any:
        """설정값 가져오기"""
        self._load_settings()
        return self._settings_cache.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """설정값 저장하기"""
        try:
            self._load_settings() # 최신 상태 로드
            self._settings_cache[key] = value
            
            path = self._get_settings_path()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._settings_cache, f, ensure_ascii=False, indent=2)
            
            # 캐시 갱신 타임스탬프 업데이트 (방금 저장했으므로 최신)
            self._last_load_time = time.time()
            return True
        except Exception as e:
            print(f"Error saving setting {key}: {e}")
            return False

    def get_all(self) -> Dict[str, Any]:
        """모든 설정 반환"""
        self._load_settings()
        return self._settings_cache.copy()

    @property
    def telegram_token(self) -> str:
        """텔레그램 토큰 (config.py에서 가져옴)"""
        return getattr(secret_config, 'telegram_token', '')

    @property
    def telegram_chat_id(self) -> str:
        """텔레그램 챗 ID"""
        return getattr(secret_config, 'telegram_chat_id', '')

    def get_api_config(self) -> Dict[str, str]:
        """현재 모드(실전/모의)에 따른 API 설정 반환"""
        account_mode = self.get('account_mode', 'PAPER')
        is_real = (account_mode == 'REAL')
        
        if is_real:
            return {
                'app_key': getattr(secret_config, 'real_app_key', ''),
                'app_secret': getattr(secret_config, 'real_app_secret', ''),
                'host_url': getattr(secret_config, 'real_host_url', ''),
                'socket_url': getattr(secret_config, 'real_socket_url', ''),
            }
        else:
            return {
                'app_key': getattr(secret_config, 'paper_app_key', ''),
                'app_secret': getattr(secret_config, 'paper_app_secret', ''),
                'host_url': getattr(secret_config, 'paper_host_url', ''),
                'socket_url': getattr(secret_config, 'paper_socket_url', ''),
            }

# 전역 인스턴스
config = ConfigManager()
