from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, 
							 QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class SignalHistoryDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("🚨 시그널 히스토리")
		self.setFixedSize(500, 600)
		self.setStyleSheet("""
			QDialog { background-color: #2D2D2D; color: white; border: 1px solid #555; }
			QLabel { color: #DDD; font-size: 14px; font-weight: bold; }
		""")
		self.init_ui()
		
	def init_ui(self):
		layout = QVBoxLayout(self)
		layout.setContentsMargins(15, 15, 15, 15)
		layout.setSpacing(10)
		
		# Title
		title = QLabel("🔥 당일 급등 및 낙수효과 시그널 내역")
		title.setStyleSheet("font-size: 16px; color: #FF5252; margin-bottom: 5px;")
		title.setAlignment(Qt.AlignmentFlag.AlignCenter)
		layout.addWidget(title)
		
		# Table
		self.table = QTableWidget()
		self.table.setColumnCount(2)
		self.table.setHorizontalHeaderLabels(["시간", "시그널 내용"])
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
		self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
		self.table.verticalHeader().setVisible(False)
		self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
		self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
		self.table.setStyleSheet("""
			QTableWidget { background-color: #1E1E1E; gridline-color: #333; border: 0; }
			QHeaderView::section { background-color: #2D2D2D; color: white; border: 1px solid #333; padding: 2px; font-weight: bold; }
			QTableWidget::item { padding: 4px; font-size: 12px; }
		""")
		layout.addWidget(self.table)
		
	def add_alerts(self, alerts, current_time):
		for alert_msg in alerts:
			row = self.table.rowCount()
			self.table.insertRow(row)
			
			item_time = QTableWidgetItem(current_time)
			item_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
			item_msg = QTableWidgetItem(alert_msg)
			
			if "초기폭발" in alert_msg:
				c = QColor("#FF5252")
			else:
				c = QColor("#00E5FF")
				
			item_time.setForeground(c)
			item_msg.setForeground(c)
			
			self.table.setItem(row, 0, item_time)
			self.table.setItem(row, 1, item_msg)
			self.table.scrollToBottom()
