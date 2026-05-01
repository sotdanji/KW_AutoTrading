import logging
import sqlite3
import json
import os
from datetime import datetime, timedelta
from shared.api import fetch_daily_chart

class DataManager:
    """
    데이터 요청, 캐싱, 관리를 담당하는 클래스.
    Singleton 패턴 혹은 단일 인스턴스로 사용 권장.
    SQLite를 사용하여 영구 캐싱을 지원합니다.
    """
    _instance = None
    # [안실장 유지보수 가이드] DB 경로를 루트의 data/ 폴더로 통합
    def get_db_path():
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        path = os.path.join(project_root, "data", "cache.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path
        
    DB_PATH = get_db_path()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataManager, cls).__new__(cls)
            cls._instance._init_once()
        return cls._instance

    def _init_once(self):
        self.logger = logging.getLogger("AT_Sig.DataManager")
        
        # SQLite 초기화
        self._init_db()

    def _init_db(self):
        """데이터베이스 및 테이블 초기화"""
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                conn.execute("PRAGMA journal_mode=WAL") # [Optimization] 동시성 성능 향상
                cursor = conn.cursor()
                # 일봉 데이터 캐시 테이블
                # stk_cd: 종목코드
                # data_json: JSON 문자열로 된 데이터
                # updated_at: 저장된 시간 (ISO Format)
                # target_date: 데이터의 기준 날짜 (장 마감일 등, 옵션)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_chart (
                        stk_cd TEXT PRIMARY KEY,
                        data_json TEXT,
                        updated_at TEXT
                    )
                """)
                conn.commit()
                self.logger.info("DataManager DB initialized.")
        except Exception as e:
            self.logger.error(f"DB Initialization failed: {e}")

    def get_daily_chart(self, stk_cd, token, use_cache=True, days=500):
        """
        일봉 차트 데이터를 가져옵니다.
        
        Args:
            stk_cd (str): 종목 코드
            token (str): API 토큰
            use_cache (bool): 캐시 사용 여부 (True 권장)
            
        Returns:
            list: 일봉 데이터 리스트
        """
        # 1. 캐시 확인
        if use_cache:
            cached_data = self._get_from_cache(stk_cd)
            if cached_data: # 90% 이상 채워져있으면 통과 (영업일 기준)
                return cached_data

        # 2. API 호출
        try:
            from config import get_current_config
            conf = get_current_config()
            host_url = conf['host_url']
            
            data = fetch_daily_chart(host_url, stk_cd, token=token, days=days)
            if data:
                if use_cache:
                    self._save_to_cache(stk_cd, data)
                return data
            else:
                self.logger.warning(f"No daily chart data for {stk_cd}")
                return []
        except Exception as e:
            self.logger.error(f"Error fetching daily chart for {stk_cd}: {e}")
            return []

    def get_minute_chart(self, stk_cd, token, min_tp='1', use_cache=True):
        """
        분봉 차트 데이터를 가져옵니다. (단타/실시간 전략 웜업용)
        
        Args:
            stk_cd (str): 종목 코드
            token (str): API 토큰
            min_tp (str): 분봉 틱수 (기본값 '1' = 1분봉)
            use_cache (bool): 캐시 사용 여부
        """
        # 분봉은 cache키를 종목코드_분봉타입 형태로 구분
        cache_key = f"{stk_cd}_m{min_tp}"
        
        if use_cache:
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                return cached_data

        try:
            from config import get_current_config
            conf = get_current_config()
            host_url = conf['host_url']
            
            from shared.api import fetch_minute_chart_ka10080
            # [안실장 추가] 분봉 데이터 호출 API 연결
            data = fetch_minute_chart_ka10080(host_url, stk_cd, token, min_tp)
            
            if data:
                if use_cache:
                    self._save_to_cache(cache_key, data)
                return data
            else:
                self.logger.warning(f"No minute chart data for {stk_cd}")
                return []
        except Exception as e:
            self.logger.error(f"Error fetching minute chart for {stk_cd}: {e}")
            return []

    def _get_from_cache(self, stk_cd):
        """DB에서 유효한 캐시 조회"""
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json, updated_at FROM daily_chart WHERE stk_cd = ?", (stk_cd,))
                row = cursor.fetchone()
                
                if row:
                    data_json, updated_at_str = row
                    updated_at = datetime.fromisoformat(updated_at_str)
                    
                    # 만료 정책: 
                    # 1. 마지막 업데이트가 오늘 장 시작 전이면 만료?
                    # 2. 간단하게: 현재 시간과 updated_at의 날짜가 다르면 만료 (하루 1회 갱신)
                    # 단, 장 중에는 실시간 데이터가 중요하므로 일봉은 전일자까지가 확실함. 
                    # 여기서는 '같은 날짜'이면 유효하다고 판단 (즉, 오늘 받은건 오늘 계속 씀)
                    if datetime.now().date() == updated_at.date():
                        self.logger.debug(f"Cache HIT for {stk_cd}")
                        return json.loads(data_json)
                    else:
                        self.logger.debug(f"Cache EXPIRED for {stk_cd} (Date mismatch)")
                else:
                    self.logger.debug(f"Cache MISS for {stk_cd}")
                    
        except Exception as e:
            self.logger.error(f"Cache read error: {e}")
            
        return None

    def _save_to_cache(self, stk_cd, data):
        """DB에 데이터 저장"""
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                json_data = json.dumps(data, ensure_ascii=False)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO daily_chart (stk_cd, data_json, updated_at)
                    VALUES (?, ?, ?)
                """, (stk_cd, json_data, now))
                conn.commit()
                self.logger.debug(f"Cache SAVED for {stk_cd}")
        except Exception as e:
            self.logger.error(f"Cache write error: {e}")

    def clear_cache(self):
        """캐시를 비웁니다 (DB Truncate)"""
        try:
            with sqlite3.connect(self.DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM daily_chart")
                conn.commit()
            self.logger.info("DataManager cache cleared (DB truncated)")
        except Exception as e:
            self.logger.error(f"Cache clear error: {e}")
