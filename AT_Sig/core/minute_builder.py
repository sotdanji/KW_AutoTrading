import pandas as pd
import threading
from datetime import datetime

class MinuteBuilder:
    """
    실시간 체결(틱) 데이터를 받아 1분봉으로 자체 조립(Resampling)하는 상업용 메모리 빌더.
    키움 API의 429 에러(조회 제한)를 우회하여 무제한 종목의 분봉을 생성할 수 있습니다.
    """
    def __init__(self):
        # 완료된 분봉 리스트 저장소: { stk_cd: [{'time': '090000', 'open': 1000, ...}, ...] }
        self.bars = {}
        # 현재 완성 중인 (진행 중인) 분봉: { stk_cd: {'min_str': '0900', 'open': 1000, ...} }
        self.current_bar = {}
        self.lock = threading.Lock()

    def init_from_history(self, stk_cd, history_data_list):
        """
        초기 웜업: API로 받아온 과거 분봉 스냅샷을 베이스로 깔아줍니다.
        history_data_list: 키움 opt10080 응답 리스트 반환값
        """
        with self.lock:
            self.bars[stk_cd] = []
            
            # 과거 데이터는 보통 최신순으로 오므로 역순으로 넣어 정방향을 만듭니다.
            for row in reversed(history_data_list):
                try:
                    # 응답 키 확인 (stck_bsop_date, stck_cntg_hour 등)
                    # 키움 opt10080 응답 구조: stck_cntg_hour, stck_prpr, stck_oprc...
                    dt_str = str(row.get('stck_bsop_date', '')) + str(row.get('stck_cntg_hour', ''))
                    # 데이터 정제
                    close_p = abs(int(row.get('stck_prpr', 0)))
                    open_p = abs(int(row.get('stck_oprc', 0)))
                    high_p = abs(int(row.get('stck_hgpr', 0)))
                    low_p = abs(int(row.get('stck_lwpr', 0)))
                    vol = int(row.get('acml_tr_pbmn', row.get('cntg_vol', 0))) # 거래량
                    
                    if close_p > 0:
                        self.bars[stk_cd].append({
                            'date': str(row.get('stck_bsop_date', datetime.now().strftime('%Y%m%d'))),
                            'time': str(row.get('stck_cntg_hour', '000000')).zfill(6),
                            'open': open_p,
                            'high': high_p,
                            'low': low_p,
                            'close': close_p,
                            'volume': vol
                        })
                except Exception:
                    continue
                    
            self.current_bar[stk_cd] = None

    def on_tick(self, stk_cd, price, volume, time_str):
        """
        실시간 틱 수신 시 호출. (handle_rt_data 내부에 삽입)
        time_str: '090115' 형식 (HHMMSS)
        반환값: True (1분이 바뀌어 새로운 봉이 닫혔을 때), False (아직 동일 분봉 진행 중)
        """
        if not time_str or len(time_str) < 4:
            return False
            
        min_str = time_str[:4] # HHMM 추출 (예: '0901')
        
        with self.lock:
            if stk_cd not in self.current_bar or self.current_bar[stk_cd] is None:
                # 완전 초기 틱
                self.current_bar[stk_cd] = {
                    'date': datetime.now().strftime('%Y%m%d'),
                    'min_str': min_str,
                    'time': min_str + "00", # 저장 시간 기준
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': volume
                }
                if stk_cd not in self.bars:
                    self.bars[stk_cd] = []
                return False

            curr = self.current_bar[stk_cd]
            
            # 같은 분(minute)에 거래된 틱
            if curr['min_str'] == min_str:
                curr['high'] = max(curr['high'], price)
                curr['low'] = min(curr['low'], price)
                curr['close'] = price
                curr['volume'] += volume
                return False
            else:
                # 시간이 바뀌었다! (이전 1분봉 사이클 완성) => 아카이빙
                finished_bar = {
                    'date': curr.get('date', datetime.now().strftime('%Y%m%d')),
                    'time': curr['time'],
                    'open': curr['open'],
                    'high': curr['high'],
                    'low': curr['low'],
                    'close': curr['close'],
                    'volume': curr['volume']
                }
                self.bars[stk_cd].append(finished_bar)
                
                # 새로운 1분봉 캡슐 열기
                self.current_bar[stk_cd] = {
                    'date': datetime.now().strftime('%Y%m%d'),
                    'min_str': min_str,
                    'time': min_str + "00",
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': volume
                }
                return True # 새로운 1분봉 생성 됨을 알림

    def get_dataframe(self, stk_cd):
        """
        수식 검증기(execution_context)에 던져넣을 pandas DataFrame 추출
        """
        with self.lock:
            # 1. 완료된 과거 분봉들
            all_bars = list(self.bars.get(stk_cd, []))
            
            # 2. 현재 실시간으로 움찔거리는 진행 중인 마지막 분봉 추가
            curr = self.current_bar.get(stk_cd)
            if curr:
                # Dict 형태로 맞춤
                active_bar = {
                    'date': curr.get('date', datetime.now().strftime('%Y%m%d')),
                    'time': curr['time'],
                    'open': curr['open'],
                    'high': curr['high'],
                    'low': curr['low'],
                    'close': curr['close'],
                    'volume': curr['volume']
                }
                all_bars.append(active_bar)
            
            if not all_bars:
                return pd.DataFrame()
                
            df = pd.DataFrame(all_bars)
            return df
