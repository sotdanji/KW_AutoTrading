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

def analyze_bbd_expansion(code, host_url, token):
    try:
        data = fetch_daily_chart(host_url, code, token, days=120)
        if not data or len(data) < 60: return None
        
        df = pd.DataFrame(data)
        df['open'] = pd.to_numeric(df['open_pric'], errors='coerce')
        df['high'] = pd.to_numeric(df['high_pric'], errors='coerce')
        df['low'] = pd.to_numeric(df['low_pric'], errors='coerce')
        df['close'] = pd.to_numeric(df['cur_prc'], errors='coerce')
        
        C = df['close']
        H = df['high']
        
        # Strategy Logic: [03_BBD첫확장]
        BD1 = TI.bbands(C, 20, 2)[2]
        BU2 = TI.bbands(C, 60, 2)[0]
        BD2 = TI.bbands(C, 60, 2)[2]
        
        # Current conditions
        curr_h = H.iloc[-1]
        curr_bu2 = BU2.iloc[-1]
        
        # Shifted values
        bd1_0 = BD1.iloc[-1]
        bd1_1 = BD1.iloc[-2]
        bd1_2 = BD1.iloc[-3]
        
        bd2_0 = BD2.iloc[-1]
        bd2_1 = BD2.iloc[-2]
        bd2_2 = BD2.iloc[-3]
        
        # Expansion Logic: Mouth opening (Upper goes up, Lower goes down)
        expansion_cond = (curr_h > curr_bu2) & \
                         (bd1_2 <= bd1_1) & (bd1_1 > bd1_0) & \
                         (bd2_2 <= bd2_1) & (bd2_1 > bd2_0)
        
        if expansion_cond:
            return {
                "close": C.iloc[-1],
                "bu2": curr_bu2,
                "msg": "BBD Expansion Burst"
            }
    except:
        return None
    return None

def run_bbd_scan():
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)
    
    today_codes = list(history.get("2026-04-10", {}).keys())
    if "052710" not in today_codes: today_codes.append("052710")
    if "050890" not in today_codes: today_codes.append("050890")
    
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    results = []
    print(f"Scanning {len(today_codes)} stocks for BBD Expansion...")
    
    for code in today_codes:
        # Get Real Name
        params = {'stk_cd': code}
        name = "Unknown"
        try:
            resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
            if resp: name = resp.json().get('stk_nm', 'Unknown')
        except: pass
        
        res = analyze_bbd_expansion(code, host_url, token)
        if res:
            # Filter Price >= 5000
            if res['close'] >= 5000:
                results.append({
                    "code": code,
                    "name": name,
                    "close": res['close'],
                    "bu2": res['bu2']
                })
        time.sleep(0.05)
    
    print("\n[BBD첫확장 전략 포착 종목 - 4/10]")
    print("-" * 70)
    for r in results:
        print(f"[{r['code']}] {r['name']:<15} | 종가: {r['close']:>8,.0f} | 60일상단(BU2): {r['bu2']:>8,.0f} | 결과: 상승 확장 중")
    print("=" * 70)

if __name__ == "__main__":
    run_bbd_scan()
