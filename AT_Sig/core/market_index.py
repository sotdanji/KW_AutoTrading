import logging
import json
from shared.api import fetch_data

logger = logging.getLogger("AT_Sig.MarketIndex")

def get_market_index(token, market="KOSPI"):
    """
    Get Market Index using ka20001 (Sector Quote)
    market: "KOSPI" or "KOSDAQ"
    return: {'price': float, 'change': float, 'rate': float}
    """
    try:
        # shared/api.py의 fetch_data 기반으로 세션 재사용 및 10054 방어
        host_url = "https://api.kiwoom.com"
        endpoint = "/api/dostk/sect"
        api_id = "ka20001"
        
        # Determine codes
        mrkt_tp = "0" # KOSPI
        inds_cd = "001" # Composite Index
        
        if market.upper() == "KOSDAQ":
            mrkt_tp = "1"
            inds_cd = "001" 
            
        params = {
            "mrkt_tp": mrkt_tp,
            "inds_cd": inds_cd,
            "stex_tp": "1"
        }
        
        resp = fetch_data(host_url, endpoint, api_id, params, token)
        if not resp:
            return None
            
        data = resp.json()
        # [안실장 픽스] API 응답 구조 유연하게 처리 (output 키 대응)
        if 'output' in data:
            data = data['output']
            
        # Parse result
        if data:
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            # cur_prc, flu_rt, pre_vs 등 추출
            try:
                cur_prc = str(data.get('cur_prc', '0')).replace(',', '')
                flu_rt = str(data.get('flu_rt', '0')).replace('%', '')
                
                return {
                    'price': float(cur_prc),
                    'rate': float(flu_rt)
                }
            except (ValueError, TypeError) as e:
                logger.error(f"Data conversion error in {api_id}: {e}")
            
    except Exception as e:
        logger.error(f"Error fetching market index: {e}")
        
    return None
