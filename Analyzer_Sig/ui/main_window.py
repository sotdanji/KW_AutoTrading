# -*- coding: utf-8 -*-
import sys
import os
import logging
import traceback
import datetime
import concurrent.futures
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
							 QPushButton, QLabel, QFrame, QTabWidget, 
							 QApplication, QMessageBox, QCheckBox, QTableWidget,
							 QTableWidgetItem, QHeaderView, QSplitter, QGroupBox,
							 QGridLayout, QDateEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QProgressBar, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, QSettings, QDate

# 프로젝트 루트 경로 설정
current_file_path = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_file_path))
if project_root not in sys.path:
	sys.path.insert(0, project_root)

# Analyzer 관련 내부 임포트
from config import ACCOUNT_MODE, REAL_CONFIG
from core.market_engine import MarketEngine as MarketAnalyzer
from core.integrator import AT_SigIntegrator
from shared.db_manager import DBManager
from shared.accumulation_manager import AccumulationManager
from core.threads import StartupThread
from core.stock_universe import filter_hot_stocks_parallel

# UI 위젯 임포트
from ui.leading_theme_widget import LeadingThemeWidget
from ui.momentum_widget import Momentum10MinWidget
from ui.program_trading_widget import ProgramTradingWidget
from ui.history_widget import HistoryWidget
from ui.accumulation_tab import AccumulationTab

# shared 모듈 임포트
from shared.ui.styles import DARK_THEME_QSS
from shared.ui.widgets import StandardStatusBar, StandardLogWindow
from shared.signal_manager import MarketSignalManager
from shared.stock_master import load_master_cache, get_stock_name
from shared.ui.strategy_mixin import StrategyMixin

class AnalyzerWindow(StrategyMixin, QMainWindow):
	"""
	Analyzer_Sig: 10개 탭 통합 버전 (Analyzer_Sig 9개 + Log 1개)
	"""
	def __init__(self):
		super().__init__()
		self.setWindowTitle("Sotdanji Analyzer_Sig: 통합 분석 관제 센터")
		self.resize(1250, 850) # AT_Sig 앱 크기에 가깝게 축소
		
		# 엔진 초기화
		self.analyzer = MarketAnalyzer(mode=ACCOUNT_MODE)
		self.integrator = AT_SigIntegrator()
		self.db_manager = DBManager()
		self.acc_mgr = AccumulationManager()
		self.signal_manager = MarketSignalManager()
		self.stock_name_map = load_master_cache() or {}
		
		self.token = None
		self.log_paused = False # 로그 정지 상태 플래그
		
		# --- 표준 출력/에러 UI 리다이렉션 ---
		self.original_stdout = sys.stdout
		self.original_stderr = sys.stderr
		sys.stdout = self
		sys.stderr = self
		
		self.init_ui()
		
		# --- 시스템 통합 로깅 핸들러 장착 ---
		from core.threads import QThandler
		self.log_handler = QThandler(self.append_log)
		logging.getLogger().addHandler(self.log_handler)
		logging.getLogger().setLevel(logging.INFO)
		
		# [Startup] 엔진 초기화 시퀀스 시작
		self.start_engines()
		
		# [New] 저장된 UI 설정 불러오기
		QTimer.singleShot(700, self.load_window_settings)

	def closeEvent(self, event):
		"""창 닫힐 때 설정 저장"""
		try:
			self.save_window_settings()
		except:
			pass
		# 기존 로그 핸들러 제거
		logging.getLogger().removeHandler(self.log_handler)
		event.accept()

	def save_window_settings(self):
		"""설정 저장"""
		settings = QSettings("Sotdanji", "AnalyzerSig")
		settings.setValue("bt_deposit", self.spin_deposit.value())
		settings.setValue("bt_ratio", self.spin_ratio.value())
		settings.setValue("bt_tp", self.spin_tp.value())
		settings.setValue("bt_sl", self.spin_sl.value())
		settings.setValue("bt_comm", self.spin_comm.value())
		settings.setValue("bt_slip", self.spin_slip.value())
		settings.setValue("bt_strategy_idx", self.combo_strategies.currentIndex())
		settings.setValue("bt_start_date", self.bt_date_start.date().toString(Qt.DateFormat.ISODate))
		settings.setValue("bt_end_date", self.bt_date_end.date().toString(Qt.DateFormat.ISODate))

	def load_window_settings(self):
		"""설정 불러오기"""
		settings = QSettings("Sotdanji", "AnalyzerSig")
		try:
			if settings.contains("bt_deposit"):
				self.spin_deposit.setValue(int(float(settings.value("bt_deposit"))))
			if settings.contains("bt_ratio"):
				self.spin_ratio.setValue(float(settings.value("bt_ratio")))
			if settings.contains("bt_tp"):
				self.spin_tp.setValue(float(settings.value("bt_tp")))
			if settings.contains("bt_sl"):
				self.spin_sl.setValue(float(settings.value("bt_sl")))
			if settings.contains("bt_comm"):
				self.spin_comm.setValue(float(settings.value("bt_comm")))
			if settings.contains("bt_slip"):
				self.spin_slip.setValue(float(settings.value("bt_slip")))
			if settings.contains("bt_strategy_idx"):
				idx = int(settings.value("bt_strategy_idx"))
				if idx < self.combo_strategies.count():
					self.combo_strategies.setCurrentIndex(idx)
			if settings.contains("bt_start_date"):
				self.bt_date_start.setDate(QDate.fromString(str(settings.value("bt_start_date")), Qt.DateFormat.ISODate))
			if settings.contains("bt_end_date"):
				self.bt_date_end.setDate(QDate.fromString(str(settings.value("bt_end_date")), Qt.DateFormat.ISODate))
			self.log("📂 분석 설정이 복구되었습니다.")
		except Exception as e:
			self.log(f"⚠️ 설정 복구 중 건너뜀: {e}")



	def log(self, msg):
		"""외부 호출용 통합 로그 인터페이스 (logging으로 유입됨)"""
		logging.info(msg)
		if hasattr(self, 'status_bar'): self.status_bar.set_message(msg)

	def write(self, text):
		"""sys.stdout/stderr 리다이렉션 수신부"""
		if text and text.strip():
			# [Tip] UI 스레드 안전성을 위해 append_log를 직접 부르지 않고 로거를 통함
			logging.info(text.strip())

	def flush(self):
		"""sys.stdout 필수 구현 메서드"""
		pass

	def append_log(self, full_msg):
		"""QThandler로부터 전달받은 포맷팅된 메시지를 UI에 출력 (최종 목적지)"""
		if self.log_paused:
			return # 정지 모드일 때는 화면 업데이트 스킵
			
		if hasattr(self, 'log_text'):
			self.log_text.append(full_msg)

	def clear_log(self):
		"""로그 창 비우기"""
		if hasattr(self, 'log_text'):
			self.log_text.clear()
			self.log("🗑️ 로그 창이 초기화되었습니다.")

	def toggle_log_pause(self, checked):
		"""로그 화면 업데이트 일시 정지/재개"""
		self.log_paused = checked
		if checked:
			self.btn_log_pause.setText("▶️ 재개")
			self.btn_log_pause.setStyleSheet("background-color: #f57c00; color: white;")
		else:
			self.btn_log_pause.setText("⏸️ 정지")
			self.btn_log_pause.setStyleSheet("")
			self.log("▶️ 로그 화면 업데이트가 재개되었습니다.")



	def init_ui(self):
		self.bt_progress_bar = None
		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		main_layout = QHBoxLayout(central_widget)
		main_layout.setContentsMargins(0, 0, 0, 0)
		main_layout.setSpacing(0)

		# 1. 사이드바
		self.setup_sidebar(main_layout)

		# 2. 메인 10탭 시스템
		self.tabs = QTabWidget()
		self.tabs.setDocumentMode(True)
		self.tabs.setStyleSheet("""
			QTabWidget::pane { border: 0; background-color: #121212; }
			QTabBar::tab { background: #1E1E1E; color: #888; padding: 10px 12px; font-weight: bold; font-size: 12px; border-right: 1px solid #333; }
			QTabBar::tab:selected { background: #2D2D2D; color: #00E5FF; border-bottom: 3px solid #00E5FF; }
			QTabBar::tab:hover { background: #333; color: #fff; }
		""")

		# --- Lead_Sig 기반 탭 (4개) ---
		self.leading_theme_widget = LeadingThemeWidget(self.db_manager, self.integrator)
		self.tabs.addTab(self.leading_theme_widget, "🔥 주도테마")
		
		self.momentum_widget = Momentum10MinWidget()
		self.tabs.addTab(self.momentum_widget, "⏱️ 모멘텀")
		
		self.program_widget = ProgramTradingWidget()
		self.tabs.addTab(self.program_widget, "📊 프로그램")
		
		self.history_widget = HistoryWidget(self.db_manager, self.analyzer)
		self.tabs.addTab(self.history_widget, "🕵️ 추적실")

		# --- 매집 분석 탭 (1개) ---
		self.acc_tab = AccumulationTab(self.acc_mgr, self.stock_name_map)
		self.acc_tab.scan_requested.connect(self.run_accumulation_scan)
		self.tabs.addTab(self.acc_tab, "🔍 매집스캔")

		# --- 통합 분석 탭 (4개) - 명칭 표준화 (Mixin 호환성) ---
		self.tab_strategy = QWidget()
		self.setup_strategy_tab() # from StrategyMixin
		self.tabs.addTab(self.tab_strategy, "📋 전략코드")

		self.tab_settings = QWidget()
		self.setup_settings_tab() 
		self.tabs.addTab(self.tab_settings, "⚙️ 분석설정")

		self.table = QTableWidget() # 'table'로 명칭 표준화
		self.table.setColumnCount(8)
		self.table.setHorizontalHeaderLabels(["종목코드", "종목명", "매수일", "매도일", "매수가", "매도가", "수익률", "상태"])
		self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		
		# [안실장 픽스] 거래내역 더블 클릭 시 HTS 차트 연동
		self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
		
		self.tabs.addTab(self.table, "💼 거래내역")

		self.tab_summary = QWidget()
		self.setup_summary_tab()
		self.tabs.addTab(self.tab_summary, "📊 성과요약")
		
		# --- 통합 로그 탭 ---
		self.tab_log = QWidget()
		l_layout = QVBoxLayout(self.tab_log)
		
		# 로그 제어 버튼부
		log_ctrl_layout = QHBoxLayout()
		self.btn_log_clear = QPushButton("🗑️ 지우기")
		self.btn_log_clear.setFixedWidth(100)
		self.btn_log_clear.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_log_clear.clicked.connect(self.clear_log)
		
		self.btn_log_pause = QPushButton("⏸️ 정지")
		self.btn_log_pause.setFixedWidth(100)
		self.btn_log_pause.setCheckable(True)
		self.btn_log_pause.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_log_pause.clicked.connect(self.toggle_log_pause)
		
		log_ctrl_layout.addStretch()
		log_ctrl_layout.addWidget(self.btn_log_clear)
		log_ctrl_layout.addWidget(self.btn_log_pause)
		l_layout.addLayout(log_ctrl_layout)
		
		self.log_text = QTextEdit()
		self.log_text.setReadOnly(True)
		self.log_text.setStyleSheet("""
			QTextEdit { 
				background-color: #1E1E1E; color: #D4D4D4; border-radius: 4px; padding: 10px; font-family: 'Consolas';
			}
		""")
		l_layout.addWidget(self.log_text)
		self.tabs.addTab(self.tab_log, "📝 실행로그")

		main_layout.addWidget(self.tabs)

		self.status_bar = StandardStatusBar()
		self.setStatusBar(self.status_bar)
		self.setStyleSheet(DARK_THEME_QSS)

	def setup_sidebar(self, parent_layout):
		sidebar = QFrame()
		sidebar.setFixedWidth(190) # 사이드바 너비 축소
		sidebar.setStyleSheet("background-color: #1E1E1E; border-right: 1px solid #333;")
		layout = QVBoxLayout(sidebar)
		layout.setContentsMargins(15, 20, 15, 20)
		layout.setSpacing(12)

		logo = QLabel("ANALYZER_SIG"); logo.setStyleSheet("font-size: 18px; font-weight: bold; color: #00E5FF;")
		layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)


		self.index_labels = {}
		index_targets = [
			("KOSPI", "코스피"), 
			("KOSPI 200", "코스피200"), 
			("KOSDAQ", "코스닥"), 
			("KOSDAQ 150", "코스닥150"), 
			("Futures", "선물(K200)")
		]
		
		for key, display_name in index_targets:
			box = QFrame()
			box.setObjectName("IndexBox")
			box.setStyleSheet("""
				QFrame#IndexBox { 
					background-color: #2b2b2b; 
					border: 1px solid #444; 
					border-radius: 4px; 
					padding: 2px; 
				}
			""")
			blayout = QVBoxLayout(box)
			blayout.setContentsMargins(5, 5, 5, 5)
			blayout.setSpacing(2)
			
			title = QLabel(display_name)
			title.setStyleSheet("color: #aaa; font-size: 10px; font-weight: bold;")
			blayout.addWidget(title)
			
			row = QHBoxLayout()
			p = QLabel("-")
			p.setStyleSheet("color: white; font-weight: bold; font-size: 12px;")
			c = QLabel("-")
			c.setStyleSheet("font-size: 11px;")
			c.setAlignment(Qt.AlignmentFlag.AlignRight)
			
			row.addWidget(p)
			row.addWidget(c)
			blayout.addLayout(row)
			layout.addWidget(box)
			
			self.index_labels[key] = {"price": p, "change": c}

		# --- Lead_Sig 엔진 제어 컨트롤러 복구 ---
		engine_ctrl_layout = QHBoxLayout()
		self.btn_engine_start = QPushButton("🚀 구동")
		self.btn_engine_start.setMinimumHeight(35)
		self.btn_engine_start.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_engine_start.setStyleSheet("""
			QPushButton { background-color: #2e7d32; color: white; border-radius: 4px; font-weight: bold; }
			QPushButton:hover { background-color: #388e3c; }
		""")
		self.btn_engine_start.clicked.connect(lambda: self.start_engines(force=True))
		
		self.btn_engine_stop = QPushButton("⏹️ 중지")
		self.btn_engine_stop.setMinimumHeight(35)
		self.btn_engine_stop.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_engine_stop.setStyleSheet("""
			QPushButton { background-color: #444; color: #ccc; border-radius: 4px; font-weight: bold; }
			QPushButton:hover { background-color: #555; color: white; }
		""")
		self.btn_engine_stop.clicked.connect(self.stop_data_feed)
		
		engine_ctrl_layout.addWidget(self.btn_engine_start)
		engine_ctrl_layout.addWidget(self.btn_engine_stop)
		layout.addLayout(engine_ctrl_layout)

		self.lbl_engine_status = QLabel("● 실시간 엔진 준비됨")
		self.lbl_engine_status.setStyleSheet("color: #888; font-size: 11px; margin-left: 5px;")
		self.lbl_engine_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
		layout.addWidget(self.lbl_engine_status)

		self.btn_signal_hist = QPushButton("🚨 시그널 히스토리")
		self.btn_signal_hist.setMinimumHeight(40)
		self.btn_signal_hist.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_signal_hist.setStyleSheet("""
			QPushButton { 
				background-color: #4A148C; color: #FFF; border: 1px solid #7B1FA2; border-radius: 6px; font-weight: bold; font-size: 13px; 
			}
			QPushButton:hover { background-color: #6A1B9A; }
		""")
		# [알림] 시그널 히스토리 창은 필요 시 지연 로딩 처리
		self.btn_signal_hist.clicked.connect(self.show_signal_history)
		layout.addWidget(self.btn_signal_hist)

		self.chk_mock = QCheckBox("모의투자 모드")
		self.chk_mock.setCursor(Qt.CursorShape.PointingHandCursor)
		self.chk_mock.setStyleSheet("""
			QCheckBox { color: #00E5FF; font-weight: bold; font-size: 13px; margin-top: 5px; }
			QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #ffffff; border-radius: 3px; background-color: #2D2D2D; }
			QCheckBox::indicator:checked { background-color: #00E5FF; border-color: #00E5FF; }
		""")
		# 현재 토크나이저 모드 동기화
		if hasattr(self, 'analyzer'): self.chk_mock.setChecked(self.analyzer.fetcher.mode == "PAPER")
		layout.addWidget(self.chk_mock)

		# --- Lead_Sig 갱신 주기 (설정 영역으로 이동) ---
		interval_layout = QHBoxLayout()
		lbl_interval = QLabel("갱신 주기")
		lbl_interval.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold;")
		interval_layout.addWidget(lbl_interval)
		
		self.interval_combo = QComboBox()
		self.interval_combo.addItems(["5초", "10초", "15초", "30초", "1분"])
		self.interval_combo.setCurrentIndex(1) # 기본 10초
		self.interval_combo.setStyleSheet("""
			QComboBox {
				background-color: #333; color: #FFD700; padding: 4px; border-radius: 4px; font-weight: bold; border: 1px solid #444;
			}
			QComboBox::drop-down { border: 0px; }
		""")
		interval_layout.addWidget(self.interval_combo, 1)
		layout.addLayout(interval_layout)

		# --- 작업 진척도 프로그래스바 추가 ---
		self.progress_bar = QProgressBar()
		self.progress_bar.setRange(0, 100)
		self.progress_bar.setValue(0)
		self.progress_bar.setTextVisible(True)
		self.progress_bar.setFixedHeight(12)
		self.progress_bar.setVisible(False)
		if hasattr(self, 'bt_progress_bar') and self.bt_progress_bar: self.bt_progress_bar.setVisible(False)
		self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.progress_bar.setStyleSheet("""
			QProgressBar { 
				background-color: #1A1A1A; 
				border: 1px solid #333; 
				border-radius: 6px; 
				text-align: center;
				color: white;
				font-size: 8px;
				font-weight: bold;
			}
			QProgressBar::chunk { 
				background-color: qlineargradient(spread:pad, x1:0, y1:0.5, x2:1, y2:0.5, 
					stop:0 #00E5FF, stop:1 #DAA520); 
				border-radius: 5px; 
			}
		""")
		layout.addWidget(self.progress_bar)

		layout.addStretch()
		
		bottom_btn_layout = QHBoxLayout()
		bottom_btn_layout.setSpacing(5)
		
		self.btn_exit = QPushButton("종료")
		self.btn_exit.setMinimumHeight(40)
		self.btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_exit.setStyleSheet("""
			QPushButton { 
				background-color: #d32f2f; color: white; border-radius: 5px; font-weight: bold; font-size: 14px; 
			}
			QPushButton:hover { background-color: #ff5252; }
		""")
		self.btn_exit.clicked.connect(self.close)
		bottom_btn_layout.addWidget(self.btn_exit, 1)

		self.btn_ontop = QPushButton("📌")
		self.btn_ontop.setCheckable(True)
		self.btn_ontop.setFixedSize(40, 40)
		self.btn_ontop.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_ontop.setStyleSheet("""
			QPushButton { 
				background-color: #2D2D2D; border: 1px solid #444; border-radius: 5px; font-size: 16px; 
			} 
			QPushButton:checked { background-color: #00E5FF; color: black; }
		""")
		self.btn_ontop.clicked.connect(self.toggle_always_on_top)
		bottom_btn_layout.addWidget(self.btn_ontop, 0)
		
		layout.addLayout(bottom_btn_layout)
		parent_layout.addWidget(sidebar)

	def setup_settings_tab(self):
		"""백테스트 및 분석 환경 설정 UI 구성"""
		layout = QVBoxLayout(self.tab_settings)
		layout.setContentsMargins(20, 20, 20, 20)
		layout.setSpacing(15)

		# --- 커스텀 헤더 (제목 + 버튼) ---
		header_layout = QHBoxLayout()
		title_lbl = QLabel("⚙️ 백테스트 및 분석 환경 설정 (Parameter Tuner)")
		title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #00E5FF;")
		header_layout.addWidget(title_lbl)
		
		header_layout.addStretch()
		
		self.btn_run_backtest = QPushButton("🚀 백테스트 시작")
		self.btn_run_backtest.setFixedWidth(160)
		self.btn_run_backtest.setMinimumHeight(35)
		self.btn_run_backtest.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_run_backtest.setStyleSheet("""
			QPushButton { 
				background-color: #1565c0; color: white; font-weight: bold; font-size: 13px; border-radius: 4px;
			}
			QPushButton:hover { background-color: #1976d2; }
			QPushButton:disabled { background-color: #444; color: #888; }
		""")
		self.btn_run_backtest.clicked.connect(self.run_backtest)
		header_layout.addWidget(self.btn_run_backtest)
		
		layout.addLayout(header_layout)

		# [NEW] 백테스트 전용 와이드 프로그래스바
		self.bt_progress_bar = QProgressBar()
		self.bt_progress_bar.setFixedHeight(16)
		self.bt_progress_bar.setVisible(False)
		self.bt_progress_bar.setTextVisible(True)
		self.bt_progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.bt_progress_bar.setStyleSheet("""
			QProgressBar {
				background-color: #141414;
				border: 1px solid #222;
				border-radius: 8px;
				text-align: center;
				color: #00E5FF;
				font-size: 10px;
				font-weight: bold;
			}
			QProgressBar::chunk {
				background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, 
					stop:0 #1565c0, stop:1 #00E5FF);
				border-radius: 7px;
			}
		""")
		layout.addWidget(self.bt_progress_bar)

		# 1. 전략 선택 및 단일 종목 설정 섹션
		strategy_group = QGroupBox("전략 및 대상 설정")
		strategy_layout = QGridLayout(strategy_group)
		
		strategy_layout.addWidget(QLabel("적용 전략:"), 0, 0)
		self.combo_strategies = QComboBox()
		self.combo_strategies.setMinimumWidth(250)
		self.combo_strategies.setMinimumHeight(35)
		strategy_layout.addWidget(self.combo_strategies, 0, 1)
		
		btn_refresh = QPushButton("🔄 갱신")
		btn_refresh.setFixedWidth(80)
		btn_refresh.setMinimumHeight(35)
		btn_refresh.clicked.connect(self.load_strategy_list)
		strategy_layout.addWidget(btn_refresh, 0, 2)
		
		strategy_layout.addWidget(QLabel("단일 종목 코드:"), 1, 0)
		self.input_single_stock = QLineEdit()
		self.input_single_stock.setPlaceholderText("비워두면 전체(300종목) 테스트 / 예: 005930")
		self.input_single_stock.setMinimumHeight(35)
		self.input_single_stock.setToolTip("특정 종목 하나만 집중적으로 백테스트하려면 6자리 코드를 입력하세요.")
		strategy_layout.addWidget(self.input_single_stock, 1, 1, 1, 2)
		
		layout.addWidget(strategy_group)

		# 2. 시뮬레이션 환경 설정
		env_group = QGroupBox("시뮬레이션 환경 설정")
		grid = QGridLayout(env_group)
		grid.setSpacing(10)
		
		grid.addWidget(QLabel("시작날짜:"), 0, 0)
		self.bt_date_start = QDateEdit(datetime.date.today() - datetime.timedelta(days=90))
		self.bt_date_start.setCalendarPopup(True)
		grid.addWidget(self.bt_date_start, 0, 1)
		
		grid.addWidget(QLabel("종료날짜:"), 0, 2)
		self.bt_date_end = QDateEdit(datetime.date.today())
		self.bt_date_end.setCalendarPopup(True)
		grid.addWidget(self.bt_date_end, 0, 3)
		
		grid.addWidget(QLabel("초기자본:"), 1, 0)
		self.spin_deposit = QSpinBox()
		self.spin_deposit.setRange(1000000, 1000000000)
		self.spin_deposit.setValue(10000000)
		self.spin_deposit.setSingleStep(1000000)
		self.spin_deposit.setSuffix(" 원")
		grid.addWidget(self.spin_deposit, 1, 1)

		grid.addWidget(QLabel("매수비중:"), 1, 2)
		self.spin_ratio = QDoubleSpinBox()
		self.spin_ratio.setRange(1.0, 100.0)
		self.spin_ratio.setValue(10.0)
		grid.addWidget(self.spin_ratio, 1, 3)

		grid.addWidget(QLabel("익절 / 손절:"), 2, 0)
		box_tp_sl = QHBoxLayout()
		self.spin_tp = QDoubleSpinBox(); self.spin_tp.setRange(0.1, 100.0); self.spin_tp.setValue(5.0); self.spin_tp.setSingleStep(0.1)
		self.spin_sl = QDoubleSpinBox(); self.spin_sl.setRange(-100.0, -0.1); self.spin_sl.setValue(-3.0); self.spin_sl.setSingleStep(0.1)
		box_tp_sl.addWidget(self.spin_tp); box_tp_sl.addWidget(QLabel("/")); box_tp_sl.addWidget(self.spin_sl)
		grid.addLayout(box_tp_sl, 2, 1)

		grid.addWidget(QLabel("비용(수수료/슬립):"), 2, 2)
		box_fee = QHBoxLayout()
		self.spin_comm = QDoubleSpinBox(); self.spin_comm.setRange(0.0, 1.0); self.spin_comm.setValue(0.015); self.spin_comm.setSingleStep(0.01); self.spin_comm.setDecimals(3)
		self.spin_slip = QDoubleSpinBox(); self.spin_slip.setRange(0.0, 5.0); self.spin_slip.setValue(0.1); self.spin_slip.setSingleStep(0.01)
		box_fee.addWidget(self.spin_comm); box_fee.addWidget(QLabel("/")); box_fee.addWidget(self.spin_slip)
		grid.addLayout(box_fee, 2, 3)

		
		layout.addWidget(env_group)

		layout.addStretch()
		
		# 초기 전략 리스트 로드
		self.load_strategy_list()

	def load_strategy_list(self):
		"""저장된 전략 JSON 리스트를 콤보박스에 로드"""
		if not hasattr(self, 'combo_strategies'): return
		
		self.combo_strategies.clear()
		s_dir = self.get_strategies_dir() # from StrategyMixin
		if os.path.exists(s_dir):
			files = [f for f in os.listdir(s_dir) if f.endswith('.json')]
			files.sort()
			self.combo_strategies.addItems(files)
			self.log(f"전략 리스트 {len(files)}개 갱신 완료 (확장자 포함)")
		else:
			self.combo_strategies.addItem("저장된 전략 없음")

	def setup_summary_tab(self):
		"""성과 요약 대시보드 구성"""
		layout = QVBoxLayout(self.tab_summary)
		layout.addWidget(QLabel("백테스트 결과 분석 리포트"))
		layout.addStretch()

	def on_table_double_clicked(self, item):
		"""거래내역 테이블 더블 클릭 시 HTS 연동"""
		row = item.row()
		# 종목코드는 0번 컬럼
		code_item = self.table.item(row, 0)
		if code_item:
			code = code_item.text().strip()
			if code:
				try:
					from shared.hts_connector import send_to_hts
					send_to_hts(str(code))
				except: pass

	def set_engine_status(self, running):
		"""엔진 구동 상태 UI 업데이트 통합 관리"""
		if running:
			self.lbl_engine_status.setText("● 실시간 엔진 구동 중")
			self.lbl_engine_status.setStyleSheet("color: #00E5FF; font-weight: bold; margin-left: 10px;")
			self.btn_engine_start.setStyleSheet("background-color: #1b5e20; color: #00E5FF; border-radius: 4px; font-weight: bold;")
			self.btn_engine_stop.setStyleSheet("background-color: #444; color: #ccc; border-radius: 4px; font-weight: bold;")
		else:
			self.lbl_engine_status.setText("○ 실시간 엔진 정지됨")
			self.lbl_engine_status.setStyleSheet("color: #FF4444; font-weight: bold; margin-left: 10px;")
			self.btn_engine_start.setStyleSheet("background-color: #2e7d32; color: white; border-radius: 4px; font-weight: bold;")
			self.btn_engine_stop.setStyleSheet("background-color: #b71c1c; color: white; border-radius: 4px; font-weight: bold;")

	def is_market_hours(self):
		"""현재 시간이 주식 시장 운영 시간(평일 08:30~16:00)인지 확인"""
		now = datetime.datetime.now()
		if now.weekday() >= 5: return False
		
		start_time = now.replace(hour=8, minute=30, second=0, microsecond=0)
		end_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
		return start_time <= now <= end_time

	def start_engines(self, force=False):
		"""앱 시작 시 시퀀스 또는 명시적 재구동"""
		self._force_start_feed = force
		if hasattr(self, 'startup_thread') and self.startup_thread.isRunning():
			self.log("⚠️ 이미 엔진 초기화 중입니다.")
			return
			
		self.log("🚀 시스템 엔진을 기동합니다...")
		self.set_engine_status(True)
		
		self.startup_thread = StartupThread(self.analyzer, self.db_manager)
		if hasattr(self, 'status_bar'):
			self.startup_thread.status_signal.connect(lambda msg: self.status_bar.set_message(msg))
		
		# [NEW] 초기화 중 로드된 지수 데이터를 사이드바에 즉시 반영
		self.startup_thread.index_ready.connect(lambda idx: self.on_data_received({"indices": idx}))
		
		self.startup_thread.finished_signal.connect(self.on_startup_finished)
		self.startup_thread.start()

	def on_startup_finished(self, success):
		"""초기화 완료 후 정규 데이터 피드 시작 여부 결정"""
		if success:
			if hasattr(self, 'status_bar'): self.status_bar.set_connection_status(True)
			
			# 장중이거나, 사용자가 수동으로 <구동> 버튼을 누른 경우(force=True) 피드 시작
			if self.is_market_hours() or getattr(self, '_force_start_feed', False):
				self.start_data_feed()
			else:
				self.log("🌙 초기화 완료. 장외 시간이므로 실시간 엔진은 [중지] 상태를 유지합니다.")
				self.set_engine_status(False)
		else:
			self.log("❌ 엔진 초기화 실패. API 연결 상태를 확인하세요.")
			self.set_engine_status(False)

	def start_data_feed(self):
		"""실시간 시장 데이터 피드 구동"""
		self.stop_data_feed()
		
		from core.threads import DataThread
		self.data_thread = DataThread(self.analyzer)
		self.data_thread.data_ready.connect(self.on_data_received)
		self.data_thread.start()
		self.log("🚀 [Analyzer_Sig] 실시간 데이터 피드가 구동되었습니다.")
		self.set_engine_status(True)

	def stop_data_feed(self):
		"""실시간 데이터 피드만 안전하게 중지"""
		if hasattr(self, 'data_thread') and self.data_thread and self.data_thread.isRunning():
			self.data_thread._stop_flag = True
			self.data_thread.quit()
			self.data_thread.wait(500)
			self.log("⏹️ [Analyzer_Sig] 실시간 데이터 피드가 중지되었습니다.")
		self.set_engine_status(False)

	def on_data_received(self, data):
		# ---지수 데이터 처리 (딕셔너리 구조 대응) ---
		indices_dict = data.get("indices", {})
		for name, info in indices_dict.items():
			if name in self.index_labels:
				price = info.get("price", "-")
				change = info.get("change", 0)
				rate = info.get("rate", "0").replace("%", "") # 만약 rate가 없으면 0
				
				self.index_labels[name]["price"].setText(str(price))
				chg_text = f"{change} ({rate})"
				self.index_labels[name]["change"].setText(chg_text)
				
				# 색상 강조
				color = "#ff3333" if float(str(change).replace('+', '')) > 0 else "#3388ff" if float(str(change).replace('+', '')) < 0 else "white"
				self.index_labels[name]["change"].setStyleSheet(f"color: {color};")

		# --- 위젯별 데이터 배달 ---
		# 1. 주도테마 위젯 (함수명: update_auto_panels, 데이터: top8_themes_data)
		self.leading_theme_widget.update_auto_panels(data.get("top8_themes_data", []))
		
		# 2. 10분 모멘텀 위젯
		self.momentum_widget.update_data(data.get("momentum_10min", []))
		
		# 3. 프로그램 매매 위젯
		self.program_widget.update_data(data.get("program_trading", {}))

	def run_accumulation_scan(self):
		token = self.analyzer.fetcher.token
		if not token: 
			QMessageBox.warning(self, "오류", "API 토큰이 없습니다. 잠시 후 다시 시도해 주세요.")
			return
		
		if hasattr(self, 'acc_tab'): self.acc_tab.btn_run_scan.setEnabled(False)
		
		try:
			from core.stock_universe import get_full_stock_universe
			self.log("📋 전체 종목 유니버스 구성 중...")
			universe = get_full_stock_universe(token)
			
			self.log("🔥 주도주 및 거래량 상위 종목 필터링 중 (기준: 50억)...")
			hot_codes = filter_hot_stocks_parallel(universe, token, min_value=5000000000)
			
			captured_pool = self.acc_mgr.get_captured_pool_codes(30)
			active_acc = self.acc_mgr.get_active_accumulation_stocks(limit=100)
			all_candidates = list(dict.fromkeys(hot_codes + captured_pool + active_acc))[:300]
			
			if not all_candidates:
				self.log("⚠️ 스캔할 후보 종목이 없습니다. 기본 우량주 풀을 사용합니다.")
				all_candidates = ["005930", "000660", "035420", "035720", "005380", "000270", "005490", "032830"]
			
			self.log(f"🕵️ 총 {len(all_candidates)}개 종목의 수급/매집 상태를 정밀 분석합니다...")
			
			self.progress_bar.setMaximum(len(all_candidates))
			self.progress_bar.setValue(0)
			self.progress_bar.setVisible(True)
			
			futures = []
			import concurrent.futures
			with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
				for c in all_candidates:
					futures.append(executor.submit(self.acc_mgr.update_accumulation_data, c, token, 30))
				
				for i, _ in enumerate(concurrent.futures.as_completed(futures)):
					self.progress_bar.setValue(i + 1)
					from PyQt6.QtWidgets import QApplication
					QApplication.processEvents()
			
			results = [dict({'code': c}, **self.acc_mgr.calculate_metrics(c, days=30)) for c in all_candidates]
			target_results = [r for r in results if r.get('is_breakout') or r.get('is_below_avg') or r.get('is_yin_dual_buy') or r.get('is_volume_dry')]
			
			display_mode = "시그널 포착"
			if not target_results:
				self.log("ℹ️ 현재 강력한 기술적 진입 신호가 발생한 종목이 없습니다. 매집 점수 상위 종목을 출력합니다.")
				results.sort(key=lambda x: x.get('score', 0), reverse=True)
				target_results = results[:20]
				display_mode = "매집 점수 상위"
			
			self.acc_tab.update_table(target_results)
			self.tabs.setCurrentWidget(self.acc_tab) 
			self.progress_bar.setVisible(False)
			if hasattr(self, 'bt_progress_bar') and self.bt_progress_bar: 
				self.bt_progress_bar.setVisible(False)
			from PyQt6.QtWidgets import QMessageBox
			QMessageBox.information(self, "완료", f"{len(target_results)}개의 매집 관심주({display_mode}) 발굴 완료!")
		except Exception as e: 
			self.log(f"Scan Error: {e}")
		finally: 
			if hasattr(self, 'acc_tab'): self.acc_tab.btn_run_scan.setEnabled(True)

	def run_backtest(self):
		"""통합 백테스트 실행 로직"""
		if not hasattr(self, 'analyzer') or not self.analyzer.fetcher.token:
			QMessageBox.warning(self, "오류", "API 인증이 완료되지 않았습니다.")
			return

		strategy_name = self.combo_strategies.currentText()
		if not strategy_name or strategy_name == "저장된 전략 없음":
			QMessageBox.warning(self, "오류", "선택된 전략이 없습니다.")
			return

		# 1. 시뮬레이션 설정값 수집
		config = {
			"deposit": self.spin_deposit.value(),
			"ratio": self.spin_ratio.value(), 
			"tp": self.spin_tp.value(),
			"sl": self.spin_sl.value(),
			"commission": self.spin_comm.value() / 100.0,
			"slippage": self.spin_slip.value() / 100.0,
			"strategy_name": strategy_name
		}

		# [안실장 픽스] 날짜 객체 강제 정규화 및 유효성 검사
		try:
			s_date_q = self.bt_date_start.date()
			e_date_q = self.bt_date_end.date()
			
			# QDate -> Python Date (문자열 거쳐서 안전하게 변환)
			s_date = datetime.datetime.strptime(s_date_q.toString("yyyy-MM-dd"), "%Y-%m-%d").date()
			e_date = datetime.datetime.strptime(e_date_q.toString("yyyy-MM-dd"), "%Y-%m-%d").date()
			
			if s_date >= e_date:
				QMessageBox.critical(self, "날짜 오류", f"시작날짜({s_date})는 종료날짜({e_date})보다 이전이어야 합니다.")
				return
		except Exception as e:
			self.log(f"❌ 날짜 변환 오류: {e}")
			return


		# [안실장 픽스] 전략 JSON 파일에서 실제 파이썬 코드 추출하여 주입
		try:
			import json
			s_dir = self.get_strategies_dir()
			s_path = os.path.join(s_dir, strategy_name)
			if os.path.exists(s_path):
				with open(s_path, 'r', encoding='utf-8') as f:
					s_data = json.load(f)
					config['strategy_code'] = s_data.get('python_code', '').strip()
					config['data_type'] = s_data.get('data_type', 'daily') # 'minute' or 'daily'
					if not config['strategy_code']:
						QMessageBox.warning(self, "오류", f"'{strategy_name}'에 변환된 파이썬 코드가 없습니다.\n[전략코드] 탭에서 [변환] 후 [저장]을 먼저 진행해 주세요.")
						return

			else:
				self.log(f"⚠️ 전략 파일을 찾을 수 없음: {s_path}")
				return
		except Exception as e:
			self.log(f"❌ 전략 로드 중 치명적 오류: {e}")
			return


		# 2. 대상 종목 자동 선정
		single_code = self.input_single_stock.text().strip()
		if single_code:
			# 단일 종목 테스트 모드
			# 만약 'A'가 붙어있다면 제거
			single_code = single_code.replace('A', '')
			if len(single_code) != 6:
				QMessageBox.warning(self, "입력 오류", "종목코드는 6자리 숫자여야 합니다.")
				self.btn_run_backtest.setEnabled(True)
				return
			sample_stocks = [single_code]
			self.log(f"🎯 단일 종목 집중 백테스트 모드: {single_code}")
		else:
			# 기존: 대상 종목 자동 선정 (최근 매집주 + 우량주 믹스)
			# 1단계: 최근 30일간 포착된 매집주 풀 (최대 30개)
			sample_stocks = self.acc_mgr.get_captured_pool_codes(days_limit=30)
			
			# 2단계: 풀이 비어있다면 DB에 저장된 활성 매집주 (최대 100개)
			if not sample_stocks:
				sample_stocks = self.acc_mgr.get_active_accumulation_stocks(limit=100)
				
			# 3단계: 최후의 보루 (시총 상위 10선)
			if not sample_stocks:
				sample_stocks = ["005930", "000660", "035420", "035720", "005380", "000270", "005490", "017670", "003550", "012330"]
		
		self.log(f"🚀 [{strategy_name}] 백테스트를 시작합니다. (대상: {len(sample_stocks)}종목)")
		self.btn_run_backtest.setEnabled(False)
		
		# 3. 엔진 초기화 및 스레드 구동
		from core.backtest_engine import BacktestEngine
		self.bt_engine = BacktestEngine(self.analyzer.fetcher.token)
		self.bt_engine.setup_run(
			stock_list=sample_stocks,
			start_date=s_date,
			end_date=e_date,
			config=config
		)

		
		# [NEW] 멀티 포인트 프로그래스바 연동 (사이드바 + 전용바)
		for pb in [self.progress_bar, self.bt_progress_bar]:
			pb.setRange(0, 100)
			pb.setValue(0)
			pb.setVisible(True)
		
		def on_bt_progress(c, t):
			self.progress_bar.setValue(c)
			self.bt_progress_bar.setValue(c)
			if c < 50: self.progress_bar.setFormat(f"Data Loading: {c*2}%")
			else: self.progress_bar.setFormat(f"Simulating: {(c-50)*2}%")

		self.bt_engine.progress_updated.connect(on_bt_progress)
		
		# 시그널 연결 (로그 및 진척도)
		self.bt_engine.log_message.connect(lambda m: self.log(f"[BT] {m}"))
		self.bt_engine.finished_backtest.connect(self.on_backtest_finished)
		
		self.bt_engine.start()

	def on_backtest_finished(self, summary):
		self.btn_run_backtest.setEnabled(True)
		self.progress_bar.setVisible(False)
		if hasattr(self, 'bt_progress_bar') and self.bt_progress_bar: 
			self.bt_progress_bar.setVisible(False)
		
		# 1. 거래 내역 테이블 업데이트
		trades = summary.get('trades', [])
		self.table.setRowCount(0)
		from PyQt6.QtWidgets import QTableWidgetItem
		from PyQt6.QtGui import QColor
		for t in trades:
			row = self.table.rowCount()
			self.table.insertRow(row)
			name = self.stock_name_map.get(t['code'], t['code'])
			items = [
				t['code'], name, t['buy_date'], t['sell_date'],
				f"{t['buy_price']:,.0f}", f"{t['sell_price']:,.0f}",
				f"{t.get('profit_pct', 0.0):+.2f}", t.get('status', 'N/A')
			]
			for i, val in enumerate(items):
				item = QTableWidgetItem(str(val))
				item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
				if i == 6:
					if t.get('profit_pct', 0.0) > 0: item.setForeground(QColor("#FF5252"))
					elif t.get('profit_pct', 0.0) < 0: item.setForeground(QColor("#448AFF"))
				self.table.setItem(row, i, item)

		# 2. 성과 요약 탭 업데이트
		self.update_summary_tab(summary)
		
		QMessageBox.information(self, "백테스트 완료", 
			f"총 수익률: {summary['return_pct']:+.2f}\n총 손익: {summary['total_profit']:+,.0f}원\n승률: {summary['win_rate']:.1f}")
		self.tabs.setCurrentWidget(self.tab_summary)

	def update_summary_tab(self, s):
		"""성과 요약 탭의 내용을 실제 결과로 채움"""
		layout = self.tab_summary.layout()
		while layout.count():
			child = layout.takeAt(0)
			if child.widget(): child.widget().deleteLater()
		
		header = QLabel(f"📊 백테스트 성과 분석 리포트 ({s.get('strategy_name', '전략')})")
		header.setStyleSheet("font-size: 18px; font-weight: bold; color: #00E5FF; margin-bottom: 20px;")
		layout.addWidget(header)
		
		metrics_layout = QGridLayout()
		stats = [
			("총 수익률", f"{s['return_pct']:+.2f}", "#FF5252" if s['return_pct']>0 else "#448AFF"),
			("총 손익", f"{s['total_profit']:+,.0f}원", "white"),
			("누적 승률", f"{s['win_rate']:.1f}", "#FFD700"),
			("총 거래 횟수", f"{s['total_trades']}회", "white"),
			("익절 / 손절", f"{s['win_count']}회 / {s['loss_count']}회", "white"),
			("최대 낙폭 (MDD)", f"{s.get('mdd', 0):.2f}", "#FF5252"),
		]
		for i, (label, val, color) in enumerate(stats):
			l = QLabel(label); l.setStyleSheet("color: #888; font-size: 13px;")
			v = QLabel(val); v.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
			metrics_layout.addWidget(l, i // 2, (i % 2) * 2)
			metrics_layout.addWidget(v, i // 2, (i % 2) * 2 + 1)
		layout.addLayout(metrics_layout)
		layout.addStretch()

	def toggle_always_on_top(self, checked):
		"""윈도우 항상 위 설정/해제"""
		if checked:
			self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
		else:
			self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
		self.show() # 플래그 변경 후 창 다시 표시 필요

	def show_signal_history(self):
		"""[Analyzer_Sig] 스타일의 시그널 히스토리 다이얼로그 표시"""
		# (Note) 프로젝트의 SignalHistoryDialog를 사용하여 구현
		QMessageBox.information(self, "시그널", "실시간 시그널 히스토리 창을 준비 중입니다.")

	def update_realtime_ui(self): pass

if __name__ == "__main__":
	app = QApplication(sys.argv)
	try: window = AnalyzerWindow(); window.show(); sys.exit(app.exec())
	except Exception as e: print(f"ERROR: {e}"); traceback.print_exc()
