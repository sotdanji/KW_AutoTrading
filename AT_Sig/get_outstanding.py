from shared.api import fetch_data

# 미체결 조회 (fn_kt00002)
def fn_kt00002(stk_cd='', token=None):
    """
    미체결 조회 (kt00002)
    shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
    """
    host_url = "https://api.kiwoom.com"
    endpoint = '/api/dostk/ordrinfo'
    api_id = 'kt00002'
    
    # ord_stat: "0" (미체결)
    params = {
        'mkrt_tp': 'KRX',
        'stk_cd': stk_cd,
        'ord_stat': '0', # 0:미체결
        'ord_dt': '', # 당일
        'sll_buy_tp': '', # 전체
    }
    
    # shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
    resp = fetch_data(host_url, endpoint, api_id, params, token)
    
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            if 'output' in data:
                return data['output'] # List of outstanding orders
        except Exception as e:
            import logging
            logging.getLogger("AT_Sig.get_outstanding").error(f"Error parsing outstanding: {e}")
            
    return []
