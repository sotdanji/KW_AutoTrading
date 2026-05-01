import json
import os
import pandas as pd
import numpy as np
import sys
import time

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from shared.api import fetch_daily_chart, fetch_data
from AT_Sig.login import fn_au10001 as get_token
from config import get_current_config
from shared.indicators import TechnicalIndicators as TI

def get_real_name(host_url, code, token):
    # ka10001: 주식기본정보요청
    params = {'stk_cd': code}
    try:
        resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
        if resp:
            data = resp.json()
            # The API returns flattened dict
            return data.get('stk_nm') or data.get('hts_kor_isnm') or "Unknown"
    except:
        pass
    return "Unknown"

def analyze_raw(code, host_url, token):
    try:
        data = fetch_daily_chart(host_url, code, token, days=60)
        if not data or len(data) < 20: return None
        
        df = pd.DataFrame(data)
        df['open'] = pd.to_numeric(df['open_pric'], errors='coerce')
        df['high'] = pd.to_numeric(df['high_pric'], errors='coerce')
        df['low'] = pd.to_numeric(df['low_pric'], errors='coerce')
        df['close'] = pd.to_numeric(df['cur_prc'], errors='coerce')
        
        C = df['close']
        O = df['open']
        H = df['high']
        L = df['low']
        
        BBU = TI.bbands(C, 20, 2)[0]
        ema20 = C.ewm(span=20, adjust=False).mean()
        atr20 = TI.atr(H, L, C, 20)
        CCU = ema20 + (atr20 * 2)
        
        A1 = (C.shift(2)>BBU.shift(2)) | (C.shift(1)>BBU.shift(1)) | (C>BBU)
        A2 = (C.shift(2)>CCU.shift(2)) | (C.shift(1)>CCU.shift(1)) | (C>CCU)
        A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
        A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
        A5 = (O > C)
        
        B = A1 & A3 & A4 & A5
        TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
        
        is_breakout = (C.shift(1) <= TargetLine.shift(1)) & (C > TargetLine)
        
        if is_breakout.iloc[-1]:
            return {
                "tl": TargetLine.iloc[-1],
                "close": C.iloc[-1],
                "ratio": ((C.iloc[-1] / TargetLine.iloc[-1]) - 1) * 100
            }
    except:
        return None
    return None

def rebuild_and_report():
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)
    
    today_codes = list(history.get("2026-04-10", {}).keys())
    if "052710" not in today_codes: today_codes.append("052710")
    
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    final_results = []
    print(f"Rebuilding mapping and analyzing {len(today_codes)} stocks...")
    
    for code in today_codes:
        # 1. Fetch REAL name from API
        real_name = get_real_name(host_url, code, token)
        
        # 2. Analyze
        res = analyze_raw(code, host_url, token)
        if res:
            final_results.append({
                "code": code,
                "name": real_name,
                "tl": res['tl'],
                "close": res['close'],
                "ratio": res['ratio']
            })
        # Throttling to avoid API rate limit
        time.sleep(0.05)
    
    final_results.sort(key=lambda x: x['ratio'], reverse=True)
    
    # Save to a report file to avoid terminal encoding issues
    report_path = os.path.join(project_root, "AT_Sig", "scratch", "rebuilt_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=4, ensure_ascii=False)
    
    print(f"Report saved to {report_path}")

if __name__ == "__main__":
    rebuild_and_report()
