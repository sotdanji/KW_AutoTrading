import os
import pandas as pd
import numpy as np
import sys

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from AT_Sig.data_manager import DataManager
from shared.indicators import TechnicalIndicators as TI
from AT_Sig.login import fn_au10001 as get_token

def analyze_specific(code, token):
    dm = DataManager()
    data = dm.get_daily_chart(code, token, use_cache=True)
    if not data: 
        print(f"DEBUG|{code}|No data")
        return None
    df = pd.DataFrame(data)
    
    # Map columns
    mapping = {
        'open_prc': 'open', 'stck_oprc': 'open', 'open_pric': 'open',
        'high_prc': 'high', 'stck_hgpr': 'high', 'high_pric': 'high',
        'low_prc': 'low', 'stck_lwpr': 'low', 'low_pric': 'low',
        'close_prc': 'close', 'stck_prpr': 'close', 'cur_prc': 'close',
        'trde_qty': 'volume', 'acml_vol': 'volume'
    }
    for k, v in mapping.items():
        if k in df.columns:
            df[v] = pd.to_numeric(df[k].astype(str).str.replace(r'[^0-9.-]', '', regex=True), errors='coerce')
    
    C = df['close']
    O = df['open']
    H = df['high']
    L = df['low']
    
    # Logic
    BBU = TI.bbands(C, 20, 2)[0]
    ema20 = C.ewm(span=20, adjust=False).mean()
    atr20 = TI.atr(H, L, C, 20)
    CCU = ema20 + (atr20 * 2)
    
    A1 = (C.rolling(window=20).max() > BBU) # Broader trend check
    A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
    A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
    A5 = (O > C)
    B = A1 & A3 & A4 & A5
    
    TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
    
    # Name from last data
    return {
        "code": code,
        "tl": TargetLine.iloc[-1],
        "close": C.iloc[-1]
    }

token = get_token()
codes = ['052710', '023160', '039490', '064260', '005460']
for c in codes:
    res = analyze_specific(c, token)
    if res:
        print(f"RESULT|{c}|{res['tl']}|{res['close']}")
