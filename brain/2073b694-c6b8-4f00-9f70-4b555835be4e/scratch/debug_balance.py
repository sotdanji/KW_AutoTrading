import requests
import sys
import os
import json

sys.path.append(r'd:\AG\KW_AutoTrading')
sys.path.append(r'd:\AG\KW_AutoTrading\AT_Sig')

from login import fn_au10001 as get_token
from config import get_current_config

def debug_balance():
    print("--- Start Balance Debug ---")
    conf = get_current_config()
    host_url = conf['host_url']
    print(f"ENV: {host_url}")
    
    token = get_token()
    if not token:
        print("Error: No Token")
        return

    endpoint = '/api/dostk/acnt'
    url = host_url + endpoint
    params = {'qry_tp': '3'}
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'kt00001',
    }
    
    try:
        print(f"Requesting: {url}")
        response = requests.post(url, headers=headers, json=params)
        print(f"Status Code: {response.status_code}")
        
        res_json = response.json()
        print("RAW Data:")
        print(json.dumps(res_json, indent=4, ensure_ascii=False))
        
        output = res_json.get('output', {})
        if isinstance(output, list) and len(output) > 0:
            output = output[0]
            
        checks = ['100stk_ord_alow_amt', 'd2_entra', 'n_pchs_possible_amt', 'd_2_settle_ext_amt', 'dnca_tot_amt', 'entr']
        print("\nValues:")
        for c in checks:
            val = res_json.get(c) or (output.get(c) if isinstance(output, dict) else 'N/A')
            print(f"- {c}: {val}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_balance()
