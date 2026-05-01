import json
import os

path = r"d:\AG\KW_AutoTrading\AT_Sig\captured_history.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

today = "2026-04-10"
if today in data:
    stocks = data[today]
    if "052710" in stocks:
        print(f"Amotech found in today's history: {stocks['052710']}")
    else:
        print("Amotech NOT found in today's history.")
        # List first 5 for context
        print("First 5 stocks:", list(stocks.keys())[:5])
else:
    print(f"Date {today} not in history.")
