import asyncio
import sys
import time
import logging
from datetime import datetime
import concurrent.futures
import multiprocessing
import csv
import os
import json
from data_manager import DataManager
from strategy_runner import StrategyRunner
from rt_search import RealTimeSearch
from core.broker_adapter import BrokerAdapter
from core.models import StockItem
from check_n_sell import chk_n_sell 
from login import fn_au10001 as get_token
from tel_send import tel_send
from get_setting import get_setting, update_setting
from stock_info import get_stock_info_async
from shared.market_status import MarketStatusEngine, MarketRegime
from shared.market_hour import MarketHour
from stock_radar import StockRadar
from core.minute_builder import MinuteBuilder
from shared.indicators import TechnicalIndicators as TI
from history_manager import record_captured, load_today_captured


# [Import Accumulation Manager from Shared Core]
try:
    from shared.accumulation_manager import AccumulationManager
except ImportError as e:
    print(f"AccumulationManager Import Failed: {e}")
    AccumulationManager = None


class TradingEngine:
	"""
	자동매매 시스템의 핵심 엔진.
	데이터 관리, 전략 실행, 매매 실행, 상태 관리를 총괄합니다.
	"""
	def __init__(self, ui_callback=None):
		self.logger = logging.getLogger("AT_Sig.TradingEngine")
		
		# 컴포넌트 초기화
		self.data_manager = DataManager()
		self.strategy_runner = StrategyRunner()
		self.rt_search = RealTimeSearch(on_connection_closed=self._on_rt_closed)
		self.broker = BrokerAdapter()
		
		self.pool = concurrent.futures.ProcessPoolExecutor(max_workers=multiprocessing.cpu_count())

		# 매집 분석 관리자
		self.acc_mgr = AccumulationManager() if AccumulationManager else None

		# 상태 변수
		self.is_running = False
		self.token = None
		self.check_sell_task = None
		self.ui_callback = ui_callback 
		self.watchlist_task = None
		self.gap_monitoring_stocks = {} # [NEW] 시가 갭 회복 매매 전용 감시 목록
		self.atr_targets = {}          # [NEW] 5번 모드: ATR 기반 돌파 목표가 저장
		
		# [안실장 픽스] 재시작 시 포착 내역 복구
		self.captured_stocks = set()
		self._initial_captured_data = load_today_captured()
		for item in self._initial_captured_data:
			if 'code' in item:
				self.captured_stocks.add(item['code'])

		# [안실장 신규] 시장 상황 분석 엔진
		self.market_engine = None 
		self.current_regime = None # {regime: MarketRegime, kospi: {}, kosdaq: {}}
		self.market_status_task = None
		
		
		# [Stock Radar Init]
		self.stock_radar = StockRadar() if StockRadar else None
		self.min_builder = MinuteBuilder()
		
		# API Sessions
		self.api_session = None
		self.warmup_sem = None # Deferred init
		self.global_rest_sem = None # [NEW] 모든 배경 작업(정보충전, 차트캐싱) 통합 조율
		
		# [Enrichment Queue] Deferred Init to avoid 'No running event loop'
		self.enrich_queue = None
		self.enriched_codes = set()
		self.enriching_codes = set() # Currently in queue
		self.enrich_worker_task = None
		
		self.processing_stocks = set()
		self.radar_cooldown = {}
		self.radar_init_lock = None # [NEW] 레이더 초기화 패싱용 락
		self.momentum_lock = None   # [NEW] 모멘텀 분석 패싱용 락
		self.last_429_time = 0      # [NEW] 전역 속도제한 추적
		
		# Pending Buy Count for rate limiting
		self.pending_buy_count = 0
		self.is_warming_up = False # [Point 1] 초기 웜업 상태 플래그
		
		# [안실장 픽스] 시장 신호 및 배수 관리자 초기화
		try:
			from shared.signal_manager import MarketSignalManager
			self.signal_manager = MarketSignalManager()
		except Exception as e:
			self.logger.warning(f"SignalManager 초기화 실패: {e}")
		
		# [NEW] 지수 정보 및 매수 가격 정보 캐시 (API 부하 감소용)
		self.market_index_cache = {"KOSPI": None, "KOSDAQ": None, "time": 0}
		self.balance_cache = {"value": 0, "time": 0}
		self.holdings_cache = {"value": [], "time": 0}
		self.last_buy_attempt = 0
		
		# [안실장 픽스] 종목별 과거 분봉 데이터 로딩 완료 상태 추적
		self.history_loaded_codes = set()

	def is_market_open(self):
		"""현재 시간이 한국 주식 시장 정규 장 운영 시간(09:00~15:30)인지 확인"""
		return MarketHour.is_market_open_time()

	def log(self, message):
		self.logger.info(message)
		try:
			print(message) 
		except UnicodeEncodeError:
			try:
				print(message.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
			except:
				pass
		if self.ui_callback:
			try: self.ui_callback("log", message)
			except: pass

	def is_eligible_stock(self, code, name, price=0):
		"""
		개별 종목 여부를 확인하여 ETF, ETN, 우선주, 선물, 특정 키워드(KODEX, 레버리지 등)를 제외합니다.
		[안실장 가이드] 5,000원 미만 저가주 및 개별 종목이 아닌 상품군을 필터링.
		"""
		if not code:
			return False
		
		# [새로운 규칙] 5,000원 미만 저가주(동전주 포함) 제외
		if price > 0 and price < 5000:
			self.logger.debug(f"🚫 [필터:시세] {name}({code}) {price}원 - 5,000원 미만 제외")
			return False

		# 1. 코드 기반 필터링 (표준 6자리 숫자가 아니거나 우선주인 경우 제외)
		code_str = str(code).replace('A', '').strip()
		
		# [안실장 픽스] 영문 포함 종목코드(0008Z0 등)도 유효 종목일 수 있으므로 길이만 체크
		if len(code_str) != 6:
			self.logger.debug(f"🚫 [필터:코드] {name}({code}) - 비표준 코드 길이 제외")
			return False

		if code_str[-1] != '0' and code_str[-1].isdigit():
			# 마지막 자리가 숫자이면서 0이 아니면 (5, 7 등) 우선주로 간주
			return False

		if not name or name == 'Unknown':
			# 이름 정보를 아직 모르는 경우, 일단 정보를 가져와야 하므로 필터 통과 (추후 재확인)
			return True

		# 2. 키워드 필터링 (사용자 요청: ETF, ETN, KODEX, 레버리지, 인버스, 선물, 우선주 제외)
		name_upper = name.upper()
		deny_keywords = ["ETF", "ETN", "KODEX", "레버리지", "인버스", "선물", "우선주"]
		
		for kw in deny_keywords:
			if kw in name_upper:
				return False
		
		# 3. 우선주 패턴 매칭 (이름 끝자리 추가 검증)
		# 6번째 자리가 0임에도 이름상 우선주인 경우 방어
		if name.endswith('우') or name.endswith('우B') or name.endswith('우C') or name.endswith('우(전환)'):
			return False
			
		return True

	def save_captured_stock(self, code, name, source="RealTime", target="-"):
		"""포착된 종목을 CSV 및 JSON 히스토리에 저장 (중복 방지)"""
		if code in self.captured_stocks:
			return

		self.captured_stocks.add(code)
		
		# [JSON 히스토리 기록 - 재시작 시 UI 복원용]
		record_captured(code, {
			"code": code,
			"name": name,
			"time": datetime.now().strftime("%m/%d %H:%M:%S"),
			"price": "0",
			"target": target,
			"ratio": "0.00",
			"msg": f"🎯 {source}"
		})

		try:
			today = datetime.now().strftime("%Y-%m-%d")
			filename = f"captured_stocks_{today}.csv"
			filepath = os.path.join(os.getcwd(), filename)
			
			exists = os.path.exists(filepath)
			
			with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
				writer = csv.writer(f)
				if not exists:
					writer.writerow(["Time", "Code", "Name", "Source"])
				
				writer.writerow([
					datetime.now().strftime("%m/%d %H:%M:%S"),
					code,
					name,
					source
				])
		except Exception as e:
			self.logger.error(f"Save captured CSV error: {e}")
		
		# [안실장 픽스] CSV 저장 여부와 상관없이 무조건 매집 분석 풀에 등록하여 백그라운드 스캔이 작동하게 함
		if hasattr(self, 'acc_mgr') and self.acc_mgr:
			self.acc_mgr.add_to_captured_pool(code, source)

	def save_condition_candidates(self, stock_list, seq):
		"""조건검색 결과(후보군)를 CSV 파일에 저장 (사용 안 함)"""
		pass



	async def handle_rt_message(self, response):
		"""
		WebSocket Raw Message Handler
		- Detect Condition Search Initial List or relevant data to Warm-up
		"""
		self._ensure_async_objects()

		try:
			if not response: return
			trnm = response.get('trnm')
			
			# Skip PING/LOGIN as they are handled in rt_search
			# Skip CNSRLST (Condition list query) as it contains search names, not stocks
			if trnm in ['PING', 'LOGIN', 'CNSRLST']: 
				return

			# [안실장 픽스] 초기조회(CNSRREQ) 수신 시 백그라운드 웜업 시작
			if trnm == 'CNSRREQ':
				data_list = response.get('output') or response.get('data') or []
				if data_list:
					# [Secure Check] item이 None이거나 dict가 아닌 경우 방어
					codes = [item.get('code') for item in data_list if item and isinstance(item, dict) and item.get('code')]
					if codes:
						asyncio.create_task(self.warm_up_stocks(codes))

			# [Debug] CNSR/REAL Packet Log
			if trnm in ['CNSR', 'CNSRREQ', 'REAL']:
				# ... (기존 로직 유지)
				seq_raw = response.get('seq')
				if not seq_raw and trnm == 'REAL':
					# Extract from first item's values if possible
					data_chk = response.get('output') or response.get('data') or []
					if data_chk and isinstance(data_chk, list) and len(data_chk) > 0:
						first_item = data_chk[0]
						if first_item and isinstance(first_item, dict):
							seq_raw = first_item.get('values', {}).get('841')
				
				seq = str(seq_raw or '?').strip()
				cond_name = self.rt_search.seq_to_name.get(seq, f"조건식({seq})")
				
				# [안실장 픽스] 매매 대상(is_trading_seq)은 오직 [조건검색식 선택] 리스트로 한정 (0, 1번은 웜업용으로 전면 제외)
				trading_seq_list = [str(s) for s in get_setting('search_seq_list', []) if str(s) not in ['0', '1']][:10]
				is_trading_seq = seq in trading_seq_list
				
				# 관심종목(0, 1번)은 '관심종목 검색식 활용' 체크 시에만 모니터링 및 UI 표시 수행 (매매는 금지)
				use_interest_toggle = get_setting('use_interest_formula', False)
				if seq in ['0', '1'] and not use_interest_toggle:
					return
				
					
				is_real = str(response.get('real_yn', '0')) == '1' or trnm == 'REAL'
				search_tp = "실시간" if is_real else "단순조회"
				
				count_val = response.get('count')
				data_chk = response.get('output') or response.get('data') or []
				safe_count = len(data_chk) if isinstance(data_chk, list) else 0
				
				# [Optimization] REAL 패킷은 로그 빈도가 너무 높으므로 초기조회(CNSRREQ)만 명시적 로깅
				ret_code = response.get('return_code', 0)
				msg_type = "초기조회" if trnm == 'CNSRREQ' else "포착"
				
				if str(ret_code) != '0':
					self.log(f"❌ [{cond_name}] {msg_type} 에러: {ret_code} ({response.get('return_msg', '사유미상')})")
				elif trnm == 'CNSRREQ':
					self.log(f"🔎 [{cond_name}] {search_tp}({msg_type}) 결과: {safe_count}개 종목")
				else:
					# REAL 패킷 등은 디버그 레벨에서만 기록 (UI 전송은 유지)
					self.logger.debug(f"[{cond_name}] {search_tp}({msg_type}) 포착: {safe_count}개")
			
			# Check for list or string data
			wrapped_data = response.get('output') or response.get('data')
			data_list = []
			
			if isinstance(wrapped_data, list):
				data_list = wrapped_data
			elif isinstance(wrapped_data, str) and wrapped_data.strip():
				# Handle concatenated string formats (e.g. "005930;000660" or "005930,000660")
				if ';' in wrapped_data: data_list = wrapped_data.split(';')
				elif ',' in wrapped_data: data_list = wrapped_data.split(',')
				else: data_list = [wrapped_data]

			if data_list:
				normalized_items = []
				for raw_item in data_list:
					item = None
					if isinstance(raw_item, dict):
						item = StockItem.from_api_dict(raw_item)
					elif isinstance(raw_item, (list, tuple)):
						item = StockItem.from_api_list(raw_item)
					elif isinstance(raw_item, str):
						item = StockItem(code=raw_item)

					if item and item.code:
						# [Validation] Stock codes in Korea are usually 6 digits. 
						# Filter out debris (like '0', '1' from metadata)
						clean_code = str(item.code).strip()
						if len(clean_code) >= 6:
							# [안실장 가이드] 개별 종목 필터링 적용 (현시점에서 이름이 있으면 체크)
							if not self.is_eligible_stock(clean_code, item.name, item.price):
								continue
							# [Enrichment] Use Cache if name is unknown or invalid
							if (item.name in ['Unknown', '조건검색'] or not item.name) and hasattr(self.broker, 'name_cache'):
								cached_name = self.broker.name_cache.get(item.code)
								# [Defensive] 만약 캐시에 dict가 들어있다면 문자열 추출
								if isinstance(cached_name, dict):
									cached_name = cached_name.get('stk_nm') or cached_name.get('name') or cached_name.get('code_name') or "Unknown"
									
								if not cached_name or cached_name in ['Unknown', '조건검색']:
									# 브로커에 직접 조회 (가벼운 마스터 정보)
									cached_name = self.broker.get_stock_name(item.code)
									if isinstance(cached_name, dict):
										cached_name = cached_name.get('stk_nm') or cached_name.get('name') or "Unknown"

								if cached_name and cached_name not in ['Unknown', '조건검색']: 
									item.name = cached_name
							
							# 만약 여전히 Unknown이라면 웜업 큐에 등록하여 정보 충전 시도
							# [안실장 가이드] 대기열이 너무 길면 패싱 (API 쿼터 보호)
							if item.name == 'Unknown':
								if self.enrich_queue.qsize() < 120:
									priority = 0 if trnm in ['CNSR', 'REAL'] else 10
									self.enrich_queue.put_nowait((priority, item.code))
								else:
									self.logger.debug(f"⚠️ [패싱] 대기열 과다({self.enrich_queue.qsize()})로 {item.code} 정보충전 생략")
							
							normalized_items.append(item)
							# Cache Optimization
							if hasattr(self.broker, 'name_cache') and item.name != 'Unknown':
								self.broker.name_cache[item.code] = item.name

				if normalized_items:
					# [Diet] 초기 전체 리스트(CNSRREQ)의 경우 상위 30개만 정예로 추출하여 API 부하 차단
					if trnm == 'CNSRREQ' and len(normalized_items) > 30:
						normalized_items = normalized_items[:30]
						self.log(f"   ⚠️ [최적화] 초기 검색 결과가 너무 많아 상위 30개 종목으로 압축하여 감시를 시작합니다.")

					codes = [it.code for it in normalized_items]
					preview = ", ".join(codes[:5])
					
					if trnm == 'CNSRREQ':
						self.log(f"   -> {len(normalized_items)}개 정예 종목 추출 완료 ({preview}...)")
					
					# [안실장 픽스] 모든 종목(초기 조회 포함)을 UI에 표시하도록 최적화 해제
					# 감시 및 데이터 로딩은 백그라운드에서 정상 수행됩니다.
					skip_ui_for_initial = False 
					
					# [중요] 모드별 즉시 대응 로직 미리 확인
					mode = get_setting('trading_mode', 'cond_base')
					
					# [NEW] 투트랙 운영 모드 (10시 이후 가속도 공략 변환)
					if mode in ['lw_breakout', 'gap_recovery'] and get_setting('use_two_track', False):
						if datetime.now().hour >= 10:
							mode = 'cond_stock_radar'

					# [안실장 고도화] 1. 포착 즉시 실시간 시세(REG) 등록 (Ticks 수신 시작)
					# 이것이 선행되어야 handle_rt_data(Ticks)에서 후속 매수가 작동합니다.
					asyncio.create_task(self.rt_search.register_sise(codes, self.token))

					msg_type_str = "실시간포착" if trnm in ['CNSR', 'REAL'] else ("초기감시" if trnm == 'CNSRREQ' else "감시대기")
					for item in normalized_items:
						# [안실장 정밀분석] 1번 '심플 조건검색' 즉시매수 로직 확인
						if is_trading_seq:
							# 1. 대상 모드 확인 (기본 모드이거나 전략 미선택 시)
							st_file = get_setting('active_strategy', '선택안함')
							is_simple_buy_mode = mode in ['cond_only', 'cond_base'] and st_file in ['선택안함', '', 'None']
							
							if is_simple_buy_mode:
								# 2. 신호 유형 및 락 상태 확인
								if trnm in ['CNSR', 'REAL']:
									if item.code not in self.processing_stocks:
										self.processing_stocks.add(item.code)
										self.log(f"⚡ [즉시매수/1번] {item.name}({item.code}) 조건식 포착 즉시 진입!")
										asyncio.create_task(self.process_buy(item.code, stock_name=item.name, msg_override="조건식포착즉시매수"))
										asyncio.get_running_loop().call_later(300, lambda c=item.code: self.processing_stocks.discard(c))
									else:
										self.logger.debug(f"[매수스킵] {item.name}: 이미 처리 중이거나 쿨다운 상태입니다.")
								else:
									self.logger.debug(f"[매수스킵] {item.name}: 초기조회(CNSRREQ) 신호이므로 즉시매수를 건너뜁니다.")
							else:
								# 매수 조건에 부합하지 않는 상태일 경우 로그 (디버깅용)
								if mode == 'cond_stock_radar':
									self.logger.debug(f"[매수스킵] {item.name}: 현재 가속도(Radar) 모드이므로 틱 분석 후 진입합니다.")
								elif mode == 'volatility_breakout':
									self.logger.debug(f"[매수스킵] {item.name}: 변동성 마디(ATR) 돌파를 대기합니다.")
								elif st_file not in ['선택안함', '', 'None']:
									self.logger.debug(f"[매수스킵] {item.name}: 전략({st_file})이 선택되어 있어 필터링 대기합니다.")
							
							# [안실장 고도화] 레이더 및 UI 업데이트를 위한 비동기 처리 (지연 방지 핵심)
							async def process_radar_and_ui(stk_item, msg_type):
								acc_msg = ""
								radar_msg = ""
								is_urgent = False
								
								if self.acc_mgr:
									q_info = self.acc_mgr.get_accumulation_quality(stk_item.code)
									if q_info.get('is_premium'):
										acc_msg = f" | {q_info['desc']}"
								
								# [안실장 고도화] 실시간 에너지 분석
								if self.stock_radar and trnm in ['CNSR', 'REAL']:
									# 분석 중인 종목이 있으면 다음은 "패싱" (429 방어)
									if self.momentum_lock.locked():
										radar_msg = " | 대기중(패싱)"
									else:
										async with self.momentum_lock:
											# [FIX] cached_rt 인자 누락 수정하여 정확한 실시간 데이터 분석 수행
											cached_rt = self.rt_search.get_cached_price(stk_item.code)
											momentum = await self.stock_radar.analyze_momentum(stk_item.code, cached_rt=cached_rt, session=self.api_session)
											if momentum['score'] >= 50:
												radar_msg = f" | {momentum['msg']}"
												if momentum['is_exploding']:
													is_urgent = True
													radar_msg = f" | 🔥 [에너지폭발] {momentum['msg']}"
											elif momentum.get('limit'):
												radar_msg = " | 속도제한(429)"

								# [안실장 픽스] 포착 즉시 가장 신선한 가격 확보 로직
								c_price = stk_item.price if stk_item.price > 0 else 0
								if c_price == 0:
									cached_rt = self.rt_search.get_cached_price(stk_item.code)
									c_price = cached_rt.get('price', 0) if cached_rt else 0
								
								# [안실장 픽스] 가격 정보가 없으면 매매 및 추적이 불가능하므로 등록 취소
								if c_price <= 0:
									self.logger.debug(f"🚫 [등록취소] {stk_item.name}({stk_item.code}): 가격 정보 획득 실패")
									return

								# [안실장 픽스] 포착 즉시 매수 목표가(Target Price) 산출 시도
								target_val = "-"
								st_file = get_setting('active_strategy', '선택안함')
								if st_file not in ['선택안함', '', 'None']:
									try:
										# 전략 코드 로드
										root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
										st_path = os.path.join(root_dir, 'shared', 'strategies', st_file)
										if os.path.exists(st_path):
											with open(st_path, 'r', encoding='utf-8') as f:
												st_json = json.load(f)
												st_code = st_json.get('python_code', '')
												st_min_bars = st_json.get('min_bars', 70)
												
												if st_code:
													# 백그라운드에서 조용히 분석 (현재가/시가 가공 없이 목표가만 추출용)
													loop = asyncio.get_event_loop()
													res = await loop.run_in_executor(
														self.trade_pool,
														lambda: self.strategy_runner.check_signal(stk_item.code, self.token, st_code, c_price, min_bars=st_min_bars)
													)
													t_raw = res.get('target', 0)
													if t_raw and float(t_raw) > 0:
														target_val = f"{int(float(t_raw)):,}"
														# [전략우선원칙] 전략에서 타점이 나오면 5번 모드용 타점으로 우선 등록
														if mode == 'volatility_breakout':
															self.atr_targets[stk_item.code] = int(float(t_raw))
															self.logger.info(f"🎯 [전략타점] {stk_item.name}: 전략 산출가 {target_val}원 우선 적용")
										
										# [NEW] 5번 모드 전용 ATR 기반 타점 자동 산출 (전략 타점이 없을 때만)
										if mode == 'volatility_breakout' and stk_item.code not in self.atr_targets:
											chart = await asyncio.get_event_loop().run_in_executor(
												self.trade_pool,
												lambda: self.data_manager.get_daily_chart(stk_item.code, self.token, use_cache=True)
											)
											if chart and len(chart) >= 20:
												df = TI.preprocess_data(chart)
												atr_v = TI.atr(df['high'], df['low'], df['close'], 20).iloc[-1]
												prev_close = df['close'].iloc[-1]
												# 마디 돌파 기준: 전일종가 + (ATR * 0.7) - 보수적 돌파 기준
												v_target = prev_close + (atr_v * 0.7)
												# 호가 단위 보정 (5원/10원 등 생략하고 정수화)
												target_val = f"{int(v_target):,}"
												self.logger.info(f"📐 [ATR타점] {stk_item.name}: 기준가 {prev_close:,} + 0.7*ATR({int(atr_v):,}) = {target_val} 돌파 대기")
												# 런타임 트리거용 타점 저장 (숫자형)
												self.atr_targets[stk_item.code] = int(v_target)
									except Exception as e:
										self.logger.warning(f"Initial target calculation failed for {stk_item.code}: {e}")

								if self.ui_callback and is_trading_seq:
									self.ui_callback("captured", {
										"code": stk_item.code,
										"name": stk_item.name,
										"time": datetime.now().strftime("%m/%d %H:%M:%S"),
										"price": str(c_price) if c_price > 0 else "---",
										"target": target_val,
										"ratio": f"{stk_item.change_rate:.2f}",
										"msg": f"{msg_type}{acc_msg}{radar_msg}"
									})
								
								if trnm == 'CNSR':
									# 포착 내역 저장 시 목표가 포함
									record_captured(stk_item.code, {
										"code": stk_item.code,
										"name": stk_item.name,
										"time": datetime.now().strftime("%m/%d %H:%M:%S"),
										"price": str(c_price),
										"target": target_val,
										"ratio": f"{stk_item.change_rate:.2f}",
										"msg": f"🎯 {msg_type}"
									})
									self.save_captured_stock(stk_item.code, stk_item.name, f"Condition{acc_msg}{radar_msg}", target=target_val)

								# Point 3 적용: 에너지 폭발 시 (레이더/가속도/매집 모드 등에서 최우선 진입)
								if is_urgent and mode in ['cond_only', 'cond_base', 'integrated', 'cond_stock_radar', 'acc_swing'] and is_trading_seq:
									if stk_item.code not in self.processing_stocks:
										self.processing_stocks.add(stk_item.code)
										self.log(f"💥 [에너지폭발] {stk_item.name}({stk_item.code}) 즉시 매수 결정!")
										asyncio.create_task(self.process_buy(stk_item.code, stock_name=stk_item.name, msg_override="🔥 거래밀도 폭발 긴급진입"))
										asyncio.get_running_loop().call_later(300, lambda c=stk_item.code: self.processing_stocks.discard(c))

							# 레이더 분석 및 UI 업데이트를 비동기로 던져서 handle_rt_message 본체 루프 속도 확보
							asyncio.create_task(process_radar_and_ui(item, msg_type_str))
							
					# [공통] 데이터 웜업 (차트 데이터 로딩)
					# 우선순위: REAL/CNSR은 1, CNSRREQ는 10
					priority = 1 if trnm in ['CNSR', 'REAL'] else 10
					asyncio.create_task(self.warm_up_stocks(codes, priority=priority))
		except Exception as e:
			self.logger.error(f"메시지 처리 오류: {e}")

	async def start(self, token=None):
		"""매매 엔진 시작 및 진단"""
		if self.is_running:
			return False
		
		# [안실장] 중복 진입 방지를 위해 즉시 설정
		self.is_running = True
		
		# 1. 상태 초기화 (Clean State)
		self.is_warming_up = True # [Point 1] 초기 웜업 상태 가동 (매수 감시 유예)
		self.pending_buy_count = 0
		self.processing_stocks.clear()
		self.radar_cooldown.clear()
		self.enriched_codes.clear()
		self.enriching_codes.clear()
		
		# 2. 토큰 획득
		self.log("🔍 [진단] API 액세스 토큰을 확인 중입니다...")
		try:
			if token:
				self.token = token
			else:
				self.token = await asyncio.get_event_loop().run_in_executor(None, get_token)
			
			if not self.token:
				self.log("❌ [진단실패] 토큰 발급에 실패했습니다. API 키 및 네트워크 상태를 확인하세요.")
				self.is_running = False
				return False
			
			# 3. 브로커 및 세션 검증
			self.broker.token = self.token # Direct set
			self.log("🔍 [진단] 계좌 연결 상태 및 API 세션을 검증 중입니다...")
			
			valid, msg = await asyncio.get_event_loop().run_in_executor(None, self.broker.validate_session)
			if not valid:
				self.log(f"❌ [접속불가] {msg}")
				self.token = None # Clear invalid token
				self.is_running = False
				return False
			
			# [내실] 실제 연결 확인 로그
			self.log(f"✅ [인증성공] {msg}")

			# [Stock Radar Reset]
			if self.stock_radar:
				self.stock_radar.reset()

			# 4. 리소스 할당
			import aiohttp
			self.api_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
			self._ensure_async_objects()
			
			# 5. 실시간 채널 연결
			self.log("📡 [시스템] 실시간 시세 및 알림 채널을 연결합니다...")
			self.rt_search.on_receive_data = self.handle_rt_data
			self.rt_search.on_message = self.handle_rt_message

			if not await self.rt_search.start(self.token):
				self.log("❌ [연결실패] 실시간 검색 엔진(WebSocket) 시작에 실패했습니다.")
				await self.api_session.close()
				self.is_running = False
				return False
			
			# 6. 백그라운드 태스크 기동
			self.check_sell_task = asyncio.create_task(self._check_sell_loop())
			self.watchlist_task = asyncio.create_task(self._watchlist_loop()) # 자동 모드 전환 및 관심종목 갱신

			# [안실장 신규] 시장 상황 분석 루프 기동
			self.market_engine = MarketStatusEngine(self.token)
			self.market_status_task = asyncio.create_task(self._market_status_loop())
			
			# [안실장 신규] 스톡 레이더 토큰 및 세션 주입
			if self.stock_radar:
				self.stock_radar.token = self.token
				self.stock_radar.session = self.api_session

			# [전략 모드 확인]
			mode = get_setting('trading_mode', 'cond_only')
			mode_names = {
				'cond_only': "1번: 심플 조건검색 (1초 매매)",
				'cond_strategy': "2번: 전략 필터링 (Strategy Filter)",
				'lw_breakout': "3번: 시가 갭 회복 (Gap Recovery)",
				'cond_stock_radar': "4번: 가속도 공략 (Stock Radar)",
				'volatility_breakout': "5번: 변동성 마디 공략 (ATR Breakout)"
			}
			self.log(f"🚀 [시스템가동] {mode_names.get(mode, mode)} 모드로 매매를 시작합니다.")

			update_setting('auto_start', True)

			# 초기 종목 로딩 (Warm-up)
			asyncio.create_task(self.load_and_warm_up())

			# [안실장 신규] 기존 포착 내역 UI 복원
			self.restore_captured_ui()

			# [V2.6] 장전/장중 매집 데이터 스캔 및 매집주/웜업망 연동
			# [안실장 픽스] 순수 1번 모드(검색식 즉시 1초 매수)를 제외하고, '틱/웜업'을 활용하는 모든 매매법에 우량 매집주 40개를 자동 투입(그물망 생성)
			use_filter_setting = get_setting('use_strategy_filter', False)
			is_pure_cond = (mode in ['cond_only', 'cond_base']) and not use_filter_setting
			
			if not is_pure_cond and self.acc_mgr:
				now = datetime.now()
				today_str = now.strftime("%Y%m%d")
				is_before_market = (now.hour < 8) or (now.hour == 8 and now.minute < 50)
				
				if not self.acc_mgr.has_any_analysis_for_day(today_str):
					self.log("⚠️ [알림] 금일 분석된 매집 데이터가 없으므로 백그라운드 상위 종목 스캔을 가동합니다 (수 분 소요).")
					# 스캔 완료 후 마지막 줄에서 자동으로 _register_active_accumulation_radar()가 호출됨
					asyncio.create_task(self._auto_scan_accumulation())
				else:
					self.log("✅ [확인] 금일 갱신된 분석 데이터가 적용되었습니다. 우량 매집주를 웜업망에 자동 편입합니다.")
					asyncio.create_task(self._register_active_accumulation_radar())

			self.log("✅ [완료] 모든 시스템이 정상 가동 중입니다.")
			tel_send("✅ AT_Sig 자동매매 서비스가 가동되었습니다.")
			return True
		except Exception as e:
			self.log(f"❌ [오류] 엔진 시작 중 예외 발생: {e}")
			self.is_running = False
			return False


	async def stop(self):
		"""매매 엔진 중지"""
		if not self.is_running:
			return True
			
		self.log("매매 엔진을 중지합니다...")
		
		await self.rt_search.stop()
		
		if self.check_sell_task:
			self.check_sell_task.cancel()
			try:
				await self.check_sell_task
			except asyncio.CancelledError:
				pass
			self.check_sell_task = None
			
		if self.watchlist_task:
			self.watchlist_task.cancel()
			try:
				await self.watchlist_task
			except asyncio.CancelledError:
				pass
			self.watchlist_task = None

		if self.market_status_task:
			self.market_status_task.cancel()
			self.market_status_task = None

		self.is_running = False
		update_setting('auto_start', False)
		# API 세션 종료
		if self.api_session:
			await self.api_session.close()
			self.api_session = None

		# [NEW] Enrichment Worker Task 정리
		if self.enrich_worker_task:
			self.enrich_worker_task.cancel()
			try:
				await self.enrich_worker_task
			except asyncio.CancelledError:
				pass
			self.enrich_worker_task = None

		self.log("매매 엔진 중지 완료.")
		tel_send("✅ 자동매매 서비스가 중지되었습니다.")
		return True
	
	def shutdown(self):
		"""프로그램 종료 시 호출 (Pool 정리)"""
		if self.pool:
			self.pool.shutdown(wait=True)

	async def _on_rt_closed(self):
		"""WebSocket 연결 종료 시 처리"""
		self.log("WebSocket 연결 종료 감지. 재시작을 시도합니다.")
		await self.stop()
		await asyncio.sleep(1)
		await self.start()

	def _ensure_async_objects(self):
		"""Ensure asyncio objects are created within a running loop."""
		if not hasattr(self, 'buy_lock') or self.buy_lock is None:
			self.buy_lock = asyncio.Lock()
		if not hasattr(self, 'trade_pool') or self.trade_pool is None:
			import concurrent.futures
			self.trade_pool = concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="TradePool")
		if self.enrich_queue is None:
			self.enrich_queue = asyncio.PriorityQueue()
		if self.enrich_worker_task is None:
			self.enrich_worker_task = asyncio.create_task(self._enrichment_worker())
		if self.warmup_sem is None:
			self.warmup_sem = asyncio.Semaphore(1)
		if self.global_rest_sem is None:
			self.global_rest_sem = asyncio.Semaphore(1)
		if self.radar_init_lock is None:
			self.radar_init_lock = asyncio.Lock()
		if self.momentum_lock is None:
			self.momentum_lock = asyncio.Lock()

	async def _enrichment_worker(self):
		"""Background worker to process enrichment queue by priority (0: Urgent, 10: Low)"""
		import time
		while True:
			# PriorityQueue returns (priority, item) or (priority, item, retry_count)
			try:
				queue_item = await self.enrich_queue.get()
				if len(queue_item) == 2:
					priority, stk_cd = queue_item
					retry_count = 0
				else:
					priority, stk_cd, retry_count = queue_item
			except (TypeError, ValueError):
				# Fallback for old queue items if any
				stk_cd = await self.enrich_queue.get()
				priority, retry_count = 10, 0

			try:
				# [안실장 가이드] 전역 속도제한 체크 (더욱 타이트한 백오프 적용)
				backoff_duration = 20.0 # 429 발생 시 기본 대기 시간
				if time.time() - self.last_429_time < backoff_duration:
					wait_left = backoff_duration - (time.time() - self.last_429_time)
					if priority <= 1: 
						await asyncio.sleep(2)
					else:
						await asyncio.sleep(min(5, wait_left))
					
					await self.enrich_queue.put((priority, stk_cd, retry_count))
					continue
					
				# Final checks before request
				if stk_cd in self.enriched_codes: continue
				
				# Wait for engine to have a token and session (if starting up)
				while (not self.token or not self.api_session) and self.is_running:
					await asyncio.sleep(1)
				
				if not self.is_running and not self.token:
					await asyncio.sleep(1)
					continue

				# [안실장 데이터 확보] 1. 데이터 확보 (캐시 우선, 실패 시 API)
				item = None
				cached = self.rt_search.get_cached_price(stk_cd) if self.rt_search else None
				
				if cached and cached.get('price', 0) > 0:
					# [Case A] 소켓 캐시 데이터 활용 (API 호출 절약)
					stk_name = "Unknown"
					if hasattr(self.broker, 'name_cache') and stk_cd in self.broker.name_cache:
						stk_name = self.broker.name_cache[stk_cd]
					
					from core.models import StockItem
					item = StockItem(
						code=stk_cd,
						name=stk_name,
						price=int(cached.get('price', 0)),
						change_rate=float(cached.get('change', 0.0)),
						volume=int(cached.get('volume', 0)),
						source="Cached"
					)
					self.logger.debug(f"💎 [Enricher] {stk_cd} 소켓 캐시 데이터 활용")
				else:
					# [Case B] REST API 호출 (캐시에 없을 때만)
					is_429 = False
					async with self.global_rest_sem:
						try:
							info, status = await get_stock_info_async(stk_cd, self.token, session=self.api_session)
							if status == 429:
								is_429 = True
								self.last_429_time = time.time()
							elif info:
								if isinstance(info, list) and len(info) > 0: info = info[0]
								if isinstance(info, dict):
									from core.models import StockItem
									item = StockItem.from_api_dict(info)
						except Exception as e:
							self.logger.debug(f"API fetch failed for {stk_cd}: {e}")

					if is_429:
						if retry_count >= 2:
							self.log(f"🛑 [{stk_cd}] 429 연속 발생으로 패싱합니다.")
						else:
							self.log(f"⚠️ [{stk_cd}] 정보 조회 429 발생. 재시도({retry_count+1}/2)...")
							await self.enrich_queue.put((priority, stk_cd, retry_count + 1))
						await asyncio.sleep(5.0)
						continue

				# [안실장 공통 분석] 2. 분석 및 UI 반영
				if item and item.name != 'Unknown':
					# 적합성 검사
					if not self.is_eligible_stock(stk_cd, item.name, item.price):
						self.logger.debug(f"🚫 [Enrich:제외] {item.name}({stk_cd}) - 매매 대상 부적합")
						self.enriched_codes.add(stk_cd)
						continue

					if self.ui_callback:
						# 기본 정보 업데이트
						self.ui_callback("filter_update", {
							"code": stk_cd,
							"name": item.name,
							"price": item.price,
							"rate": item.change_rate,
							"status": "대기"
						})

						# [안실장 신규] 전략 매수 목표가(TargetLine) 실시간 계산
						st_file = get_setting('active_strategy', '선택안함')
						if st_file and st_file != '선택안함':
							try:
								st_file_full = st_file + '.json' if not st_file.endswith('.json') else st_file
								root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
								st_path = os.path.join(root_dir, 'shared', 'strategies', st_file_full)
								
								if os.path.exists(st_path):
									with open(st_path, 'r', encoding='utf-8') as f:
										st_json = json.load(f)
										st_code = st_json.get('python_code', '')
										min_bars = st_json.get('min_bars', 70)
										
										if st_code:
											self.log(f"🔮 [{item.name}] 매수목표가 산출 중... (전략: {st_file})")
											res = await asyncio.get_event_loop().run_in_executor(
												self.trade_pool,
												lambda: self.strategy_runner.check_signal(stk_cd, self.token, st_code, item.price, min_bars)
											)
											if res and 'target' in res:
												t_val = res.get('target', 0)
												if t_val > 0:
													self.log(f"✅ [{item.name}] 목표가 계산 완료: {int(t_val):,}원")
													# [전략우선원칙] 5번 모드인 경우 전략 타점을 우선 적용
													mode = get_setting('trading_mode', 'cond_base')
													if mode == 'volatility_breakout':
														self.atr_targets[stk_cd] = int(t_val)
														self.log(f"🎯 [전략타점] {item.name}: 5번 모드 트리거 가격으로 등록 완료")

													# [안실장 픽스] UI 업데이트와 동시에 이력 데이터(JSON) 영구 저장
													t_str = f"{int(t_val):,}"
													self.ui_callback("filter_update", {"code": stk_cd, "target": t_str})
													
													# 이력 파일 갱신 (persistent storage)
													from history_manager import record_captured
													record_captured(stk_cd, {
														"code": stk_cd,
														"name": item.name,
														"time": datetime.now().strftime("%m/%d %H:%M:%S"),
														"price": str(item.price),
														"target": t_str,
														"ratio": f"{item.change_rate:+.2f}",
														"msg": f"🎯 [계산완료] {st_file}"
													})
												else:
													self.logger.debug(f"⚠️ [{item.name}] 목표가 결과 0 (조건 미충족)")
													# [전략우선원칙] 전략에서 타점이 안 나왔더라도 5번 모드면 ATR 기본 타점 산출
													mode = get_setting('trading_mode', 'cond_base')
													if mode == 'volatility_breakout':
														chart = await asyncio.get_event_loop().run_in_executor(
															self.trade_pool,
															lambda: self.data_manager.get_daily_chart(stk_cd, self.token, use_cache=True)
														)
														if chart and len(chart) >= 20:
															df = TI.preprocess_data(chart)
															atr_v = TI.atr(df['high'], df['low'], df['close'], 20).iloc[-1]
															prev_close = df['close'].iloc[-1]
															v_target = prev_close + (atr_v * 0.7)
															self.atr_targets[stk_cd] = int(v_target)
															t_str = f"{int(v_target):,}"
															self.ui_callback("filter_update", {"code": stk_cd, "target": t_str})
															self.log(f"📐 [ATR타점] {item.name}: 전략 미충족으로 기본 ATR 타점({t_str}원) 적용")
											else:
												err_msg = res.get('msg', 'Unknown Result')
												self.log(f"❌ [{item.name}] 분석 실패: {err_msg}")
							except Exception as ste:
								self.logger.error(f"Target calculation error for {stk_cd}: {ste}")

					self.enriched_codes.add(stk_cd)
					if hasattr(self.broker, 'name_cache'):
						self.broker.name_cache[stk_cd] = item.name
				else:
					self.logger.debug(f"Meaningful info not found for {stk_cd}")

				# [Throttling] 우선순위에 따른 지연 시간 차등 적용
				base_delay = 1.0 if priority <= 1 else 2.0
				await asyncio.sleep(base_delay)

			except Exception as wide_e:
				self.logger.error(f"Enrichment worker error for {stk_cd}: {wide_e}")
				# [Retry Logic] 네트워크 오류 등 일시적 문제 시 재시도
				if retry_count < 3:
					self.logger.info(f"🔄 [{stk_cd}] 정보충전 재시도 중... ({retry_count + 1}/3)")
					await asyncio.sleep(2)
					await self.enrich_queue.put((priority, stk_cd, retry_count + 1))
				else:
					self.logger.error(f"❌ [{stk_cd}] 정보충전 최종 실패 (최대 재시도 초과)")
			finally:
				self.enrich_queue.task_done()
				if stk_cd in self.enriching_codes:
					self.enriching_codes.remove(stk_cd)


	async def warm_up_stocks(self, codes, priority=5):
		"""종목 리스트에 대해 차트 데이터 및 기본 정보를 백그라운드에서 로딩 (우선순위 적용)"""
		if not codes: return
		self._ensure_async_objects()

		# 중복 제거 및 기존 정보 충전 여부 확인
		unique_input = list(set(codes))
		new_codes = [c for c in unique_input if c not in self.enriched_codes and c not in self.enriching_codes]
		
		if not new_codes: return
		
		# [안실장 가이드] 대기열이 너무 길면 패싱 (단, 실시간 포착 등 높은 우선순위는 제외)
		if priority > 1 and self.enrich_queue.qsize() > 120:
			self.logger.debug(f"⚠️ [패싱] 대기열 과다({self.enrich_queue.qsize()})로 전역 웜업({len(new_codes)}건) 생략")
			return

		for code in reversed(new_codes):
			self.enriching_codes.add(code)
			self.enrich_queue.put_nowait((priority, code))
		
		self.logger.debug(f"📥 {len(new_codes)}개 종목 정보 충전 큐 등록 완료 (대기열: {self.enrich_queue.qsize()}개)")

		# --- Phase 2: Deep Caching (Heavy Lifting) ---
		async def cache_chart(stk_cd):
			import time
			# [안실장 가이드] 전역 속도제한 체크
			if time.time() - self.last_429_time < 20:
				return

			async with self.global_rest_sem: # Use GLOBAL Semaphore
				try:
					# [Deep Cache] 차트 데이터 및 상세 정보 미리 로딩 (Ms. Ahn Optimized)
					if stk_cd in self.history_loaded_codes: return
					
					await asyncio.get_event_loop().run_in_executor(
						self.trade_pool,
						lambda: self.data_manager.get_daily_chart(stk_cd, self.token, use_cache=True)
					)
					self.history_loaded_codes.add(stk_cd)
					await asyncio.sleep(0.3)
				except Exception as e:
					self.logger.error(f"Chart caching error: {e}")

		async def background_caching():
			try:
				# [Optimization] 한꺼번에 gather하지 않고 순차적으로 처리하여 부하 분산
				for code in new_codes:
					if not self.is_running: break
					await cache_chart(code)
				self.log(f"📦 Background Chart Caching Complete: {len(new_codes)} stocks.")
			except Exception as e:
				self.logger.error(f"Background caching error: {e}")
				
		asyncio.create_task(background_caching())

	async def load_and_warm_up(self):
		"""
		Load lead_watchlist.json and perform warm-up.
		Also triggers Condition Search to try and capture initial list if possible.
		"""

		# [안실장 픽스] 기존 포착된 종목들(captured_stocks)에 대해서도 정보 충전 및 목표가 계산 수립
		if self.captured_stocks:
			captured_list = list(self.captured_stocks)
			self.log(f"🕯️ [복구] 기존 포착 종목 {len(captured_list)}건의 정보 복구 및 목표가 계산을 시작합니다.")
			
			# [안실장 고도화] 429 방어를 위해 10개씩 끊어서 웜업 수행
			batch_size = 10
			for i in range(0, len(captured_list), batch_size):
				if not self.is_running: break
				batch = captured_list[i:i+batch_size]
				await self.warm_up_stocks(batch, priority=5) # 복구는 낮은 우선순위로
				# 배치 간 대기 (REST API 쿼터 확보)
				await asyncio.sleep(3)

		# [안실장 픽스] 보유 종목(holdings)에 대해서도 실시간 시세(REG) 등록 및 웜업 수행
		# 이것이 되어야 손절 감시가 실시간 가격으로 작동합니다.
		try:
			holdings = await asyncio.get_running_loop().run_in_executor(self.trade_pool, self.broker.get_holdings)
			if holdings:
				holding_codes = [h['stk_cd'].replace('A', '') for h in holdings]
				self.log(f"💰 [잔고복구] 보유 종목 {len(holding_codes)}건에 대해 실시간 시세 감시를 시작합니다.")
				# 1. 실시간 시세 등록 (Ticks 수신)
				asyncio.create_task(self.rt_search.register_sise(holding_codes, self.token))
				# 2. 정보 충전 및 웜업 (보유 종목은 최우선 순위로)
				await self.warm_up_stocks(holding_codes, priority=1)
		except Exception as e:
			self.logger.error(f"Holdings recovery failed during warm-up: {e}")

		# [Point 1] 웜업 종료 (시스템 안정화 대기)
		self.log("📋 [시스템] 검색식 대응을 위해 엔진을 최적화 중입니다...")
		await asyncio.sleep(2) 
		self.is_warming_up = False
		self.log("✅ [완료] 초기 웜업 종료. 실시간 매니저가 매수 감시 모드로 전환되었습니다.")




	async def _init_stock_radar(self, code, name, skip_reg=False):
		"""StockRadar 초기 등록을 위한 데이터 조회 및 주입"""
		self._ensure_async_objects()
		
		# [안실장 가이드] 전역 속도제한 체크
		import time
		if time.time() - self.last_429_time < 10:
			return
		
		# [안실장 가이드] 이미 레이더에 있거나 초기화 중이면 "패싱" (429 방어 및 지연 방지)
		if self.stock_radar and code in self.stock_radar.history:
			return
		
		# [CRITICAL UPDATE] 시세 등록(register_sise)은 락에 막히면 영원히 시세가 안 들어오므로 항상 먼저 수행합니다.
		if not skip_reg and self.rt_search and self.rt_search.connected:
			try:
				await self.rt_search.register_sise(code, self.token)
			except Exception as e:
				self.logger.error(f"Failed to register_sise for {code}: {e}")
		
		if self.radar_init_lock.locked():
			# 락이 걸려있으면 일단 패싱. WebSocket REAL 데이터가 이제 들어오므로 update()에서 자연스럽게 초기화됨.
			return

		async with self.radar_init_lock:
			try:
				# [CRITICAL] 1. 실시간 시세 캐시 확인 (429 방어의 핵심)
				cached = self.rt_search.get_cached_price(code) if self.rt_search else None
				if cached and cached.get('price', 0) > 0:
					# 캐시에 유효한 시세가 있다면 REST API 조회를 건너뜁니다.
					self.logger.debug(f"⚡ [RadarInit] {name}({code}) 캐시 데이터 사용 (REST 조회 스킵)")
					if self.stock_radar:
						self.stock_radar.update(code, cached['price'], cached.get('volume', 0), 0)
					return

				# [안실장 고도화] 이름 정보를 모르는 경우에만 REST API 조회를 시도하거나, 
				# 정말 시세 데이터가 시급한 경우에만 제한적으로 호출
				async with self.global_rest_sem:
					info, status = await get_stock_info_async(code, self.token, session=self.api_session)
					
					if status == 429:
						self.last_429_time = time.time()
						self.logger.warning(f"⏳ [RadarInit] {name}({code}) 속도제한 발생. 즉시 패싱.")
						return
					
					if info:
						if isinstance(info, list) and len(info) > 0:
							info = info[0]
						
						curr = abs(int(info.get('stk_prc', 0)))
						vol = int(info.get('acml_vol', 0))
						if self.stock_radar and curr > 0:
							self.stock_radar.update(code, curr, vol, 0)
				
				# API 간격 유지를 위해 짧은 대기 (다른 태스크에 양보)
				await asyncio.sleep(0.5)
	
			except Exception as e:
				self.logger.error(f"{name} 초기화 실패(StockRadar): {e}")

	async def handle_rt_data(self, data):
		"""
		실시간 검색 데이터 수신 시 처리
		data: WebSocket에서 받은 'REAL' 데이터의 item (dict)
		"""
		if not data or not isinstance(data, dict): return
		try:
			# [Heartbeat] 100틱마다 생존 로그
			self.tick_count = getattr(self, 'tick_count', 0) + 1
			if self.tick_count % 100 == 0:
				self.logger.info(f"💓 [Heartbeat] Tick count: {self.tick_count}")

			def safe_parse_int(val_str):
				if not val_str: return 0
				try:
					clean = str(val_str).replace(',', '').strip()
					if not clean: return 0
					return int(float(clean))
				except:
					return 0

			if not data or not isinstance(data, dict): return
			
			if 'values' in data and data['values'] and '9001' in data['values']:
				stk_cd = data['values']['9001']
				try:
					vals = data.get('values', {})
					current_price = abs(safe_parse_int(vals.get('10', '0')))
					open_price = abs(safe_parse_int(vals.get('16', '0')))
					status_type = vals.get('843', 'I')
					accum_vol = safe_parse_int(vals.get('13', '0'))
					power = safe_parse_int(vals.get('228', '0'))
					time_str = vals.get('20', datetime.now().strftime("%H%M%S"))
				except:
					current_price = open_price = accum_vol = power = 0
					status_type = 'I'
					time_str = datetime.now().strftime("%H%M%S")
			else:
				stk_cd = data.get('code')
				current_price = open_price = accum_vol = power = 0
				status_type = 'I'
				time_str = datetime.now().strftime("%H%M%S")
			
			if not stk_cd: return
			

			# [안실장 틱 조립기 연동] 수신된 틱(현재가)을 1분봉 차트에 실시간 찰흙 붙이기
			if current_price > 0:
				self.min_builder.on_tick(stk_cd, current_price, accum_vol, time_str)

			stk_name = self.broker.get_stock_name(stk_cd)
			if isinstance(stk_name, dict):
				stk_name = stk_name.get('stk_nm') or stk_name.get('code_name') or str(stk_name)
			
			if not stk_name or stk_name in ['Unknown', '조건검색']:
				stk_name = stk_cd # 최후의 수단으로 코드라도 표시
			
			# [안실장 가이드] 실시간 데이터 처리 시 개별 종목 필터링 수행
			if not self.is_eligible_stock(stk_cd, stk_name, current_price):
				return
			
			fluc_rate = 0.0
			if 'values' in data and data.get('values'):
				try: fluc_rate = float(data['values'].get('12', '0'))
				except: pass

			if current_price <= 0: return

			# [Point 2 & 4 연동] 웜업 중이 아니고, 정규장 시간이며, 매수 감시 대기 중인 종목인 경우 매수 로직 호출
			if not self.is_warming_up and self.is_market_open():
				# [안실장 가이드] 초단기 가속도(Point 4) 분석을 위한 레이더 업데이트
				if self.stock_radar:
					self.stock_radar.update(stk_cd, current_price, accum_vol, power)

				# [Buy Pipeline] 모드별 진입 조건 판단
				mode = get_setting('trading_mode', 'cond_only')
				
				# [NEW] 투트랙 운영 모드
				if mode in ['lw_breakout', 'gap_recovery'] and get_setting('use_two_track', False):
					if datetime.now().hour >= 10:
						mode = 'cond_stock_radar'

				# [안실장 픽스] 1. 조건식 단독 모드 (즉시 매수)
				if mode in ['cond_only', 'cond_base'] and get_setting('active_strategy', '선택안함') in ['선택안함', '', 'None']:
					if stk_cd not in self.processing_stocks:
						self.processing_stocks.add(stk_cd)
						self.log(f"🎯 [조건포착] {stk_name}({stk_cd}) 조건식 만족! 즉시 매수 진입!")
						asyncio.create_task(self.process_buy(stk_cd, stock_name=stk_name, msg_override="조건식즉시포착"))
						# 5분간 동일 종목 재진입 방지
						asyncio.get_running_loop().call_later(300, lambda: self.processing_stocks.discard(stk_cd))

				# [안실장 픽스] 2. 전략 필터링 모드 (검증 매수)
				elif mode == 'cond_strategy' or (mode in ['cond_only', 'cond_base'] and get_setting('active_strategy', '선택안함') not in ['선택안함', '', 'None']):
					# [선택 2] 전략 필터링 매매 - 일봉 데이터 기반 [안실장 핵심 수정]
					st_file = get_setting('active_strategy', '선택안함')
					if st_file != '선택안함' and not st_file.endswith('.json'):
						st_file += '.json'
						
					root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
					st_path = os.path.join(root_dir, 'shared', 'strategies', st_file)
					
					strategy_code = ""
					strategy_data_type = "daily"
					min_bars = 70
					if os.path.exists(st_path):
						try:
							with open(st_path, 'r', encoding='utf-8') as f:
								st_json = json.load(f)
								if st_json and isinstance(st_json, dict):
									strategy_code = st_json.get('python_code', '')
									strategy_data_type = st_json.get('data_type', 'daily')
									min_bars = st_json.get('min_bars', 70)
						except: pass
					
					if strategy_code:
						is_signal = False
						signal_msg = ""
						if strategy_data_type == 'minute':
							min_df = self.min_builder.get_dataframe(stk_cd)
							if not min_df.empty:
								# [안실장 픽스] 정확한 시가 및 전일종가 주입 (분봉에는 어제 데이터가 없으므로 일봉에서 보충)
								d_chart = self.data_manager.get_daily_chart(stk_cd, token=self.token, use_cache=True)
								t_open, p_close = None, None
								if d_chart and len(d_chart) >= 2:
									t_open = float(d_chart[-1]['open_prc'] if 'open_prc' in d_chart[-1] else (d_chart[-1]['stck_oprc'] if 'stck_oprc' in d_chart[-1] else d_chart[-1].get('open_pric', 0)))
									p_close = float(d_chart[-2]['close_prc'] if 'close_prc' in d_chart[-2] else (d_chart[-2]['stck_prpr'] if 'stck_prpr' in d_chart[-2] else d_chart[-2].get('cur_prc', 0)))
								
								res = self.strategy_runner.analyze_data([], stk_cd, strategy_code, current_price, min_df, day_open=t_open, prev_close=p_close)
								if not res: return
								is_signal = res.get('result', False)
								signal_msg = res.get('msg', '')
						else:
							loop = asyncio.get_event_loop()
							res = await loop.run_in_executor(
								self.trade_pool,
								lambda: self.strategy_runner.check_signal(stk_cd, self.token, strategy_code, current_price, min_bars=min_bars)
							)
							if not res: return
							is_signal = res.get('result', False)
							signal_msg = res.get('msg', '')
						
						if is_signal and stk_cd not in self.processing_stocks:
							self.processing_stocks.add(stk_cd)
							data_type_label = "분봉" if strategy_data_type == 'minute' else "일봉"
							self.log(f"🎯 [전략포착/{data_type_label}] {stk_name}({stk_cd}) 전략 검증 완료! 매수진입! {signal_msg}")
							# [안실장 픽스] 전략에서 산출된 목표가(TargetLine)를 함께 전달
							asyncio.create_task(self.process_buy(
								stk_cd, 
								stock_name=stk_name, 
								price_override=res.get('target', 0), 
								msg_override=f"전략매수:{st_file}",
								meta=res
							))
							asyncio.get_running_loop().call_later(300, lambda: self.processing_stocks.discard(stk_cd))

				elif mode in ['lw_breakout', 'gap_recovery']:
					# [선택 3] 시가 갭 회복 (K-Breakout)
					# 장 초반 음봉 후 시가(DayOpen) 재돌파 시 진입
					if open_price > 0 and current_price >= open_price:
						if stk_cd not in self.processing_stocks:
							# [안실장 고도화] 5분봉 등 추세 확인 루틴 추가 가능 (현재는 단순 돌파)
							self.processing_stocks.add(stk_cd)
							self.log(f"🎯 [갭회복] {stk_name}({stk_cd}) 시가 재돌파 포착! 진입!")
							asyncio.create_task(self.process_buy(stk_cd, stock_name=stk_name, msg_override="시가갭회복돌파"))
							asyncio.get_running_loop().call_later(600, lambda: self.processing_stocks.discard(stk_cd))

				elif mode == 'cond_stock_radar':
					# [선택 4] 관심종목 가속도 공략 (Stock Radar)
					if self.stock_radar:
						score_info = self.stock_radar.get_score(stk_cd)
						if score_info['score'] >= get_setting('radar_buy_score', 82):
							if stk_cd not in self.processing_stocks:
								self.processing_stocks.add(stk_cd)
								self.log(f"🔥 [가속도] {stk_name}({stk_cd}) 점수:{score_info['score']}점 돌파 진입!")
								asyncio.create_task(self.process_buy(stk_cd, stock_name=stk_name, msg_override=f"가속도공공(점수:{score_info['score']})"))
								asyncio.get_running_loop().call_later(300, lambda: self.processing_stocks.discard(stk_cd))

				elif mode == 'acc_swing':
					# [선택 5] 매집 맥점 공략 (Swing)
					if self.acc_mgr and self.stock_radar:
						q_info = self.acc_mgr.get_accumulation_quality(stk_cd)
						if q_info.get('score', 0) >= 75:
							# 매집이 좋고, 실시간으로 수급(가속도)이 붙기 시작할 때
							radar_info = self.stock_radar.get_score(stk_cd)
							if radar_info['score'] >= 65:
								if stk_cd not in self.processing_stocks:
									self.processing_stocks.add(stk_cd)
									self.log(f"💎 [매집맥점] {stk_name}({stk_cd}) 매집점수:{q_info['score']} + 수급포착!")
									asyncio.create_task(self.process_buy(stk_cd, stock_name=stk_name, msg_override=f"매집스윙(점수:{q_info['score']})"))
									# 스윙 종목은 당일 재매수 방지를 위해 락 유지를 길게 가져감
									asyncio.get_running_loop().call_later(28800, lambda: self.processing_stocks.discard(stk_cd))

				elif mode == 'volatility_breakout':
					# [신규] 5번 변동성 마디 공략 (ATR Breakout)
					target_price = self.atr_targets.get(stk_cd, 0)
					if target_price > 0 and current_price >= target_price:
						if stk_cd not in self.processing_stocks:
							self.processing_stocks.add(stk_cd)
							self.log(f"⚡ [ATR돌파] {stk_name}({stk_cd}) 목표가 {target_price:,}원 돌파! 즉시 진입!")
							# ATR 기반 리스크 관리가 활성화된 경우, process_buy 내부에서 자동으로 2*ATR 손절 등이 세팅됨
							asyncio.create_task(self.process_buy(stk_cd, stock_name=stk_name, msg_override=f"ATR마디돌파({target_price:,}원)"))
							asyncio.get_running_loop().call_later(300, lambda: self.processing_stocks.discard(stk_cd))


		except Exception as e:
			self.logger.error(f"RT Data processing error: {e}")

	def _ensure_ui_captured(self, stk_cd, stk_name=None, msg="매수진입", target=None, price=0, ratio=0.0):
		"""
		주문 전/포착 즉시 해당 종목이 UI의 '포착 리스트'에 보이도록 강제 등록
		[안실장 신뢰도 강화] 전달받은 가격(price)이 있으면 캐시 조회보다 우선 사용
		"""
		if not self.ui_callback: return
		
		# 1. 가격 및 등락률 확보 (전달된 값 -> 캐시 -> 0)
		if price <= 0 and self.rt_search:
			cached = self.rt_search.price_cache.get(stk_cd, {})
			price = cached.get('price', 0)
			if ratio == 0.0:
				ratio = cached.get('change', 0.0)

		# 실시간 가격 확보 시도
		if price <= 0:
			cached = self.rt_search.price_cache.get(stk_cd, {})
			price = cached.get('price', 0)

		if price <= 0:
			self.logger.debug(f"🚫 [UI등록건너뜀] {stk_cd}: 가격 정보가 없어 등록을 취소합니다.")
			return

		display_price = str(price) if price > 0 else "---"

		# 매수 목표가 처리 (전략에서 산출된 TargetLine 등)
		display_target = "-"
		if target and float(str(target).replace(',', '')) > 0:
			display_target = f"{int(float(str(target).replace(',', ''))):,}"
		elif target:
			display_target = str(target)

		record_captured(stk_cd, {
			"code": stk_cd,
			"name": stk_name or stk_cd,
			"time": datetime.now().strftime("%m/%d %H:%M:%S"),
			"price": display_price,
			"target": display_target,
			"ratio": f"{ratio:+.2f}",
			"msg": f"🎯 {msg}"
		})

		self.ui_callback("captured", {
			"code": stk_cd,
			"name": stk_name or stk_cd,
			"time": datetime.now().strftime("%m/%d %H:%M:%S"),
			"price": display_price,
			"target": display_target,
			"status": "대기",
			"ratio": f"{ratio:+.2f}",
			"msg": f"🎯 {msg}"
		})

	def restore_captured_ui(self):
		"""재시작 시 오늘 포착되었던 종목들을 UI에 다시 뿌려줌"""
		if not self.ui_callback or not hasattr(self, '_initial_captured_data'):
			return
			
		self.log(f"♻️ [복원] 오늘 포착된 {len(self._initial_captured_data)}개 종목 리스트를 복구합니다.")
		for item in self._initial_captured_data:
			try:
				self.ui_callback("captured", {
					"code": item.get('code', ''),
					"name": item.get('name', ''),
					"time": item.get('time', ''),
					"price": item.get('price', '-'),
					"target": item.get('target', '-'),
					"status": item.get('status', '대기'),
					"ratio": item.get('ratio', '0.00'),
					"msg": item.get('msg', '🎯 복원됨')
				})
			except: pass

	async def process_buy(self, stk_cd, stock_name=None, price_override=0, msg_override=None, meta=None):
		"""
		Buy Execution Logic (The Core)
		- Check Slots, Balance, Market Index (Circuit Breaker)
		- Advanced Sizing: ATR-based Risk Management (Turtle Trading Model)
		- Execute Order via Broker
		"""
		# [안실장 가이드] 중복 진입 방지 및 리소스 보호를 위한 비동기 락
		if not self.is_running: return
		
		# [Lock 처리 개선] 무작정 취소하지 않고 순차적으로 대기하되, 대기열이 너무 길면 취소
		if self.buy_lock.locked():
			if self.pending_buy_count >= 5:
				self.log(f"⚠️ [매수취소] 대기 중인 주문건이 너무 많아 {stk_cd} 진입을 생략합니다.")
				return
			
		async with self.buy_lock:
			if self.ui_callback:
				# [안실장 픽스] 포착 리스트에 없더라도 매수 진행 시 UI상에 즉시 노출되도록 보장 (목표가 포함)
				self._ensure_ui_captured(stk_cd, stock_name, msg=msg_override or "매칭진입", target=price_override)
				self.ui_callback("filter_update", {"code": stk_cd, "status": "분석/매수중"})
			try:
				manual_mode = get_setting('manual_buy', False)
				
				# [안실장 고도화] 지수 및 시장 환경(Market Regime)에 따른 매수 방어 및 전략적 비중 조절
				if not self.current_regime:
					# 시장 상황 데이터가 아직 안 왔으면 기본값 설정 (매수 허용)
					regime_type = MarketRegime.BULL
				else:
					regime_type = self.current_regime.get('regime', MarketRegime.BULL)
				
				# 1. 폭락장(CRASH) 대응: 신규 매수 전면 차단
				if regime_type == MarketRegime.CRASH:
					self.log("🛑 [매수방어] 현재 시장은 '폭락장(CRASH)' 상태입니다. 자산 보호를 위해 신규 매수를 전면 차단합니다.")
					if self.ui_callback:
						self.ui_callback("filter_update", {"code": stk_cd, "status": "시장폭락-차단"})
					return
	
				# 2. 약세장(BEAR) 대응: 알림 출력 (배율은 아래 multiplier 로직에서 자동 조절)
				if regime_type == MarketRegime.BEAR:
					self.log(f"⚠️ [보수적접근] 현재 시장은 '약세장(BEAR)' 상태입니다. 리스크 관리를 위해 매수 비중을 축소합니다.")
	
				# [V3.0 최적화] 잔고 및 지수 정보 캐싱 최적화 (REST 호출 최소화)
				now_t = time.time()
				
				# 1. 지수 정보 (Circuit Breaker) - 2분간 캐시 유효
				if now_t - self.market_index_cache["time"] > 120:
					try:
						idx_kospi = await asyncio.get_event_loop().run_in_executor(self.trade_pool, self.broker.get_market_index, "KOSPI")
						idx_kosdaq = await asyncio.get_event_loop().run_in_executor(self.trade_pool, self.broker.get_market_index, "KOSDAQ")
						if idx_kospi and idx_kosdaq:
							self.market_index_cache.update({"KOSPI": idx_kospi, "KOSDAQ": idx_kosdaq, "time": now_t})
					except Exception as ex:
						self.logger.warning(f"Index cache refresh failed: {ex}")

				idx_kospi = self.market_index_cache["KOSPI"]
				idx_kosdaq = self.market_index_cache["KOSDAQ"]
				
				# [ Circuit Breaker - Logging only for Test Mode ]
				# 실제 매매 차단은 지시가 있을 때만 활성화 (현재는 로그만 출력 및 진행)
				
				# 2. 잔고 및 가용 자금 (30초간 캐시 유효)
				if now_t - self.balance_cache["time"] > 30:
					try:
						balance = await asyncio.get_event_loop().run_in_executor(self.trade_pool, self.broker.get_balance)
						# [안실장 픽스] 일시적 조회 실패(0) 대응을 위한 1회 재시도
						if (balance is None or balance <= 0) and self.is_running:
							await asyncio.sleep(0.5)
							balance = await asyncio.get_event_loop().run_in_executor(self.trade_pool, self.broker.get_balance)
							
						if balance is not None:
							self.balance_cache.update({"value": balance, "time": now_t})
					except Exception as ex:
						self.logger.warning(f"Balance cache refresh failed: {ex}")
						
				balance = self.balance_cache["value"]

				if now_t - self.holdings_cache["time"] > 10:
					try:
						my_stocks = await asyncio.get_running_loop().run_in_executor(self.trade_pool, self.broker.get_holdings)
						if my_stocks is not None:
							self.holdings_cache["value"] = my_stocks
							self.holdings_cache["time"] = now_t
					except Exception as ex:
						self.logger.warning(f"Failed to refresh holdings cache (using old value): {ex}")
						
				my_stocks = self.holdings_cache["value"]

				# 1. 잔고 보유 여부 확인 (중복 매수 방지)
				is_holding = any(s.get('stk_cd', '').replace('A', '') == stk_cd for s in my_stocks)
				if is_holding:
					self.log(f"⚠️ [매수스킵] {stk_cd}: 이미 잔고에 보유 중인 종목입니다.")
					if self.ui_callback:
						self.ui_callback("filter_update", {"code": stk_cd, "status": "이미보유"})
					return
	
				# 2. 거래 가능 슬롯 확인
				max_count = get_setting('max_stock_count', 10)
				hold_count = len(my_stocks)
				current_count = hold_count + self.pending_buy_count
				
				if current_count >= max_count:
					msg = f"🚫 [매수제한] 최대 보유 종목 수({max_count}개) 초과 (현재:{current_count}개)"
					self.log(msg)
					if self.ui_callback:
						self.ui_callback("filter_update", {"code": stk_cd, "status": "슬롯초과"})
					return
				
				# Race Condition 방어를 위해 카운트 선증가 (Lock 내부에서 안전하게 증가)
				self.pending_buy_count += 1
				try:
					# 3. 예수금 및 가용 자금 확인
					if balance <= 1000:
						self.log(f"❌ [매수차단] 가용 예수금 부족 (현재 잔고: {balance:,}원, 필요: 1,000원 이상)")
						if self.ui_callback:
							self.ui_callback("filter_update", {"code": stk_cd, "status": "예수금부족진짜"})
						return
		
					# [안실장 픽스] 시장 상황에 따른 매매 강도(Multiplier) 최우선 적용 (0.5x ~ 1.2x)
					multiplier = 1.0
					
					# 1. 엔진 내부의 실시간 Regime 분석 데이터 우선 참조
					if self.current_regime:
						rt_regime = self.current_regime.get('regime', MarketRegime.SIDEWAYS)
						if rt_regime == MarketRegime.BULL:
							multiplier = 1.2
						elif rt_regime == MarketRegime.BEAR:
							multiplier = 0.5
						elif rt_regime == MarketRegime.CRASH:
							multiplier = 0.0
						else: # MarketRegime.SIDEWAYS
							multiplier = 1.0
					# 2. 분석 데이터가 없을 경우 외부 신호망(SignalManager) 폴백
					elif hasattr(self, 'signal_manager'):
						multiplier = self.signal_manager.get_trading_multiplier()

					# 4. 매수 예정 금액 및 수량 계산
					# [안실장 미수방어] 예수금의 100%가 아닌 99.3%만 활용하여 수수료 및 슬리피지 공간 확보
					CASH_MARGIN = 0.993
					buy_method = get_setting('buy_method', 'percent')
					
					if buy_method == 'amount':
						target_amount = get_setting('buy_amount', 100000)
						# 강도 적용 (예: 약세장 0.5배 → 50% 금액만 매수)
						target_amount = target_amount * multiplier
						# [미치광이 미수방지] 최종 집행 금액은 가용 자금(balance)의 안전 마진을 넘지 않도록 제한
						expense = min(balance * CASH_MARGIN, target_amount)
					else:
						ratio = get_setting('buy_ratio', 10.0) / 100
						# 강도 적용
						ratio = ratio * multiplier
						# 비중 매수 시에도 전체 자산의 안전 마진 내에서만 집행함
						expense = (balance * CASH_MARGIN) * ratio
					
					# 호가 조회 (실시간 가격 캐시 활용)
					bid = 0
					if price_override > 0:
						bid = price_override
					else:
						bid = 0
						if self.rt_search and hasattr(self.rt_search, 'price_cache'):
							bid = self.rt_search.price_cache.get(stk_cd, {}).get('price', 0)
						
						if bid <= 0:
							bid = await asyncio.get_event_loop().run_in_executor(self.trade_pool, self.broker.get_current_price, stk_cd)
						
					if not bid or bid <= 0:
						self.log(f"❌ [매수불가] {stk_cd}: 현재가 조회 실패")
						if self.ui_callback:
							self.ui_callback("filter_update", {"code": stk_cd, "status": "가각오류"})
						return

					# [전역 설정] ATR 기반 리스크 관리 적용 시 (사용자 요청 사항)
					if get_setting('use_atr_risk_management', False) and (not meta or 'RiskDistance' not in meta):
						try:
							# 1. 일봉 데이터 확보 (캐시 활용)
							chart = await asyncio.get_event_loop().run_in_executor(
								self.trade_pool,
								lambda: self.data_manager.get_daily_chart(stk_cd, self.token, use_cache=True)
							)
							if chart and len(chart) >= 20:
								df = TI.preprocess_data(chart)
								atr_val = TI.atr(df['high'], df['low'], df['close'], 20).iloc[-1]
								if atr_val > 0:
									if not meta: meta = {}
									# 기본 고도화 설정: 2*ATR 손절, 4*ATR 익절
									meta['TargetStop'] = bid - (atr_val * 2)
									meta['TargetExit'] = bid + (atr_val * 4)
									meta['RiskDistance'] = atr_val * 2
									self.log(f"📐 [ATR계산] 전역설정에 의해 종목 변동성 산출: ATR {int(atr_val):,}원 적용")
						except Exception as ae:
							self.logger.error(f"Global ATR calculation failed for {stk_cd}: {ae}")
						
					# [안실장 고도화] ATR 기반 가변 수량 결정 (Turtle Trading Model)
					# 전략에서 'RiskDistance'(예: 2*ATR)가 넘어오면 이를 기준으로 1% 원칙 적용
					if meta and 'RiskDistance' in meta and float(meta.get('RiskDistance', 0)) > 0:
						risk_distance = float(meta['RiskDistance'])
						# 설정된 리스크 비중 (기본 1%)
						risk_pct = get_setting('risk_pct_per_trade', 1.0) / 100
						target_risk_amount = balance * risk_pct
						
						# 수량 = (총자산 * 리스크%) / (2 * ATR)
						advanced_qty = int(target_risk_amount // risk_distance)
						
						# [안전장치] 단, 계산된 수량이 가용 자금을 초과하면 안 됨
						max_affordable_qty = int((balance * CASH_MARGIN) // bid)
						qty = min(advanced_qty, max_affordable_qty)
						
						self.log(f"📐 [ATR사이징] 리스크폭:{int(risk_distance):,}원, 목표수량:{advanced_qty}주 (최종결정:{qty}주)")
					else:
						qty = int(expense // bid)

					if qty <= 0:
						self.log(f"❌ [자산미달] {stk_cd}: 설정된 매수금액({int(expense):,}원) 또는 리스크폭이 주가({int(bid):,}원)에 비해 커서 1주도 살 수 없습니다.")
						if self.ui_callback:
							self.ui_callback("filter_update", {"code": stk_cd, "status": "자산미달"})
						return
						
					# 5. 종목명 확정 (캐시 우선)
					if not stock_name or stock_name == 'Unknown':
						stock_name = self.broker.name_cache.get(stk_cd) or stk_cd
					
					# 6. 수동 확인 시나리오
					if manual_mode:
						self.log(f"❓ [승인대기] {stock_name}({stk_cd}) 승인 대기")
						if self.ui_callback:
							self.ui_callback("confirm", {
								'type': 'buy', 'code': stk_cd, 'name': stock_name, 'qty': qty, 'price': bid, 'cost': expense,
								'reason': msg_override or "조건 만족"
							})
							self.ui_callback("filter_update", {"code": stk_cd, "status": "승인대기"})
						return
		
					# 7. 실제 주문 실행 (시장가)
					self.log(f"🚀 [주문전송] {stock_name}({stk_cd}) {qty}주 시장가 매수 주문 시작")
					res_code, return_msg = await asyncio.get_running_loop().run_in_executor(self.trade_pool, self.broker.buy, stk_cd, qty, 0, '3')
					
					if str(res_code).strip() in ['0', '00']:
						# [중요] 주문 성공 시 즉시 '주문완료' 처리하고 잔고 캐시 무효화 (레이스 컨디션 방어)
						self.holdings_cache["time"] = 0 # 즉시 무효화하여 다음 주문 시 최신 잔고 조회 유도
						self.balance_cache["time"] = 0  # 예수금 캐시도 함께 무효화
						
						self.log(f"✅ {stock_name} 주문 요청 접수 완료. ({return_msg})")
						if self.ui_callback:
							self.ui_callback("filter_update", {"code": stk_cd, "status": "주문완료"})
						
						# 체결 대기 및 사후 처리는 Lock 밖에서 수행하도록 별도 태스크로 분리
						asyncio.create_task(self._process_buy_confirmation(stk_cd, stock_name, qty, bid, msg_override, meta=meta))
					else:
						self.log(f"❌ [주문거부] {stock_name}({stk_cd}) 실패 : {return_msg}")
						if self.ui_callback:
							self.ui_callback("filter_update", {"code": stk_cd, "status": "주문거절"})
				finally:
					# Lock 해제 직전 대기열 감소
					self.pending_buy_count -= 1
			except Exception as e:
				self.log(f"❌ [시스템오류] 매수 프로세스 중 예외 발생: {e}")
				self.logger.error(f"매수 프로세스 오류 (Lock 내부): {e}")
					
	async def _process_buy_confirmation(self, stk_cd, stock_name, qty, target_price, msg_override, meta=None):
		"""
		[비동기 체결 확인 및 사후 처리]
		주문 전송 후 Lock 밖에서 백그라운드로 실행됩니다.
		"""
		try:
			# 체결 대기 및 진단 (최대 5회 확인, 총 7.5초)
			actual_price = 0
			actual_qty = 0
			confirmed = False
			
			# [안실장 고도화] 전략 기반 가변 손절선/익절선 연동 저장
			if meta and ('TargetStop' in meta or 'TargetExit' in meta):
				from state_manager import update_stock_state
				t_stop = meta.get('TargetStop', 0)
				t_exit = meta.get('TargetExit', 0)
				update_stock_state(stk_cd, target_stop=t_stop, target_exit=t_exit)
				self.log(f"🧠 [Harness/출구설정] {stock_name}: 손절가 {int(t_stop):,}원, 익절가 {int(t_exit):,}원 설정 완료")

			for attempt in range(5):
				await asyncio.sleep(1.5)
				try:
					# 최근 5초 이내의 보유종목 정보가 있으면 캐시 활용 (부하 분산)
					now_t = time.time()
					if now_t - self.holdings_cache["time"] > 5:
						holdings = await asyncio.get_running_loop().run_in_executor(self.trade_pool, self.broker.get_holdings)
						self.holdings_cache["value"] = holdings
						self.holdings_cache["time"] = now_t
					else:
						holdings = self.holdings_cache["value"]

					target = next((h for h in holdings if h['stk_cd'].replace('A', '') == stk_cd), None)
					
					if target:
						val = target.get('pchs_avg_pric') or target.get('buy_avg_pric') or target.get('avg_prc') or 0
						q_val = target.get('rmnd_qty') or target.get('qty') or target.get('hold_qty') or 0
						actual_price = int(str(val).replace(',', '')) if val else target_price
						actual_qty = int(str(q_val).replace(',', '')) if q_val else qty
						
						if actual_qty > 0:
							confirmed = True
							break
				except Exception as e:
					self.logger.debug(f"Attempt {attempt+1} confirmation fail: {e}")

			if confirmed:
				msg_success = f"🎊 [체결성공] {stock_name}({stk_cd}) {actual_qty}주 매수 완료! (평단:{actual_price:,}원)"
				self.log(msg_success)
				tel_send(f"✅ {msg_success}")
				
				from history_manager import record_trade
				trade_msg = msg_override if msg_override else "전략 알고리즘"
				record_trade(stk_cd, 'buy', trade_msg, stock_name, str(actual_price), actual_qty)

				if self.ui_callback:
					self.ui_callback("trade", {
						"type": "매수", "time": datetime.now().strftime("%m/%d %H:%M:%S"),
						"code": stk_cd,
						"name": stock_name, "price": str(actual_price), "qty": actual_qty, "msg": trade_msg
					})
					self.ui_callback("filter_update", {"code": stk_cd, "price": str(actual_price), "status": "매수완료"})
			else:
				# 접수는 됐는데 체결 정보가 안 올라옴 (미체결 또는 지연)
				self.log(f"⚠️ [미체결경고] {stock_name} 주문은 보냈으나 잔고에 미반영. 취소 검토 중.")
				
				# 미체결 주문 자동 정리 (SOR)
				try:
					# [Optimized] Outstanding orders 조회는 캐싱하지 않고 실시간 확인
					orders = await asyncio.get_running_loop().run_in_executor(self.trade_pool, self.broker.get_outstanding_orders, stk_cd)
					if orders:
						self.log(f"⚠️ 미체결 발견: {stock_name}({stk_cd}). 즉시 취소 요청.")
						for ord in orders:
							ord_no = ord.get('ord_no')
							o_qty = ord.get('ord_qty')
							if ord_no:
								await asyncio.get_running_loop().run_in_executor(
									self.trade_pool, self.broker.cancel_order, ord_no, o_qty, stk_cd, '4'
								)
								if self.ui_callback:
									self.ui_callback("filter_update", {"code": stk_cd, "status": "미체결취소"})
				except Exception as oe:
					self.log(f"❌ 미체결 정리 중 오류: {oe}")

		except Exception as ge:
			self.logger.error(f"체결 확인 프로세스 오류: {ge}")

	async def _check_sell_loop(self):
		"""자동 매도 체크 루프 (REST 동기화 강화)"""
		while True:
			try:
				if not self.is_running or not self.token:
					await asyncio.sleep(1)
					continue
					
				manual_sell = get_setting('manual_sell', False)
				
				# [안실장 가이드] 장중이 아니면 매칭 및 매도 체크를 건너뜁니다 (API 부하 감소 및 에러 방지)
				if not self.is_market_open():
					await asyncio.sleep(10)
					continue

				# Ensure REST serialization across ALL tasks
				async with self.global_rest_sem:
					result = await asyncio.get_event_loop().run_in_executor(
						None, chk_n_sell, self.token, manual_sell, self.ui_callback, self.current_regime, self.acc_mgr, self.rt_search.price_cache
					)
				
				# [안실장 고도화] 매도가 발생했다면 즉시 잔고 캐시 무효화 (판 돈으로 바로 사기 위함)
				if isinstance(result, dict):
					if result.get('sold'):
						self.log(f"💰 매도 발생 확인 ({result.get('count',0)}건). 예수금 정보를 즉시 갱신합니다.")
						self.balance_cache["time"] = 0
						self.holdings_cache["time"] = 0
					
					if result.get('status') == 'manual_confirm':
						if self.ui_callback:
							self.ui_callback("confirm", result)

				
				# Slow down account check to leave room for enrichment (0.5 -> 2.5)
				await asyncio.sleep(2.5)
			except asyncio.CancelledError:
				self.log("매도 루프 취소됨.")
				break
			except Exception as e:
				if "429" in str(e):
					self.log("⚠️ [계좌조회] 429 속도제한 감지. 10초 대기...")
					await asyncio.sleep(10)
				else:
					self.logger.error(f"매도 루프 오류: {e}")
					await asyncio.sleep(2)

	async def _market_status_loop(self):
		"""지수 상황(Market Regime)을 주기적으로 업데이트하는 루프 (실시간성 강화)"""
		self.log("📡 [Market] 지수 상태 감시 루프 기동됨")
		while True:
			try:
				if not self.is_running or not self.token or not self.market_engine:
					await asyncio.sleep(5)
					continue
				
				self.log("🔍 [Market] 지수 분석 시작...")
				
				async def get_regime_safe():
					return await asyncio.get_event_loop().run_in_executor(
						None, self.market_engine.get_current_regime
					)
				
				regime_info = await get_regime_safe()
				
				# [안실장 고도화] 폭락장(CRASH)/약세장(BEAR) 감지 시 데이터 오류 방지를 위해 상시 10초 뒤 교차 검증 (오매도 방지)
				if regime_info:
					first_regime = regime_info['regime']
					# 1차 결과가 폭락이나 약세라면 조회 간격과 상관없이 즉시 재확인
					if first_regime in [MarketRegime.CRASH, MarketRegime.BEAR]:
						self.log(f"⏳ [Market] {first_regime.value} 감지. 데이터 교차 검증을 위해 10초 대기 중...")
						await asyncio.sleep(10)
						regime_info_v2 = await get_regime_safe()
						
						if regime_info_v2:
							# 두 번 연속으로 안 좋을 때만 최종 확정, 아니면 두 번째(최신) 데이터 신뢰
							self.log(f"✅ [Market] 2차 검증 완료: {regime_info_v2['regime'].value}")
							regime_info = regime_info_v2
				if regime_info:
					self.current_regime = regime_info
					regime_name = regime_info['regime'].value
					# 지수 추출 (None 체크 포함)
					kospi_p = 0
					kosdaq_p = 0
					if regime_info.get('kospi') and isinstance(regime_info['kospi'], dict):
						kospi_p = regime_info['kospi'].get('price', 0)
					if regime_info.get('kosdaq') and isinstance(regime_info['kosdaq'], dict):
						kosdaq_p = regime_info['kosdaq'].get('price', 0)

					display_kospi = f"{kospi_p:,}" if kospi_p > 0 else "-"
					display_kosdaq = f"{kosdaq_p:,}" if kosdaq_p > 0 else "-"
					
					if kospi_p > 0 and kospi_p < 1000:
						self.log(f"⚠️ [Data Check] KOSPI 지수가 비정상적으로 낮게 감지되었습니다 ({kospi_p}).")
					
					self.log(f"🧠 [시장분석] 현재 시장: '{regime_name}' (코스피:{display_kospi}, 코스닥:{display_kosdaq})")
					
					# [대시보드 강화] 실시간 지수 정보 UI 전송
					if self.ui_callback:
						# multiplier는 현재 market_status.py에 명시적 키가 없으므로 여기서 매핑
						mult = 1.0
						if regime_name == "폭락장": mult = 0.5
						elif regime_name == "약세장": mult = 0.8
						elif regime_name == "강세장": mult = 1.2
						
						self.ui_callback("market_update", {
							"regime": regime_name,
							"kospi": display_kospi,
							"kosdaq": display_kosdaq,
							"multiplier": mult
						})
				
				# 1분마다 갱신 (지연 시간 최적화)
				await asyncio.sleep(60)
				
			except asyncio.CancelledError:
				break
			except Exception as e:
				self.logger.error(f"Market status loop error: {e}")
				await asyncio.sleep(30)

	async def _watchlist_loop(self):
		"""Watchlist update and auto-switch for two-track mode"""
		while True:
			try:
				if self.is_running and self.token:
					# [Smart Auto-Switch] 3단계 하이브리드 파이프라인 (09시/10시/15시)
					now = datetime.now()
					current_mode = get_setting('trading_mode', 'cond_base')
					use_10h = get_setting('use_two_track', False)
					use_15h = get_setting('use_15h_switch', False)
					
					target_mode = None
					
					# 1. 15시 이후 전환 (최우선)
					if now.hour >= 15 and use_15h:
						target_mode = 'acc_swing'
						msg_tag = "15시(종배)"
					# 2. 10시 이후 전환
					elif now.hour >= 10 and use_10h:
						target_mode = 'cond_stock_radar'
						msg_tag = "10시(가속도)"
					
					# 3. 전환 실행
					if target_mode and current_mode != target_mode:
						self.log(f"🕒 [{msg_tag} 경과] 매매 모드 자동 전환: [{current_mode}] → [{target_mode}]")
						tel_send(f"🔄 [모드 자동 전환] {msg_tag}가 경과하여 '{target_mode}' 모드로 전환되었습니다.")
						
						update_setting('trading_mode', target_mode)
						update_setting('stock_radar_use', (target_mode == 'cond_stock_radar'))
						update_setting('acc_swing_use', (target_mode == 'acc_swing'))
						
						if self.ui_callback:
							self.ui_callback("settings_updated", {"mode": target_mode})

					# [NEW] 실시간 주도주 동기화 (Analyzer_Sig 연동)
					new_codes = await self.rt_search.refresh_lead_watchlist(self.token)
					if new_codes:
						for code in new_codes:
							stk_name = self.broker.get_stock_name(code)
							if isinstance(stk_name, dict): stk_name = stk_name.get('name') or stk_name.get('stk_nm')
							
							self.log(f"📡 [Analyzer_Sig] 신규 주도주 포착: {stk_name or code}({code}) -> 감시망 편입")
							
							# [신뢰도 강화] Analyzer_Sig에서 넘어온 실시간 가격 정보를 직접 활용
							price_data = self.rt_search.get_cached_price(code)
							l_price = price_data.get('price', 0) if price_data else 0
							l_ratio = price_data.get('change', 0.0) if price_data else 0.0
							
							# UI 전송 (포착 리스트 노출)
							self._ensure_ui_captured(code, stk_name, msg="[Analyzer_Sig] 주도주/후발주", price=l_price, ratio=l_ratio)
						
						# 신규 종목들 일괄 웜업 (차트 데이터 사전 로딩)
						asyncio.create_task(self.warm_up_stocks(new_codes, priority=1))
					
					# [Heartbeat] 엔진 생존 신고
					self.logger.info(f"💓 [Heartbeat] Engine Running. Watchlist: {len(self.rt_search.registered_stocks) if self.rt_search and hasattr(self.rt_search, 'registered_stocks') else 0} stocks.")
								
				await asyncio.sleep(10) # 10초마다 갱신 (Lead_Sig 연동 즉시 반영)
			except asyncio.CancelledError:
				break
			except Exception as e:
				self.logger.error(f"Watchlist 갱신 루프 오류: {e}")
				await asyncio.sleep(10)

	async def _auto_scan_accumulation(self):
		"""부재중 매집 데이터를 백그라운드에서 자동 분석 (상위 150개 대상)"""
		if not self.acc_mgr or not self.token: return
		
		try:
			from Analyzer_Sig.core.stock_universe import get_full_stock_universe
			universe_codes = get_full_stock_universe(self.token)
			
			# [NEW] 자원 재활용: 최근 30일 내 검색식에 포착되었던 종목 풀 추가
			captured_codes = self.acc_mgr.get_captured_pool_codes(days_limit=30)
			
			# 합치기 및 중복 제거
			combined_codes = list(dict.fromkeys(captured_codes + universe_codes))
			
			# [Diet] 분석 대상 150개로 대폭 축소 (API 부하 관리)
			target_codes = combined_codes[:150] 
			
			msg_src = f"(검색식포착 {len(captured_codes)}개 포함)" if captured_codes else ""
			self.log(f"📡 [백그라운드 스캔] 총 {len(target_codes)}개 {msg_src} 매집 정밀 분석 중...")
			
			count = 0
			total = len(target_codes)
			
			for code in target_codes:
				if not self.is_running: break
				
				# [CRITICAL] 전역 속도제한 체크 및 백오프
				if time.time() - self.last_429_time < 20:
					await asyncio.sleep(5)
					continue

				try:
					# DB에 오늘 데이터가 없을 때만 API 호출 (속도 최적화)
					if not self.acc_mgr.has_today_data(code):
						# [CRITICAL] 전역 REST 세마포어 사용 (다른 태스크와 충돌 방지)
						async with self.global_rest_sem:
							loop = asyncio.get_running_loop()
							# 1. 데이터 업데이트 (REST API 호출 포함)
							await loop.run_in_executor(None, self.acc_mgr.update_accumulation_data, code, self.token)
							
							# 2. 분석 지표 계산 및 저장
							metrics = await loop.run_in_executor(None, self.acc_mgr.calculate_metrics, code)
							self.acc_mgr.save_analysis_result(code, metrics)
							
							# API 호출 간격 유지 (안실장 가이드: 매집 분석은 무거운 작업이므로 1.5초 지연)
							await asyncio.sleep(1.5)
						
					count += 1
					if count % 10 == 0:
						self.log(f"📋 매집 스캔 진행 중... ({count}/{total})")
						await asyncio.sleep(0.5) # 루프 양보 및 부하 조절
						
				except Exception as e:
					if "429" in str(e):
						self.last_429_time = time.time()
						self.log(f"⏳ [매집스캔] 429 속도제한 발생. 20초 대기 모드 진입. ({code})")
						await asyncio.sleep(20)
					else:
						self.logger.error(f"Auto scan error for {code}: {e}")
					
			self.log("✅ [완료] 오늘의 매집 데이터 자동 분석이 완료되었습니다.")
			# [NEW] 스캔 직후 살아있는 매집주 레이더 즉시 가동
			asyncio.create_task(self._register_active_accumulation_radar())
			
		except Exception as e:
			self.log(f"⚠️ 매집 자동 스캔 중 오류 발생: {e}")

	async def _register_active_accumulation_radar(self):
		"""최근 고점 이후 세력 이탈이 없는 '살아있는 매집주'를 실시간 레이더 및 웜업에 강제 등록"""
		if not self.acc_mgr or not self.token: return
		
		try:
			# 최근 10일 내 75점 이상 중 이탈 없는 최상위 매집주 추출 (최대 40~50개 제어)
			loop = asyncio.get_running_loop()
			active_codes = await loop.run_in_executor(None, self.acc_mgr.get_active_accumulation_stocks, 75, 10)
			
			# API 서버 부담을 낮추기 위해 최대 40개만 반영
			active_codes = active_codes[:40]

			if active_codes:
				self.log(f"💎 [그물망] 세력 이탈 없는 1급 매집주 {len(active_codes)}개 발견! 실시간 감시 레이더 편입 완료.")
				
				# 1. 실시간 호가방 접속 (틱 수신 시작)
				await self.rt_search.register_sise(active_codes, self.token)
				
				# 2. 웜업(UI 테이블 표시 및 종목명 확보) 리스트에 밀어넣기
				# DB에서 추출된 코드이므로 이름은 "매집DB자동" 임시 부여, 웜업 내부에서 종목명 자동 수정됨
				items = [StockItem(code=code, name="매집DB자동", source="SWING") for code in active_codes]
				
				# 비동기로 웜업 엔진에 탑승시킴
				# [Fix] warm_up_stocks_async 대신 현재 클래스의 warm_up_stocks 호출 (내부 로직 통일)
				asyncio.create_task(self.warm_up_stocks(active_codes, priority=10))
				
				# 3. [확장] 갭 회복 매매(3번 모드)일 경우, 시가 갭 감시망에도 강제 접속 시킴
				current_mode = get_setting('trading_mode', 'cond_base')
				if current_mode in ['lw_breakout', 'gap_recovery']:
					for code in active_codes:
						if code not in self.gap_monitoring_stocks:
							self.gap_monitoring_stocks[code] = {'state': 'WATCHING'}
							
			else:
				self.log("📋 [그물망] 현재 특별히 관리할 매집 지속 종목이 DB에 없습니다.")
				
		except Exception as e:
			self.logger.error(f"Active acc radar registration error: {e}")
