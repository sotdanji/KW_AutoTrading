
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

# 프로젝트 경로 설정 (2단계 상위로 고정)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
if not project_root or project_root == "d:\\AG": # fallback
    project_root = "d:\\AG\\KW_AutoTrading"

sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "AT_Sig"))

from data_manager import DataManager
from login import fn_au10001 as get_token
from shared.indicators import TechnicalIndicators as TI

def diagnose_stock(stk_cd, stk_nm, token, dm):
    try:
        chart_data = dm.get_daily_chart(stk_cd, token, use_cache=True)
        if not chart_data or len(chart_data) < 70:
            return None

        # [안실장 픽스] 데이터 표준 정제 (open, high, low, close 확보)
        df = TI.preprocess_data(chart_data)
        
        # 1. BBands (Typical Price 기반)
        tp = (df['high'] + df['low'] + df['close']) / 3
        BBU1, _, _ = TI.bbands(tp, 20, 2)
        BBU2, _, _ = TI.bbands(tp, 60, 2)
        
        C, O, H, L = df['close'], df['open'], df['high'], df['low']
        
        # 2. Conditions A1 ~ A5
        A1 = (C.shift(2) > BBU1.shift(2)) | (C.shift(1) > BBU1.shift(1)) | (C > BBU1)
        A2 = (C.shift(2) > BBU2.shift(2)) | (C.shift(1) > BBU2.shift(1)) | (C > BBU2)
        
        A3 = (O.shift(2) < C.shift(2)) | (C.shift(3) < C.shift(2))
        A4 = (O.shift(1) <= C.shift(1)) | (C.shift(2) < C.shift(1))
        A5 = (O > C)
        
        B = A1 & A2 & A3 & A4 & A5
        
        # TargetLine = ValueWhen(1, B, O)
        TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
        
        if TargetLine.isna().all():
            return None

        # Final logic: today breakout
        cond = (C.shift(1) <= TargetLine.shift(1)) & (C > TargetLine)
        
        return {
            'code': stk_cd,
            'name': stk_nm,
            'target': TargetLine.iloc[-1],
            'close': C.iloc[-1],
            'result': cond.iloc[-1],
            'has_target': not np.isnan(TargetLine.iloc[-1])
        }
    except Exception as e:
        print(f"Error diagnosing {stk_cd}: {e}")
        return None

def main():
    token = get_token()
    if not token:
        print("Error: Could not obtain token.")
        return

    dm = DataManager()
    
    # captured_history.json 위치 고정
    history_file = os.path.join(project_root, "AT_Sig", "captured_history.json")
    import json
    with open(history_file, 'r', encoding='utf-8') as f:
        history = json.load(f)
    
    today = "2026-04-14"
    today_stocks = history.get(today, {})
    
    print(f"--- [오늘의 전략 진단 리포트] ({today}) ---")
    print(f"포착된 종목 총 {len(today_stocks)}개 분석 중...\n")
    
    results = []
    for code, info in today_stocks.items():
        res = diagnose_stock(code, info['name'], token, dm)
        if res:
            results.append(res)
            
    # 결과 출력 (성공 우선)
    results.sort(key=lambda x: x['result'], reverse=True)
    
    for r in results:
        status = "[BUY_OK]" if r['result'] else "[WAITING]"
        print(f" {status} {r['name']:12}({r['code']}) | Target: {r['target']:8.0f} | Current: {r['close']:8.0f}")

    valid_buys = [r for r in results if r['result']]
    print("\n--- [Final Buy Signals] ---")
    if not valid_buys:
        print("No stocks met the breakout condition today.")
    else:
        for r in valid_buys:
            print(f"MATCH: {r['name']} ({r['code']}) - Breakout Success!")

if __name__ == "__main__":
    main()
