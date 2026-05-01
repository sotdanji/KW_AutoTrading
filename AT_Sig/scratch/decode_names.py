import json
import os

codes = ["023160", "039490", "095910", "039560", "033640", "138930", "038500", "073490", "036010", "054210", "052420", "099220", "005880", "004140", "031820", "122990"]

path = r"d:\AG\KW_AutoTrading\AT_Sig\captured_history.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

today = "2026-04-10"
stocks = data[today]

print("Today (4/10) Match Stocks:")
for c in codes:
    if c in stocks:
        print(f"[{c}] {stocks[c].get('name')}")
