import json
import os
import pandas as pd
import numpy as np
import sys
from datetime import datetime

# Add project root and AT_Sig to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
at_sig_dir = os.path.join(project_root, "AT_Sig")
for d in [project_root, at_sig_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from shared.execution_context import get_execution_context
from AT_Sig.data_manager import DataManager

def get_df_mapped(code, dm):
    data = dm.get_daily_chart(code, "dummy", use_cache=True)
    if not data: return None
    df = pd.DataFrame(data)
    mapping = {
        'open_prc': 'open', 'stck_oprc': 'open', 'open_pric': 'open',
        'high_prc': 'high', 'stck_hgpr': 'high', 'high_pric': 'high',
        'low_prc': 'low', 'stck_lwpr': 'low', 'low_pric': 'low',
        'close_prc': 'close', 'stck_prpr': 'close', 'cur_prc': 'close',
        'trde_qty': 'volume', 'acml_vol': 'volume'
    }
    for k, v in mapping.items():
        if k in df.columns:
            df[v] = pd.to_numeric(df[k].astype(str).str.replace(',', ''), errors='coerce')
    if 'dt' in df.columns: df['date'] = df['dt']
    elif 'base_dt' in df.columns: df['date'] = df['base_dt']
    cols = ['open', 'high', 'low', 'close', 'volume', 'date']
    if all(c in df.columns for c in ['open', 'high', 'low', 'close']):
        return df[cols].fillna(0)
    return None

def run_specific_test():
    dm = DataManager()
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        full_history = json.load(f)
    
    today_str = "2026-04-10"
    if today_str not in full_history:
        print("No matches since no history for today.")
        return
        
    stocks = full_history[today_str]
    unique_codes = list(stocks.keys())
    
    results = []
    
    for code in unique_codes:
        df = get_df_mapped(code, dm)
        if df is None or len(df) < 55: continue
        
        # Manually apply the USER provided logic
        # 1. Indicators
        from shared.indicators import TechnicalIndicators as TI
        C = df['close']
        O = df['open']
        H = df['high']
        L = df['low']
        
        BBU = TI.bbands(C, 20, 2)[0] # Upper band
        
        # CCU = ema(C, 20) + (atr(20) * 2)
        ema20 = C.ewm(span=20, adjust=False, min_periods=20).mean()
        atr20 = TI.atr(H, L, C, 20)
        CCU = ema20 + (atr20 * 2)
        
        # A1, A2
        A1 = (C.shift(2)>BBU.shift(2)) | (C.shift(1)>BBU.shift(1)) | (C>BBU)
        A2 = (C.shift(2)>CCU.shift(2)) | (C.shift(1)>CCU.shift(1)) | (C>CCU)
        
        # A3, A4, A5
        A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
        A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
        A5 = (O > C)
        
        B = A1 & A2 & A3 & A4 & A5
        
        # TargetLine
        TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
        
        # cond
        cond = (C.shift(1) <= TargetLine.shift(1)) & (C > TargetLine)
        
        if not cond.empty and cond.iloc[-1]:
            results.append({
                "code": code,
                "name": stocks[code].get('name'),
                "target": TargetLine.iloc[-1],
                "price": C.iloc[-1]
            })

    print(f"\n[분석 결과] 사용자 제공 파이썬 로직 기반 (4/10)")
    print("-" * 60)
    if not results:
        print("만족하는 종목이 없습니다. (조금 더 엄격한 추세 필터가 적용됨)")
    else:
        for res in results:
            print(f"[{res['code']}] {res['name']:<15} | Target: {res['target']:>8,.0f} | Close: {res['price']:>8,.0f}")
    print("=" * 60)

if __name__ == "__main__":
    run_specific_test()
