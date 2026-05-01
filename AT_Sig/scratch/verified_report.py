import pandas as pd
import numpy as np
import sys
import os

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from shared.api import fetch_daily_chart
from AT_Sig.login import fn_au10001 as get_token
from config import get_current_config
from shared.indicators import TechnicalIndicators as TI

def analyze_raw(code):
    conf = get_current_config()
    token = get_token()
    data = fetch_daily_chart(conf['host_url'], code, token, days=60)
    if not data: return None
    
    df = pd.DataFrame(data)
    df['open'] = pd.to_numeric(df['open_pric'], errors='coerce')
    df['high'] = pd.to_numeric(df['high_pric'], errors='coerce')
    df['low'] = pd.to_numeric(df['low_pric'], errors='coerce')
    df['close'] = pd.to_numeric(df['cur_prc'], errors='coerce')
    
    C = df['close']
    O = df['open']
    H = df['high']
    L = df['low']
    
    # Strategy Logic
    BBU = TI.bbands(C, 20, 2)[0]
    ema20 = C.ewm(span=20, adjust=False).mean()
    atr20 = TI.atr(H, L, C, 20)
    CCU = ema20 + (atr20 * 2)
    
    A1 = (C.rolling(window=20).max() > BBU)
    A2 = (C.rolling(window=20).max() > CCU)
    
    A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
    A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
    A5 = (O > C)
    
    B = A1 & A3 & A4 & A5
    TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
    
    last_tl = TargetLine.iloc[-1]
    last_close = C.iloc[-1]
    
    # Return result
    return {
        "tl": last_tl,
        "close": last_close,
        "hit": last_close > last_tl
    }

for c in ['050890', '052710', '023160']:
    res = analyze_raw(c)
    if res:
        print(f"VERIFIED|{c}|{res['tl']}|{res['close']}|{res['hit']}")
