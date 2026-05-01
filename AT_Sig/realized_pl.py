from datetime import datetime
from shared.api import fetch_data

def fn_ka10074(token=None, base_dt=None):
    """
    일자별실현손익요청 (ka10074)
    shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
    """
    if not base_dt:
        base_dt = datetime.now().strftime("%Y%m%d")
        
    host_url = "https://api.kiwoom.com"
    endpoint = "/api/dostk/acnt"
    api_id = 'ka10074'

    params = {
        'strt_dt': base_dt,
        'end_dt': base_dt
    }

    # shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
    resp = fetch_data(host_url, endpoint, api_id, params, token)
    
    if resp and resp.status_code == 200:
        try:
            return resp.json()
        except Exception as e:
            import logging
            logging.getLogger("AT_Sig.realized_pl").error(f"Error parsing realized_pl: {e}")
            
    return None
