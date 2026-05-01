import time
from collections import deque

class StockRadar:
    """
    개별 종목의 실시간 체결 데이터를 분석하여
    상승 속도(Velocity)와 가속도(Acceleration)를 추적합니다.
    
    [핵심 기능]
    1. 실시간 가격/거래량 스냅샷 관리
    2. 속도/가속도 계산
    3. 급등 시그널(가속도 포착) 발생
    """
    def __init__(self):
        # {code: {'snapshots': deque, 'last_price': float, 'last_vol': int, 'last_time': float}}
        self.stocks = {}
        # {code: last_signal_timestamp} - 시그널 쿨다운 관리
        self.signal_cooldown = {}
        
        # 설정값
        self.snapshot_len = 10     # 스냅샷 유지 개수
        self.min_dt = 0.5          # 최소 업데이트 간격 (초) - 노이즈 방지
        self.cooldown_sec = 10.0   # 동일 종목 재진입 방지 쿨다운 (초)
        
        # 가속도 감지 임계값
        self.min_velocity = 0.1    # 초당 0.1% 상승 (10초면 1% 상승) -> 꽤 빠름
        self.min_accel = 0.03       # 가속도 양수 (속도가 빨라짐)

    def reset(self):
        """추적 중인 모든 데이터 초기화"""
        self.stocks.clear()
        self.signal_cooldown.clear()

    def update(self, code, current_price, current_vol=0, power=0):
        """
        실시간 체결 데이터 업데이트 및 분석
        
        Args:
            code (str): 종목코드
            current_price (int/float): 현재가
            current_vol (int): 누적거래량 (Optional)
            
        Returns:
            dict or None: 급등 신호 발생 시 데이터 반환, 아니면 None
        """
        now = time.time()
        
        if current_price <= 0:
            return None
            
        # 1. 초기 등록
        if code not in self.stocks:
            self.stocks[code] = {
                'snapshots': deque(maxlen=self.snapshot_len),
                'last_price': current_price,
                'last_vol': current_vol,
                'last_time': now
            }
            return None
            
        data = self.stocks[code]
        dt = now - data['last_time']
        
        # 2. 노이즈 필터 (너무 빈번한 업데이트는 무시)
        if dt < self.min_dt:
            return None
            
        prev_price = data['last_price']
        
        # 가격 변동 없으면 가속도 의미 없음 (거래량만 늘어난 횡보)
        # 단, 거래량 급증 포착을 원하면 로직 추가 가능하나 여기선 '가격 가속도'에 집중
        if current_price == prev_price:
             return None
             
        # 변동률 (%)
        price_diff = current_price - prev_price
        rate_change = (price_diff / prev_price) * 100
        
        # 거래량 변동 (주)
        vol_diff = current_vol - data['last_vol'] if current_vol > data['last_vol'] else 0
        
        # 속도(Velocity) 계산 (%/sec)
        velocity = rate_change / dt
        
        # 거래량 속도 (주/sec)
        vol_speed = vol_diff / dt
        
        # 스냅샷 저장
        snapshot = {
            'time': now,
            'price': current_price,
            'velocity': velocity,
            'vol_speed': vol_speed
        }
        data['snapshots'].append(snapshot)
        
        # 상태 업데이트
        data['last_price'] = current_price
        data['last_vol'] = current_vol
        data['last_time'] = now
        
        # 3. 가속도(Acceleration) 분석
        if len(data['snapshots']) < 3:
            return None
            
        # 최근 3개 데이터 활용
        shots = list(data['snapshots'])
        v_now = shots[-1]['velocity']
        v_prev = shots[-2]['velocity']
        
        vol_s_now = shots[-1]['vol_speed']
        vol_s_prev = shots[-2]['vol_speed']
        
        # 가속도 = 속도의 변화량
        acceleration = v_now - v_prev
        vol_accel = vol_s_now - vol_s_prev
        
        # 직전 찰나의 평균 거래 속도 (현재 틱 제외)
        past_vol_speeds = [s['vol_speed'] for s in shots[:-1]]
        avg_vol_speed = sum(past_vol_speeds) / len(past_vol_speeds) if past_vol_speeds else 0
        
        # 4. 시그널 판정
        signal_found = False
        
        # [조건 A] 고속 주행: 속도가 매우 빠름 (초당 0.15% 이상, 즉 10초에 1.5%)
        is_high_speed = (v_now >= 0.15)
        
        # [조건 B] 가속 주행: 속도가 양수이고 가속도가 붙음 (점점 빨라짐)
        is_accelerating = (v_now > 0.05 and acceleration > self.min_accel)
        
        if is_high_speed or is_accelerating:
            signal_found = True
            
        if signal_found:
            # [필살기 1] 체결강도 필터 (Momentum Power)
            # 체결강도가 제공되지 않거나(0 이하) 100 이상일 때만 통과 (매수세 우위 검증)
            if power > 0 and power < 100.0:
                return None # 매수세 약함, 진입 포기

            # [필살기 2] AI 거래대금 가속도(Value Spike Jerk) 필터 
            # 단순히 100주 이상 판별이 아닌 "상대적 거래 폭발" 및 "초당 거래대금" 측정
            is_volume_spiked = False
            
            # 초당 거래대금(Won/sec) 계산 (동전주 휩소(가짜 신호) 방어를 위한 안전장치)
            amount_speed = vol_s_now * current_price
            
            # 최소 초당 거래대금이 1,500만 원은 확보되어야 진짜 세력의 개입으로 인정
            if amount_speed >= 15000000:
                # (1) 거래 속도가 직전 평균 대비 폭발적으로 증가 (2배 이상)
                if avg_vol_speed > 0 and (vol_s_now / avg_vol_speed) >= 2.0:
                     is_volume_spiked = True
                # (2) 이전 틱 대비 거래 속도가 급격히 붙음
                elif vol_accel > 0: 
                     is_volume_spiked = True

            if not is_volume_spiked:
                return None # 의미있는 거래대금이 동반되지 않은 가짜(휩소) 상승

            # 쿨다운 체크
            last_sig = self.signal_cooldown.get(code, 0)
            if now - last_sig > self.cooldown_sec:
                self.signal_cooldown[code] = now
                
                # 시그널 메시지 생성 시 폭발 배수(Mult) 및 거래대금(백만 단위) 표시
                vol_mult = (vol_s_now / avg_vol_speed) if avg_vol_speed > 0 else 0
                amount_mega = amount_speed / 1000000
                msg_vol = f"{amount_mega:.0f}M/s({vol_mult:.1f}배 폭증)" if vol_mult >= 2.0 else f"{amount_mega:.0f}M/s(가속)"
                
                return {
                    'code': code,
                    'is_accelerating': True,
                    'velocity': v_now,
                    'acceleration': acceleration,
                    'price': current_price,
                    'vol_speed': vol_s_now,
                    'power': power,
                    'msg': f"🚀[가속] 속도:{v_now:.2f}%/s 파워:{power}% 거래:{msg_vol}"
                }
                
        return None

    def check_orderbook(self, total_ask, total_bid):
        """
        [필살기 3] 호가 잔량 분석 (Orderbook Analysis)
        
        진짜 상승(Real Rally) 조건:
        - 매도 총잔량이 매수 총잔량보다 많아야 함 (Total Ask > Total Bid)
        - 세력이 위에 쌓인 매도 물량을 잡아먹으며 올리는 구조
        
        Args:
            total_ask (int): 매도호가 총잔량
            total_bid (int): 매수호가 총잔량
            
        Returns:
            bool: 진입 적합 여부 (True=진입, False=회피)
        """
        if total_ask <= 0 or total_bid <= 0:
            return False
            
        # 매도 잔량이 매수 잔량보다 커야 함 (비율 1.1배 이상 권장)
        ratio = total_ask / total_bid
        
        # 1.1배 이상 매도 물량이 많을 때 (허매수 방지)
        if ratio >= 1.1:
            return True
            
        return False

