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
from shared.execution_context import get_execution_context

def analyze_minute_strategy(code, host_url, token, strategy_code):
    try:
        # 1. Get PreDayClose from Daily Chart
        d_data = fetch_daily_chart(host_url, code, token, days=2)
        if not d_data or len(d_data) < 2: return None
        preday_close = float(d_data[0].get('cur_prc', 0))
        day_open = float(d_data[-1].get('open_pric', 0))
        
        # 2. Get Minute Chart (Today)
        m_data = fetch_minute_chart_ka10080(host_url, code, token, min_tp='1')
        if not m_data: return None
        
        df = pd.DataFrame(m_data)
        # Standardize columns
        df['open'] = pd.to_numeric(df['stck_oprc'], errors='coerce')
        df['high'] = pd.to_numeric(df['stck_hgpr'], errors='coerce')
        df['low'] = pd.to_numeric(df['stck_lwpr'], errors='coerce')
        df['close'] = pd.to_numeric(df['stck_prpr'], errors='coerce')
        df['volume'] = pd.to_numeric(df['cntg_vol'], errors='coerce')
        df['time'] = df['stck_bsop_date'] # Time string HHMMSS
        df['date'] = datetime.now().strftime('%Y%m%d')
        
        # 3. Evaluate Strategy
        ctx = get_execution_context(df, day_open_override=day_open, preday_close_override=preday_close)
        local_vars = {}
        exec(strategy_code, ctx, local_vars)
        
        cond = local_vars.get('cond')
        if cond is not None and any(cond):
            # Find the first index where signal occurred
            hit_idx = np.where(cond)[0][0]
            hit_time = df.iloc[hit_idx]['time']
            return {
                "hit": True,
                "time": hit_time,
                "price": df.iloc[hit_idx]['close']
            }
    except Exception as e:
        print(f"Error {code}: {e}")
        return None
    return None

def run_minute_scan():
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    # Target codes from today's performers
    codes = ['052710', '033640', '039560', '011930', '008060', '023160', '001820', '050890', '049080', '095610']
    
    strategy_code = """
IsGapUp = (df['open'] >= PreDayClose())
Mark10 = ((time >= 91000)) & ((time.shift(1) < 91000))
Mark30 = ((time >= 93000)) & ((time.shift(1) < 93000))
Is10MinNeg = (pd.Series(np.where(Mark10, DayOpen() > df['close'], np.nan), index=df.index).ffill())
Is30MinNeg = (pd.Series(np.where(Mark30, DayOpen() > df['close'], np.nan), index=df.index).ffill())
Cond10 = IsGapUp & Is10MinNeg & ((time >= 91000)) & (((df['close'].shift(1) <= DayOpen()) & (df['close'] > DayOpen())))
Cond30 = IsGapUp & Is30MinNeg & ((time >= 93000)) & (((df['close'].shift(1) <= DayOpen()) & (df['close'] > DayOpen())))
cond = Cond10 | Cond30
"""
    
    results = []
    print("Analyzing minute charts for [01_분봉음봉시가돌파(10,30)]...")
    
    for code in codes:
        # Get Name
        params = {'stk_cd': code}
        name = "Unknown"
        try:
            resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
            if resp: name = resp.json().get('stk_nm', 'Unknown')
        except: pass
        
        res = analyze_minute_strategy(code, host_url, token, strategy_code)
        if res and res['hit']:
            results.append({
                "code": code,
                "name": name,
                "time": res['time'],
                "price": res['price']
            })
        time.sleep(0.1)
    
    print("\n[01_분봉음봉시가돌파(10,30) 전략 포착 종목 - 4/10]")
    print("-" * 75)
    if not results:
        print("포착된 종목이 없습니다.")
    for r in results:
        print(f"[{r['code']}] {r['name']:<15} | 포착시간: {r['time']} | 가격: {r['price']:>8,.0f} | 결과: 시가 돌파 완료")
    print("=" * 75)

if __name__ == "__main__":
    run_minute_scan()
