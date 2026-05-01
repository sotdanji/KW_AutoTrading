import json
import os
import pandas as pd
import numpy as np
import sys
import time
from datetime import datetime

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from shared.api import fetch_minute_chart_ka10080, fetch_daily_chart, fetch_data
from AT_Sig.login import fn_au10001 as get_token
from config import get_current_config
from shared.indicators import TechnicalIndicators as TI

def check_stock_minute_strategy(code, host_url, token):
    try:
        # 1. Get Daily Data for GapUp Check
        d_data = fetch_daily_chart(host_url, code, token, days=2)
        if not d_data or len(d_data) < 2: return None
        prev_close = float(d_data[0]['cur_prc'])
        day_open = float(d_data[1]['open_pric'])
        
        if day_open < prev_close: return None # No Gap Up
        
        # 2. Get Minute Data for Today (4/10)
        m_data = fetch_minute_chart_ka10080(host_url, code, token, min_tp='1')
        if not m_data: return None
        
        # Filter Today's data
        today_str = datetime.now().strftime('%Y%m%d')
        df = pd.DataFrame([d for d in m_data if d['stck_bsop_date'] == today_str])
        if df.empty: return None
        
        # Sort by time ascend
        df = df.sort_values('stck_cntg_hour').reset_index(drop=True)
        df['close'] = pd.to_numeric(df['stck_prpr'])
        df['time'] = df['stck_cntg_hour']
        
        # 3. Check 10m/30m Negative Condition
        neg_10 = False
        neg_30 = False
        
        # Get Price at exactly 09:10 and 09:30
        p_10 = df[df['time'] == '091000']
        p_30 = df[df['time'] == '093000']
        
        if not p_10.empty and day_open > p_10.iloc[0]['close']:
            neg_10 = True
        if not p_30.empty and day_open > p_30.iloc[0]['close']:
            neg_30 = True
            
        if not neg_10 and not neg_30: return None
        
        # 4. Check for Breakout AFTER 09:10/09:30
        if neg_10:
            after_10 = df[df['time'] > '091000']
            for idx, row in after_10.iterrows():
                # CrossUp Check (Simple version: Current > Open and Prev <= Open)
                # Need prev row
                prev_row = df.iloc[idx-1]
                if prev_row['close'] <= day_open and row['close'] > day_open:
                    return {"type": "10m_Recov", "time": row['time'], "price": row['close']}
        
        if neg_30:
            after_30 = df[df['time'] > '093000']
            for idx, row in after_30.iterrows():
                prev_row = df.iloc[idx-1]
                if prev_row['close'] <= day_open and row['close'] > day_open:
                    return {"type": "30m_Recov", "time": row['time'], "price": row['close']}
                    
    except Exception as e:
        return None
    return None

def run_minute_scan_fixed():
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    # Load today's captured history
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)
    today_codes = list(history.get("2026-04-10", {}).keys())
    
    # Add top performers if missing (Simulated case)
    extra = ['052710', '033640', '039560', '011930', '008060', '023160', '001820', '050890', '049080', '095610']
    for e in extra:
        if e not in today_codes: today_codes.append(e)
    
    results = []
    print(f"Scanning {len(today_codes)} stocks with FIXED [01_분봉음봉시가돌파] logic...")
    
    for code in today_codes:
        res = check_stock_minute_strategy(code, host_url, token)
        if res:
            # Get Name
            params = {'stk_cd': code}
            name = "Unknown"
            try:
                resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
                name = resp.json().get('stk_nm', 'Unknown')
            except: pass
            
            results.append({"code": code, "name": name, "res": res})
        time.sleep(0.05)
        
    print("\n[수정된 01_분봉음봉시가돌파 전략 포착 결과 - 4/10]")
    print("-" * 75)
    if not results:
        print("포착된 종목이 없습니다 (모든 조건 충족 종목 없음).")
    for r in results:
        t = r['res']
        print(f"[{r['code']}] {r['name']:<15} | 유형: {t['type']} | 시간: {t['time']} | 가격: {t['price']:>8,.0f}")
    print("=" * 75)

if __name__ == "__main__":
    run_minute_scan_fixed()
