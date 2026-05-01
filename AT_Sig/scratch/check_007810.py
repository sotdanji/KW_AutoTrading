
import os
import sys
import json

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "AT_Sig"))

from login import fn_au10001
from shared.api import fetch_daily_chart
from config import get_current_config

def main():
    token = fn_au10001()
    conf = get_current_config()
    code = "007810" # Korea Circuit
    data = fetch_daily_chart(conf['host_url'], code, token)
    if data:
        print(f"Data for {code}:")
        print(data[-1])
    else:
        print("No data")

if __name__ == "__main__":
    main()
