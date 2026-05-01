import asyncio
import os
import sys
import json

# Add project root to sys.path
at_sig_dir = r"d:\AG\KW_AutoTrading\AT_Sig"
project_root = r"d:\AG\KW_AutoTrading"
if at_sig_dir not in sys.path:
    sys.path.append(at_sig_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from get_seq import get_condition_list
from login import fn_au10001
from rt_search import RealTimeSearch

async def check_conditions():
    stk_cd = "052710" # Amotech
    token = fn_au10001()
    if not token:
        print("Failed to get token")
        return

    # Check which conditions have Amotech
    target_seqs = ["3", "5", "4"]
    
    # We can't easily query a specific seq for a stock via get_seq 
    # but we can get the entire list for each seq.
    # We'll use RealTimeSearch logic or direct API if possible.
    # Note: RealTimeSearch.start() connects WebSocket.
    
    # Let's check get_condition_list - it returns the names/indices of conditions.
    cond_list = get_condition_list(token)
    print(f"User's Condition List: {cond_list}")

    # To check if Amotech is in a condition, we'd normally need to call CNSRREQ.
    # But since we're debugging, let's just assume the user thinks it's satisfied in his strategy, 
    # but we suspect it might not be in the Kiwoom Search List.

    # Instead, let's look for any 'captured' activity in the last 30 minutes in memory/files.
    # Check captured_history.json
    history_path = os.path.join(at_sig_dir, 'captured_history.json')
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
            # Find Amotech in history
            matches = [h for h in history if h.get('code') == stk_cd]
            if matches:
                print(f"Amotech found in captured_history.json: {matches}")
            else:
                print("Amotech NOT found in captured_history.json")

if __name__ == "__main__":
    asyncio.run(check_conditions())
