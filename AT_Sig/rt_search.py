import asyncio
import websockets
import json
import random
import os
from config import get_current_config
from get_setting import get_setting
from login import fn_au10001 as get_token
from stock_info import get_stock_info_async

class RealTimeSearch:
	def __init__(self, on_connection_closed=None):
		# 설정 로드
		conf = get_current_config()
		self.socket_url = conf['socket_url'] + '/api/dostk/websocket'
		self.websocket = None
		self.connected = False
		self.keep_running = True
		self.receive_task = None
		self.on_connection_closed = on_connection_closed  # 연결 종료 시 호출될 콜백 함수
		self.token = None  # 토큰 저장
		self.on_receive_data = None # 데이터 수신 시 호출될 콜백 함수
		self.on_message = None # 모든 메시지 수신 시 호출될 콜백 함수
		self.login_event = None # Deferred init
		self.registered_seqs = set() # 등록된 조건식 시퀀스 관리
		self.seq_to_name = {} # [NEW] 조건식 번호 -> 이름 매핑 저장
		
		# [CRITICAL] 전역 시세 캐시: 429 에러 방지 및 소켓 데이터 활용 극대화
		self.price_cache = {} # { 'code': { 'price': 1000, 'change': 1.5, 'volume': 10000, 'time': ... } }

	def _ensure_event(self):
		if self.login_event is None:
			self.login_event = asyncio.Event()

	async def disconnect(self):
		"""웹소켓 연결을 종료합니다."""
		self.connected = False
		if self.websocket:
			try:
				await self.websocket.close()
			except:
				pass
			self.websocket = None

	async def connect(self, token):
		"""WebSocket 서버에 연결합니다."""
		self._ensure_event()
		try:
			# 설정 재로드 (실전/모의 변경 반영)
			conf = get_current_config()
			self.socket_url = conf['socket_url'] + '/api/dostk/websocket'

			self.token = token  # 토큰 저장
			# [안실장 픽스] websockets 라이브러리 차원의 핑 타임아웃(1011 에러) 방지를 위해 interval/timeout을 None으로 설정
			# 이미 application level(trnm: PING)에서 핑/퐁을 처리하고 있으므로 중복 처리를 차단합니다.
			self.websocket = await websockets.connect(self.socket_url, ping_interval=None, ping_timeout=None)
			self.connected = True
			print("서버와 연결을 시도 중입니다.")

			# 로그인 패킷
			param = {
				'trnm': 'LOGIN',
				'token': token
			}

			print('실시간 시세 서버로 로그인 패킷을 전송합니다.')
			# 웹소켓 연결 시 로그인 정보 전달 (연결 즉시 전송)
			if self.connected:
				if not isinstance(param, str):
					param = json.dumps(param)
				await self.websocket.send(param)

		except Exception as e:
			print(f'Connection error: {e}')
			self.connected = False
			self.websocket = None

	async def send_message(self, message, token=None):
		"""서버에 메시지를 보냅니다. 연결이 없다면 자동으로 연결합니다."""
		if not self.connected:
			if token:
				await self.connect(token)  # 연결이 끊어졌다면 재연결
		if self.connected and self.websocket:
			# message가 문자열이 아니면 JSON으로 직렬화
			if not isinstance(message, str):
				message = json.dumps(message)

			await self.websocket.send(message)
			
			# PING 메시지는 로그 출력 제외
			is_ping = False
			if isinstance(message, dict) and message.get('trnm') == 'PING':
				is_ping = True
			elif isinstance(message, str) and ('"trnm": "PING"' in message or "'trnm': 'PING'" in message):
				is_ping = True
				
			if not is_ping:
				print(f'Message sent: {message}')

	async def receive_messages(self):
		"""서버에서 오는 메시지를 수신하여 출력합니다."""
		while self.keep_running and self.connected and self.websocket:
			raw_message = None
			try:
				# 서버로부터 수신한 메시지를 받음
				raw_message = await self.websocket.recv()
				# JSON 형식으로 파싱
				response = json.loads(raw_message)
				if not response or not isinstance(response, dict):
					continue

				# 메시지 유형이 LOGIN일 경우 로그인 시도 결과 체크
				if response.get('trnm') == 'LOGIN':
					if response.get('return_code') != 0:
						print('로그인 실패하였습니다. : ', response.get('return_msg'))
						await self.disconnect()
					else:
						print('로그인 성공하였습니다.')
						self._ensure_event()
						self.login_event.set() # 로그인 성공 이벤트 설정

				# 메시지 유형이 PING일 경우 수신값 그대로 송신
				elif response.get('trnm') == 'PING':
					# print(f'PING 메시지 수신: {response}')
					await self.send_message(response)
				
				trnm = response.get('trnm')
				# [Debug] Packet Flow Check (Removed noise)

				# [NEW] 조건검색 식 목록 수신 처리
				if trnm == 'CNSRLST':
					# API 문서 상 output 키가 일반적이나 data일 수도 있음
					data = response.get('output') or response.get('data') 
					print(f"📜 [조건식 목록 수신] {len(data) if data else 0}개")
					if data and isinstance(data, list):
						for idx, item in enumerate(data):
							# 리스트 형태 ['1', '이름'] 인지 딕셔너리 {'seq':'1'} 인지 확인
							s, n = '?', '?'
							if isinstance(item, list) and len(item) >= 2:
								s, n = str(item[0]), str(item[1])
							elif isinstance(item, dict):
								s = item.get('seq') or item.get('index') or str(idx)
								n = item.get('name') or item.get('title') or item.get('cond_name') or 'Unknown'
							else:
								s, n = str(idx), str(item)
							
							# [NEW] 매핑 저장
							self.seq_to_name[s] = n
							print(f"   -> [Seq:{s}] {n}")
				
				# [Debug] Unidentified TR names
				elif trnm not in ['REAL', 'H1', 'PING', 'LOGIN', 'CNSRREQ', 'CNSRLST', 'REG']:
					print(f"⚠️ [Unidentified WS TR] {trnm}: {response}")

				# ... (기타 로직) ...
				if response.get('trnm') != 'PING' and response.get('trnm') != 'LOGIN':
					# [NEW] REG 요청 결과 처리
					if trnm == 'REG':
						ret_code = response.get('return_code', 0)
						if str(ret_code) == '0':
							pass # 성공
						else:
							print(f"❌ [실시간등록실패] {response.get('return_msg', '사유미상')}")
						continue
					
					tr_data = response.get('data') or response.get('output')
					if tr_data and self.on_message:
						await self.on_message(response)
					
				# [NEW] 실시간 시세(H1, 0B, 02) 및 보조 데이터(0A:호가, 13:프로그램) 처리
				if trnm in ['REAL', 'H1', '0B', '02', '0A', '13'] and response.get('data'):
						items = response['data']
						if items and self.on_receive_data:
							for item in items:
								if not item or not isinstance(item, dict): continue
								# [Debug] 포착 종목 로깅
								try:
									vals = item.get('values', {})
									code = vals.get('9001') or item.get('item') or item.get('code') or item.get('jmcode') or item.get('stk_cd') or 'Unknown'
									if isinstance(code, str) and code.startswith('A'): 
										code = code[1:]
									
									# Ensure vals has the code for downstream processing
									if '9001' not in vals and code != 'Unknown':
										vals['9001'] = code

									# [CRITICAL] TR 종류별 전용 캐시 업데이트
									if trnm == '0A': # 주식기세(호가)
										if code not in self.price_cache: self.price_cache[code] = {}
										self.price_cache[code].update({
											'total_ask': int(str(vals.get('121', '0')).replace(',', '') or 0),
											'total_bid': int(str(vals.get('125', '0')).replace(',', '') or 0),
											'orderbook_time': asyncio.get_event_loop().time()
										})
										continue # 레이더 검증용이므로 시세 로직은 건너뜀

									if trnm == '13': # 프로그램매매
										if code not in self.price_cache: self.price_cache[code] = {}
										self.price_cache[code].update({
											'prm_net_buy': int(str(vals.get('121', '0')).replace(',', '') or 0),
											'prm_time': asyncio.get_event_loop().time()
										})
										continue

									# [보정 로직] 현재가 0인 경우 캐시 또는 API 사용
									cur_price = vals.get('10')
									if not cur_price or str(cur_price).strip() in ['', '0']:
										# 1. 시세 캐시에 유효한 값이 있는지 확인
										cached = self.get_cached_price(code)
										if cached and cached.get('price', 0) > 0:
											vals['10'] = str(cached['price'])
											vals['12'] = str(cached.get('change', '0.00'))
											vals['13'] = str(cached.get('volume', '0'))
										else:
											# 2. 캐시에도 없으면 REST API (5분에 1번만)
											now = asyncio.get_event_loop().time()
											if not hasattr(self, 'enrichment_cache'): self.enrichment_cache = {}
											last_try = self.enrichment_cache.get(code, 0)
											
											if now - last_try > 300:
												self.enrichment_cache[code] = now
												try:
													stock_info, status = await get_stock_info_async(code, self.token)
													if stock_info:
														vals['10'] = str(stock_info.get('stk_prc', '0'))
														vals['12'] = str(stock_info.get('prdy_ctrt', '0.00'))
														vals['13'] = str(stock_info.get('acml_vol', '0'))
												except: pass

									# [UPDATE] 전역 시세 캐시 업데이트 (보정 후 최종값 저장)
									new_price = abs(int(float(str(vals.get('10', '0')).replace(',', '') or 0)))
									new_vol = int(float(str(vals.get('13', '0')).replace(',', '') or 0))
									strength = float(str(vals.get('20', '100')).replace(',', '') or 100.0) # [추가] 실시간 체결강도
									
									if new_price > 0:
										item_cache = {
											'price': new_price,
											'change': float(str(vals.get('12', '0')).replace('%', '') or 0.0),
											'volume': new_vol,
											'strength': strength,
											'open': abs(int(float(str(vals.get('16', '0')).replace(',', '') or 0))),
											'time': asyncio.get_event_loop().time(),
											'name': self.broker.get_stock_name(code) if hasattr(self, 'broker') else None
										}
										
										# 기존 호가 잔량 정보 유지 (0A TR에서 들어온 것)
										if code in self.price_cache:
											item_cache['total_ask'] = self.price_cache[code].get('total_ask', 0)
											item_cache['total_bid'] = self.price_cache[code].get('total_bid', 0)
										
										self.price_cache[code] = item_cache


									await self.on_receive_data(item)
								except Exception as e:
									print(f"종목 실시간 데이터 처리 중 오류: {e}")
									pass

			except websockets.ConnectionClosed:
				if self.on_connection_closed:
					asyncio.create_task(self.on_connection_closed())
				continue
			except Exception as e:
				if not self.keep_running: break
				print(f"📡 [WS] 수신 중 오류 발생: {e}. 5초 후 재시도...")
				self.connected = False
				await asyncio.sleep(5)
				try:
					if await self.connect(self.token):
						await asyncio.sleep(2)
						await self.re_register_all()
				except: pass
				continue

	async def start(self, token):
		"""
		실시간 검색을 시작합니다.
		"""
		try:
			# [안실장 픽스] 이미 동일한 토큰으로 연결되어 있다면 중복 연결 시도 방지 (CODE 8005 방어)
			if self.connected and self.websocket and self.token == token:
				print("📡 [WS] 이미 유효한 세션으로 연결되어 있습니다. 설정을 유지합니다.")
				# 필요한 경우 현재 설정에 맞춰 조건식만 재요청
				return True

			# keep_running 플래그를 True로 리셋
			self.keep_running = True
			self._ensure_event()
			self.login_event.clear() # 이벤트 초기화
			
			# 기존 연결 정리
			if self.receive_task and not self.receive_task.done():
				self.receive_task.cancel()
				await self.disconnect()

			# WebSocket 연결 (내부에서 connect 호출)
			# 하지만 start 메서드 내에서 connect를 호출하는 것이 아니라
			# receive_messages 태스크를 시작하고 그 안에서 메시지를 기다려야 함.
			# connect는 start에서 호출.
			await self.connect(token)
			
			if not self.connected:
				print('WebSocket 연결에 실패했습니다.')
				return False

			# WebSocket 메시지 수신을 백그라운드에서 실행합니다.
			self.receive_task = asyncio.create_task(self.receive_messages())

			# 로그인 완료 대기 (최대 10초)
			try:
				await asyncio.wait_for(self.login_event.wait(), timeout=10.0)
				# [CRITICAL] 조건검색 필수 선행: 목록 조회(CNSRLST)
				print(" rt_search: 조건검색 필수 선행 목록 조회(CNSRLST) 요청")
				await self.send_message({'trnm': 'CNSRLST'}, token)
				
				# [안정화 대기] 로그인/목록조회 직후 요청 시 응답 누락 방지
				await asyncio.sleep(3.0)
			except asyncio.TimeoutError:
				print("로그인 응답 시간 초과 (10초)")
				return False

			# 조건검색식 리스트 로드
			seq_list = get_setting('search_seq_list', [])
			if not seq_list:
				seq = get_setting('search_seq', '0')
				if seq: seq_list = [seq]
			
			# [안주인 정비] 조건검색식 등록 범위 제한 (설정에 따라 0, 1 제외 여부 결정)
			use_interest = get_setting('use_interest_formula', False)
			if use_interest:
				trading_candidate_seqs = [str(s) for s in seq_list][:3]
			else:
				trading_candidate_seqs = [str(s) for s in seq_list if str(s) not in ['0', '1']][:3]
			
			if not trading_candidate_seqs and not get_setting('warmup_seq_list', []):
				print("등록할 조건 검색식이 없습니다.")
				return True # 연결은 성공했으므로 True

			# 1. Collect all sequences to register
			sequences_to_register = {} # seq -> search_type

			warmup_seq_list = get_setting('warmup_seq_list', [])
			for seq_id in warmup_seq_list:
				seq_str = str(seq_id)
				# "장전관심" 등 백그라운드로 가져오는 리스트는 실시간('1')으로 유지하되, 
				# 엔진에서 포착 대상에서는 제외함 (rt_search 단에서는 일단 모니터링 유지)
				search_type = '1' 
				sequences_to_register[seq_str] = search_type

			# 1-2. User Selected List (Trading Seqs)
			for seq_str in trading_candidate_seqs:
				sequences_to_register[seq_str] = '1' # Force Real-time

			# 2. Register Requests
			self.registered_seqs.clear()
			registered_count = 0

			for seq_str, search_type in sequences_to_register.items():
				try:
					await self.send_message({ 
						'trnm': 'CNSRREQ', 
						'seq': seq_str, 
						'search_type': search_type, 
						'stex_tp': 'K', 
						'cont_yn': 'N',
						'next_key': '',
					}, token)
					
					type_desc = "실시간" if search_type == '1' else "단순조회"
					print(f'조건식 요청({type_desc}): seq {seq_str}')
					
					self.registered_seqs.add(seq_str)
					registered_count += 1
					await asyncio.sleep(0.5) # API Rate Limit (Increased)
				except Exception as e:
					print(f"조건식({seq_str}) 등록 실패: {e}")

			print(f'조건검색 시작 완료 | 총 {registered_count}개 조건식 등록됨')
			
			# 추가로 lead_watchlist 에 있는 종목들도 등록 (초기 등록)
			await self.refresh_lead_watchlist(token)
			
			return True
			
		except Exception as e:
			print(f'실시간 검색 시작 실패: {e}')
			return False

	async def refresh_lead_watchlist(self, token):
		"""
		lead_watchlist.json에 등록된 종목들을 실시간 감시에 추가합니다.
		파일이 갱신되었을 때만 처리하여 부하를 줄입니다.
		"""
		path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lead_watchlist.json")
		if not os.path.exists(path):
			return []

		try:
			# 파일 수정 시간 체크 (최적화)
			mtime = os.path.getmtime(path)
			if hasattr(self, 'last_watchlist_time') and self.last_watchlist_time == mtime:
				return []
			self.last_watchlist_time = mtime

			with open(path, "r", encoding="utf-8") as f:
				watchlist = json.load(f)
			
			new_codes = []
			for stock in watchlist:
				if not stock or not isinstance(stock, dict): continue
				code = stock.get('code')
				if code:
					clean_code = str(code).strip()
					if clean_code.startswith('A'): clean_code = clean_code[1:]
					
					if not hasattr(self, 'registered_stocks'):
						self.registered_stocks = set()
					
					if clean_code not in self.registered_stocks:
						new_codes.append(clean_code)
			
			if new_codes:
				print(f"📡 [Lead_Sig] 신규 주도주/후발주 {len(new_codes)}개 감지. 실시간 시세 레이더 등록을 시도합니다.")
				# 웹소켓 REG 패킷 전송
				await self.register_sise(new_codes, token)
			
			return new_codes
		except Exception as e:
			print(f"Lead Watchlist 로드 및 등록 실패: {e}")
			return []
		# import os
		# import json
		# path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lead_watchlist.json")
		# if not os.path.exists(path):
		# 	return

		# try:
		# 	with open(path, "r", encoding="utf-8") as f:
		# 		watchlist = json.load(f)
			
		# 	for stock in watchlist:
		# 		code = stock.get('code')
		# 		if code:
		# 			# 키움 웹소켓 REG 패킷 (서버 사양에 따라 다를 수 있으나 일반적인 형식)
		# 			await self.send_message({
		# 				'trnm': 'REG', # 혹은 'REALREQ' 등 서버 프로토콜에 맞춤
		# 				'code': code,
		# 			}, token)
		# 			# print(f"Lead Watchlist 등록: {code}")
		# except Exception as e:
		# 	print(f"Lead Watchlist 로드 실패: {e}")

	async def register_sise(self, codes, token=None):
		"""
		특정 종목들을 실시간 시세(REG) 감시망에 등록합니다.
		:param codes: 단일 종목코드(str) 또는 리스트(list)
		"""
		if not self.connected or not self.websocket:
			return False
		
		# 이미 등록된 종목인지 확인 (선택 사항)
		if not hasattr(self, 'registered_stocks'):
			self.registered_stocks = set()
		
		if isinstance(codes, str):
			codes = [codes]
			
		codes_to_reg = []
		for code in codes:
			clean_code = str(code).strip()
			if clean_code.startswith('A'): clean_code = clean_code[1:]
			if clean_code and clean_code not in self.registered_stocks:
				codes_to_reg.append(clean_code)

		if not codes_to_reg:
			return True
			
		try:
			# [CRITICAL] 100개씩 분할 등록 (서버 제한: 한 번에 최대 100개)
			for i in range(0, len(codes_to_reg), 100):
				chunk = codes_to_reg[i:i + 100]
				
				# [CRITICAL] TRNM: REG (키움 공식 명세 기준 실시간 등록)
				# 그룹당 100대 제한이 있으므로 chunk마다 고유 group_no 부여
				params = {
					'trnm': 'REG',
					'grp_no': str(i // 100), # 0, 1, 2... 순차 부여
					'refresh': '1', 
					'data': [
						{
							'item': chunk,
							'type': ['0A', '0B'] # 0A:호기잔량, 0B:주식체결 (13:프로그램매매는 지원되지 않아 제거)
						}
					]
				}
				await self.send_message(params, token)
				for c in chunk:
					self.registered_stocks.add(c)
				
				if len(chunk) > 1:
					print(f"📡 [실시간등록] {len(chunk)}개 종목 시세 레이더 등록 완료 (Chunk {i//100 + 1})")
				else:
					print(f"📡 [실시간등록] {chunk[0]} 시세 레이더 등록 완료")
				
				# [CRITICAL] 호출 과다 방지를 위해 지연 시간을 약간 늘립니다 (0.1 -> 0.5)
				await asyncio.sleep(0.5)

			return True
		except Exception as e:
			print(f"시세 일괄 등록 에러: {e}")
			return False

	def get_cached_price(self, code):
		"""
		캐시된 실시간 시세를 반환합니다.
		:param code: 종목코드
		:return: dict 또는 None
		"""
		clean_code = str(code).strip()
		if clean_code.startswith('A'): clean_code = clean_code[1:]
		return self.price_cache.get(clean_code)


	async def re_register_all(self):
		"""연결 재개 시 이전 등록 내역을 다시 등록합니다."""
		if not self.connected or not self.websocket: return
		
		# 1. 조건검색식 재등록
		if self.registered_seqs:
			print(f"📡 [WS] {len(self.registered_seqs)}개 조건검색식 재등록을 시작합니다...")
			for seq in list(self.registered_seqs):
				try:
					await self.send_message({
						'trnm': 'CNSRREQ', 
						'seq': str(seq), 
						'search_type': '1', 
						'stex_tp': 'K', 
						'cont_yn': 'N',
						'next_key': '',
					})
					await asyncio.sleep(0.5)
				except: pass

		# 2. 실시간 종목 시세 재등록
		if hasattr(self, 'registered_stocks') and self.registered_stocks:
			stocks = list(self.registered_stocks)
			print(f"📡 [WS] {len(stocks)}개 관심종목 시세 재등록을 시작합니다...")
			# self.registered_stocks 를 초기화하지 않고 register_sise 호출
			# register_sise 내부에서 registered_stocks에 없는 것만 추가하므로, 
			# 여기서는 임시로 registered_stocks를 비우고 다시 등록하게 함.
			temp_stocks = stocks.copy()
			self.registered_stocks.clear() 
			await self.register_sise(temp_stocks, self.token)

	async def stop(self):
		"""
		웹소켓 연결을 종료합니다.
		
		Returns:
			bool: 성공 여부
		"""
		try:
			# [권장] 종료 전 등록된 실시간 조건검색 해제 (CNSRCLR)
			# self.registered_seqs 가 존재한다면 해제 패킷 전송
			if hasattr(self, 'registered_seqs') and self.registered_seqs and self.websocket and self.connected:
				for seq in list(self.registered_seqs):
					try:
						await self.send_message({
							'trnm': 'CNSRCLR',
							'seq': str(seq)
						})
						print(f"조건검색 실시간 해제 요청: seq {seq}")
						await asyncio.sleep(0.1)
					except:
						pass
				self.registered_seqs.clear()

			# 이미 웹소켓이 돌고 있다면 종료
			if self.receive_task and not self.receive_task.done():
				self.receive_task.cancel()
				try:
					await self.receive_task
				except asyncio.CancelledError:
					pass
				self.receive_task = None
				await self.disconnect()
			
			print('실시간 검색이 중지되었습니다.')
			return True
			
		except Exception as e:
			print(f'실시간 검색 중지 실패: {e}')
			return False

# 사용 예시
async def main():
	rt_search = RealTimeSearch()
	
	# 실시간 검색 시작
	success = await rt_search.start(get_token())
	if success:
		print("실시간 검색이 성공적으로 시작되었습니다.")
		
		# 10초 후 중지
		await asyncio.sleep(10)
		await rt_search.stop()

if __name__ == '__main__':
	asyncio.run(main())
