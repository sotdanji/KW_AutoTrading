import requests
import json
import os
import sys

# Set paths
project_root = r"d:\AG\KW_AutoTrading"
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from login import fn_au10001
from config import get_current_config

def test_encodings():
    conf = get_current_config()
    token = fn_au10001()
    url = conf['host_url'] + '/api/dostk/stkinfo'
    headers = {'authorization': 'Bearer ' + token, 'api-id': 'ka10001'}
    params = {'stk_cd': '078070'}
    
    resp = requests.post(url, headers=headers, json=params)
    raw = resp.content
    
    print(f"Raw Bytes: {raw[:100]}")
    
    encodings = ['utf-8', 'cp949', 'euc-kr', 'latin-1']
    for enc in encodings:
        try:
            text = raw.decode(enc)
            data = json.loads(text)
            name = data.get('stk_nm', 'N/A')
            print(f"[{enc}]: {name}")
        except Exception as e:
            print(f"[{enc}]: Failed - {e}")

if __name__ == "__main__":
    test_encodings()
