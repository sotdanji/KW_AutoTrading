import logging
import pandas as pd
import aiohttp
import asyncio
from shared.config import REAL_HOST_URL

class StockRadar:
    """
    [안실장 고도화] 실시간 모멘텀 및 수급 밀도 분석 엔진
    포착된 종목 중 '지금 당장 에너지가 폭발하는 놈'을 골라내는 레이더
    """
    def __init__(self, token=None):
        self.token = token
        self.logger = logging.getLogger(__name__)
        self.history = {} # 종목별 히스토리 저장용
        self.session = None # 외부에서 주입하거나 내부에서 생성
        self.last_429_time = 0 # [NEW] 전역 속도제한 추적
        self.mchart_cache = {} # [NEW] 최근 분봉 분석 데이터 캐시 (60초 유효)

    def reset(self):
        """레이더 상태 초기화"""
        self.history.clear()
        self.logger.info("📡 StockRadar 리셋 완료")

    def update(self, code, price, volume, dummy=0):
        """실시간 데이터 또는 초기 스냅샷 업데이트 (인터페이스 유지)"""
        if code not in self.history:
            self.history[code] = []
        
        self.history[code].append({
            'time': pd.Timestamp.now(),
            'price': price,
            'volume': volume
        })
        # 최근 100개 데이터만 유지
        if len(self.history[code]) > 100:
            self.history[code].pop(0)

    async def analyze_momentum(self, code: str, cached_rt: dict = None, session=None) -> dict:
        """
        (비동기) 특정 종목의 찰나의 에너지 분석 - API 호출 최소화 버전
        :param cached_rt: RealTimeSearch에서 관리하는 실시간 시세 캐시
        """
        if not self.token:
            return {'score': 0, 'is_exploding': False, 'msg': "Token missing"}

        import time
        now_ts = time.time()
        
        # 429 에러 발생 시 30초간 모든 호출 원천 차단
        if now_ts - self.last_429_time < 30:
            return {'score': 0, 'is_exploding': False, 'msg': "Back-off(429)", 'limit': True}

        use_session = session or self.session
        close_session = False
        if not use_session:
            use_session = aiohttp.ClientSession()
            close_session = True

        try:
            headers = {
                'Content-Type': 'application/json;charset=UTF-8',
                'authorization': f'Bearer {self.token}',
            }

            # --- [Part 1] 분봉 밀도 분석 (Cache-First) ---
            avg_vol = 0
            cached_m = self.mchart_cache.get(code)
            # 60초 이내에 분석한 적이 있다면 API 호출 없이 캐시 사용
            if cached_m and (now_ts - cached_m['time'] < 60):
                avg_vol = cached_m['avg_vol']
            else:
                # ka10080 호출 (분봉 차트)
                mchart_url = f"{REAL_HOST_URL}/api/dostk/mchart"
                mchart_params = {'stk_cd': code, 'min_tp': '1', 'upd_stkpc_tp': '1'}
                
                async with use_session.post(mchart_url, headers={**headers, 'api-id': 'ka10080'}, json=mchart_params) as resp:
                    if resp.status == 429: 
                        self.last_429_time = now_ts
                        return {'score': 0, 'is_exploding': False, 'msg': "RateLimit(429)", 'limit': True}
                    if resp.status == 200:
                        m_res = await resp.json()
                        min_data = m_res.get('stk_min_pole_chart_qry') or m_res.get('output', [])
                        if min_data and len(min_data) >= 10:
                            df = pd.DataFrame(min_data)
                            col = 'vol' if 'vol' in df.columns else 'stk_min_pole_vol'
                            df['vol_num'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                            avg_vol = float(df.iloc[1:11]['vol_num'].mean())
                            # 캐시 저장
                            self.mchart_cache[code] = {'avg_vol': avg_vol, 'time': now_ts}

            # --- [Part 2] 실시간 에너지 분석 (API 호출 제거) ---
            # REST API(ka10001) 대신 전달받은 웹소켓 캐시(cached_rt)를 사용
            if not cached_rt:
                return {'score': 0, 'is_exploding': False, 'msg': "RT Cache Missing"}

            current_vol = float(cached_rt.get('volume', 0))
            strength = float(cached_rt.get('strength', 100.0))
            total_ask = int(cached_rt.get('total_ask', 0))
            total_bid = int(cached_rt.get('total_bid', 0))
            
            # 거래밀도 계산
            density_ratio = (current_vol / avg_vol * 100) if avg_vol > 0 else 100
            # 호가잔량비 계산
            order_book_ratio = (total_ask / total_bid) if total_bid > 0 else 1.0
            
            # --- [Part 3] 점수 산출 ---
            density_score = min(density_ratio / 20, 40) # 최대 40점
            strength_score = min((strength - 100) / 1, 30) if strength > 100 else 0 # 최대 30점
            
            order_score = 0
            if 1.1 <= order_book_ratio <= 10.0:
                order_score = 30
                
            total_score = density_score + strength_score + order_score
            is_exploding = density_ratio >= 120 and total_score >= 30 # [공격 테스트] 200->120, 50->30 하향
            
            msg = f"⚡ 밀도:{density_ratio:.0f}% | 강도:{strength:.1f}% | 호가비:{order_book_ratio:.1f}"
            
            return {
                'score': int(total_score),
                'is_exploding': is_exploding,
                'msg': msg,
                'density': density_ratio
            }

        except Exception as e:
            self.logger.error(f"Radar analysis error for {code}: {e}")
            return {'score': 0, 'is_exploding': False, 'msg': f"Error: {e}"}
        finally:
            if close_session:
                await use_session.close()

    def check_orderbook(self, total_ask, total_bid):
        """호가 잔량 상태가 매수에 적합한지 확인 (매도잔량이 더 많아야 함)"""
        if total_bid == 0: return total_ask > 0
        ratio = total_ask / total_bid
        # [공격 테스트] 유연하게 0.8배 이상이면 통과 (기존 1.1배보다 대폭 완화)
        return ratio >= 0.8
