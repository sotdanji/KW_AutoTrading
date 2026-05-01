import requests
import json
import re
import random
import time
import sys
import os
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

# shared 모듈 경로 추가
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from shared.api import get_kw_token, fetch_kw_data
from shared import stock_master as _stock_master
from core.logger import get_logger

logger = get_logger(__name__)

class DataFetcher:
	# Hardcoded Code-to-Name Map for Curated Stocks
	def _get_stock_name(self, code: str) -> str:
		"""
		shared/stock_master.py 캐시에서 종목명 조회.
		캐시에 없으면 종목코드를 그대로 반환.
		"""
		cached = _stock_master.load_master_cache()
		return cached.get(code, code)

	def __init__(self, mode="PAPER"):
		logger.debug(f"DataFetcher init mode={mode}")
		self._mode = mode
		self.token = None
		self.theme_code_cache = {}
		self._last_indices = {}  # 마지막 지수 데이터 캐싱 (Flickering 방지)

		# config.py에서 인증 키 로드
		try:
			import config as _cfg
			_api_cfg = _cfg.REAL_CONFIG if mode == "REAL" else _cfg.MOCK_CONFIG
			self._app_key = _api_cfg.get('app_key', '')
			self._app_secret = _api_cfg.get('app_secret', '')
		except Exception as e:
			logger.warning(f"config 로드 실패: {e}")
			self._app_key = ''
			self._app_secret = ''
		
		# 키움 업종 코드 매핑 (KOSPI 주요 업종)
		# ka20001 API의 inds_cd 파라미터로 사용
		self.sector_code_map = {
			"001": "종합(KOSPI)",
		}

		
		# 시장 인기 테마 (Market Themes) - 테마당 5개로 보강
		self.curated_themes = {
			"이차전지": ["373220", "006400", "051910", "112610", "066970"],
			"AI/로봇": ["047080", "121440", "289080", "415580", "305120"],
			"방산": ["047810", "012450", "000880", "003550", "017150"],
			"엔터테인먼트": ["035900", "041510", "352820", "040300", "041510"],
			"우주항공": ["047810", "272210", "012450", "044380", "007390"],
			"게임": ["251270", "035720", "064820", "298040", "041140"],
			"메타버스": ["222800", "214270", "293490", "053670", "137940"],
			"신재생": ["009830", "377300", "004020", "032500"],
		}
		
		# 추가: 실제 API에서 가져온 업종 코드 저장소 (ka10101)
		# { "전기전자": "013", ... }
		self.dynamic_sector_map = {
			# Fallback for Size Indices (Always needed)
			"대형주": "002",
			"중형주": "003",
			"소형주": "004",
			"음식료품": "005", "섬유의복": "006", "종이목재": "007", "화학": "008",
			"의약품": "009", "비금속광물": "010", "철강금속": "011", "기계": "012",
			"전기전자": "013", "의료정밀": "014", "운수장비": "015", "유통업": "016",
			"전기가스업": "017", "건설업": "018", "운수창고업": "019", "통신업": "020",
			"금융업": "021", "은행": "022", "증권": "023", "보험": "024", "서비스업": "025",
			"제조업": "026", "KOSPI200": "201"
		}
		self.sector_code_map_initialized = False

	@property
	def mode(self):
		return self._mode

	@mode.setter
	def mode(self, value):
		if self._mode != value:
			logger.debug(f"DataFetcher mode changed: {self._mode} -> {value}")
			self._mode = value
			self.token = None  # 모드 변경 시 토큰 초기화
			try:
				import config as _cfg
				_api_cfg = _cfg.REAL_CONFIG if value == "REAL" else _cfg.MOCK_CONFIG
				self._app_key = _api_cfg.get('app_key', '')
				self._app_secret = _api_cfg.get('app_secret', '')
			except Exception:
				pass

	def _request_token(self) -> str | None:
		"""
		API 토큰을 요청하는 통일 헬퍼.
		shared/api.get_kw_token에 app_key/app_secret을 주입하여 호출.
		"""
		token = get_kw_token(
			mode=self._mode,
			app_key=self._app_key,
			app_secret=self._app_secret
		)
		if token:
			self.token = token
		return token

	def get_category_data(self, category="Sectors"):
		"""
		섹터 또는 테마 그룹의 퍼포먼스 데이터를 가져옵니다.
		"""
		logger.debug(f"get_category_data category={category}, mode={self.mode}")
		
		# 테마는 실제 API 사용
		if category == "Themes":
			return self.get_theme_groups()
		
		# 섹터도 실제 API 사용
		if category == "Sectors":
			return self.get_sector_groups()
		
		return []

	def _fetch_sector_master(self):
		"""
		ka10101 API를 호출하여 최신 업종 코드 리스트를 가져옵니다.
		"""
		logger.debug("Fetching sector master data (ka10101)...")
		
		endpoint = '/api/dostk/stkinfo'
		params = { "mrkt_tp": "0" } # KOSPI
		
		try:
			res = fetch_kw_data(endpoint, 'ka10101', params, self.token, self.mode)
			
			if res and 'list' in res:
				count = 0
				for item in res['list']:
					code = item.get('code', '').strip()
					name = item.get('name', '').strip()
					if code and name:
						self.dynamic_sector_map[name] = code
						count += 1
				
				self.sector_code_map_initialized = True
				logger.info(f"Initialized dynamic sector map with {count} items")
			else:
				logger.warning("Failed to fetch sector master list or empty list")
				
		except Exception as e:
			logger.error(f"Error fetching sector master: {e}")
	
	def get_sector_groups(self):
		"""
		ka20001 API를 사용하여 실제 업종 목록을 가져옵니다.
		주요 업종만 선택하여 표시합니다.
		"""
		if self.mode == "PAPER":
			# Mock 모드: 가짜 데이터 생성
			return [{
				'name': name,
				'change': random.uniform(-5, 5),
				'volume': random.randint(100, 1000)
			} for code, name in list(self.sector_code_map.items())[:8]]
		
		# Real Mode - ka20001 API 호출
		if not self.token:
			logger.debug("Requesting token for sectors...")
			self._request_token()
		
		if not self.token:
			logger.error("Failed to get token for sectors")
			return []

		# 1. 초기화되지 않았으면 업종 마스터 조회 (ka10101)
		if not self.sector_code_map_initialized:
			self._fetch_sector_master()
		
		endpoint = '/api/dostk/sect'
		sectors = []
		
		# 조회할 업종 코드 리스트 작성 (전체 섹터 대상)
		# 1) 대/중/소형주만 조회 (속도 최적화: 산업 섹터 개별 조회 중단)
		# 전광판(Ticker) 표시에 필수적인 데이터만 빠르게 가져옵니다.
		size_indices = ['대형주', '중형주', '소형주']
		target_codes = []
		
		for name in size_indices:
			if name in self.dynamic_sector_map:
				target_codes.append(self.dynamic_sector_map[name])
			else:
				# Fallback codes if map not ready
				if name == "대형주": target_codes.append("002")
				elif name == "중형주": target_codes.append("003")
				elif name == "소형주": target_codes.append("004")
		
		# 산업 섹터 루프 제거 -> 테마가 메인 감시 대상이 됨
		
		logger.debug(f"Fetching {len(target_codes)} sector groups from ka20001...")
		
		for inds_cd in target_codes:
			params = {
				'mrkt_tp': '0',  # 0:코스피
				'inds_cd': inds_cd
			}
			
			try:
				res = fetch_kw_data(endpoint, 'ka20001', params, self.token, self.mode)
				
				if res and 'cur_prc' in res:
					flu_rt = res.get('flu_rt', '0').replace('+', '').replace('%', '').strip()
					vol_str = res.get('trde_qty', '0').strip()
					amt_str = res.get('trde_prica', '0').strip() 

					# 동적 맵에서 이름 찾기 (코드로) - 우선순위 변경
					sector_name = f"업종{inds_cd}"

					# 1. dynamic_sector_map (역방향 검색)
					found_dynamic = False
					for name, code in self.dynamic_sector_map.items():
						if code == inds_cd:
							sector_name = name
							found_dynamic = True
							break
					
					# 2. sector_code_map (기본) 확인 - Fallback only
					if not found_dynamic and inds_cd in self.sector_code_map:
						sector_name = self.sector_code_map[inds_cd]
					
					# 거래대금(백만원 단위)을 Volume으로 사용 (없으면 거래량)
					# API 리턴은 억/백만 단위가 아니라 원/주 단위일 수 있음 -> 문서 확인 필요
					# 보통 trde_prica는 '백만원' 단위일 경우가 많음.
					# 안전하게 정수변환
					trade_volume = int(amt_str) if amt_str.isdigit() else 0
					if trade_volume == 0 and vol_str.isdigit():
						trade_volume = int(vol_str)

					# [Fix] 대형/중형/소형주는 코드를 기준으로 이름 강제 통일 (UI 매핑 보장)
					if inds_cd == "002": sector_name = "대형주"
					elif inds_cd == "003": sector_name = "중형주"
					elif inds_cd == "004": sector_name = "소형주"

					sectors.append({
						'name': sector_name,
						'change': float(flu_rt) if flu_rt else 0.0,
						'volume': trade_volume
					})
					logger.debug(f"Sector {sector_name}: {flu_rt}%")
				
				# Rate Limit 방지
				if self.mode == "REAL":
					time.sleep(0.1)
					
			except Exception as e:
				logger.warning(f"Failed to fetch sector {inds_cd}: {e}")
				continue
		
		logger.debug(f"Retrieved {len(sectors)} sectors")
		return sectors
	
	def get_theme_groups(self):
		"""주요 테마(Theme) 그룹 데이터 조회 (Flat Body)"""
		if self.mode == "PAPER":
			return self._get_mock_category_data(self.curated_themes)
		
		# 1. 토큰 체크 및 발급
		if not self.token:
			self._request_token()
		
		max_retries = 2
		for attempt in range(max_retries):
			url = "https://api.kiwoom.com/api/dostk/thme"
			headers = {
				"Content-Type": "application/json",
				"authorization": f"Bearer {self.token}",
				"api-id": "ka90001"
			}
			body = {
				"qry_tp": "0",
				"date_tp": "1",
				"flu_pl_amt_tp": "1",
				"stex_tp": "1"
			}
			
			try:
				res = requests.post(url, headers=headers, data=json.dumps(body), timeout=5)
				
				if res.status_code != 200:
					logger.error(f"Theme API HTTP Error: {res.status_code} - {res.text}")
					return []

				data = res.json()
				
				# [핵심] 토큰 만료 체크 (8005)
				ret_code = str(data.get('return_code') or data.get('code') or '')
				ret_msg = str(data.get('return_msg') or data.get('msg1') or '')
				
				if ret_code == '3' and '8005' in ret_msg:
					logger.warning("Token expired (8005). Refreshing token and retrying...")
					self.token = None
					self._request_token()
					if self.token: continue
					else: return []
				
				# 토큰 만료는 아닌데 에러인 경우
				if ret_code != '0' and ret_code != '':
					logger.error(f"⚠️ API Error: [{ret_code}] {ret_msg}")
					return []

				theme_list = []
				if 'output' in data:
					theme_list = data['output']
				elif 'thema_grp' in data:
					theme_list = data['thema_grp']
				elif 'ds' in data and 'thema_grp' in data['ds']:
					theme_list = data['ds']['thema_grp']
				else:
					logger.warning(f"Unexpected Response Structure: {list(data.keys())} | Msg: {ret_msg}")
					return []
				
				parsed_themes = []
				for item in theme_list:
					t_name = (item.get('group_name') or item.get('thema_nm') or '').strip()
					t_rate = item.get('avg_rate') or item.get('flu_rt') or '0'
					t_code = item.get('group_code') or item.get('thema_grp_cd') or ''
					t_vol  = item.get('stk_cnt') or item.get('stk_num') or '0'
					
					if not t_name or t_name.isdigit(): continue
					
					try:
						rate_val = float(str(t_rate).replace(',', ''))
						vol_val = int(str(t_vol).replace(',', ''))
					except:
						rate_val, vol_val = 0.0, 0

					if t_code: self.theme_code_cache[t_name] = t_code
					
					parsed_themes.append({
						'name': t_name, 'change': rate_val, 'volume': vol_val, 'theme_code': t_code
					})
				
				parsed_themes.sort(key=lambda x: x['change'], reverse=True)
				return parsed_themes
				
			except Exception as e:
				logger.error(f"Theme fetch exception: {e}")
				return []
		return []

	def get_theme_stocks(self, theme_name):
		"""
		ka90002 API를 사용하여 특정 테마의 구성 종목을 가져옵니다.
		"""
		if self.mode == "PAPER":
			return self._get_mock_stock_data(theme_name)
		
		# 테마 코드 조회
		theme_code = self.theme_code_cache.get(theme_name)
		if not theme_code:
			logger.warning(f"Theme code not found for: {theme_name}")
			return []
		
		# Real Mode - ka90002 API 호출
		if not self.token:
			self._request_token()
		
		if not self.token:
			logger.error("Failed to get token for theme stocks")
			return []
		
		endpoint = '/api/dostk/thme'
		params = {
			'date_tp': '1',
			'thema_grp_cd': theme_code,
			'stex_tp': '1'
		}
		
		logger.debug(f"Fetching theme stocks for {theme_name} (code: {theme_code})...")
		res = fetch_kw_data(endpoint, 'ka90002', params, self.token, self.mode)
		
		# [Fix] 응답 구조 유연성 강화 (output/ds/root 어디에 있든 파싱)
		theme_comp_stk = []
		if 'thema_comp_stk' in res:
			theme_comp_stk = res['thema_comp_stk']
		elif 'output' in res and 'thema_comp_stk' in res['output']:
			theme_comp_stk = res['output']['thema_comp_stk']
		elif 'ds' in res and 'thema_comp_stk' in res['ds']:
			theme_comp_stk = res['ds']['thema_comp_stk']
		
		if not theme_comp_stk:
			logger.warning(f"No stock data found in API response for theme: {theme_name}")
			return []
		
		# 응답 파싱
		stocks = []
		for item in theme_comp_stk:
			try:
				stk_cd = item.get('stk_cd', '').strip()
				stk_nm = item.get('stk_nm', '').strip()
				cur_prc = item.get('cur_prc', '0').replace(',', '').strip()
				flu_rt = item.get('flu_rt', '0').replace('+', '').replace('%', '').strip()
				
				if not stk_cd or not stk_nm:
					continue
				
				# Fix: Handle signs (+/-)
				price_str = cur_prc.replace('+', '').replace('-', '')
				price = int(price_str) if price_str.isdigit() else 0
				rate = float(flu_rt)
				
				stocks.append({
					'code': stk_cd,
					'name': stk_nm,
					'price': price, # 현재가는 기본적으로 있음
					'change': rate,
					'rate': rate,
					'open': price,  # 기본값 (상세조회 전)
					'high': price,  # 기본값
					'low': price,   # 기본값
					'volume': 0     # 기본값
				})
			except (ValueError, KeyError) as e:
				logger.warning(f"Failed to parse stock item: {e}")
				continue
		
		# [NEW] Top 5 Enrichment Logic
		# 1. 등락률 순 정렬
		stocks.sort(key=lambda x: x['change'], reverse=True)
		
		# 2. 상위 5개 종목에 대해 상세 데이터(OHLCV) 조회 및 보강
		top_candidates = stocks[:5]
		
		for stock in top_candidates:
			try:
				# _fetch_stock_quote는 ka10005 등을 사용하여 상세 데이터를 가져옴
				detail = self._fetch_stock_quote(stock['code'])
				if detail:
					# 데이터 매핑 (API 필드명 -> 내부 구조)
					# ka10005 (stk_ddwkmm) 기준: 
					# close_pric(종가/현재가), open_pric(시가), high_pric(고가), low_pric(저가), trde_qty(거래량)
					
					# 가격 및 수량 데이터 정규화 (부호 및 콤마 제거 후 정수 변환)
					def _parse_abs_int(val_str):
						if not val_str: return 0
						clean_str = str(val_str).replace(',', '').replace('+', '').replace('-', '').strip()
						return int(clean_str) if clean_str.isdigit() else 0

					# 데이터 매핑 (API 필드명 -> 내부 구조 보강)
					stock['price'] = _parse_abs_int(d_price)
					stock['open'] = _parse_abs_int(d_open)
					stock['high'] = _parse_abs_int(d_high)
					stock['low'] = _parse_abs_int(d_low)
					stock['volume'] = _parse_abs_int(d_vol)
					
					logger.debug(f"Enriched {stock['name']}: O={stock['open']} H={stock['high']} V={stock['volume']}")
					
					# Rate Limit 방지 (짧은 대기)
					if self.mode == "REAL":
						time.sleep(0.05)
			except Exception as e:
				logger.warning(f"Failed to enrich stock {stock['name']}: {e}")
		
		logger.debug(f"Retrieved {len(stocks)} stocks for theme: {theme_name} (Top {len(top_candidates)} enriched)")
		return stocks

	def get_program_trading_data(self):
		"""[프로그램 매매] 상위 50 및 시장 추이 데이터 반환 (ka90003, ka90007)"""
		if self.mode == "PAPER":
			import random
			def gen_mock_list(prefix):
				return [{
					'rank': i+1,
					'stk_nm': f"{prefix} 종목 {i+1}",
					'cur_prc': str(random.randint(10000, 100000)),
					'flu_rt': f"{random.uniform(-5, 5):.2f}",
					'prm_netprps_amt': str(random.randint(100, 5000))
					} for i in range(50)]
			return {
				"kospi_prm": gen_mock_list("KOSPI"),
				"kosdaq_prm": gen_mock_list("KOSDAQ"),
				"market_prm_trend": {
					"kospi": f"+{random.randint(100, 1000)}억",
					"kosdaq": f"+{random.randint(10, 200)}억"
				}
			}

		if not self.token:
			self._request_token()

		max_retries = 2
		for attempt in range(max_retries):
			try:
				from shared.api import fetch_program_ranking_ka90003, fetch_market_program_trend_ka90007, _get_host_url
				host_url = _get_host_url(self.mode)

				# 1. Ranking (ka90003)
				kospi_prm = fetch_program_ranking_ka90003(host_url, self.token, mrkt_tp='P00101')
				kosdaq_prm = fetch_program_ranking_ka90003(host_url, self.token, mrkt_tp='P10102')
				
				# 2. Trend (ka90007)
				kospi_trend_raw = fetch_market_program_trend_ka90007(host_url, self.token, mrkt_tp='0')
				kosdaq_trend_raw = fetch_market_program_trend_ka90007(host_url, self.token, mrkt_tp='1')

				def get_trend_str(raw_list):
					if not raw_list: return "-"
					if isinstance(raw_list, dict) and (raw_list.get('code') == '3' or raw_list.get('return_code') == '3'):
						return "REFRESH_NEEDED"
					if not isinstance(raw_list, list) or len(raw_list) == 0: return "-"
					latest = raw_list[0]
					tdy = latest.get('all_tdy', '0')
					if tdy == '0' and len(raw_list) > 1:
						tdy = latest.get('all_acc', '0')
						return f"누적 {tdy}"
					return tdy

				k_trend = get_trend_str(kospi_trend_raw)
				if k_trend == "REFRESH_NEEDED":
					logger.warning("Program Token Expired. Refreshing...")
					self.token = None
					self._request_token()
					if self.token: continue
				
				return {
					"kospi_prm": kospi_prm if isinstance(kospi_prm, list) else [],
					"kosdaq_prm": kosdaq_prm if isinstance(kosdaq_prm, list) else [],
					"market_prm_trend": {
						"kospi": k_trend,
						"kosdaq": get_trend_str(kosdaq_trend_raw)
					}
				}
			except Exception as e:
				logger.error(f"Program data fetch failed: {e}")
				break
		return {"kospi_prm": [], "kosdaq_prm": [], "market_prm_trend": {"kospi": "-", "kosdaq": "-"}}

	def _fetch_stock_quote(self, code):
		"""Helper to fetch stock quote using ka10005 (Chart/Price Data)"""
		if self.mode == "PAPER":
			return {
				'stk_cd': code,
				'stk_nm': f"Mock_{code}",
				'close_pric': str(random.randint(1000, 500000)),
				'pre': str(random.randint(-1000, 1000)),
				'flu_rt': str(random.uniform(-30, 30)),
				'open_pric': str(random.randint(1000, 500000)), # Open
				'high_pric': str(random.randint(1000, 500000)),  # High
				'low_pric': str(random.randint(1000, 500000)),  # Low
				'trde_qty': str(random.randint(1000, 20000))  # Volume
			}
			
		# [FIX] 토큰이 없으면 발급 시도
		if not self.token:
			from core.api_helper import get_kw_token
			self._request_token()

		if not self.token:
			logger.error("[Fetcher] API Token missing for stock quote")
			return None

		# Using ka10005 (Stock Candle/Day/Week) to get OHLCV
		endpoint = '/api/dostk/mrkcond'
		try:
			res = fetch_kw_data(endpoint, 'ka10005', {'stk_cd': code}, self.token, self.mode)
			
			if res:
				data_list = []
				if 'stk_ddwkmm' in res:
					data_list = res['stk_ddwkmm']
				elif 'output' in res:
					output = res['output']
					if isinstance(output, dict) and 'stk_ddwkmm' in output:
						data_list = output['stk_ddwkmm']
					elif isinstance(output, list):
						data_list = output
				
				if data_list and len(data_list) > 0:
					return data_list[0]
				else:
					# 데이터 본문이 없는 경우 전체 응답 확인 (필드명 확인용)
					logger.warning(f"[Fetcher] No list data for {code}. Res keys: {list(res.keys())}")
			else:
				logger.warning(f"[Fetcher] API Response is None for {code}")
		except Exception as e:
			logger.error(f"[Fetcher] Exception in _fetch_stock_quote: {e}")

		return None

	def _get_mock_category_data(self, source):
		sectors = []
		for name in source.keys():
			sectors.append({
				"name": name,
				"change": random.uniform(-10, 10),
				"volume": random.randint(100, 1000)
			})
		return sectors

	def get_leading_stocks(self, sector_name):
		"""
		Fetches leading stocks for a specific sector or theme.
		"""
		logger.debug(f"get_leading_stocks called with sector_name: '{sector_name}'")
		
		if self.mode == "PAPER":
			return self._get_mock_stock_data(sector_name)
		
		# 테마인지 확인 (캐시에 있으면 테마)
		if sector_name in self.theme_code_cache:
			logger.debug(f"{sector_name} is a theme, using get_theme_stocks")
			return self.get_theme_stocks(sector_name)
		
		# 섹터인 경우: 업종 코드 찾기
		sector_code = None
		
		# Ensure token and map are initialized
		if not self.token:
			self._request_token()
			
		if not self.sector_code_map_initialized:
			self._fetch_sector_master()
			
		# 1. 동적 맵에서 찾기
		if sector_name in self.dynamic_sector_map:
			sector_code = self.dynamic_sector_map[sector_name]
			logger.debug(f"Sector code found in dynamic map: {sector_code} for '{sector_name}'")
			
		# 2. 기본 맵에서 찾기 (fallback)
		if not sector_code:
			for code, name in self.sector_code_map.items():
				if name == sector_name:
					sector_code = code
					break
			if sector_code:
				logger.debug(f"Sector code found in static map: {sector_code} for '{sector_name}'")
				
		# 3. 이름 부분 일치 검색
		if not sector_code:
			for name, code in self.dynamic_sector_map.items():
				if sector_name in name: # "전기/전자" -> "전기전자" 등 매칭 시도
					sector_code = code
					logger.debug(f"Sector code found via fuzzy match: {sector_code} for '{sector_name}'")
					break
		
		if not sector_code:
			logger.warning(f"Sector code not found for: '{sector_name}'")
			logger.debug(f"Available sectors: {list(self.sector_code_map.values())}")
			return []
		
		# Real Mode logic - 섹터 종목 조회 (ka20002)
		if not self.token:
			self._request_token()
		
		# ka20002 API로 섹터 구성 종목 조회
		endpoint = '/api/dostk/sect'
		params = {
			'mrkt_tp': '0',  # 0:코스피
			'inds_cd': sector_code,
			'stex_tp': '1'   # 1:KRX
		}
		
		logger.debug(f"Fetching sector stocks for {sector_name} (code: {sector_code})...")
		res = fetch_kw_data(endpoint, 'ka20002', params, self.token, self.mode)
		
		# 디버깅: API 응답 전체 출력
		logger.debug(f"ka20002 API response keys: {res.keys() if res else 'None'}")
		if res and 'inds_stkpc' in res:
			logger.debug(f"inds_stkpc count: {len(res['inds_stkpc'])}")
			if res['inds_stkpc']:
				logger.debug(f"First item in inds_stkpc: {res['inds_stkpc'][0]}")
		
		if not res or 'inds_stkpc' not in res:
			logger.warning(f"No stock data received for sector: {sector_name}")
			return []
		
		# 응답 파싱
		results = []
		for item in res['inds_stkpc'][:20]:  # 상위 20개
			try:
				stk_cd = item.get('stk_cd', '').strip()
				stk_nm = item.get('stk_nm', '').strip()
				cur_prc = item.get('cur_prc', '0').replace(',', '').replace('-', '').strip()
				flu_rt = item.get('flu_rt', '0').replace('+', '').replace('%', '').strip()
				now_trde_qty = item.get('now_trde_qty', '0').replace(',', '').strip()
				
				if not stk_cd or not stk_nm:
					continue
				
                # Fix: Handle signs (+/-) for price parsing/check
				price_str = cur_prc.replace('+', '').replace('-', '')
				price = int(cur_prc) if price_str.isdigit() else 0
				rate = float(flu_rt) if flu_rt and flu_rt.replace('.', '').replace('-', '').isdigit() else 0.0
				volume = int(now_trde_qty) if now_trde_qty and now_trde_qty.isdigit() else 0
				
				results.append({
					'code': stk_cd,
					'name': stk_nm,
					'price': price,
					'change': rate,
					'rate': rate,
					'open': price,
					'high': price,
					'low': price,
					'volume': volume
				})
			except (ValueError, KeyError) as e:
				logger.warning(f"Failed to parse stock item: {e}")
				continue
		
		logger.debug(f"Retrieved {len(results)} stocks for sector {sector_name}")
		
		# 디버깅: 첫 번째 종목 데이터 구조 확인
		if results:
			logger.debug(f"First stock data: {results[0]}")
		
		# Sort by change %
		return sorted(results, key=lambda x: x['change'], reverse=True)

	def get_market_indices(self):
		"""시장 지수(코스피, 코스피200, 코스닥, 코스닥150, 선물) 데이터를 가져옵니다."""
		if self.mode == "PAPER":
			return {
				"KOSPI": {"price": random.uniform(2550, 2560), "change": random.uniform(-0.5, 0.5)},
				"KOSPI 200": {"price": random.uniform(340, 345), "change": random.uniform(-0.5, 0.5)},
				"KOSDAQ": {"price": random.uniform(850, 860), "change": random.uniform(-0.8, 0.8)},
				"KOSDAQ 150": {"price": random.uniform(1300, 1310), "change": random.uniform(-0.8, 0.8)},
				"Futures": {"price": 0.0, "change": 0.0}
				}
		
		if not self.token:
			self._request_token()
			
		indices = {}
		targets = {
			"KOSPI": ("0", "001"),
			"KOSPI 200": ("0", "201"),
			"KOSDAQ": ("1", "101"),
			"KOSDAQ 150": ("1", "150"),
			"Futures": ("2", "207")
		}
		
		endpoint = '/api/dostk/sect'
		
		for name, (mrkt_tp, inds_cd) in targets.items():
			max_retries = 2
			for attempt in range(max_retries):
				try:
					params = { "mrkt_tp": mrkt_tp, "inds_cd": inds_cd }
					res_obj = fetch_kw_data(endpoint, 'ka20001', params, self.token, self.mode)
					
					# 토큰 만료 체크 (가이드: ka20001 등은 return_code 3 / 8005)
					if res_obj and (res_obj.get('return_code') == '3' or res_obj.get('code') == '3'):
						msg = str(res_obj.get('return_msg', ''))
						if '8005' in msg:
							logger.warning(f"Index Token Expired for {name}. Refreshing...")
							self.token = None
							self._request_token()
							if self.token: continue
					
					if res_obj and 'cur_prc' in res_obj:
						val_price = res_obj.get('cur_prc', '0').strip().replace(',', '')
						val_change = res_obj.get('flu_rt', '0').strip().replace('+', '').replace('%', '').replace(',', '')

						current_data = {
							"price": abs(float(val_price)),
							"change": float(val_change)
						}
						indices[name] = current_data
						self._last_indices[name] = current_data
					else:
						indices[name] = self._last_indices.get(name, {"price": 0.0, "change": 0.0})
					
					break # 성공 시 루프 탈출
					
				except Exception as e:
					logger.error(f"Failed to fetch index {name}: {e}")
					indices[name] = {"price": 0.0, "change": 0.0}
					break
			
			time.sleep(0.05)
				
		return indices

	def _get_mock_stock_data(self, sector_name):
		# 5개까지 유동적으로 생성
		stocks = []
		for i in range(1, 6):

			# Mock scenarios for testing filters
			change = random.uniform(-5, 25)
			price = random.randint(10000, 200000)
			
			# Generate Open/High based on change to simulate Wick/Gap
			if change > 10: 
				# Strong Stock
				open_p = price * (1 - change/100) * 1.02 # Gap up 2%
				high_p = price * 1.05 # 5% higher than current (Wick)
			else:
				open_p = price * 0.98
				high_p = price * 1.02
				
			stocks.append({
				"code": f"M{i:05d}",
				"name": f"{sector_name} 대장{i}",
				"price": price, 
				"open": int(open_p),
				"high": int(high_p),
				"low": int(price * 0.95),
				"change": change,
				"volume": random.randint(5000, 50000) # 거래대금(백만) -> 50억~500억
			})
		return stocks
