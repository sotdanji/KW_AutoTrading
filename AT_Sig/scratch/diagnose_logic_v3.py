import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

# 프로젝트 경로 설정
scratch_dir = os.path.dirname(os.path.abspath(__file__))
at_sig_dir = os.path.dirname(scratch_dir)
project_root = os.path.dirname(at_sig_dir)

if at_sig_dir not in sys.path: sys.path.insert(0, at_sig_dir)
if project_root not in sys.path: sys.path.insert(0, project_root)

from data_manager import DataManager
from login import fn_au10001 as get_token
from shared.indicators import TechnicalIndicators as TI

def run_report(code, name):
    print(f"--- [DIAGNOSTIC REPORT] {name} ({code}) ---")
    try:
        token = get_token()
        dm = DataManager()
        chart_data = dm.get_daily_chart(code, token, use_cache=False)
        if not chart_data:
            print("Fail to get data")
            return
        df = TI.preprocess_data(chart_data)
        BBU1, _, _ = TI.bbands(df['close'], 20, 2)
        BBU2, _, _ = TI.bbands(df['close'], 60, 2)
        C, O, H, L = df['close'], df['open'], df['high'], df['low']
        A1 = (C.shift(2) > BBU1.shift(2)) | (C.shift(1) > BBU1.shift(1)) | (C > BBU1)
        A2 = (C.shift(2) > BBU2.shift(2)) | (C.shift(1) > BBU2.shift(1)) | (C > BBU2)
        A3 = (O.shift(2) < C.shift(2)) | (C.shift(3) < C.shift(2))
        A4 = (O.shift(1) <= C.shift(1)) | (C.shift(2) < C.shift(1))
        A5 = (O > C)
        B = A1 & A2 & A3 & A4 & A5
        TargetLine = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
        cond = (C.shift(1) <= TargetLine.shift(1)) & (C > TargetLine)

        print(f"Total days: {len(df)}")
        b_history = df[B].copy()
        if not b_history.empty:
            print("History of B (Signal Bar):")
            for idx, row in b_history.tail(5).iterrows():
                print(f"  Date: {idx}, Open: {row['open']}, Target: {TargetLine[idx]}")
        else:
            print("No Signal Bar (B) found in history.")

        last_idx = df.index[-1]
        print(f"Latest (Today): {last_idx}")
        print(f"  Current: {C.iloc[-1]}, Target: {TargetLine.iloc[-1]}")
        print(f"  Prev Close: {C.shift(1).iloc[-1]}, Prev Target: {TargetLine.shift(1).iloc[-1]}")
        print(f"  Breakout result: {cond.iloc[-1]}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_report("032640", "LG_Uplus")
    run_report("432720", "Qualitas")
