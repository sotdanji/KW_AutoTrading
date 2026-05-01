import asyncio
import json
import os
import sys

# Add project root to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "AT_Sig"))

from stock_info import get_stock_info_async
from login import fn_au10001 as get_token

async def check_truth():
    token = get_token()
    codes = ["039560", "033640", "064260", "005460", "052710"]
    print(f"Checking names for {codes} from API...")
    
    for code in codes:
        info, status = await get_stock_info_async(code, token)
        if info:
            name = info.get('stk_nm') or info.get('hts_kor_isnm') or "Unknown"
            print(f"[{code}] -> {name} (Status: {status})")
        else:
            print(f"[{code}] -> Info not found (Status: {status})")

if __name__ == "__main__":
    asyncio.run(check_truth())
