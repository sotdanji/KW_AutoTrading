import pandas as pd
import numpy as np

class TechnicalIndicators:
    """
    영웅문4 HTS 키움 수식에서 사용되는 모든 기술지표 구현체.
    AI 의존성 제로(Zero-AI-Dependency) 목표로 완전 구현.
    
    ── 이평선 ────────────────────────────────────────────
    sma, ema, wma, dema, tema
    ── 볼린저 밴드 ──────────────────────────────────────
    bbands, disparity, pctb, band_width, envelope_up, envelope_down
    ── 모멘텀/오실레이터 ─────────────────────────────────
    rsi, macd, stochastics_slow, cci, adx, dmi,
    momentum, roc, trix, williams_r, force_index
    ── 거래량 ───────────────────────────────────────────
    obv, mfi, vr, vwap
    ── 변동성/추세 ───────────────────────────────────────
    atr, sar, ichimoku
    ── 가격 구조 ─────────────────────────────────────────
    true_high, true_low, true_range, pivot
    ── 유틸 ─────────────────────────────────────────────
    bars_since, highest, lowest
    """
    @staticmethod
    def preprocess_data(chart_data):
        """
        Converts API chart data to Pandas DataFrame and sorts by date (Past -> Future).
        """
        if not chart_data:
            return None
            
        df = pd.DataFrame(chart_data)
        
        # Column mapping - Handle both Stock and Index API responses
        # Stock (ka10081): dt, open_pric, high_pric, low_pric, cur_prc, trde_qty
        # Index (ka20006): base_dt, open_prc, high_prc, low_prc, close_prc/clpr, trd_qty
        rename_map = {
            'dt': 'date',
            'base_dt': 'date',
            'trd_dt': 'date',
            'bas_dt': 'date',
            'dt_n': 'date',
            'stck_bsop_date': 'date',     # ka10080 분봉 일자
            'inds_trd_dt': 'date',
            'open_pric': 'open',
            'open_prc': 'open',
            'stck_oprc': 'open',          # ka10080 분봉 시가
            'high_pric': 'high',
            'high_prc': 'high',
            'stck_hgpr': 'high',          # ka10080 분봉 고가
            'low_pric': 'low', 
            'low_prc': 'low',
            'stck_lwpr': 'low',           # ka10080 분봉 저가
            'cur_prc': 'close',
            'close_prc': 'close',
            'clpr': 'close',
            'stck_prpr': 'close',         # ka10080 분봉 종가(현재가)
            'stck_prpr_n': 'close',
            'cur_prc_n': 'close',
            'trde_qty': 'volume',
            'trd_qty': 'volume',
            'trd_vol': 'volume',
            'cntg_vol': 'volume',         # ka10080 분봉 거래량
            'acc_trde_qty_n': 'volume',
            'stck_cntg_hour': 'time',     # ka10080 분봉 시간 (HHMMSS)
            'trde_prica': 'amount',      # ka10081 거래대금 (단위: 백만원)
            'trd_amt': 'amount',
            'acml_tr_pbmn': 'amount',
            'acml_tr_amt': 'amount',
            'total_value': 'amount',
            '거래대금': 'amount'
        }
        
        available_cols = {}
        for api_key, std_key in rename_map.items():
            if api_key in df.columns:
                available_cols[api_key] = std_key
        
        df = df.rename(columns=available_cols)
        
        # [안실장 긴급 조치] 중복된 칼럼 이름 처리 (예: close가 2개인 경우 첫 번째만 유지)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        
        # Fill missing OHLC columns with 'close' if they are missing (common for some index TRs)
        for col in ['open', 'high', 'low']:
            if col not in df.columns and 'close' in df.columns:
                df[col] = df['close']
        
        # Final check for required columns
        required_cols = ['open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                print(f"[WARN] Missing required column: {col}")
                return None
        
        # Numeric conversion
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if col in df.columns:
                # Remove any non-numeric characters except decimals
                df[col] = df[col].astype(str).str.replace(r'[^0-9.]', '', regex=True)
                # Convert to numeric and take absolute value
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).abs()
        
        # [거래대금 자동 계산]
        # trde_prica(ka10081): 백만원 단위 → amount에 그대로 저장
        # acml_tr_pbmn 등 원 단위 API → 백만원으로 변환
        # API 거래대금이 없을 때 → close × volume / 1,000,000 (백만원 추정)
        # 수식 기준: AMT >= 3000 = 3,000백만원 = 30억원 이상
        if 'amount' not in df.columns or (df['amount'] == 0).all():
            if 'close' in df.columns and 'volume' in df.columns:
                df['amount'] = (df['close'] * df['volume']) / 1_000_000  # 원 → 백만원
        elif 'amount' in df.columns:
            # 원 단위로 받은 경우(평균 > 10억원) 백만원으로 변환
            if df['amount'].mean() > 1_000_000_000:
                df['amount'] = df['amount'] / 1_000_000
        
        # If 'date' not found, skip
        if 'date' not in df.columns:
            return None
            
        # Ensure 'date' is string and clean
        df['date'] = df['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        if 'time' in df.columns:
            df['time'] = df['time'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        
        # Sort: Past -> Future (Strict Date/Time alignment)
        sort_cols = ['date']
        if 'time' in df.columns:
            sort_cols.append('time')
            
        df = df.sort_values(by=sort_cols, ascending=True).reset_index(drop=True)
        
        return df

    @staticmethod
    def _safe_period(p, default=20):
        try:
            res = default
            if isinstance(p, (int, float)): res = int(p)
            else: res = int(float(str(p).strip()))
            return max(1, res)
        except:
            return default

    @staticmethod
    def sma(series, period):
        return series.rolling(window=TechnicalIndicators._safe_period(period)).mean()

    @staticmethod
    def ema(series, period):
        return series.ewm(span=TechnicalIndicators._safe_period(period), adjust=False).mean()

    @staticmethod
    def bbands(series, period=20, std_dev=2):
        p = TechnicalIndicators._safe_period(period)
        mid = series.rolling(window=p).mean()
        # [안실장 픽스] 키움 HTS 표준인 ddof=0 적용
        std = series.rolling(window=p).std(ddof=0)
        upper = mid + (std * std_dev)
        lower = mid - (std * std_dev)
        return upper, mid, lower

    @staticmethod
    def atr(high, low, close, period=14):
        high_low = high - low
        high_close = np.abs(high - close.shift(1))
        low_close = np.abs(low - close.shift(1))
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        
        # Using Wilder's Smoothing (alpha=1/period) effectively
        p = TechnicalIndicators._safe_period(period)
        return true_range.ewm(alpha=1/p, adjust=False).mean()

    @staticmethod
    def macd(close, short=12, long=26, signal=9):
        s = TechnicalIndicators._safe_period(short)
        l = TechnicalIndicators._safe_period(long)
        sig = TechnicalIndicators._safe_period(signal)
        short_ema = close.ewm(span=s, adjust=False).mean()
        long_ema = close.ewm(span=l, adjust=False).mean()
        macd_line = short_ema - long_ema
        signal_line = macd_line.ewm(span=sig, adjust=False).mean()
        return macd_line, signal_line

    @staticmethod
    def stochastics_slow(high, low, close, n=12, m=5, t=5):
        pn = TechnicalIndicators._safe_period(n)
        pm = TechnicalIndicators._safe_period(m)
        pt = TechnicalIndicators._safe_period(t)
        lowest_low = low.rolling(window=pn).min()
        highest_high = high.rolling(window=pn).max()
        fast_k = ((close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)) * 100
        
        slow_k = fast_k.rolling(window=pm).mean()
        slow_d = slow_k.rolling(window=pt).mean()
        
        return slow_k, slow_d

    @staticmethod
    def cci(high, low, close, period=14):
        p = TechnicalIndicators._safe_period(period)
        tp = (high + low + close) / 3
        sma = tp.rolling(window=p).mean()
        mad = (tp - sma).abs().rolling(window=p).mean()
        # Avoid division by zero
        mad = mad.replace(0, 0.0001)
        cci = (tp - sma) / (0.015 * mad)
        return cci

    @staticmethod
    def rsi(close, period=14):
        p = TechnicalIndicators._safe_period(period)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        
        avg_gain = gain.ewm(alpha=1/p, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/p, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def dmi(high, low, close, period=14):
        p = TechnicalIndicators._safe_period(period)
        up = high - high.shift(1)
        down = low.shift(1) - low
        
        pdm = np.where((up > down) & (up > 0), up, 0)
        mdm = np.where((down > up) & (down > 0), down, 0)
        
        pdm_s = pd.Series(pdm, index=high.index).ewm(alpha=1/p, adjust=False).mean()
        mdm_s = pd.Series(mdm, index=high.index).ewm(alpha=1/p, adjust=False).mean()
        atr_s = TechnicalIndicators.atr(high, low, close, p)
        
        di_plus = (pdm_s / atr_s) * 100
        di_minus = (mdm_s / atr_s) * 100
        
        return di_plus, di_minus

    @staticmethod
    def obv(close, volume):
        obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        return obv

    @staticmethod
    def mfi(high, low, close, volume, period=14):
        p = TechnicalIndicators._safe_period(period)
        tp = (high + low + close) / 3
        rmf = tp * volume
        
        diff = tp.diff()
        
        # FIX: explicitly using tp.index
        pos_flow = pd.Series(np.where(diff > 0, rmf, 0), index=tp.index)
        neg_flow = pd.Series(np.where(diff < 0, rmf, 0), index=tp.index)
        
        pos_mf = pos_flow.rolling(window=p).sum()
        neg_mf = neg_flow.rolling(window=p).sum()
        
        mfi = 100 - (100 / (1 + (pos_mf / neg_mf)))
        return mfi

    @staticmethod
    def sar(high, low, af=0.02, max_af=0.2):
        length = len(high)
        psar = np.zeros(length)
        
        psar[0] = low[0]
        bull = True
        ep = high[0]
        acc = af
        
        for i in range(1, length):
            prev_psar = psar[i-1]
            if bull:
                psar[i] = prev_psar + acc * (ep - prev_psar)
                
                if low[i] < psar[i]: # Reversal
                    bull = False
                    psar[i] = ep
                    ep = low[i]
                    acc = af
                else:
                    if high[i] > ep:
                        ep = high[i]
                        acc = min(acc + af, max_af)
            else:
                psar[i] = prev_psar + acc * (ep - prev_psar)
                
                if high[i] > psar[i]: # Reversal
                    bull = True
                    psar[i] = ep
                    ep = high[i]
                    acc = af
                else:
                    if low[i] < ep:
                        ep = low[i]
                        acc = min(acc + af, max_af)
                        
        return pd.Series(psar, index=high.index)

    @staticmethod
    def vr(close, open_price, volume, period=20):
        p = TechnicalIndicators._safe_period(period)
        # Kiwoom / Standard VR Logic:
        # UpVol = V if C > O else 0
        # DownVol = V if C < O else 0
        # FlatVol = V if C == O else 0
        # VR = (Sum(Up) + Sum(Flat)/2) / (Sum(Down) + Sum(Flat)/2) * 100
        
        up_vol = np.where(close > open_price, volume, 0)
        down_vol = np.where(close < open_price, volume, 0)
        flat_vol = np.where(close == open_price, volume, 0)
        
        # Ensure Series for rolling
        up_s = pd.Series(up_vol, index=close.index).rolling(window=p).sum()
        down_s = pd.Series(down_vol, index=close.index).rolling(window=p).sum()
        flat_s = pd.Series(flat_vol, index=close.index).rolling(window=p).sum()
        
        # Avoid division by zero
        denom = down_s + flat_s / 2
        denom = denom.replace(0, 0.0001)
        
        vr = (up_s + flat_s / 2) / denom * 100
        return vr

    @staticmethod
    def adx(high, low, close, period=14):
        p = TechnicalIndicators._safe_period(period)
        di_plus, di_minus = TechnicalIndicators.dmi(high, low, close, p)
        dx = (np.abs(di_plus - di_minus) / (di_plus + di_minus)) * 100
        dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0)
        adx = dx.ewm(alpha=1/p, adjust=False).mean()
        return adx

    @staticmethod
    def momentum(close, period=10):
        p = TechnicalIndicators._safe_period(period)
        return (close / close.shift(p)) * 100

    @staticmethod
    def roc(close, period=12):
        p = TechnicalIndicators._safe_period(period)
        return ((close - close.shift(p)) / close.shift(p)) * 100

    @staticmethod
    def trix(close, period=12):
        p = TechnicalIndicators._safe_period(period)
        ema1 = close.ewm(span=p, adjust=False).mean()
        ema2 = ema1.ewm(span=p, adjust=False).mean()
        ema3 = ema2.ewm(span=p, adjust=False).mean()
        return ((ema3 - ema3.shift(1)) / ema3.shift(1).replace(0, np.nan)) * 100

    @staticmethod
    def williams_r(high, low, close, period=14):
        p = TechnicalIndicators._safe_period(period)
        highest_high = high.rolling(window=p).max()
        lowest_low = low.rolling(window=p).min()
        denom = (highest_high - lowest_low).replace(0, np.nan)
        return ((highest_high - close) / denom) * -100

    @staticmethod
    def ichimoku(high, low, short_period=9, mid_period=26, long_period=52):
        sp = TechnicalIndicators._safe_period(short_period)
        mp = TechnicalIndicators._safe_period(mid_period)
        lp = TechnicalIndicators._safe_period(long_period)
        
        tenkan_sen = (high.rolling(window=sp).max() + low.rolling(window=sp).min()) / 2
        kijun_sen = (high.rolling(window=mp).max() + low.rolling(window=mp).min()) / 2
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(mp - 1)
        senkou_span_b = ((high.rolling(window=lp).max() + low.rolling(window=lp).min()) / 2).shift(mp - 1)
        return tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b

    # ================================================================
    # [신규] 이평선
    # ================================================================

    @staticmethod
    def wma(series, period):
        """가중이동평균 (Weighted Moving Average) - 최근 봉에 높은 가중치"""
        p = TechnicalIndicators._safe_period(period)
        weights = np.arange(1, p + 1, dtype=float)
        return series.rolling(window=p).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True
        )

    @staticmethod
    def dema(series, period):
        """이중지수이동평균 (Double EMA) = 2*EMA - EMA(EMA)"""
        p = TechnicalIndicators._safe_period(period)
        ema1 = series.ewm(span=p, adjust=False).mean()
        ema2 = ema1.ewm(span=p, adjust=False).mean()
        return 2 * ema1 - ema2

    @staticmethod
    def tema(series, period):
        """삼중지수이동평균 (Triple EMA) = 3*EMA - 3*EMA2 + EMA3"""
        p = TechnicalIndicators._safe_period(period)
        ema1 = series.ewm(span=p, adjust=False).mean()
        ema2 = ema1.ewm(span=p, adjust=False).mean()
        ema3 = ema2.ewm(span=p, adjust=False).mean()
        return 3 * ema1 - 3 * ema2 + ema3

    # ================================================================
    # [신규] 볼린저 밴드 파생
    # ================================================================

    @staticmethod
    def disparity(series, period):
        """이격도 = (현재가 / MA) x 100. 100 이상=이격 과대, 100=MA 일치"""
        p = TechnicalIndicators._safe_period(period)
        ma = series.rolling(window=p).mean()
        return (series / ma.replace(0, np.nan)) * 100

    @staticmethod
    def pctb(series, period=20, std_dev=2):
        """볼린저 퍼센트B (0=하단, 0.5=중간, 1=상단, 음수/1초과=이탈)"""
        p = TechnicalIndicators._safe_period(period)
        upper, _, lower = TechnicalIndicators.bbands(series, p, std_dev)
        band_range = (upper - lower).replace(0, np.nan)
        return (series - lower) / band_range

    @staticmethod
    def band_width(series, period=20, std_dev=2):
        """볼린저 밴드폭 = (상단-하단)/중간선 x 100. 스퀴즈(수렴) 탐지용"""
        p = TechnicalIndicators._safe_period(period)
        upper, mid, lower = TechnicalIndicators.bbands(series, p, std_dev)
        return ((upper - lower) / mid.replace(0, np.nan)) * 100

    @staticmethod
    def envelope_up(series, period=20, percent=6):
        """엔벨로프 상단 = MA x (1 + percent/100)"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).mean() * (1 + percent / 100.0)

    @staticmethod
    def envelope_down(series, period=20, percent=6):
        """엔벨로프 하단 = MA x (1 - percent/100)"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).mean() * (1 - percent / 100.0)

    # ================================================================
    # [신규] 거래량 지표
    # ================================================================

    @staticmethod
    def vwap(high, low, close, volume):
        """VWAP (거래량가중평균가) - 누적방식. 일봉 데이터의 경우 세션 reset 불가"""
        tp = (high + low + close) / 3
        return (tp * volume).cumsum() / volume.cumsum().replace(0, np.nan)

    @staticmethod
    def force_index(close, volume, period=13):
        """포스 인덱스 (Elder): EMA(가격변화 x 거래량, period)"""
        p = TechnicalIndicators._safe_period(period)
        return (close.diff(1) * volume).ewm(span=p, adjust=False).mean()

    # ================================================================
    # [신규] 가격 구조
    # ================================================================

    @staticmethod
    def true_high(high, close):
        """진정고가 = max(당일고가, 전일종가)"""
        return pd.concat([high, close.shift(1)], axis=1).max(axis=1)

    @staticmethod
    def true_low(low, close):
        """진정저가 = min(당일저가, 전일종가)"""
        return pd.concat([low, close.shift(1)], axis=1).min(axis=1)

    @staticmethod
    def true_range(high, low, close):
        """진정범위 (True Range) = max(H-L, |H-C(1)|, |C(1)-L|)"""
        hl = high - low
        hc = (high - close.shift(1)).abs()
        lc = (low  - close.shift(1)).abs()
        return pd.concat([hl, hc, lc], axis=1).max(axis=1)

    @staticmethod
    def pivot(high, low, close, pivot_type='standard'):
        """피봇 포인트 - 전일 HLC 기준 당일 지지저항
        Returns: (pivot, r1, s1, r2, s2)
        pivot_type: 'standard' | 'fibonacci'
        """
        p = (high.shift(1) + low.shift(1) + close.shift(1)) / 3
        rng = high.shift(1) - low.shift(1)
        if pivot_type == 'fibonacci':
            r1 = p + 0.382 * rng
            s1 = p - 0.382 * rng
            r2 = p + 0.618 * rng
            s2 = p - 0.618 * rng
        else:
            r1 = 2 * p - low.shift(1)
            s1 = 2 * p - high.shift(1)
            r2 = p + rng
            s2 = p - rng
        return p, r1, s1, r2, s2

    # ================================================================
    # [신규] 유틸 지표
    # ================================================================

    @staticmethod
    def highest(series, period):
        """N봉 중 최고값 (rolling max)"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).max()

    @staticmethod
    def lowest(series, period):
        """N봉 중 최저값 (rolling min)"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).min()

    @staticmethod
    def bars_since(condition):
        """BarsSince: 조건이 마지막으로 True였던 이후 경과 봉수."""
        cond = condition.astype(bool)
        result = np.full(len(cond), np.nan)
        counter = np.nan
        for i, val in enumerate(cond.values):
            if val:
                counter = 0.0
            elif not np.isnan(counter):
                counter += 1.0
            result[i] = counter
        return pd.Series(result, index=cond.index)

    @staticmethod
    def value_when(condition, data, n=1):
        """ValueWhen(Condition, Data, N) - 조건이 N번째 만족된 시점의 Data 값."""
        cond = condition.astype(bool).values
        data_vals = data.values
        result = np.full(len(cond), np.nan)
        true_indices = np.where(cond)[0]
        for i in range(len(cond)):
            past_indices = true_indices[true_indices <= i]
            if len(past_indices) >= n:
                result[i] = data_vals[past_indices[-n]]
        return pd.Series(result, index=data.index)

    @staticmethod
    def highest_since(condition, data):
        """HighestSince(Condition, Data) - 조건 만족 이후 Data의 최고가."""
        cond = condition.astype(bool).values
        data_vals = data.values
        result = np.full(len(cond), np.nan)
        current_max = np.nan
        for i in range(len(cond)):
            if cond[i]:
                current_max = data_vals[i]
            elif not np.isnan(current_max):
                current_max = max(current_max, data_vals[i])
            result[i] = current_max
        return pd.Series(result, index=data.index)

    @staticmethod
    def lowest_since(condition, data):
        """LowestSince(Condition, Data) - 조건 만족 이후 Data의 최저가."""
        cond = condition.astype(bool).values
        data_vals = data.values
        result = np.full(len(cond), np.nan)
        current_min = np.nan
        for i in range(len(cond)):
            if cond[i]:
                current_min = data_vals[i]
            elif not np.isnan(current_min):
                current_min = min(current_min, data_vals[i])
            result[i] = current_min
        return pd.Series(result, index=data.index)

    # ================================================================
    # [신규] 통계 / 회귀 분석
    # ================================================================

    @staticmethod
    def linear_reg(series, period):
        """선형회귀값 (Linear Regression) — N봉 OLS 회귀선의 현재 시점 예측값."""
        p = TechnicalIndicators._safe_period(period)
        def _lr(x):
            n = len(x)
            t = np.arange(n, dtype=float)
            A = np.vstack([t, np.ones(n)]).T
            try:
                m, b = np.linalg.lstsq(A, x, rcond=None)[0]
                return m * (n - 1) + b
            except Exception:
                return np.nan
        return series.rolling(window=p).apply(_lr, raw=True)

    @staticmethod
    def slope(series, period):
        """기울기 (Slope) — N봉 선형회귀 기울기(단위: 가격/봉)."""
        p = TechnicalIndicators._safe_period(period)
        def _slope(x):
            n = len(x)
            t = np.arange(n, dtype=float)
            A = np.vstack([t, np.ones(n)]).T
            try:
                m, _ = np.linalg.lstsq(A, x, rcond=None)[0]
                return m
            except Exception:
                return np.nan
        return series.rolling(window=p).apply(_slope, raw=True)

    @staticmethod
    def correlation(series_a, series_b, period):
        """상관계수 (Pearson Correlation) — N봉 윈도우."""
        p = TechnicalIndicators._safe_period(period)
        return series_a.rolling(window=p).corr(series_b)

    @staticmethod
    def zigzag(series, pct=5.0):
        """지그재그 (ZigZag) — pct% 이상 방향 전환 시 피벗 연결선.
        전환점 사이는 선형 보간. 미래 참조 없는 후행 방식.
        pct: 전환 기준 변화율 (%)
        """
        s = series.values.copy().astype(float)
        n = len(s)
        result = np.full(n, np.nan)
        threshold = pct / 100.0

        if n < 2:
            return pd.Series(result, index=series.index)

        last_pivot_idx = 0
        last_pivot_val = s[0]
        direction = 0  # 0=미결, 1=상승, -1=하락
        result[0] = s[0]

        for i in range(1, n):
            chg = (s[i] - last_pivot_val) / (abs(last_pivot_val) + 1e-10)
            if direction == 0:
                if chg >= threshold:
                    direction = 1
                elif chg <= -threshold:
                    direction = -1
            elif direction == 1:
                if chg <= -threshold:
                    result[last_pivot_idx] = last_pivot_val
                    last_pivot_idx = i
                    last_pivot_val = s[i]
                    direction = -1
                elif s[i] > last_pivot_val:
                    last_pivot_val = s[i]
                    last_pivot_idx = i
            elif direction == -1:
                if chg >= threshold:
                    result[last_pivot_idx] = last_pivot_val
                    last_pivot_idx = i
                    last_pivot_val = s[i]
                    direction = 1
                elif s[i] < last_pivot_val:
                    last_pivot_val = s[i]
                    last_pivot_idx = i

        result[last_pivot_idx] = last_pivot_val

        # 피벗 사이 선형 보간
        pivot_indices = np.where(~np.isnan(result))[0]
        for k in range(len(pivot_indices) - 1):
            ia, ib = pivot_indices[k], pivot_indices[k + 1]
            va, vb = result[ia], result[ib]
            for j in range(ia, ib + 1):
                result[j] = va + (vb - va) * (j - ia) / (ib - ia)

        return pd.Series(result, index=series.index)

    # ================================================================
    # [신규] 수학 / 변환 유틸
    # ================================================================

    @staticmethod
    def nz(series, default=0):
        """Nz (Null to Zero/default) — NaN을 default 값으로 대체.
        영웅문4 Nz(source, default) 와 동일.
        """
        return series.fillna(default)

    @staticmethod
    def cum(series):
        """Cum (Cumulative Sum) — 누적합. 영웅문4 Cum(source) 와 동일."""
        return series.cumsum()

    @staticmethod
    def bar_count(series):
        """BarCount — 전체 봉 수를 Series로 반환 (상수 Series).
        영웅문4에서 BarCount는 현재 봉까지의 총 봉 수.
        누적 방식: 1, 2, 3, ... n 으로 반환.
        """
        return pd.Series(np.arange(1, len(series) + 1, dtype=float), index=series.index)

    # ── highest / lowest 별칭 (영웅문 구버전 HHV/LLV) ──────────────
    @staticmethod
    def hhv(series, period):
        """HHV (Highest High Value) — highest의 구버전 별칭"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).max()

    @staticmethod
    def llv(series, period):
        """LLV (Lowest Low Value) — lowest의 구버전 별칭"""
        p = TechnicalIndicators._safe_period(period)
        return series.rolling(window=p).min()

    # ── 교차 분석 (신규) ──────────────────────────────────────────
    @staticmethod
    def cross_up(series_a, series_b):
        """CrossUp (골든크로스) — series_a가 series_b를 상향 돌파"""
        return (series_a > series_b) & (series_a.shift(1) <= series_b.shift(1))

    @staticmethod
    def cross_down(series_a, series_b):
        """CrossDown (데드크로스) — series_a가 series_b를 하향 돌파"""
        return (series_a < series_b) & (series_a.shift(1) >= series_b.shift(1))

