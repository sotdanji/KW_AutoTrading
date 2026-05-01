import json
import os
import time
import sys

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from shared.api import fetch_data
from AT_Sig.login import fn_au10001 as get_token
from config import get_current_config

def sync_all_stock_names():
    conf = get_current_config()
    token = get_token()
    host_url = conf['host_url']
    
    master_file = os.path.join(project_root, "stock_master.json")
    
    # Load existing to merge (or start fresh)
    if os.path.exists(master_file):
        with open(master_file, 'r', encoding='utf-8') as f:
            full_map = json.load(f)
    else:
        full_map = {}
        
    markets = [('0', 'KOSPI'), ('10', 'KOSDAQ')]
    count_new = 0
    
    print("Starting Comprehensive Stock Master Sync...")
    
    for m_code, m_name in markets:
        print(f"Fetching {m_name} stocks...")
        cont_yn = 'N'
        next_key = ''
        
        while True:
            params = {'mrkt_tp': m_code}
            resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10099', params, token, cont_yn, next_key)
            if not resp: break
            
            data = resp.json()
            # The list key in NXT ka10099 is 'output'
            items = data.get('output', [])
            if not items: break
            
            for s in items:
                code = s.get('code')
                name = s.get('name')
                if code and name:
                    if full_map.get(code) != name:
                        full_map[code] = name
                        count_new += 1
            
            # Check pagination
            cont_yn = resp.headers.get('cont-yn', 'N')
            next_key = resp.headers.get('next-key', '')
            
            if cont_yn != 'Y' or not next_key:
                break
                
            print(f"  - Progressing... (Current count in master: {len(full_map)})")
            time.sleep(0.3)
            
    # Final check for specific codes known to be missing
    target_check = ['078070']
    for tc in target_check:
        if tc not in full_map:
            print(f"Manual fallback for {tc}...")
            # Use ka10001 for specific fallback
            params = {'stk_cd': tc}
            resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
            if resp:
                name = resp.json().get('stk_nm')
                if name:
                    full_map[tc] = name
                    count_new += 1

    # Save
    with open(master_file, 'w', encoding='utf-8') as f:
        # Sort by key for consistency
        sorted_map = dict(sorted(full_map.items()))
        json.dump(sorted_map, f, ensure_ascii=False, indent=2)
        
    print(f"\n[Master Sync Complete]")
    print(f"- Total Stocks in Master: {len(sorted_map)}")
    print(f"- Updated/New Entries: {count_new}")
    print(f"- 078070 Name: {sorted_map.get('078070', 'N/A')}")

if __name__ == "__main__":
    sync_all_stock_names()
