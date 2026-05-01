"""
Stock Universe Module

Provides stock list and filtering functions for multi-stock backtesting.
"""

# Hardcoded KOSPI top stocks (시가총액 기준 상위 종목)
# Mock API에서 전체 종목 리스트를 가져올 수 없으므로 하드코딩
KOSPI_TOP_100 = [
    '005930',  # 삼성전자
    '000660',  # SK하이닉스
    '051910',  # LG화학
    '035420',  # NAVER
    '006400',  # 삼성SDI
    '005380',  # 현대차
    '035720',  # 카카오
    '000270',  # 기아
    '068270',  # 셀트리온
    '012330',  # 현대모비스
    '105560',  # KB금융
    '055550',  # 신한지주
    '207940',  # 삼성바이오로직스
    '005490',  # POSCO홀딩스
    '028260',  # 삼성물산
    '034020',  # 두산에너빌리티
    '003670',  # 포스코퓨처엠
    '000810',  # 삼성화재
    '017670',  # SK텔레콤
    '009150',  # 삼성전기
    '032830',  # 삼성생명
    '003550',  # LG
    '010130',  # 고려아연
    '011200',  # HMM
    '086790',  # 하나금융지주
    '096770',  # SK이노베이션
    '033780',  # KT&G
    '018260',  # 삼성에스디에스
    '030200',  # KT
    '009540',  # 한국조선해양
    '015760',  # 한국전력
    '010950',  # S-Oil
    '000100',  # 유한양행
    '024110',  # 기업은행
    '047050',  # 포스코인터내셔널
    '003490',  # 대한항공
    '011070',  # LG이노텍
    '012450',  # 한화에어로스페이스
    '004020',  # 현대제철
    '036570',  # 엔씨소프트
    '001450',  # 현대해상
    '024120',  # 삼성SDS
    '010140',  # 삼성중공업
    '066570',  # LG전자
    '000720',  # 현대건설
    '011170',  # 롯데케미칼
    '051900',  # LG생활건강
    '004170',  # 신세계
    '078930',  # GS
    '090430',  # 아모레퍼시픽
    '012830',  # 삼성증권
]

def get_full_stock_universe(token=None):
    """
    전체 종목 유니버스 반환 (API 사용)
    
    Args:
        token: API 토큰
    
    Returns:
        list: 종목 코드 리스트 (API 실패 시 빈 리스트)
    """
    if not token:
        print("[ERROR] No API token provided")
        return []
    
    try:
        from .stock_master import get_all_stocks
        api_stocks = get_all_stocks(token, market='ALL')
        
        if api_stocks and len(api_stocks) > 0:
            print(f"[INFO] Loaded {len(api_stocks)} stocks from API")
            return api_stocks
        else:
            print(f"[ERROR] API returned no stocks - check API configuration")
            return []
    except Exception as e:
        print(f"[ERROR] Failed to fetch stocks from API: {e}")
        return []


def filter_by_price_volume(stock_codes, token, min_price, min_volume):
    """
    최소가격/거래량 필터 적용
    
    Args:
        stock_codes: 필터링할 종목 코드 리스트
        token: API 토큰
        min_price: 최소 주가 (원)
        min_volume: 최소 거래량 (주)
    
    Returns:
        list: 필터 통과한 종목 코드 리스트
    """
    from .daily_chart import get_daily_chart
    import datetime
    
    filtered = []
    today = datetime.datetime.now().strftime("%Y%m%d")
    
    for code in stock_codes:
        try:
            # 최근 1일 데이터만 가져오기
            chart_data = get_daily_chart(code, token=token, end_date=today)
            
            if not chart_data or len(chart_data) == 0:
                continue
            
            # 최근 데이터 (첫 번째 row)
            latest = chart_data[0]
            
            # 현재가와 거래량 추출
            current_price = float(latest.get('cur_prc', 0))
            trade_volume = float(latest.get('trde_qty', 0))
            
            # 필터 조건 체크
            if current_price >= min_price and trade_volume >= min_volume:
                filtered.append(code)
                
        except Exception as e:
            # 에러 발생 시 해당 종목 스킵
            print(f"[WARN] Filter error for {code}: {e}")
            continue
    
    return filtered
