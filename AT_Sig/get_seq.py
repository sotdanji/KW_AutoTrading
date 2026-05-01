import asyncio 
import websockets
import json
from config import get_current_config
from login import fn_au10001 as get_token

# SOCKET_URL 전역 변수 제거 (함수 내에서 동적 생성)

class WebSocketClient:
	def __init__(self, uri):
		self.uri = uri
		self.websocket = None
		self.connected = False
		self.keep_running = True
		self.received_data = None
		self.received_data = None
		self.login_event = asyncio.Event() # 로그인 완료 대기용 이벤트
		self.target_tr = None # 특정 TR 응답 대기용

	# WebSocket 서버에 연결합니다.
	async def connect(self, token):
		try:
			self.websocket = await websockets.connect(self.uri)
			self.connected = True
			print("서버와 연결을 시도 중입니다.")

			# 로그인 패킷
			param = {
				'trnm': 'LOGIN',
				'token': token
			}

			print('실시간 시세 서버로 로그인 패킷을 전송합니다.')
			# 웹소켓 연결 시 로그인 정보 전달
			if self.connected:
				if not isinstance(param, str):
					param = json.dumps(param)
				await self.websocket.send(param)

		except Exception as e:
			print(f'Connection error: {e}')
			self.connected = False

	# 서버에 메시지를 보냅니다.
	async def send_message(self, message, token=None):
		if not self.connected:
			if token:
				await self.connect(token)
		
		if self.connected:
			if not isinstance(message, str):
				message = json.dumps(message)
			await self.websocket.send(message)
			print(f'Message sent: {message}')

	# 서버에서 오는 메시지를 수신하여 출력합니다.
	async def receive_messages(self):
		while self.keep_running:
			try:
				if not self.websocket:
					break
				response = json.loads(await self.websocket.recv())

				# 메시지 유형이 LOGIN일 경우 로그인 시도 결과 체크
				if response.get('trnm') == 'LOGIN':
					if response.get('return_code') != 0:
						print('로그인 실패하였습니다. : ', response.get('return_msg'))
						self.keep_running = False 
						await self.disconnect()
					else:
						print('로그인 성공하였습니다.')
						self.login_event.set() # 로그인 성공 이벤트 발생

				# 메시지 유형이 PING일 경우 수신값 그대로 송신
				elif response.get('trnm') == 'PING':
					await self.send_message(response)

				# SYSTEM 메시지 무시 (연결 종료 방지)
				elif response.get('trnm') == 'SYSTEM':
					print(f"System Message: {response.get('message')}")
					continue

				if response.get('trnm') != 'PING' and response.get('trnm') != 'LOGIN':
					trnm = response.get('trnm')
					# 특정 TR만 대기하는 경우 필터링
					if self.target_tr and trnm != self.target_tr:
						print(f"Skipping TR: {trnm} (Target: {self.target_tr})")
						continue

					# Capture ANY other message as potential response
					# [Debug] 모든 중요 메시지 출력
					print(f"WS Recv Full: {response}")
					
					if 'data' in response:
						data = response['data']
					elif 'output' in response:
						data = response.get('output', [])
					elif 'block1' in response:
						data = response.get('block1', [])
					elif isinstance(response, list):
						data = response
					else:
						# 데이터 필드가 없는 경우 (예: 단순 ACK, 등록 성공 메시지 등)
						# 여기서 종료하면 안됨! 실제 데이터 패킷을 기다려야 함.
						print(f"No data field in response. Waiting for next message...")
						continue

					self.received_data = data
					self.keep_running = False  
					await self.disconnect()     
					return data

			except websockets.ConnectionClosed:
				print('Connection closed by the server')
				self.connected = False
				self.keep_running = False
			except Exception as e:
				print(f"Receive error: {e}")
				self.keep_running = False

	# WebSocket 실행
	async def run(self, token):
		await self.connect(token)
		await self.receive_messages()

	# WebSocket 연결 종료
	async def disconnect(self):
		self.keep_running = False
		if self.connected and self.websocket:
			await self.websocket.close()
			self.connected = False


async def get_condition_list(token):
	"""조건식 목록을 가져오는 함수"""
	if not token:
		print("조건식 조회 실패: 토큰 없음")
		return None
	try:
		# 설정 로드
		conf = get_current_config()
		socket_url = conf['socket_url']
		ws_url = socket_url + '/api/dostk/websocket'
		
		# WebSocketClient 전역 변수 선언
		websocket_client = WebSocketClient(ws_url)

		# WebSocket 클라이언트를 백그라운드에서 실행합니다.
		receive_task = asyncio.create_task(websocket_client.run(token))

		# 로그인 완료 대기 (최대 5초)
		try:
			await asyncio.wait_for(websocket_client.login_event.wait(), timeout=5.0)
		except asyncio.TimeoutError:
			print("로그인 시간 초과")
			websocket_client.keep_running = False
			return None

		# 실시간 항목 등록 (CNSRLST)
		await websocket_client.send_message({ 
			'trnm': 'CNSRLST', # TR명
		}, token)

		# 수신 작업이 종료될 때까지 대기
		await receive_task
		
		# 결과 반환
		return websocket_client.received_data
		
	except Exception as e:
		print(f"조건식 목록 가져오기 실패: {e}")
		return None

async def get_condition_stock_list(token, seq_idx):
	"""특정 조건식(seq)의 종목 리스트를 가져오는 함수 (단순조회)"""
	if not token:
		return None
	try:
		# 설정 로드
		conf = get_current_config()
		socket_url = conf['socket_url']
		ws_url = socket_url + '/api/dostk/websocket'
		
		websocket_client = WebSocketClient(ws_url)
		# CNSR 응답 대기 (조건검색 결과) - 필수 설정 (CNSRLST 응답 무시하기 위해)
		websocket_client.target_tr = 'CNSRREQ'
		# Note: 서버 응답 TR이 'CNSR' 인지 확인 필요. 보통 조회 요청에 대한 응답은 같은 TR이거나 연관된 TR임.
		# rt_search.py 로직 상 on_receive_data 는 'REAL' 일 때 처리하지만,
		# 단순 조회 요청(search_type='0')의 경우 응답 포맷이 다를 수 있음.
		# 일단 모든 응답을 받도록 target_tr 설정 안함 (또는 확인 후 설정)
		
		# 백그라운드 실행
		receive_task = asyncio.create_task(websocket_client.run(token))

		# 로그인 대기
		try:
			await asyncio.wait_for(websocket_client.login_event.wait(), timeout=5.0)
		except asyncio.TimeoutError:
			print("로그인 시간 초과")
			websocket_client.keep_running = False
			return None

		# [CRITICAL] 조건검색 실시간 요청 전제조건: CNSRLST 먼저 요청해야 함 (API 문서)
		# CNSRLST 응답은 target_tr이 아니므로 receive_messages에서 무시되고 연결 유지됨
		print("조건검색 필수 선행: 목록 조회(CNSRLST) 요청")
		await websocket_client.send_message({'trnm': 'CNSRLST'}, token)
		await asyncio.sleep(1.0) # 서버 처리 대기

		# 조건검색 요청 (실시간 type='1', seq는 zfill 없이 그대로)
		seq_str = str(seq_idx)
		params = { 
			'trnm': 'CNSRREQ', 
			'seq': seq_str, 
			'search_type': '1', 
			'stex_tp': 'K', 
		}
		
		await websocket_client.send_message(params, token)
		print(f"조건검색 요청(실시간): {seq_str}")

		# 데이터 수신 대기 (타임아웃 적용 - 종목 많을 수 있으므로 넉넉히)
		try:
			# 30초 대기 (장전 데이터가 많거나 서버 지연 대비)
			await asyncio.wait_for(receive_task, timeout=30.0)
		except asyncio.TimeoutError:
			print(f"조건검색({seq_str}) 조회 결과 수신 시간 초과")
			websocket_client.keep_running = False
			await websocket_client.disconnect()
			# 타임아웃이라도 일부 데이터가 들어왔는지 확인
			if websocket_client.received_data:
				raw_data = websocket_client.received_data
			else:
				return None
		else:
			raw_data = websocket_client.received_data
		
		stock_list = []
		if raw_data:
			# API 문서에 따르면 { 'trnm': 'CNSRREQ', 'data': [...] } 형태일 수 있음
			target_list = None
			if isinstance(raw_data, list):
				target_list = raw_data
			elif isinstance(raw_data, dict):
				# data 키가 있으면 사용, 없으면 output 등 다른 키 확인하거나 자체를 리스트로 간주 불가
				if 'data' in raw_data:
					target_list = raw_data['data']
				else:
					# 혹시 딕셔너리 자체가 종목 정보일 경우는 드물지만 예외처리
					target_list = [raw_data]

			if target_list and isinstance(target_list, list):
				for item in target_list:
					# API 문서 기준 종목코드는 'jmcode', 종목명은 없는 경우도 많음
					# 또한 종목코드는 '9001' 키로 들어올 수도 있음 (문서 예제 참고)
					code = item.get('jmcode', '') 
					if not code:
						code = item.get('code', '') # 기존 호환
					if not code:
						code = item.get('9001', '') # 문서 예제 키

					name = item.get('name', '') 
					if not name:
						name = item.get('302', '') # 문서 예제 키 (종목명)

					if code:
						# 종목코드 앞에 'A'가 붙어올 수 있음 (API 특성)
						if code.startswith('A'):
							code = code[1:]
						stock_list.append({'code': code, 'name': name})
				
		return stock_list

	except Exception as e:
		print(f"조건검색 결과 조회 실패: {e}")
		return None

async def main():
	# For testing purposes only
    pass

# asyncio로 프로그램을 실행합니다.
if __name__ == '__main__':
	asyncio.run(main())