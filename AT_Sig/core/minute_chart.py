import requests
import json
import time
import datetime
import sys
import os

# Add parent directory to path to import config module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from config import get_current_config
except ImportError as e:
    print(f"[ERROR] minute_chart config import failed: {e}")

def get_minute_chart(stk_cd, token, tick='1', next_key=''):
    try:
        conf = get_current_config()
        host_url = conf['host_url']
    except Exception as e:
        print(f"[ERROR] Config Load Failed: {e}")
        return [], ''

    url = f"{host_url}/api/dostk/chart"
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10080',
        'cont-yn': 'N' if not next_key else 'Y',
        'next-key': next_key
    }
    
    params = {
        'stk_cd': stk_cd,
        'tic_scope': tick, # 1:1min, 3:3min, etc.
        'upd_stkpc_tp': '1', # Adjusted Price
        'date_est_yn': 'Y'   # Check Date estimation
    }
    
    try:
        response = requests.post(url, headers=headers, json=params, timeout=5)
        
        if response.status_code != 200:
            print(f"[ERROR] Minute chart failed: {response.status_code} {response.text}")
            return [], ''
            
        data = response.json()
        
        # Check keys
        chart_data = data.get('stk_min_pole_chart_qry', [])
        # Also check output block if different
        if not chart_data:
            chart_data = data.get('output', [])
             
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
