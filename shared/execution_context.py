
import pandas as pd
import numpy as np
from shared.indicators import TechnicalIndicators as TI

def get_execution_context(df, day_open_override=None, preday_close_override=None):
    """
    Returns a dictionary of globals (variables and functions) 
    to be used in exec() validation and backtesting.
    
    day_open_override: (float) 일봉에서 가져온 정확한 당일 시가
    preday_close_override: (float) 일봉에서 가져온 정확한 전일 종가
    """
    
    # 1. Base Variables
    # ... (columns: open, high, low, close, volume)
    C = df['close']
    O = df['open']
    H = df['high']
    L = df['low']
    V = df['volume']
    AMT = df['amount'] if 'amount' in df.columns else (df['value'] if 'value' in df.columns else pd.Series(0, index=df.index))
    
    # Date/Time Series
    date_series = df['date'] if 'date' in df.columns else pd.to_datetime(df.index)
    
    def _extract_time(d):
        d_str = str(d)
        # [안실장 픽스] YYYY-MM-DD HH:MM:SS 또는 YYYYMMDDHHMMSS 등 다양한 형식 대응
        import re
        digits = re.sub(r'[^0-9]', '', d_str)
        if len(digits) >= 6:
            return digits[-6:]
        return "000000"
        
    _ts = df['time'] if 'time' in df.columns else (df['date'].apply(_extract_time) if 'date' in df.columns else pd.Series("000000", index=df.index))
    # [안실장 픽스] Time/DATE 시리즈를 정수로 변환하여 수식 비교 호환성 확보
    # 문자열 내의 콜론(:) 등 특수문자를 제거 후 변환
    time_series = _ts.astype(str).str.replace(r'[^0-9]', '', regex=True).replace('', '0').astype(int)
    
    # Date change detection for DayOpen / PreDayClose
    _day_groups = (date_series != date_series.shift(1)).cumsum()
    
    # [안실장 픽스] DayOpen 및 PreDayClose 로직 강화
    # 1. 데이터(df)의 첫 번째 봉 시간이 09:00~09:01 사이가 아니라면 현재 첫 봉을 시가로 인정하지 않음
    # 2. override 값이 주어지면 해당 값을 최우선으로 사용하여 데이터 누락 시에도 안전하게 대응
    
    # 기본값 추출
    _raw_day_open_series = O.groupby(_day_groups).transform('first')
    
    if day_open_override is not None:
        # 마지막 그룹(오늘)에 대해 override 값 적용
        last_group_id = _day_groups.iloc[-1]
        _day_open_series = _raw_day_open_series.copy()
        _day_open_series.loc[_day_groups == last_group_id] = float(day_open_override)
    else:
        _day_open_series = _raw_day_open_series

    if preday_close_override is not None:
        last_group_id = _day_groups.iloc[-1]
        # _preday_close_series 생성 시 오늘 그룹에 대해서는 전달된 값을 사용
        _daily_close = C.groupby(_day_groups).last()
        _base_preday = _day_groups.map(_daily_close.shift(1))
        _preday_close_series = _base_preday.copy()
        _preday_close_series.loc[_day_groups == last_group_id] = float(preday_close_override)
    else:
        _daily_close = C.groupby(_day_groups).last()
        _preday_close_series = _day_groups.map(_daily_close.shift(1))
    
    def _DayOpen(): return _day_open_series
    def _PreDayClose(): return _preday_close_series
    
    # 2. Helpers (Indicators)
    def _ATR(period=14): return TI.atr(H, L, C, period)
    def _RSI(period=14): return TI.rsi(C, period)
    def _CCI(period=14): return TI.cci(H, L, C, period)
    
    def _MACD(short=12, long=26): 
        macd, _ = TI.macd(C, short, long, 9)
        return macd
        
    def _MACDSignal(short=12, long=26, signal=9):
        _, sig = TI.macd(C, short, long, signal)
        return sig
        
    def _MACDOscillator(short=12, long=26, signal=9):
        macd, sig = TI.macd(C, short, long, signal)
        return macd - sig

    def _StochasticsSlowK(n=12, m=5, t=5):
        k, _ = TI.stochastics_slow(H, L, C, n, m, t)
        return k
        
    def _StochasticsSlowD(n=12, m=5, t=5):
        _, d = TI.stochastics_slow(H, L, C, n, m, t)
        return d
        
    def _DIPlus(period=14):
        dp, _ = TI.dmi(H, L, C, period)
        return dp
        
    def _DIMinus(period=14):
        _, dm = TI.dmi(H, L, C, period)
        return dm
        
    def _ADX(period=14):
        dp, dm = TI.dmi(H, L, C, period)
        diff = np.abs(dp - dm)
        sum_ = dp + dm
        dx = (diff / sum_.replace(0, 1)) * 100
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        return adx

    def _OBV(): return TI.obv(C, V)
    def _MFI(period=14): return TI.mfi(H, L, C, V, period)
    def _Parabolic(af=0.02, max_af=0.2): return TI.sar(H, L, af, max_af)

    def _BBandsUp(period=20, std_dev=2): return TI.bbands(C, period, std_dev)[0]
    def _BBandsDown(period=20, std_dev=2): return TI.bbands(C, period, std_dev)[2]
    def _BBandsMid(period=20, std_dev=2): return TI.bbands(C, period, std_dev)[1]
    
    def _SMA(series, period): return TI.sma(series, period)
    def _EMA(series, period): return TI.ema(series, period)

    def _EnvelopeUp(period=20, percent=6):
        ma = TI.sma(C, period)
        return ma * (1 + percent / 100.0)

    def _EnvelopeDown(period=20, percent=6):
        ma = TI.sma(C, period)
        return ma * (1 - percent / 100.0)

    # ── 이평선 (신규) ────────────────────────────────────────────
    def _WMA(series, period): return TI.wma(series, period)
    def _DEMA(series, period): return TI.dema(series, period)
    def _TEMA(series, period): return TI.tema(series, period)

    # ── 볼린저 파생 (신규) ────────────────────────────────────────
    def _Disparity(period=20): return TI.disparity(C, period)
    def _PCTB(period=20, std=2): return TI.pctb(C, period, std)
    def _BandWidth(period=20, std=2): return TI.band_width(C, period, std)

    # ── 거래량 (신규) ─────────────────────────────────────────────
    def _VWAP(): return TI.vwap(H, L, C, V)
    def _ForceIndex(period=13): return TI.force_index(C, V, period)

    # ── 가격 구조 (신규) ──────────────────────────────────────────
    def _TrueHigh(): return TI.true_high(H, C)
    def _TrueLow():  return TI.true_low(L, C)
    def _TrueRange(): return TI.true_range(H, L, C)
    def _PivotP():   return TI.pivot(H, L, C)[0]
    def _PivotR1():  return TI.pivot(H, L, C)[1]
    def _PivotS1():  return TI.pivot(H, L, C)[2]
    def _PivotR2():  return TI.pivot(H, L, C)[3]
    def _PivotS2():  return TI.pivot(H, L, C)[4]

    # ── 유틸 (신규) ───────────────────────────────────────────────
    def _BarsSince(condition): return TI.bars_since(condition)

    # 3. Math / Logic Helpers
    def _to_series(s):
        if isinstance(s, (pd.Series, pd.DataFrame)):
            return s
        # Ensure alignment with main dataframe index
        return pd.Series(s, index=df.index)

    def _to_int(val, default=20):
        try:
            res = default
            if isinstance(val, (int, float)): res = int(val)
            elif isinstance(val, str) and val.strip().isdigit(): res = int(val.strip())
            else: res = int(float(val))
            return max(1, res)
        except:
            return default

    def _highest(series, period): 
        p = _to_int(period)
        return _to_series(series).rolling(window=p).max()
    def _lowest(series, period): 
        p = _to_int(period)
        return _to_series(series).rolling(window=p).min()
    
    def _MAX(*args): return pd.concat([_to_series(a) for a in args], axis=1).max(axis=1)
    def _MIN(*args): return pd.concat([_to_series(a) for a in args], axis=1).min(axis=1)
    
    def _CrossUp(a, b): 
        a, b = _to_series(a), _to_series(b)
        return (a > b) & (a.shift(1) <= b.shift(1))
        
    def _CrossDown(a, b): 
        a, b = _to_series(a), _to_series(b)
        return (a < b) & (a.shift(1) >= b.shift(1))
        
    def _shift(series, period): return _to_series(series).shift(period)
    
    def _CountSince(condition, data):
        # condition and data are expected to be Series (or convertable)
        condition = _to_series(condition)
        data = _to_series(data)
        
        # Group by Cumulative Sum of condition (increments on True)
        # We need to make sure index alignment holds
        groups = condition.cumsum()
        
        if data.dtype == bool:
            data = data.astype(int)
            
        return data.groupby(groups).cumsum()

    def _stdev(series, period): 
        p = _to_int(period)
        return _to_series(series).rolling(window=p).std()
    def _sum(series, period): 
        p = _to_int(period)
        return _to_series(series).rolling(window=p).sum()

    def _ValueWhen(n, condition, data): return TI.value_when(_to_series(condition), _to_series(data), n)
    def _HighestSince(condition, data): return TI.highest_since(_to_series(condition), _to_series(data))
    def _LowestSince(condition, data): return TI.lowest_since(_to_series(condition), _to_series(data))

    # ── 참조 함수 (신규) ───────────────────────────────────────────
    def _Ref(series, n):             return _to_series(series).shift(n)

    # ── 수학 / 변환 (신규) ─────────────────────────────────────────
    def _Abs(series):                return _to_series(series).abs()
    def _Nz(series, default=0):      return _to_series(series).fillna(default)
    def _Int(series):                return np.floor(_to_series(series))
    def _Round(series, n=0):         return _to_series(series).round(n)
    def _Sqrt(series):               return np.sqrt(_to_series(series))
    def _Log(series):                return np.log(_to_series(series))
    def _Exp(series):                return np.exp(_to_series(series))
    def _Cum(series):                return _to_series(series).cumsum()
    def _BarCount():                 return pd.Series(np.arange(1, len(df) + 1, dtype=float), index=df.index)

    # ── 통계 / 회귀 (신규) ─────────────────────────────────────────
    def _LinearReg(series, period):  return TI.linear_reg(_to_series(series), period)
    def _Slope_fn(series, period):   return TI.slope(_to_series(series), period)
    def _Correlation(a, b, period):  return TI.correlation(_to_series(a), _to_series(b), period)

    # ── 지그재그 / 구버전 별칭 (신규) ─────────────────────────────
    def _ZigZag(pct=5):              return TI.zigzag(C, pct)
    def _HHV(series, period):        
        p = _to_int(period)
        return _to_series(series).rolling(window=p).max()
    def _LLV(series, period):        
        p = _to_int(period)
        return _to_series(series).rolling(window=p).min()

    # --- New Context Wrappers for Indicators ---
    def _PDI(period=14): return TI.dmi(H, L, C, period)[0]
    def _MDI(period=14): return TI.dmi(H, L, C, period)[1]
    def _Momentum(period=10): return TI.momentum(C, period)
    def _ROC(period=12): return TI.roc(C, period)
    def _TRIX(period=12): return TI.trix(C, period)
    def _WilliamsR(period=14): return TI.williams_r(H, L, C, period)
    
    def _Ichi_Tenkan(short=9, mid=26, long=52): return TI.ichimoku(H, L, short, mid, long)[0]
    def _Ichi_Kijun(short=9, mid=26, long=52): return TI.ichimoku(H, L, short, mid, long)[1]
    def _Ichi_SenkouA(short=9, mid=26, long=52): return TI.ichimoku(H, L, short, mid, long)[2]
    def _Ichi_SenkouB(short=9, mid=26, long=52): return TI.ichimoku(H, L, short, mid, long)[3]

    # 4. Context Dictionary
    context = {
        'df': df, 'pd': pd, 'np': np, 'TI': TI,
        'C': C, 'c': C, 'close': C, 'Close': C,
        'O': O, 'o': O, 'open': O, 'Open': O,
        'H': H, 'h': H, 'high': H, 'High': H,
        'L': L, 'l': L, 'low': L, 'Low': L,
        'V': V, 'v': V, 'volume': V, 'Volume': V,
        'AMT': AMT, 'amt': AMT, 'amount': AMT, 'Amount': AMT, '거래대금': AMT,
        
        'date': date_series, 'Date': date_series, 'DATE': date_series,
        'time': time_series, 'Time': time_series, 'TIME': time_series,
        
        'DayOpen': _DayOpen, 'dayopen': _DayOpen, 'DAYOPEN': _DayOpen, 'day_open': _day_open_series, '당일시가': _day_open_series,
        'PreDayClose': _PreDayClose, 'predayclose': _PreDayClose, 'PREDAYCLOSE': _PreDayClose, 'prev_close': _preday_close_series, '전일종가': _preday_close_series,
        
        'ATR': _ATR, 'atr': _ATR,
        'RSI': _RSI, 'rsi': _RSI,
        'CCI': _CCI, 'cci': _CCI,
        'MACD': _MACD, 'macd': _MACD,
        'MACDSignal': _MACDSignal, 'macdsignal': _MACDSignal,
        'MACDOscillator': _MACDOscillator, 'macdos': _MACDOscillator, 'MACD_OSC': _MACDOscillator,
        'StochasticsSlowK': _StochasticsSlowK, 'stochasticsSlowK': _StochasticsSlowK, 'StochasticsSlow': _StochasticsSlowK, 'StochasticsK': _StochasticsSlowK,
        'StochasticsSlowD': _StochasticsSlowD, 'stochasticsSlowD': _StochasticsSlowD, 'StochasticsD': _StochasticsSlowD,
        
        'PDI': _PDI, 'pdi': _PDI, 'DIPlus': _DIPlus, 'diplus': _DIPlus,
        'MDI': _MDI, 'mdi': _MDI, 'DIMinus': _DIMinus, 'diminus': _DIMinus,
        'ADX': _ADX, 'adx': _ADX,
        
        'OBV': _OBV, 'obv': _OBV,
        'MFI': _MFI, 'mfi': _MFI,
        'Parabolic': _Parabolic, 'parabolic': _Parabolic, 'PSAR': _Parabolic, 'SAR': _Parabolic,
        'BBandsUp': _BBandsUp, 'BBU': _BBandsUp,
        'BBandsDown': _BBandsDown, 'BBD': _BBandsDown,
        'BBandsMid': _BBandsMid, 'BBM': _BBandsMid,
        'SMA': _SMA, 'sma': _SMA, 'avg': _SMA, 'ma': _SMA, '_ma': _SMA, '_avg': _SMA,
        'EMA': _EMA, 'ema': _EMA, 'eavg': _EMA, '_ema': _EMA,
        'stdev': _stdev, 'STDEV': _stdev, '_stdev': _stdev,
        'sum': _sum, 'SUM': _sum, '_sum': _sum,
        
        'Momentum': _Momentum, 'momentum': _Momentum,
        'ROC': _ROC, 'roc': _ROC,
        'TRIX': _TRIX, 'trix': _TRIX,
        'WilliamsR': _WilliamsR, 'williamsr': _WilliamsR,
        
        'Ichi_Tenkan': _Ichi_Tenkan,
        'Ichi_Kijun': _Ichi_Kijun,
        'Ichi_SenkouA': _Ichi_SenkouA,
        'Ichi_SenkouB': _Ichi_SenkouB,
        
        # ── 기존 등록 ─────────────────────────────────────────────
        'EnvelopeUp': _EnvelopeUp, 'envelopeUp': _EnvelopeUp, 'envelopeup': _EnvelopeUp, '_EnvelopeUp': _EnvelopeUp,
        'EnvelopeDown': _EnvelopeDown, 'envelopeDown': _EnvelopeDown, 'envelopedown': _EnvelopeDown, '_EnvelopeDown': _EnvelopeDown,
        'VR': lambda period=20: TI.vr(C, O, V, period), 'vr': lambda period=20: TI.vr(C, O, V, period),
        'highest': _highest, 'Highest': _highest, '_highest': _highest,
        'lowest': _lowest, 'Lowest': _lowest, '_lowest': _lowest,
        'MAX': _MAX, 'Max': _MAX, '_MAX': _MAX,
        'MIN': _MIN, 'Min': _MIN, '_MIN': _MIN,
        'CrossUp': _CrossUp,   '_CrossUp': _CrossUp,
        'CrossDown': _CrossDown, '_CrossDown': _CrossDown,
        'shift': _shift, 'Shift': _shift,
        'CountSince': _CountSince, '_CountSince': _CountSince,
        'ValueWhen': _ValueWhen, 'valueWhen': _ValueWhen, 'valuewhen': _ValueWhen, '_ValueWhen': _ValueWhen,
        'HighestSince': _HighestSince, 'highestSince': _HighestSince, 'highestsince': _HighestSince, '_HighestSince': _HighestSince,
        'LowestSince': _LowestSince, 'lowestSince': _LowestSince, 'lowestsince': _LowestSince, '_LowestSince': _LowestSince,

        # ── 신규 등록 (AI 의존성 제로화) ────────────────────────────
        # 이평선
        'WMA': _WMA, 'wma': _WMA,
        'DEMA': _DEMA, 'dema': _DEMA,
        'TEMA': _TEMA, 'tema': _TEMA,
        # 볼린저 파생
        'Disparity': _Disparity, 'disparity': _Disparity, '_Disparity': _Disparity,
        'PCTB': _PCTB, 'pctb': _PCTB, '_PCTB': _PCTB,
        'BandWidth': _BandWidth, 'band_width': _BandWidth, '_BandWidth': _BandWidth,
        # 거래량
        'VWAP': _VWAP, 'vwap': _VWAP, '_VWAP': _VWAP,
        'ForceIndex': _ForceIndex, 'force_index': _ForceIndex, '_ForceIndex': _ForceIndex,
        # 가격 구조
        'TrueHigh': _TrueHigh, '_TrueHigh': _TrueHigh,
        'TrueLow': _TrueLow, '_TrueLow': _TrueLow,
        'TrueRange': _TrueRange, '_TrueRange': _TrueRange,
        'PivotP': _PivotP, 'Pivot': _PivotP,
        'PivotR1': _PivotR1, 'PivotS1': _PivotS1,
        'PivotR2': _PivotR2, 'PivotS2': _PivotS2,
        # 유틸
        'BarsSince': _BarsSince, 'bars_since': _BarsSince, '_BarsSince': _BarsSince,
        # BBandsMid 별칭
        'BBandsMid': _BBandsMid, 'BBM': _BBandsMid,

        # ── 미지원 함수 완전 추가 (v2.1) ─────────────────────────────
        # 참조 함수
        'Ref': _Ref, 'ref': _Ref, '_Ref': _Ref,
        # 수학 / 변환
        'Abs': _Abs, 'abs': _Abs, '_Abs': _Abs,
        'Nz': _Nz,  'nz': _Nz,  '_Nz': _Nz,
        'Int': _Int, '_Int': _Int,
        'Round': _Round, '_Round': _Round,
        'Sqrt': _Sqrt, 'sqrt': _Sqrt, '_Sqrt': _Sqrt,
        'Log':  _Log,  'log':  _Log,  '_Log': _Log,
        'Exp':  _Exp,  'exp':  _Exp,  '_Exp': _Exp,
        'Cum':  _Cum,  'cum':  _Cum,  '_Cum': _Cum,
        'BarCount': _BarCount, 'bar_count': _BarCount, '_BarCount': _BarCount,
        # 통계 / 회귀
        'LinearReg': _LinearReg, 'linear_reg': _LinearReg, '_LinearReg': _LinearReg,
        'Slope': _Slope_fn, 'slope': _Slope_fn, '_Slope': _Slope_fn, '_Slope_fn': _Slope_fn,
        'Correlation': _Correlation, 'correlation': _Correlation, '_Correlation': _Correlation,
        # 지그재그 / 구버전 별칭
        'ZigZag': _ZigZag, 'zigzag': _ZigZag, '_ZigZag': _ZigZag,
        'HHV': _HHV, 'hhv': _HHV, '_HHV': _HHV,
        'LLV': _LLV, 'llv': _LLV, '_LLV': _LLV,
        
        # ── Kiwoom Default Variables (Prevent NameError during validation) ──
        'P1': 5, 'P2': 10, 'P3': 20, 'P4': 60, 'P5': 120,
        'p1': 5, 'p2': 10, 'p3': 20, 'p4': 60, 'p5': 120,
        '기간1': 5, '기간2': 10, '기간3': 20, '기간4': 60, '기간5': 120,
        '배수': 2, '비중': 10,
        '현재가': C, '시가': O, '고가': H, '저가': L, '종가': C, '거래량': V
    }

    return context
