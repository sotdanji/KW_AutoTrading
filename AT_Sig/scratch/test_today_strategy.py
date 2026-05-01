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

# Standard imports for execution context
from shared.execution_context import get_execution_context
from AT_Sig.data_manager import DataManager

def get_df_mapped(code, dm):
    # Try to get from cache first (no token needed if cached)
    data = dm.get_daily_chart(code, "dummy_token", use_cache=True)
    if not data:
        return None
        
    df = pd.DataFrame(data)
    
    # Mapping for various Kiwoom API versions
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
    
    # Add date column for execution_context
    if 'dt' in df.columns: df['date'] = df['dt']
    elif 'base_dt' in df.columns: df['date'] = df['base_dt']
    else: df['date'] = "20260410"
            
    cols = ['open', 'high', 'low', 'close', 'volume', 'date']
    # Check if we have at least OHLC
    if all(c in df.columns for c in ['open', 'high', 'low', 'close']):
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df[cols].fillna(0)
    return None

def test_today_signals():
    # 1. Load captured stocks for today
    history_path = os.path.join(project_root, "AT_Sig", "captured_history.json")
    if not os.path.exists(history_path):
        print("History file not found.")
        return

    with open(history_path, "r", encoding="utf-8") as f:
        full_history = json.load(f)

    # Use actual date or fallback to yesterday if needed
    today_str = "2026-04-10"
    if today_str not in full_history:
        # Try latest key
        sorted_keys = sorted(full_history.keys(), reverse=True)
        if not sorted_keys:
            print("No history keys found.")
            return
        today_str = sorted_keys[0]
        print(f"Using {today_str} as the most recent captured date.")

    today_stocks = full_history[today_str]
    unique_codes = list(today_stocks.keys())
    print(f"Total {len(unique_codes)} stocks captured on {today_str}. Analyzing...")

    # 2. Setup strategy logic (전고음봉시가돌파)
    # TargetLine: A3 조건(2양봉+1음봉) 발생 시점의 시가(Open)
    # Signal: 현재가가 TargetLine 상향 돌파
    strategy_code = """
BBU = BBU(20, 2)
CCU = ema(C, 20) + (atr(20) * 2)

A1 = sum(C > BBU, 20) > 0
A2 = sum(C > CCU, 20) > 0
A3 = (O.shift(2) < C.shift(2)) & (O.shift(1) <= C.shift(1)) & (O > C)

B = (A1 | A2) & A3
TargetLine = ValueWhen(1, B, O)

cond = CrossUp(C, TargetLine)
"""

    dm = DataManager()
    results = []

    success_count = 0
    for code in unique_codes:
        name = today_stocks[code].get('name', 'Unknown')
        
        df = get_df_mapped(code, dm)
        if df is None or len(df) < 50:
            continue
            
        success_count += 1
        try:
            # Get execution context
            exec_ctx = get_execution_context(df)
            
            # Execute strategy code
            exec(strategy_code, {}, exec_ctx)
            
            # [Debug Amotech]
            if code == "052710":
                tl = exec_ctx.get('TargetLine').iloc[-1]
                yesterday_c = df['close'].iloc[-2]
                today_c = df['close'].iloc[-1]
                print(f"DEBUG [Amotech] TL: {tl}, Yest: {yesterday_c}, Today: {today_c}")

            # Check last row of 'cond'
            sig_series = exec_ctx.get('cond')
            if sig_series is not None and not sig_series.empty:
                # We check the VERY LAST BAR (today)
                if sig_series.iloc[-1]:
                    target = exec_ctx.get('TargetLine').iloc[-1]
                    price = df['close'].iloc[-1]
                    results.append({
                        "code": code,
                        "name": name,
                        "target": target,
                        "price": price
                    })
        except Exception as e:
            # print(f"Error checking {name}({code}): {e}")
            pass

    print("\n" + "="*70)
    print(f"검색 대상: {today_str} 포착 종목 | 분석 성공: {success_count}/{len(unique_codes)}")
    print(f"전략명: 전고음봉시가돌파(20)")
    print("-" * 70)
    
    # Analyze matches for the last 5 days
    lookback_results = {i: [] for i in range(5)}
    for code in unique_codes:
        df = get_df_mapped(code, dm)
        if df is None or len(df) < 55: continue
        exec_ctx = get_execution_context(df)
        try:
            exec(strategy_code, {}, exec_ctx)
            cond = exec_ctx.get('cond')
            if cond is not None:
                for i in range(5):
                    idx = -(i+1)
                    if cond.iloc[idx]:
                        name = today_stocks[code].get('name', 'Unknown')
                        lookback_results[i].append(f"{name}({code})")
        except: pass

    for i in range(5):
        date_offset = f"T-{i}" if i > 0 else "Today"
        matches = lookback_results[i]
        print(f"[{date_offset}] 포착 종목: {', '.join(matches) if matches else '없음'}")
    print("="*70)

if __name__ == "__main__":
    test_today_signals()
