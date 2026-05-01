# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
							 QPushButton, QTextEdit, QGroupBox, QFormLayout, 
							 QDoubleSpinBox, QSpinBox, QSplitter, QFrame)
from PyQt6.QtCore import Qt

# Matplotlib 연동
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class ValidationTab(QWidget):
	"""
	전략 연구소 위젯 (전략 검증 메인 영역)
	"""
	def __init__(self):
		super().__init__()
		self.init_ui()

	def init_ui(self):
		layout = QHBoxLayout(self)
		layout.setContentsMargins(10, 10, 10, 10)
		
		splitter = QSplitter(Qt.Orientation.Horizontal)
		
		# --- 좌측: 전략 설정 및 에디터 ---
		left_panel = QFrame()
		left_layout = QVBoxLayout(left_panel)
		
		# 1. 시뮬레이션 설정
		settings_group = QGroupBox("🧪 백테스트 설정")
		form = QFormLayout(settings_group)
		self.spin_tp = QDoubleSpinBox(); self.spin_tp.setValue(5.0); form.addRow("익절", self.spin_tp)
		self.spin_sl = QDoubleSpinBox(); self.spin_sl.setValue(3.0); form.addRow("손절", self.spin_sl)
		self.spin_deposit = QSpinBox(); self.spin_deposit.setRange(100, 100000); self.spin_deposit.setValue(1000); self.spin_deposit.setSuffix(" 만원")
		form.addRow("초기자금", self.spin_deposit)
		left_layout.addWidget(settings_group)
		
		# 2. 전략 코드 에디터
		editor_group = QGroupBox("📋 전략 스크립트 (Python)")
		editor_layout = QVBoxLayout(editor_group)
		self.code_editor = QTextEdit()
		self.code_editor.setPlaceholderText("# 여기에 매수/매도 로직을 작성하세요...")
		self.code_editor.setStyleSheet("font-family: 'Consolas'; background-color: #1e1e1e; color: #d4d4d4;")
		editor_layout.addWidget(self.code_editor)
		left_layout.addWidget(editor_group)
		
		splitter.addWidget(left_panel)
		
		# --- 우측: 성과 그래프 및 요약 ---
		right_panel = QFrame()
		right_layout = QVBoxLayout(right_panel)
		
		# Chart Area
		chart_group = QGroupBox("📊 수익률 곡선 (Equity Curve)")
		chart_vbox = QVBoxLayout(chart_group)
		self.fig = Figure(facecolor='#1e1e1e')
		self.canvas = FigureCanvas(self.fig)
		self.ax = self.fig.add_subplot(111)
		self.ax.set_facecolor('#1e1e1e')
		self.ax.tick_params(colors='white')
		chart_vbox.addWidget(self.canvas)
		right_layout.addWidget(chart_group)
		
		# Summary Metrics
		metrics_layout = QHBoxLayout()
		self.lbl_total_return = QLabel("총 수익률: 0.0"); self.lbl_total_return.setStyleSheet("font-size: 16px; font-weight: bold; color: #00cc66;")
		self.lbl_win_rate = QLabel("승률: 0.0"); self.lbl_win_rate.setStyleSheet("font-size: 16px; font-weight: bold; color: #00aaff;")
		metrics_layout.addWidget(self.lbl_total_return)
		metrics_layout.addWidget(self.lbl_win_rate)
		right_layout.addLayout(metrics_layout)
		
		splitter.addWidget(right_panel)
		splitter.setStretchFactor(0, 4)
		splitter.setStretchFactor(1, 6)
		
		layout.addWidget(splitter)
