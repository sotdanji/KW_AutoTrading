import os
import sys
import json
import requests

# [Simple Data Fetch]
app_key = "yvXD2wI7ujIWV5o-9Altz1gVc-TWV_pTdUjNt71Oppw"
app_secret = "xra9zLJMYbO2GzDuuRQzz-XsCdGQyaW_02fPdmqxsYc"

def get_token():
    url = "https://api.kiwoom.com/api/au10001" # Real
    headers = {"Content-Type": "application/json"}
    body = {"app_key": app_key, "app_secret": app_secret}
    res = requests.post(url, headers=headers, json=body)
    return res.json().get('token')

def get_daily(code, token):
    url = "https://api.kiwoom.com/api/ka10001" 
    headers = {"authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"stk_cd": code, "count": "30"}
    res = requests.post(url, headers=headers, json=params)
    return res.json().get('output', [])

def main():
    stk_cd = "402490"
    token = get_token()
    data = get_daily(stk_cd, token)
    
    print(f"--- {stk_cd} 최근 30일 시세 ---")
    print(data) # [Debug]
    if not data:
        print("Empty Output")

if __name__ == "__main__":
    main()
