import logging
import numpy as np
import pandas as pd
import traceback
import math
from datetime import datetime
from data_manager import DataManager
from shared.indicators import TechnicalIndicators as TI
from shared.execution_context import get_execution_context

class StrategyRunner:
    """
    Class responsible for strategy execution and signal checking.
    Supports dynamic strategy execution via Python code injection.
    """
    def __init__(self):
        self.logger = logging.getLogger("AT_Sig.StrategyRunner")
        self.data_manager = DataManager() # Singleton

    @staticmethod
    def analyze_data(chart_data, stk_cd, strategy_code=None, current_price=None, min_df=None, day_open=None, prev_close=None):
        """
        Analyze data and check for signals.
        Supports both legacy hardcoded logic and dynamic strategy code.
        """
        try:
            # 1. Preprocess Data
            if min_df is not None and not min_df.empty:
                df = min_df.copy()
                df.reset_index(drop=True, inplace=True)
            else:
                df = TI.preprocess_data(chart_data)
                
            if df is None or len(df) == 0:
                return {'result': False, 'msg': 'Data Preprocess Failed'}
            
            # [Fix for Stale Cache] Update latest tick price
            if current_price is not None and current_price > 0:
                df.iloc[-1, df.columns.get_loc('close')] = float(current_price)
                if current_price > df.iloc[-1]['high']:
                    df.iloc[-1, df.columns.get_loc('high')] = float(current_price)
                if current_price < df.iloc[-1]['low']:
                    df.iloc[-1, df.columns.get_loc('low')] = float(current_price)
            
            C, O, H, L, V = df['close'], df['open'], df['high'], df['low'], df['volume']

            # === Dynamic Strategy Execution (Strict Daily Anchor) ===
            if strategy_code and strategy_code.strip():
                try:
                    # 1. Prepare Strategy Execution Data Context
                    if min_df is not None and not min_df.empty:
                        target_df = min_df.copy()
                    else:
                        target_df = TI.preprocess_data(chart_data) if isinstance(chart_data, list) else None
                        
                    if target_df is None or target_df.empty:
                        return {'result': False, 'msg': 'Target Data missing for Strategy'}

                    # [시스템 픽스] 장중 유동성을 반영하기 위해 새로운 봉 생성 또는 최신 봉 주입
                    if current_price is not None and current_price > 0:
                        last_dt = str(target_df.iloc[-1].get('dt', target_df.index[-1]))
                        today_dt = datetime.now().strftime('%Y%m%d')
                        
                        # 마지막 데이터가 오늘 이전 날짜라면, 오늘 분량을 새로 추가 (Append)
                        if last_dt != today_dt:
                            new_row = target_df.iloc[-1].copy()
                            new_row['dt'] = today_dt
                            new_row['open'] = float(current_price) # 장중이므로 현재가를 시가/고가/저가/종가로 초기화하여 시작
                            new_row['high'] = float(current_price)
                            new_row['low'] = float(current_price)
                            new_row['close'] = float(current_price)
                            new_row['volume'] = 0
                            target_df = pd.concat([target_df, pd.DataFrame([new_row])], ignore_index=True)
                            last_idx = target_df.index[-1]
                        else:
                            # 이미 오늘 봉이 있다면 (Daily Chart API가 오늘치를 포함했다면) 업데이트만 수행
                            last_idx = target_df.index[-1]
                            target_df.loc[last_idx, 'close'] = float(current_price)
                            if current_price > target_df.loc[last_idx, 'high']:
                                target_df.loc[last_idx, 'high'] = float(current_price)
                            if current_price < target_df.loc[last_idx, 'low']:
                                target_df.loc[last_idx, 'low'] = float(current_price)

                    # 2. Run Strategy on Target Context (Price + Price Base Overrides Injected)
                    exec_globals = get_execution_context(target_df, day_open_override=day_open, preday_close_override=prev_close)
                    local_vars = {}
                    # [Fix] 전략 코드 내에서 local_vars를 직접 참조하는 경우를 위한 주입
                    exec_globals['local_vars'] = local_vars
                    exec(strategy_code, exec_globals, local_vars)
                    
                    if 'cond' in local_vars:
                        cond = local_vars['cond']
                        is_signal = bool(cond.iloc[-1]) if hasattr(cond, 'iloc') else bool(cond)
                        score = local_vars.get('score', 0)
                        msg = local_vars.get('msg', f"Strict Daily Signal: {stk_cd}")
                        
                        # [픽스] TargetLine 추출: NaN 방어 + 마지막 유효값(ffill 이후에도 NaN이면 dropna로 최근값 탐색)
                        import math
                        has_target_line = 'TargetLine' in local_vars
                        target = 0.0
                        if has_target_line:
                            tl = local_vars['TargetLine']
                            if hasattr(tl, 'iloc'):
                                # Series: iloc[-1]이 NaN이면 dropna()로 마지막 유효값 사용
                                tl_last = tl.iloc[-1]
                                try:
                                    tl_last_f = float(tl_last)
                                    if not math.isnan(tl_last_f) and tl_last_f > 0:
                                        target = tl_last_f
                                    else:
                                        # NaN 또는 0 → 전체 Series에서 마지막 유효값 탐색
                                        tl_valid = tl.dropna()
                                        if len(tl_valid) > 0:
                                            target = float(tl_valid.iloc[-1])
                                except (TypeError, ValueError):
                                    pass
                            else:
                                try:
                                    v = float(tl) if tl is not None else 0.0
                                    target = v if not math.isnan(v) else 0.0
                                except (TypeError, ValueError):
                                    pass
                        
                        return {'result': is_signal, 'score': score, 'target': target,
                                'has_target_line': has_target_line,
                                'msg': msg if is_signal else 'No Signal'}
                    else:
                        return {'result': False, 'msg': "'cond' variable not found in strategy"}
                        
                except Exception as e:
                    import logging
                    st_logger = logging.getLogger("AT_Sig.StrategyRunner")
                    st_logger.error(f"Strategy Execution Error (Daily Mode) [{stk_cd}]:\n{traceback.format_exc()}")
                    return {'result': False, 'msg': f"Strategy Exec Error: {e}"}

            # === Legacy Hardcoded Logic (Fallback) ===
            # Used if no strategy code provided (Breakout of TargetLine + 10 indicators)
            bbu, _, _ = TI.bbands(C, 20, 2)
            ccu = TI.ema(C, 20) + (TI.atr(H, L, C, 20) * 2)
            
            cond_a3 = (O.shift(2) < C.shift(2)) & (O.shift(1) <= C.shift(1)) & (O > C)
            cond_b = ((C.shift(1) > bbu.shift(1)) | (C.shift(1) > ccu.shift(1))) & cond_a3
            
            target_line_val = 0
            valid_indices = np.where(cond_b[:-1])[0]
            if len(valid_indices) > 0:
                target_line_val = O.iloc[valid_indices[-1]]
            else:
                return {'result': False, 'msg': 'No TargetLine (Legacy)'}

            cond_cross_up = (C.iloc[-2] <= target_line_val) and (C.iloc[-1] > target_line_val)
            if not cond_cross_up:
                return {'result': False, 'score': 0, 'msg': 'No Breakout (Legacy)'}

            # 10 Indicators Scoring...
            score = 0
            macd, ms = TI.macd(C)
            s_macd = TI.ema(macd, 9)
            if macd.iloc[-1] > s_macd.iloc[-1]: score += 1
            
            fk, sk = TI.stochastics_slow(H, L, C, 12, 5, 5)
            sd = TI.ema(sk, 5)
            if sk.iloc[-1] > sd.iloc[-1]: score += 1
            
            if TI.cci(H, L, C, 14).iloc[-1] > 0: score += 1
            if TI.rsi(C, 14).iloc[-1] > 50: score += 1
            
            dip, dim = TI.dmi(H, L, C, 14)
            if dip.iloc[-1] > dim.iloc[-1]: score += 1
            
            if C.iloc[-1] > TI.sma(C, 10).iloc[-1]: score += 1
            if TI.obv(C, V).iloc[-1] > TI.ema(TI.obv(C, V), 9).iloc[-1]: score += 1
            if TI.mfi(H, L, C, V, 14).iloc[-1] > 50: score += 1
            if C.iloc[-1] > TI.sar(H, L, 0.02, 0.2).iloc[-1]: score += 1
            if C.iloc[-1] > TI.sma(C, 60).iloc[-1]: score += 1

            if score >= 7:
                return {'result': True, 'score': score, 'target': target_line_val, 'msg': f"Legacy Signal: {score}"}
            else:
                return {'result': False, 'score': score, 'msg': 'Legacy Low Score'}

        except Exception as e:
            import logging
            logging.getLogger("AT_Sig.StrategyRunner").error(f"Analyze Global Error: {e}")
            return {'result': False, 'msg': f"Analyze Error: {e}"}

    def check_signal(self, stk_cd, token, strategy_code=None, current_price=0, min_bars=70):
        """
        Check signal for a stock.
        """
        try:
            # 1. Get Chart Data (안실장 픽스: 500일치 충분히 조회)
            chart_data = self.data_manager.get_daily_chart(stk_cd, token=token, use_cache=True, days=500)
            
            # [안실장 픽스] 전략별 최소 요구 데이터 개수 적용
            needed = int(min_bars) if min_bars else 70
            if not chart_data or len(chart_data) < needed:
                self.logger.debug(f"Data Insufficient: {stk_cd} (Has: {len(chart_data) if chart_data else 0}, Need: {needed})")
                return {'result': False, 'target': 0, 'msg': f'데이터 부족({len(chart_data) if chart_data else 0}/{needed}봉)'}

            # 2. Analyze
            res = self.analyze_data(chart_data, stk_cd, strategy_code, current_price)
            
            # [안실장 픽스] 결과 객체 반환 (상태, 점수, 목표가 등 포함)
            return res

        except Exception as e:
            self.logger.error(f"Error in check_signal for {stk_cd}: {e}")
            return {'result': False, 'msg': f"CheckSignal Error: {e}"}
