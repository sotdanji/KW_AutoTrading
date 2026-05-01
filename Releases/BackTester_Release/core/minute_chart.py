import requests
import json
import time
import datetime
import pandas as pd
from .config import get_api_config

def get_minute_chart(stk_cd, token, tick='1', next_key=''):
    """
    Fetches minute chart from Kiwoom API.
    API: ka10086 (분봉조회) or similar structure.
    Using: /api/dostk/chart (likely same endpoint with different params)
    Actually, Kiwoom REST API for minute chart is usually:
    - URL: /api/dostk/chart
    - Param: 'tick_unit': '1' (1 minute)
    """
    conf = get_api_config()
    host_url = conf['host_url']
    url = f"{host_url}/api/dostk/chart"
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10080', # Minute Chart
        'cont-yn': 'N' if not next_key else 'Y',
        'next-key': next_key
    }
    
    # Current Time for base_dt
    now_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    
    params = {
        'stk_cd': stk_cd,
        'tic_scope': tick, # 1:1min, 3:3min, etc.
        'upd_stkpc_tp': '1'
    }
    
    try:
        response = requests.post(url, headers=headers, json=params, timeout=10)
        
        if response.status_code != 200:
            print(f"[ERROR] Minute chart faled: {response.status_code} {response.text}")
            return [], ''
            
        data = response.json()
        
        # Check keys
        chart_data = data.get('stk_min_pole_chart_qry', [])
             
        next_key = response.headers.get('next-key', '')
        
        return chart_data, next_key
        
    except Exception as e:
        print(f"[ERROR] Minute chart exception: {e}")
        return [], ''

def get_minute_chart_continuous(stk_cd, token, tick='1', max_pages=5):
    all_data = []
    next_key = ''
    
    for i in range(max_pages):
        data, key = get_minute_chart(stk_cd, token, tick, next_key)
        if not data:
            break
            
        all_data.extend(data)
        next_key = key
        
        if not next_key:
            break
            
        time.sleep(0.2) # Rate limit safety
        
    return all_data
