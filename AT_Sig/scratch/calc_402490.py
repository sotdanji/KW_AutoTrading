import os
import sys
import json
import requests
import pandas as pd
import numpy as np

# [Config]
app_key = "yvXD2wI7ujIWV5o-9Altz1gVc-TWV_pTdUjNt71Oppw"
app_secret = "xra9zLJMYbO2GzDuuRQzz-XsCdGQyaW_02fPdmqxsYc"
host_url = "https://api.kiwoom.com"

def get_token():
    url = f"{host_url}/oauth2/token"
    headers = {"Content-Type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": app_key, "secretkey": app_secret}
    res = requests.post(url, headers=headers, json=body)
    return res.json().get('token')

def fetch_data(stk_cd, token):
    params = {'stk_cd': stk_cd, 'cnt_tp': '0', 'upd_stkpc_tp': '1'}
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10081'
    }
    url = f"{host_url}/api/dostk/chart"
    res = requests.post(url, headers=headers, json=params)
    data = res.json()
    items = data.get('stk_dt_pole_chart_qry') or data.get('stk_day_chart_qry') or data.get('output', [])
    
    # 정규화
    cleaned = []
    for row in items:
        # 필드명 매핑 (API 응답 필드 확인 필요하나 보통 이렇습니다)
        # dt, open_prc, high_prc, low_prc, close_prc
        d = {
            'dt': row.get('dt'),
            'open': int(str(row.get('open_prc', 0)).replace(',', '').replace('+', '').replace('-', '') or 0),
            'high': int(str(row.get('high_prc', 0)).replace(',', '').replace('+', '').replace('-', '') or 0),
            'low': int(str(row.get('low_prc', 0)).replace(',', '').replace('+', '').replace('-', '') or 0),
            'close': int(str(row.get('close_prc', 0)).replace(',', '').replace('+', '').replace('-', '') or 0),
            'volume': int(str(row.get('trde_qty', 0)).replace(',', '') or 0)
        }
        cleaned.append(d)
    
    # 과거->현재 정렬
    cleaned.sort(key=lambda x: x['dt'])
    return pd.DataFrame(cleaned)

def main():
    stk_cd = "402490"
    token = get_token()
    df = fetch_data(stk_cd, token)
    
    if df.empty:
        print("No Data")
        return

    # 전략 로직 (가장 최근 음봉 시가)
    # BBands/EMA 수동 계산 (간단히 20일 이동평균으로 대체하거나 정확히 계산)
    df['ma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bbu20'] = df['ma20'] + (df['std20'] * 2)
    
    df['ma60'] = df['close'].rolling(60).mean()
    df['std60'] = df['close'].rolling(60).std()
    df['bbu60'] = df['ma60'] + (df['std60'] * 2)
    
    C, O = df['close'], df['open']
    BBU1, BBU2 = df['bbu20'], df['bbu60']
    
    A1 = (C.shift(2)>BBU1.shift(2)) | (C.shift(1)>BBU1.shift(1)) | (C>BBU1)
    A2 = (C.shift(2)>BBU2.shift(2)) | (C.shift(1)>BBU2.shift(1)) | (C>BBU2)
    A3 = (O.shift(2)<C.shift(2)) | (C.shift(3)<C.shift(2))
    A4 = (O.shift(1)<=C.shift(1)) | (C.shift(2)<C.shift(1))
    A5 = (O>C) 
    
    B = A1 & A2 & A3 & A4 & A5
    
    # ValueWhen(1, B, O)
    df['TargetLine'] = pd.Series(np.where(B, O, np.nan), index=df.index).ffill()
    
    print(f"--- [그린리소스 (402490)] 분석 완료 ---")
    last_15 = df.tail(15)
    print(last_15[['dt', 'open', 'close', 'TargetLine']])
    
    final_tl = df['TargetLine'].iloc[-1]
    last_b_dt = df[B]['dt'].iloc[-1] if B.any() else "None"
    
    print(f"\n✅ 가장 최근 패턴 발생일: {last_b_dt}")
    print(f"✅ 결정된 TargetLine(시가): {final_tl:,.0f}원")

if __name__ == "__main__":
    main()
