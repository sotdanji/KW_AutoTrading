"""
Stock Universe Module

Provides stock list and filtering functions for multi-stock backtesting.
Using REAL API for fetching stock data.
"""

def get_full_stock_universe(token=None):
	"""
	전체 종목 유니버스 반환 (API 사용 + 필터링)
	단일 종목만 남기고 ETF, ETN, 스팩, 리츠, 우선주 등을 제외합니다.
	
	Args:
		token: API 토큰
	
	Returns:
		list: 필터링된 단일 종목 코드 리스트
	"""
	if not token:
		print("[ERROR] No API token provided")
		return []
	
	try:
		from shared.api import _get_host_url
		host_url = _get_host_url("REAL")
		from .stock_master import get_all_stocks
		# 이름 기반 필터링을 위해 MAP 형식으로 호출
		api_map = get_all_stocks(host_url, token, market='MAP')
		
		if not api_map:
			print(f"[ERROR] API returned no stocks - check API configuration")
			return []
			
		filtered_codes = []
		
		# 제외 대상 키워드 (ETF/ETN 브랜드 및 특수 유형)
		exclude_keywords = [
			'KODEX', 'TIGER', 'ACE', 'SOL', 'ARIRANG', 'PLUS', 'HANARO', 'RISE', 'KOSEF', '1Q', 'KoAct', 
			'KBSTAR', 'KINDEX', '히어로즈', '마이티', '아이엠에셋', '에셋플러스', '마이다스',
			'ETF', 'ETN', '스팩', '리츠', 'REITs', '인버스', '레버리지', '(합성', '(H', '채권', '국채', '액티브', '2X', 'X2'
		]

		for code, name in api_map.items():
			# 1. 코드가 6자리 숫자가 아니면 제외 (파생상품, 인덱스 등)
			if not code.isdigit() or len(code) != 6:
				continue
				
			# 2. 이름에 ETF, ETN, 스팩, 리츠 등 키워드 포함 시 제외
			upper_name = name.upper()
			if any(k.upper() in upper_name for k in exclude_keywords):
				continue
				
			# 3. 우선주 제외
			# 한국 시장 우선주는 보통 이름 끝에 '우', '우B', '우C' 등이 붙음
			# 단, 'DB'와 같은 실주를 위해 끝 3글자 내에 '우'가 포함된 경우만 체크
			if '우' in name[-3:] and (name.endswith('우') or name.endswith('B') or name.endswith('C')):
				continue
			
			filtered_codes.append(code)
			
		print(f"[INFO] Filtered {len(filtered_codes)} individual stocks (from {len(api_map)} total items)")
		return filtered_codes
		
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

def filter_hot_stocks_parallel(stock_codes, token, min_price=1000, min_volume=100000, min_value=15000000000, progress_callback=None):
	"""
	[V2 고속 스캔] 시장 랭킹 API를 직접 타격하여 주도주를 0.5초 이내에 추출합니다.
	(2500+회 호출 → 4~8회 호출로 단축)
	"""
	from shared.api import _get_host_url, fetch_market_ranking_ka10027, fetch_market_ranking_ka10032
	universe_set = set(stock_codes)
	host_url = _get_host_url("REAL")
	candidates = {} # {code: {price, vol, value}}
	
	def safe_get_metrics(s):
		try:
			prc_val = str(s.get('cur_prc', '0')).replace(',', '').replace('+', '').replace('-', '')
			if not prc_val or not prc_val.strip(): prc_val = '0'
			prc = abs(float(prc_val))
			
			vol_val = str(s.get('acml_tr_vol', '0') or s.get('now_trde_qty', '0')).replace(',', '')
			if not vol_val or not vol_val.strip(): vol_val = '0'
			vol = float(vol_val)
			
			return prc, vol
		except (ValueError, TypeError):
			return 0.0, 0.0

	# 등락률 상위 + 거래대금 상위 (각 2페이지씩)
	for page in [1, 2]:
		# 등락률 상위
		for s in fetch_market_ranking_ka10027(host_url, token, page=page):
			code = s.get('stk_cd', '').split('_')[0].strip()
			if code in universe_set:
				prc, vol = safe_get_metrics(s)
				if prc > 0:
					candidates[code] = {'price': prc, 'vol': vol, 'value': prc * vol}
		
		# 거래대금 상위
		for s in fetch_market_ranking_ka10032(host_url, token, page=page):
			code = s.get('stk_cd', '').split('_')[0].strip()
			if code in universe_set:
				prc, vol = safe_get_metrics(s)
				if prc > 0:
					candidates[code] = {'price': prc, 'vol': vol, 'value': prc * vol}
		
		if progress_callback: progress_callback(page * 100, 400)

	filtered = []
	for code, info in candidates.items():
		if info['price'] >= min_price and info['vol'] >= min_volume and info['value'] >= min_value:
			filtered.append(code)
	filtered.sort(key=lambda x: candidates[x]['value'], reverse=True)
	return filtered
