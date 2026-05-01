
import os
import sys

print(f"DEBUG: __file__ = {__file__}")
print(f"DEBUG: abspath = {os.path.abspath(__file__)}")
script_dir = os.path.dirname(os.path.abspath(__file__))
print(f"DEBUG: script_dir = {script_dir}")
p1 = os.path.dirname(script_dir)
print(f"DEBUG: parent1 = {p1}")
p2 = os.path.dirname(p1)
print(f"DEBUG: parent2 = {p2}")

sys.path.append(p2)
print(f"DEBUG: sys.path = {sys.path}")

try:
    from shared.api import fetch_daily_chart
    print("SUCCESS: Import shared.api")
except Exception as e:
    print(f"FAIL: {e}")
