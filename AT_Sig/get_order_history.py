import requests
from datetime import datetime, timedelta
from config import get_current_config
from login import fn_au10001 as get_token

# 위탁종합거래내역요청 (kt00015) - 일별/기간별 거래내역 조회
def fn_kt00015(start_dt=None, end_dt=None, cont_yn='N', next_key='', token=None):
    # 설정 로드
    conf = get_current_config()
    host_url = conf['host_url']

    # 1. 요청할 API URL
    endpoint = '/api/dostk/acnt'
    url =  host_url + endpoint

    # 날짜 기본값: 오늘
    if not start_dt:
        start_dt = datetime.now().strftime("%Y%m%d")
    if not end_dt:
        end_dt = datetime.now().strftime("%Y%m%d")

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8', 
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'kt00015', 
    }

    # 3. 요청 데이터
    params = {
        'start_dt': start_dt,
        'end_dt': end_dt,
        'strt_dt': start_dt, # Redundant but safe based on testing
        'qry_tp': '1', 
        'stk_bond_tp': '1', 
        'tp': '0',
        'gds_tp': '10', 
        'inqr_dvsn': '00', # 00:전체
        'dmst_stex_tp': 'KRX',
    }
    
    # 3. http POST 요청 및 페이징 처리
    all_trades = []
    
    while True:
        try:
            # Header Update for Next Key
            if next_key:
                headers['next-key'] = next_key
                headers['cont-yn'] = 'Y'
            else:
                 headers['cont-yn'] = 'N'

            response = requests.post(url, headers=headers, json=params, timeout=5)
            
            if response.status_code == 200:
                res_json = response.json()
                if 'trst_ovrl_trde_prps_array' in res_json:
                     all_trades.extend(res_json['trst_ovrl_trde_prps_array'])
                
                # Check Next Key
                next_key = response.headers.get('next-key', '')
                
                if not next_key:
                    break # No more pages
            else:
                print(f"kt00015 Error Code: {response.status_code}")
                break
                
        except Exception as e:
            print(f"kt00015 Exception: {e}")
            break
            
    return all_trades

# 주식주문체결내역상세요청 (kt00007) - 당일 주문/체결 내역
def fn_kt00007(ord_dt=None, cont_yn='N', next_key='', token=None):
    # 설정 로드
    conf = get_current_config()
    host_url = conf['host_url']

    # 1. 요청할 API URL
    endpoint = '/api/dostk/acnt'
    url =  host_url + endpoint

    # 날짜 기본값: 오늘
    if not ord_dt:
        ord_dt = datetime.now().strftime("%Y%m%d")

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8', 
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'kt00007', 
    }

    # 3. 요청 데이터
    params = {
        'ord_dt': ord_dt,
        'qry_tp': '1', 
        'stk_bond_tp': '1', 
        'dmst_stex_tp': 'KRX',
        'sell_tp': '00', # 00:전체
        'inqr_dvsn': '00', # 00:전체
        'stk_cd': '',
        'ord_gno_brno': '',
        'ord_no': '',
    }
    
    # 3. http POST 요청 및 페이징 처리
    all_orders = []
    
    while True:
        try:
            # Header Update for Next Key
            if next_key:
                headers['next-key'] = next_key
                headers['cont-yn'] = 'Y'
            else:
                 headers['cont-yn'] = 'N'

            response = requests.post(url, headers=headers, json=params, timeout=5)
            
            if response.status_code == 200:
                res_json = response.json()
                potential_keys = ['acnt_ord_cntr_prps_dtl', 'dtl', 'output']
                found = False
                for k in potential_keys:
                    if k in res_json:
                        all_orders.extend(res_json[k])
                        found = True
                        break
                
                next_key = response.headers.get('next-key', '')
                if not next_key:
                    break
            else:
                print(f"kt00007 Error Code: {response.status_code}")
                break
                
        except Exception as e:
            print(f"kt00007 Exception: {e}")
            break
            
    return all_orders

def get_combined_history(token=None):
    """오늘(kt00007) + 과거(kt00015) 통합 조회"""
    today = datetime.now().strftime("%Y%m%d")
    month_start = datetime.now().strftime("%Y%m") + "01"
    
    # 1. Today's Trades (kt00007)
    today_orders = fn_kt00007(ord_dt=today, token=token)
    
    today_trades = []
    if today_orders:
        for order in today_orders:
             # Check if executed (Map fields robustly based on provided sample)
             ccld_qty_raw = (order.get('cntr_qty') or order.get('tot_ccld_qty') or 
                             order.get('cnfm_qty') or '0')
             exec_qty = int(str(ccld_qty_raw).replace(',', '')) if str(ccld_qty_raw).replace(',', '').isdigit() else 0
             
             if exec_qty > 0:
                 # Map fields robustly
                 s_b_tp = (order.get('sell_buy_tp_nm') or order.get('sll_buy_tp_nm') or 
                           order.get('io_tp_nm') or order.get('side_nm') or '')
                 
                 # Price mapping: Use cntr_uv (체결단가) from sample if available
                 exec_price = (order.get('cntr_uv') or order.get('ord_prc') or 
                               order.get('avg_prc') or order.get('cntr_prc') or '0')

                 today_trades.append({
                     'trde_dt': today,
                     'stk_cd': order.get('stk_cd', ''),
                     'stk_nm': order.get('stk_nm', ''),
                     'io_tp_nm': s_b_tp, # 매수/매도 구분
                     'trde_qty_jwa_cnt': str(exec_qty),
                     'trde_unit': str(exec_price), 
                     'proc_tm': (order.get('ord_tm') or order.get('proc_tm') or '000000'), 
                 })

    # 2. Past Trades (kt00015)
    yesterday_dt = datetime.now() - timedelta(days=1)
    yesterday = yesterday_dt.strftime("%Y%m%d")
    
    past_trades = []
    if month_start <= yesterday:
         past_trades = fn_kt00015(start_dt=month_start, end_dt=yesterday, token=token)

    # Time Normalization Logic
    final_list = []
    
    # Process Today Trades
    for t in today_trades:
        tm = t.get('proc_tm', '000000')
        if len(tm) == 6:
            t['proc_tm'] = f"{tm[:2]}:{tm[2:4]}:{tm[4:]}"
        final_list.append(t)
        
    # Process Past Trades
    for t in past_trades:
        tm = t.get('proc_tm', '00:00:00')
        if ':' in tm:
            try:
                h, m, s = map(int, tm.split(':'))
                if h < 8:
                     h += 9
                     t['proc_tm'] = f"{h:02}:{m:02}:{s:02}"
            except:
                pass
        else:
             if len(tm) == 6:
                 try:
                    h = int(tm[:2])
                    m = int(tm[2:4])
                    s = int(tm[4:])
                    if h < 8:
                         h += 9
                    t['proc_tm'] = f"{h:02}:{m:02}:{s:02}"
                 except:
                    t['proc_tm'] = f"{tm[:2]}:{tm[2:4]}:{tm[4:]}"
        final_list.append(t)

    return final_list

if __name__ == '__main__':
    # Test
    token = get_token()
    print("Fetching combined history...")
    res = get_combined_history(token=token)
    print(f"Found {len(res)} trades total")
    if res:
        print(res[0])
