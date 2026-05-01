# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
							 QTableWidget, QTableWidgetItem, QHeaderView, 
							 QGroupBox, QGridLayout, QFrame, QTabWidget,
							 QDateEdit, QSpinBox, QDoubleSpinBox, QPushButton,
							 QProgressBar)
from PyQt6.QtCore import Qt, QDate
from shared.ui.strategy_mixin import StrategyMixin

class StrategyLabTab(StrategyMixin, QWidget):
	"""
	BackTester의 4개 핵심 탭을 통합 관리하는 전략 연구소 위젯
	"""
	def __init__(self, token=None):
		super().__init__()
		self.token = token
		self.init_ui()

	def init_ui(self):
		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		
		self.tabs = QTabWidget()
		self.tabs.setDocumentMode(True)
		
		# 1. 시뮬레이션 설정 탭
		self.tab_settings = QWidget()
		self.setup_settings_tab()
		self.tabs.addTab(self.tab_settings, "⚙️ 백테스트 설정")
		
		# 2. 전략 코드 검증 탭
		self.tab_strategy = QWidget()
		self.setup_strategy_tab()
		self.tabs.addTab(self.tab_strategy, "📋 전략 코드 검증")
		
		# 3. 거래 내역 탭
		self.table_history = QTableWidget()
		self.table_history.setColumnCount(8)
		self.table_history.setHorizontalHeaderLabels(["종목코드", "종목명", "매수일", "매도일", "매수가", "매도가", "수익률(%)", "상태"])
		self.table_history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		self.tabs.addTab(self.table_history, "💼 거래 내역")
		
		# 4. 성과 요약 탭
		self.tab_summary = QWidget()
		self.setup_summary_tab()
		self.tabs.addTab(self.tab_summary, "📊 성과 요약")
		
		layout.addWidget(self.tabs)

	def setup_settings_tab(self):
		layout = QVBoxLayout(self.tab_settings)
		# 기존 BackTester의 설정 UI 로직 (생략/요약 구현)
		form_group = QGroupBox("시뮬레이션 기본 환경 설정")
		grid = QGridLayout(form_group)
		
		grid.addWidget(QLabel("시작날짜:"), 0, 0)
		self.date_start = QDateEdit(QDate.currentDate().addMonths(-3))
		grid.addWidget(self.date_start, 0, 1)
		
		grid.addWidget(QLabel("종료날짜:"), 0, 2)
		self.date_end = QDateEdit(QDate.currentDate())
		grid.addWidget(self.date_end, 0, 3)
		
		grid.addWidget(QLabel("초기자본:"), 1, 0)
		self.spin_deposit = QSpinBox()
		self.spin_deposit.setRange(1000000, 1000000000)
		self.spin_deposit.setValue(10000000)
		grid.addWidget(self.spin_deposit, 1, 1)
		
		layout.addWidget(form_group)
		layout.addStretch()

	def setup_summary_tab(self):
		layout = QVBoxLayout(self.tab_summary)
		title = QLabel("종합 백테스트 리포트")
		title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00E5FF;")
		layout.addWidget(title)
		
		# 차트 및 지표 카드 공간 (나중에 matplotlib 연동)
		self.summary_label = QLabel("백테스트를 완료하면 상세 보고서가 여기에 나타납니다.")
		self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		layout.addWidget(self.summary_label)
		layout.addStretch()
