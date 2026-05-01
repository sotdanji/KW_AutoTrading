import json
import os
import pandas as pd
import numpy as np
import sys
from datetime import datetime

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from shared.api import fetch_daily_chart
from AT_Sig.login import fn_au10001 as get_token
from config import get_current_config
from shared.indicators import TechnicalIndicators as TI

def analyze_raw(code, host_url, token):
    try:
        data = fetch_daily_chart(host_url, code, token, days=60)
        if not data or len(data) < 20: return None
        
        df = pd.DataFrame(data)
        df['open'] = pd.to_numeric(df['open_pric'], errors='coerce')
        df['high'] = pd.to_numeric(df['high_pric'], errors='coerce')
        df['low'] = pd.to_numeric(df['low_pric'], errors='coerce')
        df['close'] = pd.to_numeric(df['cur_prc'], errors='coerce')
        df = df.fillna(0)
        
        C = df['close']
        O = df['open']
        H = df['high']
        L = df['low']
        
        # Strategy Logic: [02_전고음봉시가돌파(일봉)]
        BBU = TI.bbands(C, 20, 2)[0]
        ema20 = C.ewm(span=20, adjust=False).mean()
        atr20 = TI.atr(H, L, C, 20)
        CCU = ema20 + (atr20 * 2)
        
        # A1/A2: Recent strength (last 3 days)
        A1 = (C.shift(2)>BBU.shift(2)) | (C.shift(1)>BBU.shift(1)) | (C>BBU)
        A2 = (C.shift(2)>CCU.shift(2)) | (C.shift(1)>CCU.shift(1)) | (C>CCU)
        
        # A3/A4/A5: Adjustment pattern (2 greens + 1 blue)
        A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
        A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
        A5 = (O > C)
        
        B = A1 & A3 & A4 & A5
        TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
        
        # Breakout check for Today
        if len(C) < 2: return None
        is_breakout = (C.shift(1) <= TargetLine.shift(1)) & (C > TargetLine)
        
        if is_breakout.iloc[-1]:
            return {
                "tl": TargetLine.iloc[-1],
                "close": C.iloc[-1],
                "ratio": ((C.iloc[-1] / TargetLine.iloc[-1]) - 1) * 100
            }
    except Exception as e:
        return None
    return None

def run_total_scan():
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)
    
    today_stocks = history.get("2026-04-10", {})
    codes = list(today_stocks.keys())
    
    # Add Amotech manually as it might have been missed in history but user noted it
    if "052710" not in codes: codes.append("052710")
    
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    results = []
    print(f"Scanning {len(codes)} stocks for breakout signal...")
    
    for code in codes:
        res = analyze_raw(code, host_url, token)
        if res:
            name = today_stocks.get(code, {}).get('name', 'Unknown')
            # Fix if Amotech was manually added
            if code == "052710": name = "아모텍"
            
            results.append({
                "code": code,
                "name": name,
                "tl": res['tl'],
                "close": res['close'],
                "ratio": res['ratio']
            })
    
    results.sort(key=lambda x: x['ratio'], reverse=True)
    print("\n[전략 포착 종목 리스트 - 4/10]")
    print("-" * 70)
    for r in results:
        print(f"[{r['code']}] {r['name']:<15} | TL: {r['tl']:>8,.0f} | 종가: {r['close']:>8,.0f} | 돌파률: {r['ratio']:>6.2f}%")
    print("=" * 70)

if __name__ == "__main__":
    run_total_scan()
