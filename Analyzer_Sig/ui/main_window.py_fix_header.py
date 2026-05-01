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
							 QGridLayout, QDateEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit,
							 QProgressBar)
from PyQt6.QtCore import Qt, QTimer

# 프로젝트 루트 경로 설정
current_file_path = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_file_path))
if project_root not in sys.path:
	sys.path.insert(0, project_root)

# Analyzer 관련 내부 임포트
from config import ACCOUNT_MODE, REAL_CONFIG
from core.market_engine import MarketEngine as MarketAnalyzer
from core.integrator import AT_SigIntegrator
from core.db_manager import DBManager
from core.accumulation_manager import AccumulationManager
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
	Sotdanji Analyzer_Sig 메인 윈도우
	- Lead_Sig(주도주/실시간) + BackTester(전략검증) 통합 플랫폼
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
		
		# [Startup] 엔진 초기화 시퀀스 시작 (장중/장외 상관없이 로그인은 항상 수행)
		self.start_engines()
