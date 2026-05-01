import requests
from config import get_current_config

# 주식호가요청 (Full Data)
def get_orderbook(stk_cd, token=None):
    """
    주식 호가 잔량 정보를 조회합니다.
    Ref: ka10004 (주식호가조회)
    
    Returns:
        dict: {
            'code': stk_cd,
            'total_ask': int, # 매도호가 총잔량
            'total_bid': int, # 매수호가 총잔량
        }
    """
    if not token:
        return None
        
    # 설정 로드
    conf = get_current_config()
    host_url = conf['host_url']

    # 1. 요청할 API URL
    endpoint = '/api/dostk/mrkcond'
    url =  host_url + endpoint

    # 2. header 데이터
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': 'N',
        'next-key': '',
        'api-id': 'ka10004',
    }

    # 3. 요청 데이터
    params = {
        'stk_cd': stk_cd,
    }

    try:
        # 4. http POST 요청
        response = requests.post(url, headers=headers, json=params)
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        
        # [CRITICAL] 키움 REST API (ka10004) 공식 필드명: tot_sel_req, tot_buy_req
        total_ask = data.get('tot_sel_req')
        if total_ask is None: total_ask = data.get('tot_sell_remn')
        if total_ask is None: total_ask = data.get('total_sell_remn', 0)
        
        total_bid = data.get('tot_buy_req')
        if total_bid is None: total_bid = data.get('tot_buy_remn')
        if total_bid is None: total_bid = data.get('total_buy_remn', 0)
        
        return {
            'code': stk_cd,
            'total_ask': int(total_ask),
            'total_bid': int(total_bid)
        }

        
    except Exception as e:
        print(f"호가잔량 조회 실패({stk_cd}): {e}")
        return None
