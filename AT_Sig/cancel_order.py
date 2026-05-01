import logging
from shared.api import fetch_data, generate_idempotency_key, REAL_HOST

# 주문 취소 (fn_kt00003)
def fn_kt00003(org_ord_no, can_qty, stk_cd, token=None, buy_sell_tp='2'): 
    """
    주문 취소/정정 (kt00003)
    shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
    """
    host_url = REAL_HOST
    endpoint = '/api/dostk/ordr'
    api_id = 'kt00003'
    
    # Params for Cancel:
    params = {
        'org_ord_no': org_ord_no,
        'stk_cd': stk_cd,
        'ord_qty': str(can_qty), # Cancel logic
        'ord_price': '0', # Market Cancel often 0
        'ord_tp': buy_sell_tp, # 3: Sell Cancel, 4: Buy Cancel
    }
    
    # shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
    # 멱등성 키 생성
    idempotency_key = generate_idempotency_key()

    resp = fetch_data(host_url, endpoint, api_id, params, token, idempotency_key=idempotency_key)
    
    if resp and resp.status_code == 200:
        try:
            return resp.json().get('return_code')
        except Exception as e:
            logging.getLogger("AT_Sig.cancel_order").error(f"Error parsing cancel response: {e}")
            
    return None
