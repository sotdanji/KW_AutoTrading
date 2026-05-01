import sys
import os
import time
import logging
import traceback
from PyQt6.QtWidgets import (QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, 
							 QPushButton, QFrame, QComboBox, QTabWidget, QMessageBox, 
							 QApplication, QProgressBar, QTextEdit, QCheckBox)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QCursor, QColor, QTextCursor

from core.market_engine import MarketEngine as MarketAnalyzer
from core.integrator import AT_SigIntegrator
from config import ACCOUNT_MODE
from core.settings import get_kw_setting, update_kw_setting
from shared.db_manager import DBManager
from ui.history_widget import HistoryWidget
from ui.signal_history_dialog import SignalHistoryDialog
from ui.leading_theme_widget import LeadingThemeWidget
from ui.momentum_widget import Momentum10MinWidget
from ui.program_trading_widget import ProgramTradingWidget
from core.threads import StartupThread, DataThread, QThandler
from core.logger import get_logger

# 로거 초기화
logger = get_logger(__name__)

class MarketDashboard(QMainWindow):
	def __init__(self):
		super().__init__()
		logger.debug("Dashboard __init__ start")
		# Load mode from local settings or config
		mode = get_kw_setting('data_mode', ACCOUNT_MODE)
		logger.debug(f"Dashboard init mode: {mode}")
		self.analyzer = MarketAnalyzer(mode=mode)
		self.integrator = AT_SigIntegrator()
		self.db_manager = DBManager()
		
		# [안실장 유지보수 가이드] 시장 신호 공유를 위한 매니저 초기화
		from shared.signal_manager import MarketSignalManager
		self.signal_manager = MarketSignalManager()
		
		self.consecutive_failures = 0 # Track connection failures
		
		self.current_data = {
			"themes": [], 
			"top8_themes_data": [],
			"size_indices": [] 
		} 
		self.data_thread = None
		self.timer = QTimer()
		self.timer.timeout.connect(self.request_data_update)
		self.update_interval = 10000  # 타이머 interval 고정 (10초)
		
		# [NEW] Signal History Dialog
		self.signal_history_dlg = SignalHistoryDialog(self)
		
		self.init_ui()
		
		# Setup Logger
		self.log_handler = QThandler(self.append_log)
		logging.getLogger().addHandler(self.log_handler)
		
		# [NEW] Startup Sequence
		self.startup_thread = StartupThread(self.analyzer, self.db_manager)
		self.startup_thread.status_signal.connect(self.update_status_message)
		self.startup_thread.index_ready.connect(self.on_initial_indices_ready)
		self.startup_thread.finished_signal.connect(self.on_startup_finished)
		self.startup_thread.start()
		
	def on_initial_indices_ready(self, indices):
		"""Initial index data received during startup"""
		self.current_data["indices"] = indices
		self.update_index_display()
		
	def update_status_message(self, msg):
		if hasattr(self, 'status_label'):
			self.status_label.setText(msg)
		
	def on_startup_finished(self, success):
		if success:
			logger.info("Startup sequence completed successfully.")
			self.request_data_update()
		else:
			QMessageBox.critical(self, "오류", "시스템 초기화 중 문제가 발생했습니다.\n로그를 확인해주세요.")

	def closeEvent(self, event):
		if hasattr(self, 'log_handler'):
			logging.getLogger().removeHandler(self.log_handler)
		if hasattr(self, 'timer') and self.timer.isActive():
			self.timer.stop()
		if hasattr(self, 'data_thread') and self.data_thread and self.data_thread.isRunning():
			self.data_thread._stop_flag = True
			self.data_thread.quit()
			if not self.data_thread.wait(100):
				self.data_thread.terminate()
		event.accept()

	def append_log(self, text):
		if hasattr(self, 'leading_theme_widget'):
			self.leading_theme_widget.append_log(text)

	def init_ui(self):
		self.setWindowTitle("Lead_Sig: 주도주 발굴 시스템 (Market Analyzer)")
		self.resize(1280, 800)
		self.setMinimumSize(1280, 800)
		self.setStyleSheet("background-color: #121212; color: white;")

		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		
		main_layout = QHBoxLayout(central_widget)
		main_layout.setContentsMargins(0, 0, 0, 0)
		main_layout.setSpacing(0)

		# === 1. Left Sidebar ===
		sidebar = QFrame()
		sidebar.setFixedWidth(240)
		sidebar.setStyleSheet("background-color: #1E1E1E; border-right: 1px solid #333;")
		
		sidebar_layout = QVBoxLayout(sidebar)
		sidebar_layout.setContentsMargins(15, 20, 15, 20)
		sidebar_layout.setSpacing(15)

		# --- Header (Logo + Title) ---
		header_container = QFrame()
		header_layout = QHBoxLayout(header_container)
		header_layout.setContentsMargins(0, 0, 0, 10)
		header_layout.setSpacing(15)

		header_layout.addStretch() # 가로 중앙 정렬

		# 1. Logo
		logo_label = QLabel()
		current_file_dir = os.path.dirname(os.path.abspath(__file__))
		project_root = os.path.dirname(current_file_dir)
		# [중앙 관리] CI는 workspace root의 shared/assets 폴더에서 관리합니다.
		ws_root = os.path.dirname(project_root)
		logo_path_svg = os.path.join(ws_root, "shared", "assets", "logo.svg")
		logo_path_png = os.path.join(ws_root, "shared", "assets", "logo.png")
		
		from PyQt6.QtGui import QIcon, QPixmap
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
		
		label_title = QLabel("Lead_Sig")
		label_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff; line-height: 1.2;")
		
		label_sub = QLabel("Market Analyzer")
		label_sub.setStyleSheet("font-size: 13px; color: #aaaaaa; font-weight: 500; letter-spacing: 0.5px;")
		
		text_container.addWidget(label_title)
		text_container.addWidget(label_sub)
		header_layout.addLayout(text_container)
		
		header_layout.addStretch() # 가로 중앙 정렬

		sidebar_layout.addWidget(header_container)
		
		interval_layout = QHBoxLayout()
		lbl_interval = QLabel("갱신 주기")
		lbl_interval.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
		interval_layout.addWidget(lbl_interval)
		
		self.interval_combo = QComboBox()
		self.interval_combo.addItems(["5초", "10초", "15초", "30초", "1분"])
		self.interval_combo.setCurrentIndex(1)
		self.interval_combo.setStyleSheet("""
			QComboBox {
				background-color: #333; color: #FFD700; padding: 5px; border-radius: 3px; font-weight: bold; border: 1px solid #444;
			}
			QComboBox::drop-down { border: 0px; }
		""")
		interval_layout.addWidget(self.interval_combo, 1)
		sidebar_layout.addLayout(interval_layout)


		line1 = QFrame(); line1.setFrameShape(QFrame.Shape.HLine); line1.setFrameShadow(QFrame.Shadow.Sunken); line1.setStyleSheet("background-color: #333; margin: 10px 0;")
		sidebar_layout.addWidget(line1)

		self.index_labels = {}
		index_names = ["KOSPI", "KOSPI 200", "KOSDAQ", "KOSDAQ 150", "Futures"]
		for name in index_names:
			box = QFrame()
			box.setStyleSheet("background-color: #383838; border: 1px solid #555555; border-radius: 4px;")
			blayout = QVBoxLayout(box)
			blayout.setContentsMargins(8, 6, 8, 6)
			blayout.setSpacing(2)
			idx_title = QLabel(name); idx_title.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold;")
			blayout.addWidget(idx_title)
			row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
			price = QLabel("-"); price.setStyleSheet("color: white; font-size: 13px; font-weight: bold;"); row.addWidget(price)
			row.addStretch()
			change = QLabel("-"); change.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); change.setStyleSheet("color: #AAAAAA; font-size: 11px;")
			row.addWidget(change); blayout.addLayout(row)
			sidebar_layout.addWidget(box)
			self.index_labels[name] = {"price": price, "change": change}

		line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine); line2.setFrameShadow(QFrame.Shadow.Sunken); line2.setStyleSheet("background-color: #333; margin: 10px 0;")
		sidebar_layout.addWidget(line2)

		self.btn_signal = QPushButton("🚨 시그널 히스토리")
		self.btn_signal.setFixedHeight(35); self.btn_signal.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_signal.setStyleSheet("""
			QPushButton { background-color: #4A148C; color: #FFF; border: 1px solid #7B1FA2; border-radius: 4px; font-weight: bold; font-size: 13px; }
			QPushButton:hover { background-color: #6A1B9A; }
		""")
		self.btn_signal.clicked.connect(self.signal_history_dlg.show); sidebar_layout.addWidget(self.btn_signal)

		self.status_label = QLabel("시스템 대기 중")
		self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.status_label.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold; margin-top: 5px;")
		sidebar_layout.addWidget(self.status_label)

		# [Mock Investment Mode Checkbox] - Backtest 앱과 유사한 스타일 적용
		self.chk_mock = QCheckBox("모의투자 모드")
		self.chk_mock.setCursor(Qt.CursorShape.PointingHandCursor)
		self.chk_mock.setStyleSheet("""
			QCheckBox { color: #00E5FF; font-weight: bold; font-size: 14px; margin-top: 10px; margin-bottom: 5px; }
			QCheckBox::indicator { 
				width: 18px; height: 18px; 
				border: 1px solid #ffffff; 
				border-radius: 3px; 
				background-color: #2D2D2D;
			}
			QCheckBox::indicator:checked { 
				background-color: #00E5FF; 
				border-color: #00E5FF;
				image: url(none); /* 필요시 체크 이미지 추가 가능 */
			}
			QCheckBox::indicator:unchecked:hover {
				border-color: #00E5FF;
			}
		""")
		# [상용 로직] 초기 상태 자동 감지
		current_mode = self.analyzer.fetcher.mode
		self.chk_mock.setChecked(current_mode == "PAPER")
		self.chk_mock.stateChanged.connect(self.update_server_mode_ui)
		sidebar_layout.addWidget(self.chk_mock)

		bottom_btn_layout = QHBoxLayout(); bottom_btn_layout.setSpacing(5)
		self.exit_btn = QPushButton(" 종료"); self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.exit_btn.setFixedHeight(40)
		self.exit_btn.setStyleSheet("""
			QPushButton { 
				background-color: #d32f2f; 
				color: white; 
				border: 1px solid #c62828; 
				border-radius: 5px;
				font-weight: bold; 
				font-size: 16px; 
			}
			QPushButton:hover { 
				background-color: #ff5252; 
				border: 1px solid #ff867c;
			}
			QPushButton:pressed { 
				background-color: #b71c1c; 
			}
		""")
		self.exit_btn.clicked.connect(QApplication.instance().quit)
		self.top_btn = QPushButton("📌"); self.top_btn.setCheckable(True); self.top_btn.setFixedSize(40, 40); self.top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
		self.top_btn.setStyleSheet("QPushButton { background-color: #2D2D2D; border: 1px solid #444; border-radius: 4px; font-size: 16px; } QPushButton:checked { background-color: #00E5FF; color: black; }")
		self.top_btn.clicked.connect(self.toggle_always_on_top)
		bottom_btn_layout.addWidget(self.exit_btn, 1); bottom_btn_layout.addWidget(self.top_btn, 0)
		sidebar_layout.addLayout(bottom_btn_layout)
		main_layout.addWidget(sidebar)

		# === 2. Right Content Area (Tabs) ===
		content_area = QWidget()
		content_layout = QVBoxLayout(content_area)
		content_layout.setContentsMargins(10, 10, 10, 10)
		
		# Tabs
		self.tabs = QTabWidget()
		self.tabs.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
		self.tabs.setStyleSheet("""
			QTabWidget::pane { border: 0; background-color: #121212; }
			QTabBar::tab { background: #1E1E1E; color: #888; padding: 10px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; font-weight: bold; font-size: 13px; }
			QTabBar::tab:selected { background: #2D2D2D; color: #00E5FF; border-bottom: 2px solid #00E5FF; }
		""")
		
		# [NEW] Pop-out Button on Tab Corner
		self.popout_container = QWidget()
		popout_layout = QHBoxLayout(self.popout_container)
		popout_layout.setContentsMargins(0, 5, 10, 0)
		
		self.btn_popout = QPushButton("↗️ 분리")
		self.btn_popout.setFixedSize(60, 25)
		self.btn_popout.setToolTip("현재 탭을 별도 창으로 분리 (Pop-out)")
		self.btn_popout.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_popout.setStyleSheet("""
			QPushButton {
				background-color: #333; color: #00E5FF; border: 1px solid #444; border-radius: 4px; font-size: 11px; font-weight: bold;
			}
			QPushButton:hover { background-color: #444; border-color: #555; }
		""")
		self.btn_popout.clicked.connect(self.pop_out_current_tab)
		popout_layout.addWidget(self.btn_popout)
		
		self.tabs.setCornerWidget(self.popout_container, Qt.Corner.TopRightCorner)
		
		content_layout.addWidget(self.tabs)
		main_layout.addWidget(content_area)
		
		# [안실장 유지보수 가이드] 공용 상태바 적용 (StandardStatusBar)
		from shared.ui.widgets import StandardStatusBar
		from shared.market_hour import MarketHour
		self.status_bar = StandardStatusBar()
		self.setStatusBar(self.status_bar)
		
		# 초기 상태 설정
		is_mock = self.chk_mock.isChecked()
		self.status_bar.set_server_mode(is_real=not is_mock)
		market = MarketHour()
		m_status, m_open = market.get_market_status_text()
		self.status_bar.update_market_status(m_status, is_open=m_open)
		self.status_bar.set_connection_status(True) # Lead_Sig은 보통 실행 시 연결됨
		
		# --- Tab 1: 실시간 주도테마 ---
		self.leading_theme_widget = LeadingThemeWidget(self.db_manager, self.integrator)
		self.tabs.addTab(self.leading_theme_widget, "🔥 실시간 주도테마")
		
		self.momentum_widget = Momentum10MinWidget()
		self.tabs.addTab(self.momentum_widget, "⏱️ 10분 등락률 (10Min Momentum)")
		
		# --- Tab 3: 프로그램 매매 ---
		self.program_widget = ProgramTradingWidget()
		self.tabs.addTab(self.program_widget, "📊 프로그램 수급 상위")
		
		self.history_widget = HistoryWidget(self.db_manager, self.analyzer)
		self.tabs.addTab(self.history_widget, "🕵️ 추적실 (Tracking Room)")
		
		# === 3. Signals Connect (After UI defined) ===
		self.interval_combo.currentIndexChanged.connect(self.change_interval)
		self.tabs.currentChanged.connect(self.on_tab_changed)
		
	def pop_out_current_tab(self):
		"""현재 활성화된 탭을 별도 독립 창으로 실행"""
		idx = self.tabs.currentIndex()
		module_map = {
			0: "ui.leading_theme_widget",
			1: "ui.momentum_widget",
			2: "ui.program_trading_widget",
			3: "ui.history_widget"
		}
		
		module_name = module_map.get(idx)
		if module_name:
			# Get the path of Python executable (prefer pythonw for no console)
			python_exe = sys.executable.replace("python.exe", "pythonw.exe")
			
			# Lead_Sig 폴더의 부모 디렉토리를 PYTHONPATH로 설정하거나
			# 현재 작업 디렉토리 기준 모듈 실행 (-m)
			base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
			
			import subprocess
			# python -m ui.leading_theme_widget 등을 호출하여 독립 프로세스로 띄움
			subprocess.Popen([python_exe, "-m", module_name], cwd=base_dir)
			self.status_label.setText(f"새 창 분리 실행 완료: {module_name}")

	def request_data_update(self):
		if self.data_thread and self.data_thread.isRunning():
			return
		self.data_thread = DataThread(self.analyzer)
		self.data_thread.data_ready.connect(self.on_data_received)
		self.data_thread.status_signal.connect(self.update_status_message)
		self.data_thread.start()

	def on_data_received(self, data_dict):
		self.current_data.update(data_dict)
		self.update_index_display()
		self.update_market_signal(data_dict.get("indices"))
		
		if not self.timer.isActive():
			self.timer.start(self.update_interval)

		if "momentum_10min" in data_dict:
			self.momentum_widget.update_data(data_dict["momentum_10min"])
			
		if "program_trading" in data_dict:
			self.program_widget.update_data(data_dict["program_trading"])

		if "top8_themes_data" in data_dict:
			self.leading_theme_widget.update_auto_panels(data_dict["top8_themes_data"])

		if "system_alerts" in data_dict and data_dict["system_alerts"]:
			current_time = time.strftime("%H:%M:%S")
			for alert_msg in data_dict["system_alerts"]:
				self.leading_theme_widget.append_log(alert_msg)
			if hasattr(self, "signal_history_dlg"):
				self.signal_history_dlg.add_alerts(data_dict["system_alerts"], current_time)

		self.status_label.setText(f"마지막 업데이트: {time.strftime('%H:%M:%S')}")

	def update_market_signal(self, indices):
		"""지수 데이터를 분석하여 공용 시장 신호(Regime) 업데이트"""
		if not indices or not self.signal_manager:
			return
			
		kospi_chg = indices.get("KOSPI", {}).get("change", 0.0)
		kosdaq_chg = indices.get("KOSDAQ", {}).get("change", 0.0)
		
		regime = "NEUTRAL"
		score = 50
		message = "시장 횡보 중"
		
		# 판별 로직 (0.5% 기준)
		if kospi_chg > 0.5 and kosdaq_chg > 0.5:
			regime = "BULL"
			score = 80
			message = "시장 강세 (적극 매수 권장)"
		elif kospi_chg < -0.5 or kosdaq_chg < -0.5:
			regime = "BEAR"
			score = 20
			message = "시장 약세 (보수적 접근 필요)"
		elif kospi_chg > 0 and kosdaq_chg > 0:
			regime = "NEUTRAL"
			score = 60
			message = "시장 완만한 상승"
		elif kospi_chg < 0 and kosdaq_chg < 0:
			regime = "NEUTRAL"
			score = 40
			message = "시장 완만한 조정"

		# 파일 저장 (AT_Sig에서 참조)
		self.signal_manager.save_signal(regime, score, message, source="Lead_Sig")

	def update_index_display(self):
		indices = self.current_data.get("indices", {})
		for name, data in indices.items():
			if name in self.index_labels:
				price_val = data.get("price", 0)
				change_val = data.get("change", 0)
				bg_color = "#CC3333" if change_val > 0 else "#3333CC" if change_val < 0 else "transparent"
				self.index_labels[name]["price"].setText(f"{price_val:,.2f}")
				self.index_labels[name]["price"].setStyleSheet("color: white; font-size: 15px; font-weight: bold;")
				self.index_labels[name]["change"].setText(f"{change_val:.2f}")
				self.index_labels[name]["change"].setStyleSheet(f"color: white; background-color: {bg_color}; border-radius: 3px; padding: 2px; font-size: 12px; font-weight: bold;")

	def update_server_mode_ui(self):
		"""모의투자 체크박스 상태에 따라 서버 모드 및 상태바 갱신"""
		is_mock = self.chk_mock.isChecked()
		mode = "PAPER" if is_mock else "REAL"
		
		# 엔진 모드 변경 및 설정 저장
		self.analyzer.fetcher.mode = mode
		update_kw_setting('data_mode', mode)
		
		# 상태바 즉시 갱신
		self.status_bar.set_server_mode(is_real=not is_mock)
		
		if is_mock:
			self.status_label.setText("모드 변경: Simulation")
			logger.info("💡 [모의투자 모드]로 전환되었습니다.")
		else:
			self.status_label.setText("모드 변경: Real-time")
			logger.info("🔥 [실전투자 모드]로 전환되었습니다.")
			
		self.request_data_update()

	def change_interval(self, index):
		intervals = [5000, 10000, 15000, 30000, 60000]
		self.update_interval = intervals[index]
		self.timer.setInterval(self.update_interval)
		self.status_label.setText(f"갱신 주기 변경: {self.update_interval//1000}초")

	def on_tab_changed(self, index):
		tab_name = self.tabs.tabText(index)
		self.status_label.setText(f"탭 전환: {tab_name}")
		self.request_data_update()
		if index == 3: # 🕵️ 추적실 (Tracking Room)
			self.history_widget.load_data(fetch_prices=True, recent_only=True)
			self.history_widget.start_auto_refresh()
		else:
			self.history_widget.stop_auto_refresh()

	def toggle_always_on_top(self, checked):
		flags = self.windowFlags()
		if checked: self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
		else: self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
		self.show()
