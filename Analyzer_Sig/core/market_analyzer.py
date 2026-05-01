from core.data_fetcher import DataFetcher
from core.pre_market_loader import PreMarketLoader

from config import (
    THEME_RANK_COUNT,
    MIN_TRADING_VALUE,
    MIN_PRICE_CHANGE,
    MAX_UPPER_WICK,
    MAX_GAP_START
)

# [CONSTANTS] Scoring Weights & Thresholds
# 1. Momentum (Scalping) Weights
WEIGHT_MOMENTUM_CHANGE = 0.7
WEIGHT_MOMENTUM_VOLUME = 0.3

# 2. Close Betting (Stability) Weights
WEIGHT_CLOSE_CHANGE = 0.3
WEIGHT_CLOSE_VOLUME = 0.2
WEIGHT_CLOSE_SAFETY = 0.5

# 3. Badge Threshold
BADGE_THRESHOLD_SCORE = 30

class MarketAnalyzer:
    def __init__(self, mode="PAPER"):
        self.fetcher = DataFetcher(mode=mode)
        self.loader = PreMarketLoader(self.fetcher) # [NEW] 장전 로더
        self._theme_cache = None
        self._theme_cache_time = 0
        
    def initialize_loader(self):
        """장전 데이터 로딩 시작 (외부 호출용)"""
        if not self.loader.is_initialized:
            self.loader.initialize_universe()
    
    def get_ranked_data(self, category="Sectors", limit=10):
        """
        'Market Attention Score'를 기준으로 섹터 또는 테마 순위를 반환합니다.
        Score = abs(change) * volume_weight
        
        테마의 경우: 상승률이 높은 순서로 정렬 (주도주)
        섹터의 경우: 관심도 점수 기준 정렬
        """
        data = self.fetcher.get_category_data(category)
        
        if category == "Themes":
            # [Refined Logic]
            # DataFetcher에서 이미 Smart Ranking(2-Stage Sorting)이 완료된 상태로 반환됨
            # 따라서 별도의 정렬 로직 없이 그대로 사용하거나, 필요한 경우 필터링만 수행
            # 단, 상위권과 하위권(하락)을 시각적으로 분리하기 위해 로직 유지하되 순서 보존
            
            # Smart Ranking 점수(score)가 있으면 그것을 신뢰
            if data and 'score' in data[0]:
                 ranked = data
            else:
                # Fallback: 기존 로직 (점수가 없는 Mock 모드 등)
                positive_data = [item for item in data if item['change'] > 0]
                negative_data = [item for item in data if item['change'] <= 0]
                
                for item in positive_data:
                    item['attention_score'] = item['change'] * item['volume']
                for item in negative_data:
                    item['attention_score'] = abs(item['change']) * item['volume']
                    
                pos_ranked = sorted(positive_data, key=lambda x: x['attention_score'], reverse=True)
                neg_ranked = sorted(negative_data, key=lambda x: x['attention_score'], reverse=True)
                ranked = pos_ranked + neg_ranked
        else:
            # 섹터는 관심도 점수 기준 (Sizing) + 등락률 기준 정렬 (Sorting)
            for item in data:
                # Sizing: 절대 변동폭 * 거래대금 (중요도)
                item['attention_score'] = abs(item['change']) * (item['volume'] / 100)
            
            # 정렬: 실제 등락률 내림차순 (상승 -> 하락)
            # 이렇게 하면 양수는 앞쪽(좌/상), 음수는 뒤쪽(우/하)에 배치됨
            ranked = sorted(data, key=lambda x: x['change'], reverse=True)
        
        return ranked[:limit] if limit else ranked


    def get_themes_cached(self):
        """
        테마 데이터를 캐싱하여 중복 조회 방지 (5초 캐시)
        attention_score 포함
        상위 10개 테마만 조회 (성능 최적화)
        """
        import time
        current_time = time.time()
        cache_duration = 5  # 5초 캐시
        
        if self._theme_cache is None or \
           current_time - self._theme_cache_time > cache_duration:
            # 상위 10개만 조회 (트리맵 8개 + Top 2개)
            self._theme_cache = self.get_ranked_data("Themes", limit=10)
            self._theme_cache_time = current_time
        
        return self._theme_cache
    
    def get_theme_stocks_direct(self, theme_name):
        """
        테마 종목을 직접 조회 (섹터 체크 제거)
        """
        return self.get_lead_signals_for_theme(theme_name)

    def get_lead_signals_for_theme(self, theme_name):
        """
        Returns all stocks in a specific theme, ranked, with logic for identifying Leaders vs Fakes.
        """
        stocks = self.fetcher.get_leading_stocks(theme_name)
        
        if not stocks:
            return []
        
        # [NEW] Calculate normalization factors
        max_change = max((abs(s.get('change', 0)) for s in stocks), default=1)
        max_volume = max((s.get('volume', 0) for s in stocks), default=1)
        
        # Calculate scores and flags
        for s in stocks:
            # Extract values first
            price = s.get('price', 0)
            open_p = s.get('open', 0)
            high_p = s.get('high', 0)
            change = s.get('change', 0)
            volume = s.get('volume', 0) # Trading Amount (Million KRW)
            
            # (1) Normalized Change Rate (0~100, weight 40%)
            norm_change = (abs(change) / max_change * 100) if max_change > 0 else 0
            
            # (2) Normalized Volume (0~100, weight 30%)
            norm_volume = (volume / max_volume * 100) if max_volume > 0 else 0
            
            # (3) Upper Wick Ratio: (High - Current) / Current * 100
            if price > 0:
                upper_wick = ((high_p - price) / price) * 100
            else:
                upper_wick = 0
                
            # (4) Gap Start Ratio: (Open - PrevClose) / PrevClose * 100
            # PrevClose can be derived: Current / (1 + change/100)
            if (1 + change/100) != 0:
                prev_close = price / (1 + change/100)
                gap_start = ((open_p - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            else:
                gap_start = 0

            # (5) Safety Score (0~100, weight 30%)
            safety_score = 100 - upper_wick - gap_start
            safety_score = max(0, min(100, safety_score))  # Clamp to 0~100

            # [NEW] Dual Scoring System
            # 1. Scalping/Breakout (Momentum): Focus on Power (Change + Volume)
            momentum_score = (norm_change * WEIGHT_MOMENTUM_CHANGE) + (norm_volume * WEIGHT_MOMENTUM_VOLUME)
            
            # 2. Close Betting (Stability): Focus on Finish (Safety + Change)
            # Safety includes Upper Wick penalty
            close_score = (norm_change * WEIGHT_CLOSE_CHANGE) + (norm_volume * WEIGHT_CLOSE_VOLUME) + (safety_score * WEIGHT_CLOSE_SAFETY)

            s['momentum_score'] = momentum_score
            s['close_score'] = close_score
            s['complex_score'] = (momentum_score + close_score) / 2 # Default sorting

            # [NEW] PreMarketLoader 지표 - V3에서는 빈 dict 반환 (Legacy)
            s['tech_signals'] = {}

            # 3. Determine Status (Leader/Caution)
            is_leader = False
            is_caution = False
            caution_reason = []

            # Check Leader Condition (Relaxed for badge logic)
            if (volume >= MIN_TRADING_VALUE and change >= MIN_PRICE_CHANGE):
                 is_leader = True
            
            # Check Caution Condition
            if upper_wick > MAX_UPPER_WICK:
                is_caution = True
                caution_reason.append(f"윗꼬리 -{upper_wick:.1f}%")
            
            if gap_start >= MAX_GAP_START:
                is_caution = True
                caution_reason.append(f"갭과열 +{gap_start:.1f}%")

            s['is_leader'] = is_leader
            s['is_caution'] = is_caution
            s['caution_reason'] = ", ".join(caution_reason)

        # [NEW] Assign Badges based on Rank within Theme
        # Find Top Score for each category
        if stocks:
            max_mom = max(stocks, key=lambda x: x['momentum_score'])
            max_cls = max(stocks, key=lambda x: x['close_score'])
            
            for s in stocks:
                badges = []
                # Threshold: Must be significant (> BADGE_THRESHOLD_SCORE)
                if s['momentum_score'] > BADGE_THRESHOLD_SCORE and s == max_mom:
                    badges.append("돌") # 돌파/단타
                
                if s['close_score'] > BADGE_THRESHOLD_SCORE and s == max_cls:
                    badges.append("종") # 종가베팅
                    
                # Assign Signal Type (Data) instead of modifying Name (View)
                if "돌" in badges and "종" in badges:
                    s['signal_type'] = "king"
                elif "돌" in badges:
                    s['signal_type'] = "breakout"
                elif "종" in badges:
                    s['signal_type'] = "close"
                else:
                    s['signal_type'] = None

        # Sort by complex_score (descending) for list display
        ranked_stocks = sorted(stocks, key=lambda x: x['complex_score'], reverse=True)
        
        # 유동적 필터링: 최소 3개 유지
        final_stocks = ranked_stocks[:3]
        if len(ranked_stocks) > 3:
            leader_score = ranked_stocks[0].get('complex_score', 0)
            for s in ranked_stocks[3:THEME_RANK_COUNT]:
                if leader_score > 0 and (s['complex_score'] / leader_score) > 0.15:
                    final_stocks.append(s)
                elif leader_score == 0: 
                    final_stocks.append(s)
        
        return final_stocks
