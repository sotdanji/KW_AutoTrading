"""
Stock Master API Module

Fetches full stock list from Kiwoom API.
API: ka10099 종목정보 리스트
"""
import requests
import json
import time
from .config import get_api_config

def get_all_stocks(token, market='ALL'):
    """
    키움 API에서 전체 종목 리스트 조회 (ka10099)
    
    Args:
        token: API 토큰
        market: 시장 구분
            - 'KOSPI' or '01': KOSPI 종목
            - 'KOSDAQ' or '02': KOSDAQ 종목
            - 'ALL': 전체 종목 (KOSPI + KOSDAQ)
    
    Returns:
        list: 종목 코드 리스트
    """
    conf = get_api_config()
    host_url = conf['host_url']
    
    # 종목정보 리스트 API (ka10099)
    url = f"{host_url}/api/dostk/stkinfo"
    
    # 시장 구분 코드 매핑 (ka10099 API 문서 기준)
    market_codes = {
        'KOSPI': '0',   # 코스피
        '0': '0',
        'KOSDAQ': '10', # 코스닥
        '10': '10',
        'ALL': 'ALL'
    }
    
    market_code = market_codes.get(market, 'ALL')
    
    # Get stocks from each market if ALL is requested
    if market_code == 'ALL':
        stocks = []
        
        # KOSPI 조회
        print("[INFO] Fetching KOSPI stocks...")
        kospi_stocks = _fetch_stocks_by_market(url, token, '0')  # 코스피: 0
        if kospi_stocks:
            stocks.extend(kospi_stocks)
            print(f"[INFO] KOSPI: {len(kospi_stocks)} stocks")
        
        # Rate limit 방지를 위해 3초 대기
        print("[INFO] Waiting 3 seconds before KOSDAQ query to avoid rate limit...")
        time.sleep(3)
        
        # KOSDAQ 조회
        print("[INFO] Fetching KOSDAQ stocks...")
        kosdaq_stocks = _fetch_stocks_by_market(url, token, '10')  # 코스닥: 10
        if kosdaq_stocks:
            stocks.extend(kosdaq_stocks)
            print(f"[INFO] KOSDAQ: {len(kosdaq_stocks)} stocks")
        
        return stocks
    else:
        return _fetch_stocks_by_market(url, token, market_code)


def _fetch_stocks_by_market(url, token, market_code):
    """
    특정 시장의 종목 리스트 조회 (내부 함수)
    
    Args:
        url: API URL
        token: API 토큰
        market_code: 시장 구분 코드 ('01' or '02')
    
    Returns:
        list: 종목 코드 리스트
    """
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'api-id': 'ka10099',  # 종목정보 리스트
        'cont-yn': 'N',  # 첫 조회
        'next-key': ''
    }
    
    params = {
        'mrkt_tp': market_code  # 시장구분 (필수)
    }
    
    all_stocks = []
    cont_yn = 'N'
    next_key = ''
    
    # 연속조회 처리
    max_iterations = 100  # 무한루프 방지
    iteration = 0
    
    try:
        while iteration < max_iterations:
            iteration += 1
            
            # 연속조회 헤더 업데이트
            headers['cont-yn'] = cont_yn
            headers['next-key'] = next_key
            
            response = requests.post(url, headers=headers, json=params)
            
            if response.status_code != 200:
                print(f"Stock list request failed: {response.status_code}")
                print(f"Response: {response.text}")
                return all_stocks if all_stocks else []
                
            data = response.json()
            
            # DEBUG: Print full response to understand structure
            if iteration == 1:  # Only print on first iteration
                print(f"[DEBUG] Full API response: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # 응답에서 종목 리스트 추출
            stock_list = data.get('list', [])
            if not stock_list:
                stock_list = data.get('output', [])
            if not stock_list:
                stock_list = data.get('stk_info_list', [])
            if not stock_list:
                stock_list = data.get('output1', [])
            
            # 종목 코드 추출
            for item in stock_list:
                if isinstance(item, dict):
                    # 종목코드는 'code' 키에 있음 (ka10099 API 응답)
                    code = item.get('code', '')
                    if code:
                        all_stocks.append(code)
                elif isinstance(item, str):
                    # 이미 코드 문자열인 경우
                    all_stocks.append(item)
            
            # 연속조회 여부 확인
            cont_yn = data.get('cont_yn', 'N')
            next_key = data.get('next_key', '')
            
            if cont_yn != 'Y' or not next_key:
                break  # 더 이상 조회할 데이터 없음
        
        print(f"[INFO] Fetched {len(all_stocks)} stocks from market {market_code}")
        return all_stocks
        
    except Exception as e:
        print(f"Error fetching stock list for market {market_code}: {e}")
        return all_stocks if all_stocks else []
