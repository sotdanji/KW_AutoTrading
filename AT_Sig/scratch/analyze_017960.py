import asyncio
import os
import sys
import json
from datetime import datetime

# [CRITICAL] 프로젝트 루트 강제 등록 (임포트 오류 방지)
project_root = r"D:\AG\KW_AutoTrading"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# AT_Sig 폴더도 등록
at_sig_dir = os.path.join(project_root, "AT_Sig")
if at_sig_dir not in sys.path:
    sys.path.insert(0, at_sig_dir)

from login import fn_au10001 as get_token
from data_manager import DataManager
from stock_info import get_stock_info_async
from strategy_runner import StrategyRunner

async def analyze_stock(code):
    token = get_token()
    dm = DataManager()
    sr = StrategyRunner()
    
    print(f"--- Analysis for {code} ---")
    
    # 1. Daily Chart
    chart = dm.get_daily_chart(code, token=token)
    if not chart:
        print("Failed to get daily chart.")
        return
    
    print(f"Recent Daily Data (last 3):")
    for day in chart[-3:]:
        print(day)
    
    # 2. Strategy Check
    st_file = "02_전고음봉시가돌파(일봉).json"
    st_path = os.path.join(project_root, 'shared', 'strategies', st_file)
    
    if not os.path.exists(st_path):
        print(f"Strategy file not found: {st_path}")
        return
        
    with open(st_path, 'r', encoding='utf-8') as f:
        st_data = json.load(f)
        py_code = st_data.get('python_code', '')
    
    # 3. Current Info
    info, _ = await get_stock_info_async(code, token)
    current_price = float(info.get('stk_prc', 0))
    print(f"Current Price: {current_price}")
    
    # 4. Simulate Signal
    res = sr.check_signal(code, token, py_code, current_price, min_bars=70)
    print(f"Signal Result: {res}")

if __name__ == "__main__":
    import json
    asyncio.run(analyze_stock('017960'))
