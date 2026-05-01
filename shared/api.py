import requests
import json
import logging
import time
import datetime
import uuid
import threading
import queue

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# 중앙 설정 상수 (하드코딩 방지)
# ----------------------------------------------------------------
REAL_HOST = "https://api.kiwoom.com"
PAPER_HOST = "https://mockapi.kiwoom.com"
DEFAULT_MODE = "PAPER" # 기본 모드 설정

# ----------------------------------------------------------------
# mode 기반 편의 함수 (Lead_Sig / AT_Sig 공용)
# ----------------------------------------------------------------

def _get_host_url(mode: str = None) -> str:
	"""모드에 따른 키움 REST API 호스트 URL 반환"""
	m = mode or DEFAULT_MODE
	return REAL_HOST if m == "REAL" else PAPER_HOST

def get_kw_token(mode: str = "PAPER", app_key: str = "", app_secret: str = "") -> str | None:
	"""mode 기반 키움 REST API 토큰 발급"""
	host_url = _get_host_url(mode)
	return get_token(host_url, app_key, app_secret)

def fetch_kw_data(endpoint: str, api_id: str, params: dict,
				  token: str, mode: str = "PAPER") -> dict | None:
	"""mode 기반 키움 REST API 단일 호출 (Retry 포함)"""
	host_url = _get_host_url(mode)
	resp = fetch_data(host_url, endpoint, api_id, params, token)
	if resp is not None:
		try:
			return resp.json()
		except (json.JSONDecodeError, Exception) as e:
			logger.error(f"파싱 오류 ({api_id}): {e} | Response: {resp.text[:100]}")
	return None

def get_token(host_url, app_key, app_secret):
	"""발급받은 토큰을 반환합니다."""
	url = host_url.rstrip('/') + '/oauth2/token'
	headers = {'Content-Type': 'application/json;charset=UTF-8'}
	data = {
		'grant_type': 'client_credentials',
		'appkey': app_key,
		'secretkey': app_secret,
	}
	try:
		response = requests.post(url, headers=headers, json=data, timeout=5)
		if response.status_code == 200:
			return response.json().get('token')
		else:
			logger.error(f"Token error: {response.status_code} - {response.text}")
	except Exception as e:
		logger.error(f"Token exception: {e}")
	return None

def generate_idempotency_key():
	"""주문 중복 방지를 위한 고유 멱등성 키 생성"""
	return str(uuid.uuid4())

# ----------------------------------------------------------------
# 전역 유량 제어 (Rate Limiting) - 429 에러 방지
# ----------------------------------------------------------------
class KiwoomRateLimiter:
	"""키움 API 유량 제한을 준수하기 위한 자가 제어기"""
	def __init__(self, tps=3):
		self.tps = tps
		self.interval = 1.0 / tps
		self.last_call_time = 0
		self._lock = threading.Lock() # 스레드 안전 호출 간격 보장

	def wait(self):
		"""호출 전 대기 시간을 계산하여 실행 간격을 조절합니다 (Thread-safe)."""
		with self._lock:
			now = time.time()
			elapsed = now - self.last_call_time
			if elapsed < self.interval:
				time.sleep(self.interval - elapsed)
			self.last_call_time = time.time()

# 전역 리미터 인스턴스 (초당 3회 제한)
_limiter = KiwoomRateLimiter(tps=3)
_session = requests.Session()

# ----------------------------------------------------------------
# 비동기 워커 시스템 (Async/Threaded Queue)
# ----------------------------------------------------------------
class ApiRequest:
	"""API 요청 정보를 담는 객체"""
	def __init__(self, func, args, kwargs, callback=None):
		self.func = func
		self.args = args
		self.kwargs = kwargs
		self.callback = callback
		self.result = None

class ThreadedApiWorker(threading.Thread):
	"""백그라운드에서 API 요청을 순차적으로 처리하는 워커"""
	def __init__(self):
		super().__init__(daemon=True)
		self.queue = queue.Queue()
		self._stop_event = threading.Event()
		self.name = "KiwoomApiWorker"

	def run(self):
		logger.info("KiwoomApiWorker started.")
		while not self._stop_event.is_set():
			try:
				# 1초 대기하며 큐에서 요청 인출
				request = self.queue.get(timeout=1.0)
				try:
					# 실제 API 함수 실행 (이미 내부에서 _limiter.wait() 적용됨)
					request.result = request.func(*request.args, **request.kwargs)
				except Exception as e:
					logger.error(f"[Worker/API오류] {request.func.__name__}: {e}")
				else:
					# [HIGH-3 수정] 콜백 예외를 별도 try/except로 분리하여 로그 명확화
					if request.callback:
						try:
							request.callback(request.result)
						except Exception as cb_e:
							logger.error(f"[Worker/콜백오류] {request.func.__name__}: {cb_e}")
				finally:
					self.queue.task_done()
			except queue.Empty:
				continue

	def submit(self, func, *args, callback=None, **kwargs):
		"""요청을 큐에 등록"""
		req = ApiRequest(func, args, kwargs, callback)
		self.queue.put(req)
		return req

# [HIGH-4 수정] 지연 초기화 패턴: 명시적 get_worker() 호출 시에만 스레드 기동
_worker: ThreadedApiWorker | None = None
_worker_lock = threading.Lock()

def get_worker() -> ThreadedApiWorker:
	"""전역 API 워커를 반환합니다. 최초 호출 시 스레드를 기동합니다."""
	global _worker
	if _worker is None:
		with _worker_lock:
			if _worker is None: # Double-checked locking
				_worker = ThreadedApiWorker()
				_worker.start()
				logger.info("KiwoomApiWorker 초기화 완료.")
	return _worker


def fetch_data(host_url, endpoint, api_id, params, token, cont_yn='N', next_key='', max_retries=3, idempotency_key=None):
	"""표준 REST API 요청 함수 (Retry 로직, 유량 제어, 멱등성 키 포함)"""
	# [HIGH-2 수정] 토큰 유효성 즉시 검증 (Fail-fast): None이면 3번 재시도 낭비 방지
	if not token:
		logger.error(f"[fetch_data] token이 None 또는 빈 값입니다. ({api_id}) API 호출을 중단합니다.")
		return None

	url = host_url.rstrip('/') + '/' + endpoint.lstrip('/')
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'api-id': api_id,
		'cont-yn': cont_yn,
		'next-key': next_key
	}
	
	# 주문 등 멱등성이 필요한 경우 헤더에 키 추가
	if idempotency_key:
		headers['X-Idempotency-Key'] = idempotency_key
	
	for attempt in range(max_retries):
		try:
			# [V40 개선] 요청 전 전역 리미터를 통한 유량 제어 발동
			_limiter.wait()
			
			# 전역 세션을 사용하여 연결 재사용
			response = _session.post(url, headers=headers, json=params, timeout=10)
			
			if response.status_code == 200:
				return response
				
			# Rate Limit (429) 및 서버 장애 (502, 503, 504) 대응
			if response.status_code in [429, 502, 503, 504]:
				wait_time = (attempt + 1) * 2
				if response.status_code == 429:
					wait_time = (attempt + 1) * 5 # 429일 경우 더 길게 대기
				logger.warning(f"Server Busy/Error ({response.status_code}) for {api_id}. Waiting {wait_time}s... ({attempt+1}/{max_retries})")
				time.sleep(wait_time)
				continue
			
			logger.error(f"API Error {api_id}: {response.status_code} - {response.text[:200]}")
			return None
			
		except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
			# 10054 (Connection Reset) 포함 네트워크 끊김 대응
			wait_time = (attempt + 1) * 3
			logger.warning(f"Network issue {api_id}: {e}. Retrying after {wait_time}s... ({attempt+1}/{max_retries})")
			time.sleep(wait_time)
			
		except requests.exceptions.RequestException as e:
			logger.warning(f"Request exception {api_id}: {e}. Retrying...")
			time.sleep(1)
			
	return None

def _sanitize_numeric(val):
	"""문자열 숫자를 안전하게 float으로 변환 (콤마, 퍼센트, 부호 제거 후 절대값)"""
	if val is None: return 0.0
	if isinstance(val, (int, float)): return abs(float(val))
	try:
		clean_s = str(val).replace(',', '').replace('%', '').replace('+', '').replace('-', '').strip()
		if not clean_s or clean_s == '-' or clean_s == '--': return 0.0
		return abs(float(clean_s))
	except:
		return 0.0

_INDEX_MRKT_MAP = {'001': '0', '101': '1', '201': '2', '701': '7'}

def _index_to_mrkt_tp(index_cd: str) -> str:
	"""업종 코드 → 시장구분 코드 변환 (중복 로직 통합)"""
	return _INDEX_MRKT_MAP.get(index_cd, '1')

def fetch_daily_chart(host_url, stk_cd, token, days=500, base_dt=None):
	"""주식 일봉 차트 연속 조회 (ka10081)"""
	if not base_dt:
		base_dt = datetime.datetime.now().strftime("%Y%m%d")
	
	all_data = []
	cont_yn = 'N'
	next_key = ''
	
	while len(all_data) < days:
		params = {'stk_cd': stk_cd, 'base_dt': base_dt, 'upd_stkpc_tp': '1'}
		resp = fetch_data(host_url, '/api/dostk/chart', 'ka10081', params, token, cont_yn, next_key)
		if not resp: break
		
		data = resp.json()
		chart_data = data.get('stk_dt_pole_chart_qry') or data.get('stk_day_chart_qry') or data.get('output', [])
		if not chart_data: break
		
		for row in chart_data:
			for key in ['open_pric', 'high_pric', 'low_pric', 'cur_prc', 'trde_qty', 'trde_prica', 'open_prc', 'high_prc', 'low_prc', 'close_prc']:
				if key in row: row[key] = _sanitize_numeric(row[key])
					
		all_data.extend(chart_data)
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		if len(all_data) < days: time.sleep(0.5)
			
	all_data.sort(key=lambda x: x.get('dt') or x.get('base_dt', '00000000'))
	return all_data[-days:]

def fetch_minute_chart_ka10080(host_url, stk_cd, token, min_tp='1'):
	"""주식 분봉 차트 조회 (ka10080)"""
	params = {'stk_cd': stk_cd, 'tic_scope': min_tp, 'upd_stkpc_tp': '1'}
	resp = fetch_data(host_url, '/api/dostk/chart', 'ka10080', params, token)
	if not resp: return []
	data = resp.json()
	raw_list = data.get('stk_min_pole_chart_qry') or data.get('output', [])
	
	normalized = []
	for row in raw_list:
		full_tm = str(row.get('cntr_tm', ''))
		normalized.append({
			'stck_bsop_date': full_tm[:8],
			'stck_cntg_hour': full_tm[8:],
			'stck_prpr': _sanitize_numeric(row.get('cur_prc')),
			'stck_oprc': _sanitize_numeric(row.get('open_pric')),
			'stck_hgpr': _sanitize_numeric(row.get('high_pric')),
			'stck_lwpr': _sanitize_numeric(row.get('low_pric')),
			'cntg_vol': _sanitize_numeric(row.get('trde_qty')),
			'acml_tr_pbmn': _sanitize_numeric(row.get('acc_trde_qty'))
		})
	normalized.sort(key=lambda x: (x['stck_bsop_date'], x['stck_cntg_hour']))
	return normalized

def fetch_stock_basic_ka10001(host_url, stk_cd, token):
	"""주식 기본 정보 조회 (ka10001)"""
	params = {'stk_cd': stk_cd}
	resp = fetch_data(host_url, '/api/dostk/basic', 'ka10001', params, token)
	if not resp: return None
	data = resp.json() # [최적화] 한 번만 파싱하여 진행
	raw = data.get('stk_basic_info_qry') or data.get('output', {})
	for key in ['stck_prpr', 'prdy_ctrt', 'acml_vol', 'askp1', 'bidp1', 'total_askp_rsqn', 'total_bidp_rsqn']:
		if key in raw: raw[key] = _sanitize_numeric(raw[key])
	return raw

# [최적화] 중복 함수 fetch_stock_info를 fetch_stock_basic_ka10001의 별칭으로 설정하여 코드량 축소
fetch_stock_info = fetch_stock_basic_ka10001

def fetch_index_current_price_ka20001(host_url, index_cd, token):
	"""업종/지수 실시간 현재가 조회 (ka20001)"""
	mrkt_tp = _index_to_mrkt_tp(index_cd) # [최적화] 헬퍼 함수 사용

	params = {'mrkt_tp': mrkt_tp, 'inds_cd': index_cd}
	resp = fetch_data(host_url, '/api/dostk/sect', 'ka20001', params, token)
	if not resp: return None
	
	try:
		res = resp.json()
		if res and 'cur_prc' in res:
			return {
				'cur_prc': _sanitize_numeric(res.get('cur_prc', '0')),
				'flu_rt': float(str(res.get('flu_rt', '0')).replace(',', '').replace('%', ''))
			}
		return None
	except Exception as e:
		logger.error(f"ka20001 parsing error: {e}")
		return None

def fetch_index_chart(host_url, index_cd, token, days=600):
	"""업종/지수 차트 조회"""
	all_data = []
	cont_yn = 'N'
	next_key = ''
	
	curr_price_info = fetch_index_current_price_ka20001(host_url, index_cd, token)
	
	mrkt_tp = _index_to_mrkt_tp(index_cd) # [최적화] 헬퍼 함수 재사용
	
	base_dt = datetime.datetime.now().strftime("%Y%m%d")
	page_count = 0
	
	while len(all_data) < days and page_count < 5:
		page_count += 1
		params = {'mrkt_tp': mrkt_tp, 'inds_cd': index_cd}
		resp = fetch_data(host_url, '/api/dostk/sect', 'ka20009', params, token, cont_yn, next_key)
		
		if resp:
			data = resp.json()
			chart_data = data.get('inds_cur_prc_daly_rept', [])
			if chart_data:
				for row in chart_data:
					for key in ['open_prc', 'high_prc', 'low_prc', 'close_prc', 'trd_qty', 'trd_amt']:
						if key in row: row[key] = _sanitize_numeric(row[key])
				all_data.extend(chart_data)
				cont_yn = resp.headers.get('cont-yn', 'N')
				next_key = resp.headers.get('next-key', '')
				if cont_yn != 'Y' or not next_key: break
				time.sleep(0.5)
				continue
		
		# ka20009 실패 시 fallback: ka20006 호출 (cont_yn 오염 방지를 위해 초기화)
		cont_yn = 'N'
		next_key = ''
		params = {'inds_cd': index_cd, 'base_dt': base_dt}
		resp = fetch_data(host_url, '/api/dostk/chart', 'ka20006', params, token, cont_yn, next_key)
		if not resp: break
			
		data = resp.json()
		chart_data = data.get('inds_dt_pole_qry') or data.get('output', [])
		if not chart_data: break
		
		for row in chart_data:
			p_col = 'close_prc' if 'close_prc' in row else 'cur_prc'
			row['close_prc'] = _sanitize_numeric(row.get(p_col, 0))
			all_data.append(row)
		
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		time.sleep(0.5)

	if curr_price_info:
		today_str = base_dt
		updated = False
		for i, d in enumerate(all_data):
			if d.get('stck_bsop_date') == today_str or d.get('dt') == today_str:
				all_data[i]['close_prc'] = curr_price_info['cur_prc']
				updated = True
				break
		if not updated:
			all_data.insert(0, {'dt': today_str, 'close_prc': curr_price_info['cur_prc']})

	return all_data

def fetch_brokerage_data(host_url, stk_cd, token):
	"""종목별 거래원(창구) 현황 조회 (ka10002)"""
	params = {'stk_cd': stk_cd}
	resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10002', params, token)
	return resp.json() if resp else None

def fetch_brokerage_rank_ka10038(host_url, stk_cd, token, st_dt, ed_dt, dt='19'):
	"""종목별증권사순위요청 (ka10038)"""
	params = {'stk_cd': stk_cd, 'strt_dt': st_dt, 'end_dt': ed_dt, 'qry_tp': '2', 'dt': dt}
	resp = fetch_data(host_url, '/api/dostk/rkinfo', 'ka10038', params, token)
	if resp:
		data = resp.json()
		return data.get('stk_sec_rank') or data.get('output') or []
	return None

def fetch_brokerage_period_ka10042(host_url, stk_cd, token, st_dt, ed_dt):
	"""순매수거래원순위요청 (ka10042)"""
	params = {'stk_cd': stk_cd, 'strt_dt': st_dt, 'end_dt': ed_dt, 'qry_dt_tp': '0', 'pot_tp': '0', 'dt': '20', 'sort_base': '1'}
	resp = fetch_data(host_url, '/api/dostk/rkinfo', 'ka10042', params, token)
	if resp:
		data = resp.json()
		return data.get('netprps_trde_ori_rank') or data.get('output', [])
	return None

def fetch_investor_trends(host_url, stk_cd, token, days=20):
	"""종목별 투자자별 매매동향 연속 조회 (ka10009)"""
	all_data = []
	cont_yn = 'N'
	next_key = ''
	while len(all_data) < days:
		params = {'stk_cd': stk_cd}
		resp = fetch_data(host_url, '/api/dostk/frgnistt', 'ka10009', params, token, cont_yn, next_key)
		if not resp: break
		data = resp.json()
		trends = data.get('stk_ivst_trde_trnd_qry') or data.get('stk_ivst_trde_trnd_qry_list') or data.get('daly_trde_dtl') or data.get('output', [])
		if not trends: break
		all_data.extend(trends)
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		time.sleep(0.5)
	return all_data[:days]

def fetch_continuous_trading_status(host_url, token, params, cont_yn='N', next_key=''):
	"""기관외국인연속매매현황요청 (ka10131)"""
	resp = fetch_data(host_url, '/api/dostk/frgnistt', 'ka10131', params, token, cont_yn, next_key)
	return resp.json() if resp else None

def fetch_stock_institution_summary(host_url, stk_cd, token):
	"""주식기관요청 (ka10009)"""
	params = {'stk_cd': stk_cd}
	resp = fetch_data(host_url, '/api/dostk/frgnistt', 'ka10009', params, token)
	return resp.json() if resp else None

def fetch_investor_details_ka10059(host_url, stk_cd, token, days=20, base_dt=None):
	"""종목별 투자자 기관별 상세 조회 (ka10059)"""
	if not base_dt: base_dt = datetime.datetime.now().strftime("%Y%m%d")
	all_data = []
	cont_yn = 'N'
	next_key = ''
	while len(all_data) < days:
		params = {'stk_cd': stk_cd, 'dt': base_dt, 'amt_qty_tp': '2', 'trde_tp': '0', 'unit_tp': '1'}
		resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10059', params, token, cont_yn, next_key)
		if not resp: break
		data = resp.json()
		trends = data.get('stk_invsr_orgn') or data.get('output', [])
		if not trends: break
		all_data.extend(trends)
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		time.sleep(0.5)
	return all_data[:days]

def fetch_stock_basic_info(host_url, stk_cd, token):
	"""주식기본정보요청 (ka10001) - 상장주식수 등 조회"""
	params = {'stk_cd': stk_cd}
	resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10001', params, token)
	if resp:
		data = resp.json()
		stk_info = data.get('stk_info', [])
		if stk_info:
			info = stk_info[0]
			def to_int(v): return int(str(v).replace(',', '')) if v and str(v).strip() else 0
			raw_close = str(info.get('stck_prpr', '0')).replace(',', '').replace('+', '').replace('-', '')
			return {
				'floating_shares': to_int(info.get('flo_stk')) * 1000,
				'circulating_shares': to_int(info.get('dstr_stk')) * 1000,
				'circulating_ratio': float(info.get('dstr_rt') or 0.0),
				'current_price': int(raw_close) if raw_close.isdigit() else 0,
				'volume': to_int(info.get('acml_tr_vol'))
			}
	return None

def fetch_market_ranking_ka10027(host_url, token, page=1):
	"""주식등락률상위요청 (ka10027)"""
	params = {'mrkt_tp': '000', 'sort_tp': '1', 'updown_incls': '1', 'trde_qty_cnd': '0000', 'stk_cnd': '0', 'crd_cnd': '0', 'pric_cnd': '0', 'trde_prica_cnd': '0', 'stex_tp': '3'}
	cont_yn = 'Y' if page > 1 else 'N'
	resp = fetch_data(host_url, '/api/dostk/rkinfo', 'ka10027', params, token, cont_yn=cont_yn)
	if resp: return resp.json().get('pred_pre_flu_rt_upper') or resp.json().get('output', [])
	return []

def fetch_market_ranking_ka10032(host_url, token, page=1):
	"""주식거래대금상위요청 (ka10032)"""
	now_dt = datetime.datetime.now().strftime('%Y%m%d')
	params = {'mrkt_tp': '000', 'mang_stk_incls': '0', 'stex_tp': '3', 'base_dt': now_dt}
	cont_yn = 'Y' if page > 1 else 'N'
	resp = fetch_data(host_url, '/api/dostk/rkinfo', 'ka10032', params, token, cont_yn=cont_yn)
	if resp: return resp.json().get('trde_prica_upper') or resp.json().get('output', [])
	return []

def fetch_program_ranking_ka90003(host_url, token, mrkt_tp='P00101', trde_tp='2', limit=50):
	"""프로그램매매순매수상위50요청 (ka90003)"""
	all_data = []
	cont_yn = 'N'
	next_key = ''
	params = {'trde_upper_tp': trde_tp, 'amt_qty_tp': '1', 'mrkt_tp': mrkt_tp, 'stex_tp': '1'}
	while len(all_data) < limit:
		resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka90003', params, token, cont_yn, next_key)
		if not resp: break
		items = resp.json().get('prm_netprps_upper_50') or resp.json().get('output', [])
		if not items: break
		all_data.extend(items)
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		time.sleep(0.3)
	return all_data[:limit]

def fetch_market_program_trend_ka90007(host_url, token, mrkt_tp='0', date=''):
	"""프로그램매매누적추이요청 (ka90007)"""
	if not date: date = datetime.datetime.now().strftime('%Y%m%d')
	params = {'date': date, 'amt_qty_tp': '1', 'mrkt_tp': mrkt_tp, 'stex_tp': '3'}
	resp = fetch_data(host_url, '/api/dostk/mrkcond', 'ka90007', params, token)
	if resp: return resp.json().get('prm_trde_acc_trnsn') or resp.json().get('output', [])
	return []

def fetch_stock_program_trend_ka90008(host_url, token, stk_cd, date=''):
	"""종목시간별프로그램매매추이요청 (ka90008)"""
	if not date: date = datetime.datetime.now().strftime('%Y%m%d')
	params = {'amt_qty_tp': '1', 'stk_cd': stk_cd, 'date': date}
	resp = fetch_data(host_url, '/api/dostk/mrkcond', 'ka90008', params, token)
	if resp: return resp.json().get('stk_tm_prm_trde_trnsn') or resp.json().get('output', [])
	return []

def fetch_stock_program_daily_ka90013(host_url, stk_cd, token, days=20):
	"""종목일별프로그램매매추이요청 (ka90013)"""
	now_dt = datetime.datetime.now().strftime('%Y%m%d')
	all_data = []
	cont_yn = 'N'
	next_key = ''
	for i in range(10):
		params = {'stk_cd': stk_cd, 'base_dt': now_dt, 'upd_stkpc_tp': '1'}
		resp = fetch_data(host_url, '/api/dostk/mrkcond', 'ka90013', params, token, cont_yn, next_key)
		if not resp: break
		items = resp.json().get('stk_daly_prm_trde_trnsn') or resp.json().get('output', [])
		if not items: break
		all_data.extend(items)
		cont_yn = resp.headers.get('cont-yn', 'N')
		next_key = resp.headers.get('next-key', '')
		if cont_yn != 'Y' or not next_key: break
		time.sleep(0.3)
	return all_data[:days]
