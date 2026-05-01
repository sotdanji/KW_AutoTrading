from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.logger import get_logger
from config import (
    UNIV_MIN_PRICE, 
    UNIV_MIN_PREV_VOL, 
    UNIV_HISTORY_DAYS
)

logger = get_logger(__name__)

class PreMarketLoader:
    """
    [장전/초기화 단계 핵심 모듈]
    1. 전 종목(혹은 주요 섹터) 스캔
    2. 1차 필터 (가격 >= 2000, 전일거래량 >= 10만) 적용
    3. 통과된 'Target Universe'에 대해 600일치 일봉 데이터 확보
    4. 기술적 지표(이평선, 볼린저, 전고점) 사전 계산 및 캐싱
    """
    
    def __init__(self, data_fetcher):
        self.fetcher = data_fetcher
        from shared.db_manager import DBManager
        self.db = DBManager()
        self.market_universe = {}  # {code: {name, info...}} 1차 필터 통과 종목
        self.daily_cache = {}      # {code: DataFrame OR Dict} 
        # Note: DB 로드 시 dict, API 로드 시 DataFrame일 수 있음 -> 통일 필요하지만,
        # get_indicator_status에서 유연하게 처리하도록 함.
        self.is_initialized = False

    def initialize_universe(self):
        """
        전체 종목을 스캔하여 '자격 있는 종목'만 선별 (Target Universe 구성)
        """
        logger.info("[PreMarket] Starting Universe Scan...")
        start_time = time.time()
        
        # [NEW] 1. DB 캐시 우선 확인 (Smart Loading) -> [Disabled] 항상 전체 스캔 수행
        # 142개 테마 전체 분석을 위해 캐시를 무시하고 강제 스캔
        # db_cache = self.db.load_daily_cache()
        # if db_cache:
        #     logger.info(f"[PreMarket] Loaded {len(db_cache)} stocks from DB Cache.")
        #     self.daily_cache = db_cache 
        #     self.is_initialized = True
        #     return

        # --- Cache MISS -> Fallback to API Scan ---

        
        # 1. 전체 종목 리스트 확보
        # (API 효율성을 위해 모든 섹터를 순회하거나, 마스터 파일을 다운로드 받는 방식 사용)
        # 여기서는 DataFetcher를 통해 가용한 모든 종목을 스캔한다고 가정
        # *최적화*: DataFetcher에 '모든 종목 간략 정보 로딩' 기능 필요. 
        # 현재는 개별 섹터 조회를 순회하는 방식으로 구현 (병렬 처리 권장)
        
        all_candidates = self._fetch_all_candidates()
        logger.info(f"[PreMarket] Scanned {len(all_candidates)} raw candidates.")

        # 2. 1차 필터링 (In-Memory Filter)
        passed_stocks = []
        for stock in all_candidates:
            if self._check_basic_qualification(stock):
                passed_stocks.append(stock)
                
        # 3. Universe 등록
        for s in passed_stocks:
            self.market_universe[s['code']] = s
            
        logger.info(f"[PreMarket] Universe Created. {len(passed_stocks)} stocks survived (Time: {time.time() - start_time:.2f}s)")
        
        # 4. 심층 데이터 로딩 (Deep Loading) - V3 엔진에서는 당일 거래대금과 등락률만 사용하므로 과거 데이터 수집 생략 
        # self._load_history_data_parallel(passed_stocks)
        
        self.is_initialized = True

    def _fetch_all_candidates(self):
        """
        모든 종목의 기본 정보를 가져옴.
        Mark-V: 섹터 수집 제거, 오직 '테마(Theme)' 기준으로만 수집.
        """
        candidates = []
        seen_codes = set()
        
        # Mock Mode인 경우
        if self.fetcher.mode == "PAPER":
            return self.fetcher._get_mock_stock_data("Universe_Scan") * 5 
            
        # [Theme Only Strategy]
        # 전체 테마를 조회한 후, 상위 테마들의 구성 종목을 모두 수집하여 Universe로 삼음.
        
        logger.info("[PreMarket] Scanning Themes (No Sectors)...")
        try:
            # 전체 테마 리스트를 가져와서 내부 캐시(theme_code_cache)를 갱신
            all_themes = self.fetcher.get_theme_groups() 
            
            # 섹터를 포기했으므로 테마 범위를 넓힘 (Top 40)
            # 너무 많으면 초기 로딩이 길어질 수 있으니 40개 정도로 타협
            scan_limit = 40
            target_themes = all_themes[:scan_limit]
            
            logger.info(f"[PreMarket] Collecting stocks from Top {len(target_themes)} Themes...")
            
            for i, theme_info in enumerate(target_themes):
                t_name = theme_info['name']
                # 각 테마별 종목 수집
                stocks = self.fetcher.get_theme_stocks(t_name)
                
                count = 0
                for s in stocks:
                    if s['code'] not in seen_codes:
                        seen_codes.add(s['code'])
                        candidates.append(s)
                        count += 1
                        
                # 진행 상황 로깅 (가끔)
                if (i+1) % 10 == 0:
                    logger.debug(f"Scanned {i+1}/{len(target_themes)} themes...")
                    
                time.sleep(0.1) # API 부하 조절
                
        except Exception as e:
            logger.warning(f"Failed to scan themes: {e}")
            
        return candidates

    def _check_basic_qualification(self, stock):
        """
        1차 필터 검증
        """
        price = stock.get('price', 0)
        # 거래량 필드: volume (당일), 전일 거래량은 API 응답에 따라 다를 수 있음.
        # *중요*: scan 시점에 '전일 거래량' 필드가 없다면, 
        # 당일 거래량이 장 시작 후 쌓인 것일 수 있으므로 주의 필요.
        # 장전 로직에서는 '전일 데이터'를 기준으로 해야 함.
        # 현재 DataFetcher 구조상 실시간 시세 위주이므로, 
        # 여기서는 '현재 가격'만 1차로 보고 패스하거나, 별도 쿼리가 필요.
        
        # (임시) 가격 조건만 체크
        if price < UNIV_MIN_PRICE:
            return False
            
        return True

    def _load_history_data_parallel(self, stock_list):
        """
        선별된 종목들의 600일치 데이터를 병렬로 가져와 지표 계산
        """
        logger.info(f"[PreMarket] Loading 600-day history for {len(stock_list)} stocks...")
        
        # 너무 많은 병렬 요청은 API 밴 위험 -> 적절히 조절 (Executor Workers = 2~4)
        count = 0 
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_code = {
                executor.submit(self._process_single_history, s['code']): s['code'] 
                for s in stock_list
            }
            
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    df = future.result()
                    if df is not None:
                        self.daily_cache[code] = df
                        count += 1
                except Exception as e:
                    logger.error(f"Error processing history for {code}: {e}")
                    
        if count > 0:
            logger.info(f"[PreMarket] Saving {count} records to DB Cache...")
            self.db.save_daily_cache(self.daily_cache)
            
        logger.info(f"[PreMarket] Deep Loading Complete. Cached {count}/{len(stock_list)} stocks.")

    def _process_single_history(self, code):
        """
        단일 종목의 600일 데이터 요청 및 지표 계산
        """
        # 1. API Fetch
        # DataFetcher에 _fetch_daily_history(code, days) 메서드가 필요함 (신규 구현 필요)
        # 여기서는 메서드 호출을 가정
        raw_data = self.fetcher.fetch_daily_history_raw(code, days=UNIV_HISTORY_DAYS)
        
        if not raw_data:
            return None
            
        # 2. DataFrame 변환
        df = pd.DataFrame(raw_data)
        # 필수 컬럼: date, open, high, low, close, volume (모두 숫자형 변환 필수)
        
        try:
            df['close'] = pd.to_numeric(df['close'])
            df['open'] = pd.to_numeric(df['open'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['volume'] = pd.to_numeric(df['volume'])
            df = df.sort_values('date') # 날짜 오름차순
        except Exception as e:
            logger.warning(f"Data conversion failed for {code}: {e}")
            return None
            
        # 3. 2차 필터 (전일 거래량 확인)
        # 데이터의 마지막(-1)은 오늘(혹은 최근), 그 전(-2)이 전일
        if len(df) >= 2:
            prev_vol = df.iloc[-2]['volume']
            if prev_vol < UNIV_MIN_PREV_VOL:
                return None # 탈락
                
                
        # 4. (Legacy) 기술적 지표 계산 생략
        # V3 엔진에서는 당일 거래대금과 등락률(가속도)만으로 판단하므로
        # 과거 일봉 기반 볼린저밴드, 전고점 등의 지표는 더 이상 사용하지 않음.
        
        # 최신 값만 남기거나 전체 유지 (여기서는 전체 유지)
        return df

    def get_indicator_status(self, code, current_price):
        """
        V3: 더 이상 사용하지 않음 (Legacy)
        """
        return {}
