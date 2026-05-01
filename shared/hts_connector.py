import ctypes
import time
from ctypes import wintypes

# Windows API 및 상수 정의
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
imm32 = ctypes.WinDLL('imm32', use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND

# 가상 키코드
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_A = 0x41
VK_BACK = 0x08
KEYEVENTF_KEYUP = 0x0002

# IME 관련 상수
IMC_GETCONVERSIONSTATUS = 0x0001
IMC_SETCONVERSIONSTATUS = 0x0002
IME_CMODE_ALPHANUMERIC = 0x0000
IME_CMODE_NATIVE = 0x0001

# GUI 스레드 정보 구조체
class GUITHREADINFO(ctypes.Structure):
	_fields_ = [
		("cbSize", wintypes.DWORD),
		("flags", wintypes.DWORD),
		("hwndActive", wintypes.HWND),
		("hwndFocus", wintypes.HWND),
		("hwndCapture", wintypes.HWND),
		("hwndMenuOwner", wintypes.HWND),
		("hwndMoveSize", wintypes.HWND),
		("hwndCaret", wintypes.HWND),
		("rcCaret", wintypes.RECT)
	]

def get_focused_window(target_hwnd=None):
	"""지정된 윈도우에서 포커스된 핸들을 반환합니다."""
	gui_info = GUITHREADINFO()
	gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)
	thread_id = user32.GetWindowThreadProcessId(target_hwnd, None) if target_hwnd else 0
	if user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
		if gui_info.hwndFocus:
			return gui_info.hwndFocus
	return None

def set_english_mode(hwnd=None):
	"""HTS 입력 모드를 영어로 전환합니다."""
	try:
		english_layout = user32.LoadKeyboardLayoutW("00000409", 1)
		user32.ActivateKeyboardLayout(english_layout, 0)
		if hwnd:
			user32.PostMessageW(hwnd, 0x0050, 0, english_layout)
			himc = imm32.ImmGetContext(hwnd)
			if himc:
				imm32.ImmSetConversionStatus(himc, 0, 0)
				imm32.ImmReleaseContext(hwnd, himc)
	except Exception as e:
		print(f"[HTS 연동/IME] 전환 오류: {e}")

def restore_korean_mode(hwnd=None):
	"""HTS 입력 모드를 한국어로 복구합니다."""
	try:
		korean_layout = user32.LoadKeyboardLayoutW("00000412", 1)
		user32.ActivateKeyboardLayout(korean_layout, 0)
		if hwnd:
			user32.PostMessageW(hwnd, 0x0050, 0, korean_layout)
			himc = imm32.ImmGetContext(hwnd)
			if himc:
				imm32.ImmSetConversionStatus(himc, 1, 0)
				imm32.ImmReleaseContext(hwnd, himc)
	except:
		pass

def is_admin():
	"""현재 프로세스가 관리자 권한인지 확인합니다."""
	try:
		return shell32.IsUserAnAdmin() != 0
	except:
		return False

def get_window_text(hwnd):
	"""창 제목을 가져옵니다."""
	length = user32.GetWindowTextLengthW(hwnd)
	buff = ctypes.create_unicode_buffer(length + 1)
	user32.GetWindowTextW(hwnd, buff, length + 1)
	return buff.value

def find_hts_window():
	"""영웅문 메인 창 핸들을 찾습니다."""
	for cls in ["_NKHeroMainClass", "KHuMain", "KHVP_Main", "KHVT_Main"]:
		hwnd = user32.FindWindowW(cls, None)
		if hwnd and user32.IsWindowVisible(hwnd): 
			return hwnd
	return None

def find_0600_chart_window(main_hwnd):
	"""[0600] 종합차트 창을 찾습니다."""
	found_hwnd = [None]
	def enum_child_proc(hwnd, lParam):
		title = get_window_text(hwnd)
		if "0600" in title or "종합차트" in title:
			found_hwnd[0] = hwnd
			return False
		return True
	user32.EnumChildWindows(main_hwnd, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(enum_child_proc), 0)
	return found_hwnd[0]

def release_all_modifiers():
	"""조합키를 해제합니다."""
	for vk in [VK_CONTROL, VK_SHIFT, VK_MENU]:
		user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
	time.sleep(0.05)

def key_tap(vk, modifier=None):
	"""일반 가상 키코드를 사용하여 키를 누릅니다 (조합키 지원)."""
	if modifier:
		user32.keybd_event(modifier, 0, 0, 0)
	user32.keybd_event(vk, 0, 0, 0)
	time.sleep(0.02)
	user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
	if modifier:
		user32.keybd_event(modifier, 0, KEYEVENTF_KEYUP, 0)
	time.sleep(0.02)

def send_to_hts(stock_code):
	"""
	디펜시브 키 타이핑 방식을 사용하여 HTS 종목을 갱신합니다. (V5)
	- 관리자 권한 체크
	- [0600] 차트창 존재 여부 확인 및 포커싱 시도
	- 창 제목 검증을 통한 오작동 방지
	"""
	if not stock_code: return False
	
	# 0. 관리자 권한 경고 (로그용)
	if not is_admin():
		print("[HTS 연동/경고] Antigravity가 관리자 권한으로 실행되지 않았습니다. HTS 제어가 실패할 수 있습니다.")

	code = stock_code.replace('A', '').strip()
	main_hwnd = find_hts_window()
	chart_hwnd = None  # [MEDIUM-1 수정] finally 블록에서 NameError 방지용 사전 초기화
	
	if not main_hwnd:
		print(f"[HTS 연동/실패] 영웅문 창을 찾을 수 없습니다.")
		return False

	try:
		# 1. HTS 메인 창 활성화
		user32.ShowWindow(main_hwnd, 5) # SW_SHOW
		user32.SetForegroundWindow(main_hwnd)
		time.sleep(0.3)

		# [V18 핵심] 차트 창 검증 및 포커스 고정
		chart_hwnd = find_0600_chart_window(main_hwnd)
		if not chart_hwnd:
			print(f"[HTS 연동/실패] '[0600] 종합차트' 창을 찾을 수 없습니다. 전송을 중단합니다.")
			return False
		
		# [V19] 차트 창 활성화 시도 강화
		user32.ShowWindow(chart_hwnd, 5) # SW_SHOW
		user32.BringWindowToTop(chart_hwnd)
		user32.SetForegroundWindow(chart_hwnd)
		time.sleep(0.2)

		# 포그라운드 창 확인 및 계층 검증
		active_hwnd = user32.GetForegroundWindow()
		active_parent = user32.GetParent(chart_hwnd)
		
		# [V19 핵심] 자식 창(MDI) 구조 대응: 활성창이 차트 본인이거나 부모라면 OK
		is_valid_focus = (active_hwnd == chart_hwnd) or (active_hwnd == main_hwnd) or (active_hwnd == active_parent)
		
		active_title = get_window_text(active_hwnd)
		
		if not is_valid_focus:
			print(f"[HTS 연동/취소] 포커스 유실 (Active: {active_title}, HWND: {hex(active_hwnd)}). 안전을 위해 중단합니다.")
			return False

		print(f"[HTS 연동/V38] '{code}' 전송 가동 (Target: {active_title})")
		
		# [V31] IME 영어 모드 강제 전환 (한글 입력 간섭 방지)
		set_english_mode(chart_hwnd)
		
		# 1. 입력창 초기화
		key_tap(VK_A, modifier=VK_CONTROL)
		time.sleep(0.1)
		key_tap(VK_BACK)
		time.sleep(0.1)

		# 2. 실제 포커스된 입력창 핸들 찾기
		time.sleep(0.4) # 초기화 후 안정화 시간 대폭 증가 (0.2 -> 0.4)
		target_hwnd = get_focused_window(chart_hwnd)
		if not target_hwnd:
			target_hwnd = active_hwnd
			print("[HTS 연동/경고] 포커스된 자식 창을 찾지 못했습니다. 기본 핸들을 사용합니다.")
		
		# [V34] 대상 입력창에 대해서도 IME 영어 모드 재확인 (포커스 변경 대응)
		if target_hwnd != chart_hwnd:
			set_english_mode(target_hwnd)
			time.sleep(0.1) # IME 변경 반영 대기
		
		# 3. 동기식 메시지 주입 (SendMessageW) - 데이터 유실 방지
		print(f"[HTS 연동/V38] '{code}' 동기식 주입 개시 (HWND: {hex(target_hwnd)})")
		WM_CHAR = 0x0102
		WM_KEYDOWN = 0x0100
		WM_KEYUP = 0x0101
		VK_RIGHT = 0x27
		
		# 첫 문자 전송 전 추가 안정화 (V38: 0.3 -> 0.6)
		# 9시~9시 30분 사이 서버 부하 대응 핵심 지점
		time.sleep(0.6)
		
		for i, char in enumerate(code.upper()):
			# SendMessage는 대상 창이 메시지를 처리할 때까지 대기함 (동기식)
			user32.SendMessageW(target_hwnd, WM_CHAR, ord(char), 0)
			
			if i == 0:
				time.sleep(0.4) # HTS 검색 루틴 트리거 대기 (0.3 -> 0.4)
				# [V37 핵심] EM_SETSEL 대신 자연스러운 오른쪽 화살표 키 입력으로 블록 지정 해제
				# 기존 입력된 1글자가 블록 지정되어 다음 글자에 덮어씌워지는 현상 방지
				user32.SendMessageW(target_hwnd, WM_KEYDOWN, VK_RIGHT, 0)
				user32.SendMessageW(target_hwnd, WM_KEYUP, VK_RIGHT, 0)
				time.sleep(0.05)
			else:
				time.sleep(0.12) # 일반 문자 간격
		
		# 4. 마무리 및 모드 복구
		time.sleep(0.1)
		release_all_modifiers()
		
		print(f"[HTS 연동] ✅ {code} 전송 완료 (V38 복구 모드)")
		return True

	except Exception as e:
		print(f"[HTS 연동/오류] {e}")
		return False
	finally:
		# [V38 논리 수정] 성공/실패/예외 모든 경우에 한국어 모드 복구 보장
		# chart_hwnd가 None이면 복구 시도 불필요 (창을 못 찾은 경우)
		if chart_hwnd:
			try:
				restore_korean_mode(chart_hwnd)
			except Exception:
				pass

if __name__ == "__main__":
	if is_admin():
		send_to_hts("005930")
	else:
		print("테스트를 위해 관리자 권한으로 실행해 주세요.")
