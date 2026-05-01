import sys
import os

# ── [H-2] Python 버전 검증 ───────────────────────────────────────────
# api.py에서 `X | Y` Union 타입 힌트 사용 → Python 3.10+ 필요
if sys.version_info < (3, 10):
	print(f"[오류] Python 3.10 이상이 필요합니다. 현재 버전: {sys.version}")
	print("       https://www.python.org 에서 최신 버전을 설치하세요.")
	sys.exit(1)

# ── [H-3] 환경 변수 및 .env 파일 로드 확인 ──────────────────────────
def _startup_check():
	"""기동 전 필수 환경 설정을 검증합니다."""
	_root = os.path.dirname(os.path.abspath(__file__))
	_env_path = os.path.join(_root, ".env")

	# .env 파일 존재 여부
	if not os.path.exists(_env_path):
		print("[경고] .env 파일이 없습니다. 'python setup_keys.py'를 먼저 실행하세요.")
		return

	# python-dotenv 설치 여부
	try:
		from dotenv import load_dotenv
		load_dotenv(_env_path)
	except ImportError:
		print("[경고] python-dotenv가 설치되지 않았습니다. 'pip install python-dotenv'를 실행하세요.")
		return

	# 핵심 API 키 로드 여부
	missing = [k for k in ["AT_REAL_APP_KEY", "TELEGRAM_TOKEN"] if not os.environ.get(k)]
	if missing:
		print(f"[경고] 다음 환경변수가 설정되지 않았습니다: {', '.join(missing)}")
		print("       .env 파일을 확인하거나 'python setup_keys.py'를 재실행하세요.")

_startup_check()

import time
import subprocess
import json
import psutil
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
							 QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
							 QTabWidget, QSplitter)
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QSize, QProcess
try:
	from PyQt6.QtSvgWidgets import QSvgWidget
except ImportError:
	QSvgWidget = None

# ----------------------------------------------------------------
# 중앙 테마 및 스타일 상수 (하드코딩 방지)
# ----------------------------------------------------------------
THEME = {
	"bg_main": "#1a1a1b",
	"bg_card": "#252526",
	"bg_hover": "#2d2d30",
	"border": "#3e3e42",
	"border_focus": "#007acc",
	"text_main": "#e0e0e0",
	"text_dim": "#cccccc",
	"accent": "#00E5FF",
	"success": "#00ff7f",
	"danger": "#d83b01",
	"warning": "#ffaa00",
	"gold": "#FFD700"
}

UI_STYLE_CARD = f"""
	AppStatusCard {{
		background-color: {THEME['bg_card']};
		border: 1px solid {THEME['border']};
		border-radius: 8px;
	}}
	AppStatusCard:hover {{
		border: 1px solid {THEME['border_focus']};
	}}
"""

UI_STYLE_BUTTON = """
	QPushButton {
		font-weight: bold;
		border-radius: 4px;
	}
"""

# [안실장 유지보수 가이드] 
# 공용 모듈 경로 추가 (Master_Control이 루트에 있으므로 바로 import 가능)
from shared.ui.widgets import StandardLogWindow, StandardStatusBar
from shared.signal_manager import MarketSignalManager
from shared.config import get_data_path

# Analyzer_Sig, AT_Sig 경로 추가 (내부 모듈 import 호환성 확보)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.join(ROOT_DIR, "Analyzer_Sig") not in sys.path:
	sys.path.append(os.path.join(ROOT_DIR, "Analyzer_Sig"))
if os.path.join(ROOT_DIR, "AT_Sig") not in sys.path:
	sys.path.append(os.path.join(ROOT_DIR, "AT_Sig"))

class AppStatusCard(QFrame):
	"""개별 프로젝트 상태를 표시하는 카드 위젯"""
	log_requested = pyqtSignal(str, str) # message, color
	
	def __init__(self, name, project_dir, main_script, parent=None):
		super().__init__(parent)
		self.name = name
		self.project_dir = project_dir
		self.main_script = main_script
		self.offset_x = 0
		self.offset_y = 0
		self.q_process = None # QProcess 객체용
		self.is_manual_stopping = False # 수동 중지 플래그
		self.was_running = False # 이전 상태 추적용
		self.captured_error = "" # 런타임 오류 캡처용
		
		self.setFrameShape(QFrame.Shape.StyledPanel)
		self.setMinimumHeight(150)
		self.setStyleSheet(UI_STYLE_CARD)
		
		layout = QVBoxLayout(self)
		
		# Header (Name)
		self.lbl_name = QLabel(name)
		self.lbl_name.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
		layout.addWidget(self.lbl_name)
		
		# Info & Status Dot
		info_layout = QHBoxLayout()
		self.lbl_info = QLabel("상태: 확인 중...")
		self.lbl_info.setStyleSheet("color: #cccccc; font-size: 12px;")
		
		self.lbl_status_dot = QLabel("●")
		self.lbl_status_dot.setStyleSheet("color: #777777; font-size: 18px; margin-right: 2px;")
		
		info_layout.addWidget(self.lbl_info)
		info_layout.addStretch()
		info_layout.addWidget(self.lbl_status_dot)
		layout.addLayout(info_layout)
		
		layout.addSpacing(10) # Reduced gap between info and buttons
		
		# Buttons
		btn_layout = QHBoxLayout()
		self.btn_start = QPushButton("시작")
		self.btn_stop = QPushButton("중지")
		self.btn_restart = QPushButton("재시작")
		
		for btn in [self.btn_start, self.btn_stop, self.btn_restart]:
			btn.setCursor(Qt.CursorShape.PointingHandCursor)
			btn.setFixedHeight(30)
			
		self.btn_start.setStyleSheet(f"background-color: #2d7d46; color: white; {UI_STYLE_BUTTON}")
		self.btn_stop.setStyleSheet(f"background-color: {THEME['danger']}; color: white; {UI_STYLE_BUTTON}")
		self.btn_restart.setStyleSheet(f"background-color: {THEME['border_focus']}; color: white; {UI_STYLE_BUTTON}")
		
		btn_layout.addWidget(self.btn_start)
		btn_layout.addWidget(self.btn_stop)
		btn_layout.addWidget(self.btn_restart)
		layout.addLayout(btn_layout)
		
		# Connect Actions
		self.btn_start.clicked.connect(self.start_app)
		self.btn_stop.clicked.connect(self.stop_app)
		self.btn_restart.clicked.connect(self.restart_app)

	def is_running(self, external_procs=None):
		"""프로세스가 실제로 실행 중인지 확인 (엄격한 cmdline 대조)"""
		# 1. 관리 중인 QProcess 확인
		if self.q_process and self.q_process.state() == QProcess.ProcessState.Running:
			return True
			
		# 2. 외부 프로세스 확인 (psutil)
		if external_procs is None:
			try:
				external_procs = psutil.process_iter(['name', 'cmdline', 'cwd'])
			except:
				return False

		abs_proj_dir_raw = os.path.abspath(self.project_dir)
		abs_proj_dir = abs_proj_dir_raw.lower().replace('\\', '/')
		target_script = self.main_script.lower()
		
		for proc in external_procs:
			try:
				cmdline = proc.info.get('cmdline')
				if not cmdline: continue
				
				cmdline_str = " ".join(cmdline).lower().replace('\\', '/')
				
				# [엄격한 체크] 
				# 1. 스크립트 파일명이 cmdline에 포함되어야 함
				# 2. 프로젝트 디렉토리 경로가 cmdline 또는 cwd와 일치해야 함
				if target_script in cmdline_str:
					# 경로 포함 여부 확인
					if abs_proj_dir in cmdline_str:
						return True
					
					# CWD(작업 디렉토리) 확인
					try:
						proc_cwd = proc.info.get('cwd') or proc.cwd()
						if proc_cwd and abs_proj_dir == proc_cwd.lower().replace('\\', '/'):
							return True
					except: pass
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				pass
		return False

	def update_status_ui(self, external_procs=None):
		"""상태 UI 갱신 (3초 타이머에 의해 호출됨)"""
		running = self.is_running(external_procs)
		
		# QProcess가 아닌 외부에서 시작/종료된 경우만 여기서 감지
		# (QProcess로 시작된 건 on_process_finished에서 즉시 처리됨)
		if self.was_running and not running and not self.is_manual_stopping:
			self.log_requested.emit(f"ℹ️ [{self.name}] 앱이 외부 명령 또는 종료 버튼에 의해 중지되었습니다.", "#aaaaaa")
		
		self.was_running = running
		
		if running:
			self.lbl_status_dot.setStyleSheet("color: #00ff7f;") # Green
			self.lbl_info.setText("상태: 실행 중 (Active)")
			self.btn_start.setEnabled(False)
			self.btn_stop.setEnabled(True)
		else:
			self.lbl_status_dot.setStyleSheet("color: #ff3333;") # Red
			self.lbl_info.setText("상태: 중지됨 (Inactive)")
			self.btn_start.setEnabled(True)
			self.btn_stop.setEnabled(False)

	def start_app(self):
		# [안실장 유지보수 가이드] 스마트 자원 조절 (Smart Throttling)
		if "Analyzer" in self.name:
			# AT_Sig가 실행 중인지 체크
			at_running = False
			for proc in psutil.process_iter(['cmdline']):
				try:
					cmdline = proc.info.get('cmdline')
					if cmdline and any("trading_ui.py" in s for s in cmdline):
						at_running = True
						break
				except : pass
			
			if at_running:
				from PyQt6.QtWidgets import QMessageBox
				reply = QMessageBox.warning(self, "자원 충돌 경고", 
										  "현재 [AT_Sig 실전 매매]가 가동 중입니다.\n"
										  "백테스터 실행 시 시스템 부하로 인해 매매 타이밍을 놓칠 수 있습니다.\n\n"
										  "그래도 강제로 실행하시겠습니까?",
										  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
				if reply == QMessageBox.StandardButton.No:
					return

		if not self.is_running():
			# [안실장 유지보수 가이드] 현재 실행 중인 파이썬 인터프리터를 사용하여 안정성 확보
			python_exe = sys.executable
			# GUI 앱이므로 가급적 pythonw 시도하되, 없으면 python 사용
			pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
			exec_bin = pythonw_exe if os.path.exists(pythonw_exe) else python_exe
			
			self.is_manual_stopping = False
			self.q_process = QProcess(self)
			self.q_process.setWorkingDirectory(os.path.abspath(self.project_dir))
			self.q_process.finished.connect(self.on_process_finished)
			# [추가] 프로세스 기동 오류 핸들링
			self.q_process.errorOccurred.connect(self.on_process_error)
			# [관제 강화] 표준 출력/에러 캡처
			self.q_process.readyReadStandardOutput.connect(self.on_ready_read_stdout)
			self.q_process.readyReadStandardError.connect(self.on_ready_read_stderr)
			self.captured_error = ""
			
			# [안실장 유지보수 가이드] 메인 윈도우 위치를 기준으로 오프셋 계산
			main_pos = self.window().pos()
			target_x = main_pos.x() + self.offset_x
			target_y = main_pos.y() + self.offset_y
			
			args = [self.main_script, f"--offset-x={target_x}", f"--offset-y={target_y}"]
			self.q_process.start(exec_bin, args)
			
			self.log_requested.emit(f"🚀 [{self.name}] 앱을 시작했습니다.", "#00ff7f")
			self.was_running = True 
			QTimer.singleShot(1500, self.update_status_ui)

	def on_ready_read_stdout(self):
		"""앱의 표준 출력 캐치"""
		raw_data = self.q_process.readAllStandardOutput().data()
		# 여러 인코딩 시도
		data = ""
		for enc in ['utf-8', 'cp949']:
			try:
				data = raw_data.decode(enc)
				break
			except: continue
		
		if not data: return
		
		if "[CENTER] INITIALIZED" in data:
			self.log_requested.emit(f"✅ [{self.name}] 앱이 정상 응답 중입니다.", "#00E5FF")
		else:
			# 일반 출력물도 디버깅용으로 작게 표시 (첫 50자만)
			clean_msg = data.strip().splitlines()[0][:50]
			if clean_msg and not clean_msg.startswith("Warning"):
				self.log_requested.emit(f"💬 [{self.name}] Output: {clean_msg}...", "#555555")

	def on_ready_read_stderr(self):
		"""앱의 오류 출력 캐치 (런타임 에러 추적)"""
		raw_data = self.q_process.readAllStandardError().data()
		err = ""
		for enc in ['utf-8', 'cp949']:
			try:
				err = raw_data.decode(enc)
				break
			except: continue
			
		if err.strip():
			# 치명적 오류 또는 단순 경고 모두 출력
			msg = err.strip().splitlines()[-1]
			if "Error" in err or "Traceback" in err or "Exception" in err:
				self.captured_error += err
				self.log_requested.emit(f"⚠️ [{self.name}] 런타임 오류: {msg}", "#ffaa00")
			else:
				# 단순 경고/정보성 에러 출력
				self.log_requested.emit(f"💡 [{self.name}] 정보: {msg[:60]}", "#777777")

	def on_process_error(self, error):
		"""QProcess 실행 중 에러 발생 시 호출"""
		if self.is_manual_stopping:
			return

		error_msgs = {
			QProcess.ProcessError.FailedToStart: "프로세스 시작 실패 (파일을 찾을 수 없거나 권한 부족)",
			QProcess.ProcessError.Crashed: "프로세스가 실행 중 갑자기 종료됨",
			QProcess.ProcessError.Timedout: "프로세스 응답 시간 초과",
			QProcess.ProcessError.WriteError: "데이터 쓰기 오류",
			QProcess.ProcessError.ReadError: "데이터 읽기 오류",
			QProcess.ProcessError.UnknownError: "알 수 없는 오류"
		}
		msg = error_msgs.get(error, f"프로세스 오류 발생 (Code: {error})")
		self.log_requested.emit(f"❌ [{self.name}] {msg}", "#ff3333")
		self.update_status_ui()

	def stop_app(self):
		"""특정 프로젝트의 프로세스 종료"""
		self.is_manual_stopping = True
		
		# 1. 관리 중인 QProcess 먼저 시도
		if self.q_process and self.q_process.state() == QProcess.ProcessState.Running:
			self.q_process.terminate()
			# 최대 3초 대기 (Kiwoom API 해제 시간 고려)
			if not self.q_process.waitForFinished(3000):
				self.q_process.kill()
				self.q_process.waitForFinished(1000)
			
			self.log_requested.emit(f"🛑 [{self.name}] 앱을 관제 센터에서 중지했습니다.", "#ff3333")
			self.update_status_ui()
			return
			
		# 2. 외부 프로세스인 경우 psutil로 시도
		abs_proj_dir = os.path.abspath(self.project_dir).lower().replace('\\', '/')
		for proc in psutil.process_iter(['name', 'cmdline']):
			try:
				cmdline = proc.info.get('cmdline')
				if cmdline:
					cmdline_str = " ".join(cmdline).lower().replace('\\', '/')
					if self.main_script.lower() in cmdline_str and abs_proj_dir in cmdline_str:
						proc.terminate()
						self.log_requested.emit(f"🛑 [{self.name}] 앱을 외부 프로세스 목록에서 찾아 중지했습니다.", "#ff3333")
			except (psutil.NoSuchProcess, psutil.AccessDenied):
				pass
		
		QTimer.singleShot(1000, lambda: self.update_status_ui())

	def on_process_finished(self, exit_code, exit_status):
		"""QProcess 종료 시 즉시 호출되는 슬롯 (이벤트 기반)"""
		if not self.is_manual_stopping:
			if exit_code != 0:
				self.log_requested.emit(f"❌ [{self.name}] 앱이 비정상 종료되었습니다. (Code: {exit_code})", "#ff3333")
				if self.captured_error:
					# 마지막 2줄 정도의 핵심 에러 리포트
					err_lines = [l for l in self.captured_error.strip().splitlines() if l.strip()]
					summary = " | ".join(err_lines[-2:])
					self.log_requested.emit(f"🔍 원인추정: {summary}", "#ff9999")
			else:
				self.log_requested.emit(f"ℹ️ [{self.name}] 앱이 스스로 종료되었거나 외부에서 중지되었습니다.", "#aaaaaa")
		
		self.was_running = False
		self.update_status_ui()

	def restart_app(self):
		"""앱 중지 후 자원 해제 대기 시간을 갖고 재시작"""
		self.stop_app()
		# [안실장 픽스] Kiwoom API나 OS 자원이 완전히 해제될 시간을 충분히 부여 (1.5초)
		QTimer.singleShot(1500, self.start_app)

class MasterControl(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle("KW_AutoTrading 통합 관제 센터 (Master Control)")
		self.resize(1280, 800)
		self.setMinimumSize(1280, 800)
		self.setStyleSheet("""
			QMainWindow, QWidget { 
				background-color: #1a1a1b; 
				color: #e0e0e0; 
				font-family: 'Malgun Gothic', 'Segoe UI';
			}
			QTabWidget::pane { border: 1px solid #333; background: #1e1e1e; }
			QTabBar::tab {
				background: #252526;
				padding: 10px 20px;
				border: 1px solid #333;
				border-bottom: none;
				margin-right: 2px;
			}
			QTabBar::tab:selected { background: #1e1e1e; border-top: 2px solid #007acc; }
		""")
		
		self.signal_manager = MarketSignalManager()
		from shared.ui.widgets import StandardStockTable
		
		# Central Widget & Main Layout
		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		main_layout = QHBoxLayout(central_widget)
		main_layout.setContentsMargins(0, 0, 0, 0)
		main_layout.setSpacing(0)
		
		# === 1. Left Sidebar (Project Controls) ===
		sidebar = QFrame()
		sidebar.setFixedWidth(240)
		sidebar.setStyleSheet("background-color: #252526; border-right: 1px solid #333;")
		sidebar_layout = QVBoxLayout(sidebar)
		sidebar_layout.setContentsMargins(15, 20, 15, 20)
		sidebar_layout.setSpacing(15)
		
		# Logo & Brand Header in Sidebar (Integrated Style)
		header_container = QFrame()
		header_layout = QHBoxLayout(header_container)
		header_layout.setContentsMargins(0, 0, 0, 10)
		header_layout.setSpacing(15)
		
		header_layout.addStretch() # Horizontal Center
		
		# 1. Logo (SVG/PNG)
		logo_label = QLabel()
		ws_root = os.path.dirname(os.path.abspath(__file__))
		logo_path_svg = os.path.join(ws_root, "shared", "assets", "logo.svg")
		logo_path_png = os.path.join(ws_root, "shared", "assets", "logo.png")
		
		pixmap = None
		if os.path.exists(logo_path_svg):
			pixmap = QIcon(logo_path_svg).pixmap(65, 65)
		elif os.path.exists(logo_path_png):
			pixmap = QPixmap(logo_path_png).scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)

		if pixmap and not pixmap.isNull():
			logo_label.setPixmap(pixmap)
			logo_label.setFixedWidth(70)
			logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		else:
			logo_label.setText("S")
			logo_label.setFixedSize(60, 60)
			logo_label.setStyleSheet("background-color: #DAA520; color: black; font-weight: bold; font-size: 32px; border-radius: 8px;")
			logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		
		header_layout.addWidget(logo_label)

		# 2. Title Text (Two Lines)
		text_container = QVBoxLayout()
		text_container.setSpacing(0)
		
		label_title = QLabel("SYSTEM")
		label_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff; line-height: 1.1;")
		
		label_sub = QLabel("CONTROL")
		label_sub.setStyleSheet("font-size: 20px; font-weight: bold; color: #00E5FF; line-height: 1.1;")
		
		text_container.addWidget(label_title)
		text_container.addWidget(label_sub)
		header_layout.addLayout(text_container)
		
		header_layout.addStretch() # Horizontal Center
		
		sidebar_layout.addWidget(header_container)
		sidebar_layout.addSpacing(5)
		
		# [NEW] Market Signal & Admin Status in Sidebar
		self.signal_card = QFrame()
		self.signal_card.setStyleSheet("background-color: #1e1e1e; border-radius: 5px; border: 1px solid #333; margin: 5px;")
		sig_layout = QVBoxLayout(self.signal_card)
		
		# Admin Badge
		from shared.hts_connector import is_admin
		self.admin_status = is_admin()
		self.lbl_admin = QLabel("ADMIN PROTECTED" if self.admin_status else "⚠ NON-ADMIN MODE")
		self.lbl_admin.setAlignment(Qt.AlignmentFlag.AlignCenter)
		admin_color = "#00FF7F" if self.admin_status else "#FF5252"
		self.lbl_admin.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {admin_color}; background-color: #2a2a2a; border-radius: 3px; padding: 2px;")
		sig_layout.addWidget(self.lbl_admin)

		self.lbl_sig_regime = QLabel("시장 상태 확인 중...")
		self.lbl_sig_regime.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.lbl_sig_regime.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFD700;")
		self.lbl_sig_msg = QLabel("-")
		self.lbl_sig_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.lbl_sig_msg.setStyleSheet("font-size: 10px; color: #aaaaaa;")
		sig_layout.addWidget(self.lbl_sig_regime)
		sig_layout.addWidget(self.lbl_sig_msg)
		sidebar_layout.addWidget(self.signal_card)
		
		sidebar_layout.addSpacing(10)
		
		# Project Cards (Vertical)
		# 사이드바 너비(220px) + 여유(20px) = 240px 지점부터 앱 배치 시작
		# 우상향(Upward-Right) 배치를 위해 offset_y를 음수(위쪽)로 설정
		# 타이틀바(약 30px) + 5px 여유를 주어 35px 간격으로 촘촘하게 배치
		# 우측(X) 간격은 80px로 설정하여 컴팩트하게 배치
		self.card_analyzer = AppStatusCard("Analyzer_Sig (통합 분석)", "Analyzer_Sig", "Anal_Main.py")
		self.card_analyzer.offset_x, self.card_analyzer.offset_y = 240, -35
		
		self.card_at = AppStatusCard("AT_Sig (실전 매매)", "AT_Sig", "Trade_Main.py")
		self.card_at.offset_x, self.card_at.offset_y = 320, -70
		
		sidebar_layout.addWidget(self.card_analyzer)
		sidebar_layout.addWidget(self.card_at)
		
		sidebar_layout.addStretch()
		
		# [NEW] Exit Button at Bottom
		self.btn_exit = QPushButton("시스템 종료")
		self.btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_exit.setFixedHeight(45)
		self.btn_exit.setStyleSheet("""
			QPushButton {
				background-color: #c42b1c; 
				color: white; 
				font-weight: bold; 
				font-size: 15px;
				border-radius: 5px;
				margin: 10px;
			}
			QPushButton:hover { background-color: #e81123; }
		""")
		self.btn_exit.clicked.connect(self.close)
		sidebar_layout.addWidget(self.btn_exit)
		
		main_layout.addWidget(sidebar)
		
		# === 2. Right Content Area (Tabs) ===
		content_area = QWidget()
		content_layout = QVBoxLayout(content_area)
		
		# Tabs
		self.tabs = QTabWidget()
		self.tabs.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
		
		# Tab 1: Integrated Log
		self.tab_log = QWidget()
		log_layout = QVBoxLayout(self.tab_log)
		self.log_window = StandardLogWindow()
		log_layout.addWidget(self.log_window)
		self.tabs.addTab(self.tab_log, "🔍 통합 모니터링 로그")
		
		# Connect project card logs
		self.card_analyzer.log_requested.connect(self.log_window.append_log)
		self.card_at.log_requested.connect(self.log_window.append_log)
		
		# Tab 2: Leading & Accumulated Stocks
		self.tab_stocks = QWidget()
		stocks_layout = QVBoxLayout(self.tab_stocks)
		
		# Splitter for two tables in Tab 2 (Horizontal for more rows)
		stock_splitter = QSplitter(Qt.Orientation.Horizontal)
		
		# Leading Stocks Table
		lead_container = QWidget()
		lead_vbox = QVBoxLayout(lead_container)
		lbl_lead = QLabel("🔥 실시간 주도주 (Analyzer_Sig)")
		lbl_lead.setAlignment(Qt.AlignmentFlag.AlignCenter)
		lbl_lead.setStyleSheet("font-weight: bold; color: #FF5252; margin-bottom: 5px;")
		lead_vbox.addWidget(lbl_lead)
		self.table_lead = StandardStockTable(["시간", "종목명", "신호", "테마군"])
		self.table_lead.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
		self.table_lead.setColumnWidth(0, 45)  # 시간
		self.table_lead.setColumnWidth(1, 110) # 종목명
		self.table_lead.setColumnWidth(2, 50)  # 신호
		self.table_lead.setColumnWidth(3, 140) # [조정] 테마군 너비 확보
		self.table_lead.horizontalHeader().setStretchLastSection(True) # 테마군 자동 확장
		lead_vbox.addWidget(self.table_lead)
		stock_splitter.addWidget(lead_container)
		
		# Accumulation Stocks Table
		accum_container = QWidget()
		accum_vbox = QVBoxLayout(accum_container)
		lbl_accum = QLabel("💎 매집 분석 상위 (Accumulation)")
		lbl_accum.setAlignment(Qt.AlignmentFlag.AlignCenter)
		lbl_accum.setStyleSheet("font-weight: bold; color: #00E5FF; margin-bottom: 5px;")
		accum_vbox.addWidget(lbl_accum)
		self.table_accum = StandardStockTable(["종목명", "점수", "매집비", "공략유형", "상태(창구)"])
		self.table_accum.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
		self.table_accum.setColumnWidth(0, 130) # 종목명 조금 더 확보
		self.table_accum.setColumnWidth(1, 45)  # 점수
		self.table_accum.setColumnWidth(2, 55)  # 매집비
		self.table_accum.setColumnWidth(3, 85)  # 공략유형 (상세 표시 위해 약간 확장)
		self.table_accum.setColumnWidth(4, 180) # [조정] 창구 상세 정보 기본 너비 지정
		self.table_accum.horizontalHeader().setStretchLastSection(True) # 상태 컬럼이 남은 공간 채움
		accum_vbox.addWidget(self.table_accum)
		stock_splitter.addWidget(accum_container)
		
		# [안실장 가이드] 좌측 테마군 시인성을 높이기 위해 스플리터 비율 재조정 (50:50에 가깝게 조정)
		stock_splitter.setSizes([550, 730]) 
		
		stocks_layout.addWidget(stock_splitter)
		self.tabs.addTab(self.tab_stocks, "📈 주도주/매집 분석")
		
		content_layout.addWidget(self.tabs)
		main_layout.addWidget(content_area)
		
		# 5. Status Bar
		self.status_bar = StandardStatusBar()
		self.setStatusBar(self.status_bar)
		
		# [안실장 유지보수 가이드] DB 매니저 초기화 (주도주 신호 저장용)
		try:
			from shared.db_manager import DBManager
			self.signal_db = DBManager()
		except Exception:
			self.signal_db = None
			
		from shared.accumulation_manager import AccumulationManager
		self.accum_mgr = AccumulationManager()

		# [안실장 유지보수 가이드] 종목명 매핑 정보 로드
		self.stock_names = {}
		try:
			from shared.stock_master import load_master_cache
			self.stock_names = load_master_cache()
			print(f"[?] 종목 마스터 데이터를 로드하였습니다. ({len(self.stock_names)}개 종목)")
		except Exception as e:
			print(f"Error loading stock master: {e}")
		
		# 로그 감시 포인터 초기화 (기동 시점 이후의 로그만 표시)
		log_path = get_data_path("logs/fatal_errors.log")
		if os.path.exists(log_path):
			self.last_log_pos = os.path.getsize(log_path)
		else:
			self.last_log_pos = 0
		
		# Timers
		self.ui_timer = QTimer(self)
		self.ui_timer.timeout.connect(self.update_all_status)
		self.ui_timer.start(3000)
		
		self.log_check_timer = QTimer(self)
		self.log_check_timer.timeout.connect(self.check_fatal_logs)
		self.log_check_timer.start(5000)
		
		# Stock Update Timer (30s)
		self.stock_timer = QTimer(self)
		self.stock_timer.timeout.connect(self.update_stock_tables)
		self.stock_timer.start(30000)
		
		self.log_window.append_log("관제 시스템 기동 완료. 실시간 데이터 스트리밍을 시작합니다.")
		self.update_all_status()
		self.update_stock_tables()

		# [안실장 유지보수 가이드] 메인 윈도우 좌하단 자동 배치 설정
		QTimer.singleShot(0, self.position_on_bottom_left)

		# [안실장 픽스] HTS 연동 기능 활성화 (모든 앱 전역 연동)
		self.table_lead.enable_hts_interlock(code_column=1)
		self.table_accum.enable_hts_interlock(code_column=0)

	def position_on_bottom_left(self):
		"""화면 해상도를 체크하여 창을 좌하단으로 이동시키고, 하위 앱들이 우상향으로 배치되게 함"""
		# [안실장 유지보수 가이드] 다중 모니터 대응: 현재 윈도우가 속한 스크린의 지오메트리 사용
		screen = self.screen().availableGeometry()
		window_geo = self.frameGeometry()
		
		# 좌하단 여백(50px)을 고려한 위치 계산
		margin = 50
		x = screen.left() + margin
		# y 좌표는 화면 하단 - 창 높이 - 여백
		y = screen.top() + screen.height() - window_geo.height() - margin
		
		self.move(x, y)

	def closeEvent(self, event):
		"""메인 관제 센터 종료 시 모든 하위 앱 일괄 종료"""
		self.log_window.append_log("🔴 메인 시스템 종료 중... 모든 하위 앱을 일괄 중지합니다.")
		
		# 개별 카드 위젯의 중지 로직 호출
		self.card_analyzer.stop_app()
		self.card_at.stop_app()
		
		# 프로세스 종료 대기 (최대 2초)
		time.sleep(1)
		event.accept()

	def update_all_status(self):
		"""모든 앱의 상태와 시장 신호 갱신"""
		# [안실장 유지보수 가이드] 부하 경감: 프로세스 목록을 한 번만 조회하여 배포
		py_procs = []
		try:
			# 'python'이 포함된 프로세스만 필터링하여 최소화
			for p in psutil.process_iter(['name', 'cmdline']):
				try:
					p_info = p.info
					if p_info and p_info.get('name') and 'python' in p_info['name'].lower():
						py_procs.append(p)
				except: pass
		except: pass

		self.card_analyzer.update_status_ui(py_procs)
		self.card_at.update_status_ui(py_procs)
		
		# 시장 신호 갱신
		signal = self.signal_manager.load_signal()
		if not signal:
			return

		regime = signal.get("regime", "NEUTRAL")
		msg = signal.get("message", "-")
		color = "#00FF7F" if regime == "BULL" else "#FF5252" if regime == "BEAR" else "#FFD700"
		
		self.lbl_sig_regime.setText(f"시장: {regime}")
		self.lbl_sig_regime.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 14px;")
		self.lbl_sig_msg.setText(msg)
		
		# 상태바 업데이트
		self.status_bar.update_market_status(regime, is_open=(regime != "UNKNOWN"))

		# [안실장 픽스] 신규 종목 대응 및 종목명 복구 대응 (마스터 캐시 강제 동기화)
		try:
			from shared.stock_master import load_master_cache
			self.stock_names = load_master_cache()
		except: pass

	def _format_stock_name(self, code, raw_name=None):
		"""이름 매핑, 정크 필터링 및 5자 제한 통합 처리 (최적화)"""
		import re
		name = raw_name or self.stock_names.get(code, "")
		
		# 정크 필터 (한글/영문 없는 이름은 코드로 대체)
		if not name or not re.search('[가-힣a-zA-Z]', str(name)):
			name = code
			
		# 8자 제한 루틴 (기존 5자에서 완화하여 가독성 확보)
		return name[:8] if len(str(name)) > 8 else str(name), str(name)

	def update_stock_tables(self):

		# 0. 공통 데이터 추출 (교집합 종목)
		active_codes = []
		high_score_codes = []
		
		try:
			if self.signal_db:
				active_codes = [s.get('code') for s in self.signal_db.get_active_stocks() if s.get('code')]
			high_score_codes = self.accum_mgr.get_recent_high_score_stocks(days_limit=7, score_limit=70)
		except:
			pass
			
		common_codes = set(active_codes) & set(high_score_codes)

		# 2. Accumulation 매집주 업데이트 및 교집합 강조용 집합 생성
		high_score_gold_set = set()      # 85점 이상 (황금색)
		accumulation_all_set = set()     # 매집 리스트 포함 전체 (노란색 후보)
		
		try:
			self.table_accum.setRowCount(0)
			row_idx = 0
			
			for code in high_score_codes[:100]:
				res = self.accum_mgr.get_stock_analysis_result(code)
				if res:
					display_name, full_name = self._format_stock_name(code, self.stock_names.get(code, ""))
					
					score = res.get('score', 0)
					accumulation_all_set.add(code) # 일단 매집 리스트에 있으면 추가
					
					is_gold_acc = score >= 85
					if is_gold_acc:
						high_score_gold_set.add(code)
					
					self.table_accum.insertRow(row_idx)
					
					# 점수 85점 이상이면 황금색, 그 외 매집주는 일반색 (또는 필요시 노랑)
					color = "#FFD700" if is_gold_acc else None
					self.table_accum.set_item(row_idx, 0, display_name, color=color, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, code=code)
					self.table_accum.item(row_idx, 0).setToolTip(full_name)
					
					self.table_accum.set_numeric_item(row_idx, 1, score)
					self.table_accum.set_numeric_item(row_idx, 2, res.get('acc_ratio', 0))
					
					# 공략유형 조합
					types = []
					if res.get('is_breakout'): types.append("돌파")
					if res.get('is_below_avg'): types.append("평단")
					if res.get('is_yin_dual_buy'): types.append("쌍끌")
					if res.get('is_volume_dry'): types.append("급감")
					self.table_accum.set_item(row_idx, 3, "/".join(types) if types else "-")
					
					# [안실장 고도화] 매집 창구의 질(Quality) 분석 데이터 연동
					quality = self.accum_mgr.get_accumulation_quality(code)
					self.table_accum.set_item(row_idx, 4, quality.get('desc', ''), align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
					
					row_idx += 1
					
			# 3. [재정의] 실시간 주도주 리스트 업데이트 (교집합 색상 반영)
			if self.signal_db:
				active_stocks = self.signal_db.get_active_stocks()
				self.table_lead.setRowCount(0)
				seen_codes = set()
				row_idx = 0
				for s in active_stocks:
					code = s.get('code')
					if not code or code in seen_codes: continue
					seen_codes.add(code)
					if row_idx >= 100: break
					
					display_name, full_name = self._format_stock_name(code)
					
					# [안실장 픽스] 색상 우선순위 적용
					# 1. 황금색: 매집 85점 이상
					# 2. 노란색: 매집 리스트 포함 (85점 미만)
					color = None
					if code in high_score_gold_set:
						color = "#FFD700" # Gold
					elif code in accumulation_all_set:
						color = "#FFFF00" # Yellow
					
					self.table_lead.insertRow(row_idx)
					self.table_lead.set_item(row_idx, 0, s.get('found_at', '')[5:16])
					self.table_lead.set_item(row_idx, 1, display_name, color=color, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, code=code)
					self.table_lead.item(row_idx, 1).setToolTip(full_name)
					self.table_lead.set_item(row_idx, 2, s.get('signal_type', '포착'))
					self.table_lead.set_item(row_idx, 3, s.get('sector', ''), align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
					row_idx += 1
					
		except Exception as e:
			print(f"Stock Table Sync Error: {e}")

	def check_fatal_logs(self):
		"""중앙 에러 로그 파일 모니터링 (실시간 신규 에러만 추출)"""
		log_path = get_data_path("logs/fatal_errors.log")
		if not os.path.exists(log_path):
			return
			
		try:
			file_size = os.path.getsize(log_path)
			if file_size < self.last_log_pos: # 파일이 로테이트되거나 초기화됨
				self.last_log_pos = 0
				
			if file_size > self.last_log_pos:
				with open(log_path, 'r', encoding='utf-8') as f:
					f.seek(self.last_log_pos)
					new_lines = f.readlines()
					self.last_log_pos = f.tell()
					
					for line in new_lines:
						if "ERROR" in line or "CRITICAL" in line:
							self.log_window.append_log(f"⚠️ {line.strip()}", color="#ff3333")
						elif "INFO" in line or "WARNING" in line:
							# 관제센터 로그창에 일반 정보도 표시 (선택 사항)
							self.log_window.append_log(f"ℹ️ {line.strip()}", color="#aaaaaa")
		except Exception:
			pass

if __name__ == "__main__":
	from shared.hts_connector import is_admin
	app = QApplication(sys.argv)
	
	# 관리자 권한 체크 (HTS 연동 필수 조건)
	if not is_admin():
		from PyQt6.QtWidgets import QMessageBox
		msg_box = QMessageBox()
		msg_box.setIcon(QMessageBox.Icon.Warning)
		msg_box.setWindowTitle("관리자 권한 경고")
		msg_box.setText("Antigravity가 관리자 권한으로 실행되지 않았습니다.")
		msg_box.setInformativeText("HTS 자동 연동(차트 동기화) 기능이 정상 작동하지 않을 수 있습니다.\n가급적 관리자 권한으로 다시 실행해 주세요.")
		msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
		msg_box.exec()

	window = MasterControl()
	window.show()
	sys.exit(app.exec())
