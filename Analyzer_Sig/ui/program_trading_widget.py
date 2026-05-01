import sys
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
							 QTableWidget, QTableWidgetItem, QHeaderView, 
							 QAbstractItemView, QFrame, QMainWindow, QApplication)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

class ProgramTradingWidget(QWidget):
	"""
	프로그램 매매 순매수 상위 50 (ka90003) 위젯
	코스피/코스닥 두 개의 테이블을 제공합니다.
	"""
	def __init__(self, parent=None):
		super().__init__(parent)
		self.init_ui()

	def init_ui(self):
		main_layout = QVBoxLayout(self)
		main_layout.setContentsMargins(10, 10, 10, 10)
		main_layout.setSpacing(10)
		
		# Market Trend Area (ka90007)
		self.trend_frame = QFrame()
		self.trend_frame.setStyleSheet("background-color: #1E1E1E; border-radius: 6px; border: 1px solid #333;")
		self.trend_frame.setFixedHeight(60)
		trend_layout = QHBoxLayout(self.trend_frame)
		
		self.lbl_trend_title = QLabel("📊 시장 프로그램 누적 추이:")
		self.lbl_trend_title.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 13px;")
		trend_layout.addWidget(self.lbl_trend_title)
		
		self.lbl_kospi_trend = QLabel("KOSPI: -")
		self.lbl_kospi_trend.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
		trend_layout.addWidget(self.lbl_kospi_trend)
		
		self.lbl_kosdaq_trend = QLabel("KOSDAQ: -")
		self.lbl_kosdaq_trend.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
		trend_layout.addWidget(self.lbl_kosdaq_trend)
		
		trend_layout.addStretch()
		main_layout.addWidget(self.trend_frame)
		
		# Tables Layout
		tables_layout = QHBoxLayout()
		tables_layout.setSpacing(15)
		
		def create_prm_table(titleText):
			container = QWidget()
			container.setStyleSheet("background-color: #2D2D2D; border-radius: 6px;")
			l = QVBoxLayout(container)
			l.setContentsMargins(5, 5, 5, 5)
			
			title = QLabel(titleText)
			title.setAlignment(Qt.AlignmentFlag.AlignCenter)
			title.setStyleSheet("color: #FFD700; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
			l.addWidget(title)
			
			table = QTableWidget()
			table.setColumnCount(5)
			table.setHorizontalHeaderLabels(["순위", "종목명", "현재가", "등락률", "순매수액"])
			
			# Header Resize Modes
			header = table.horizontalHeader()
			header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
			table.setColumnWidth(0, 40)
			header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
			header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
			header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
			header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
			
			table.verticalHeader().setVisible(False)
			table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
			table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
			table.setStyleSheet("""
				QTableWidget { background-color: #1E1E1E; gridline-color: #333; border: 0; }
				QHeaderView::section { background-color: #2D2D2D; color: white; border: 1px solid #333; padding: 2px; font-weight: bold; }
				QTableWidget::item { padding: 4px; font-size: 12px; }
			""")
			l.addWidget(table)
			
			# [안실장 픽스] 더블 클릭 시 HTS 차트 연동
			table.cellDoubleClicked.connect(self.on_cell_double_clicked)
			
			return container, table

		self.cont_kospi, self.table_kospi = create_prm_table("🟦 KOSPI 프로그램 순매수 Top 50")
		self.cont_kosdaq, self.table_kosdaq = create_prm_table("🟥 KOSDAQ 프로그램 순매수 Top 50")
		
		tables_layout.addWidget(self.cont_kospi)
		tables_layout.addWidget(self.cont_kosdaq)
		
		main_layout.addLayout(tables_layout)

	def update_data(self, data):
		"""
		data: {
			"kospi_prm": [...],
			"kosdaq_prm": [...],
			"market_prm_trend": {"kospi": "...", "kosdaq": "..."}
		}
		"""
		if not data: return
		
		# Update Trend Labels
		trend = data.get("market_prm_trend", {})

		def _fmt(val):
			if not val or val == '-': return '-'
			# 키움 API 특유의 '--' 기호를 '-'로 보정
			s_val = str(val).replace('--', '-').replace('+', '').strip()
			
			# 숫자만 추출하여 콤마 포맷팅 시도
			import re
			match = re.search(r'(-?\d+\.?\d*)', s_val.replace(',', ''))
			if match:
				try:
					num_str = match.group(1)
					num = int(float(num_str))
					formatted_num = f"{num:,}"
					return s_val.replace(num_str, formatted_num).replace(',', ',') # 콤마 중복 방지
				except:
					pass
			return s_val

		self.lbl_kospi_trend.setText(f"KOSPI: {_fmt(trend.get('kospi', '-'))}")
		self.lbl_kosdaq_trend.setText(f"KOSDAQ: {_fmt(trend.get('kosdaq', '-'))}")
		
		# Fill Tables
		self._fill_table(self.table_kospi, data.get("kospi_prm", []))
		self._fill_table(self.table_kosdaq, data.get("kosdaq_prm", []))

	def _fill_table(self, table, items):
		table.setRowCount(0)
		if not items: return
		
		def parse_kw_num(s):
			if not s: return 0
			clean = str(s).replace(',', '').replace('%', '').replace('--', '-').replace('+', '').strip()
			try: return float(clean)
			except: return 0

		for i, item in enumerate(items[:50]):
			table.insertRow(i)
			
			# Rank
			rank_item = QTableWidgetItem(str(item.get('rank', i+1)))
			rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
			table.setItem(i, 0, rank_item)
			
			name_item = QTableWidgetItem(item.get('stk_nm', '-'))
			name_item.setForeground(Qt.GlobalColor.white)
			
			# [안실장 픽스] HTS 연동을 위한 메타데이터 저장
			code = item.get('stk_cd', '')
			if code:
				name_item.setData(Qt.ItemDataRole.UserRole, str(code))
				
			table.setItem(i, 1, name_item)
			
			# Price
			price_raw = item.get('cur_prc', '0')
			price_val = int(parse_kw_num(price_raw))
			price_item = QTableWidgetItem(f"{price_val:,}" if price_val != 0 else price_raw)
			price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			table.setItem(i, 2, price_item)
			
			# Rate
			rate_raw = item.get('flu_rt', '0')
			rate = parse_kw_num(rate_raw)
			rate_item = QTableWidgetItem(f"{rate:+.2f}")
			rate_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			color = "#FF5252" if rate > 0 else "#448AFF" if rate < 0 else "white"
			rate_item.setForeground(QColor(color))
			table.setItem(i, 3, rate_item)
			
			# Net Amt (Program Net Purchase)
			amt_raw = item.get('prm_netprps_amt', '0')
			amt_val = int(parse_kw_num(amt_raw))
			
			amt_item = QTableWidgetItem(f"{amt_val:,}")
			amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			
			if amt_val > 0:
				amt_item.setForeground(Qt.GlobalColor.yellow)
			elif amt_val < 0:
				amt_item.setForeground(QColor("#00E5FF"))
			else:
				amt_item.setForeground(Qt.GlobalColor.gray)
				
			table.setItem(i, 4, amt_item)

	def on_cell_double_clicked(self, row, col):
		"""더블 클릭 시 HTS 연동 (어느 열이든 해당 행의 코드 추출)"""
		table = self.sender()
		if not table: return
		for c in range(table.columnCount()):
			item = table.item(row, c)
			if item:
				code = item.data(Qt.ItemDataRole.UserRole)
				if code:
					try:
						from shared.hts_connector import send_to_hts
						send_to_hts(str(code))
						break
					except: pass

class ProgramTradingWindow(QMainWindow):
	"""독립 실행용 프로그램 매매 창"""
	def __init__(self, analyzer=None):
		super().__init__()
		self.setWindowTitle("Lead_Sig: 프로그램 수급 (Independent)")
		self.resize(1200, 700)
		self.setStyleSheet("background-color: #121212; color: white;")
		
		from core.market_engine import MarketEngine
		from core.threads import DataThread
		
		self.analyzer = analyzer or MarketEngine(mode="REAL")
		
		central = QWidget()
		self.setCentralWidget(central)
		layout = QVBoxLayout(central)
		
		header = QHBoxLayout()
		title = QLabel("📊 프로그램 수급 상위 (Top 50)")
		title.setStyleSheet("font-size: 20px; font-weight: bold; color: #00E5FF;")
		header.addWidget(title)
		header.addStretch()
		self.status_lbl = QLabel("대기 중...")
		header.addWidget(self.status_lbl)
		layout.addLayout(header)
		
		self.widget = ProgramTradingWidget()
		layout.addWidget(self.widget)
		
		self.data_thread = None
		self.timer = QTimer()
		self.timer.timeout.connect(self.request_update)
		
		self.status_lbl.setText("준비 완료")
		self.request_update()
		self.timer.start(10000)

	def request_update(self):
		if self.data_thread and self.data_thread.isRunning(): return
		from core.threads import DataThread
		self.data_thread = DataThread(self.analyzer)
		self.data_thread.data_ready.connect(self.on_data_received)
		self.data_thread.start()

	def on_data_received(self, data):
		import time
		if "program_trading" in data:
			self.widget.update_data(data["program_trading"])
		self.status_lbl.setText(f"최근 업데이트: {time.strftime('%H:%M:%S')}")

if __name__ == "__main__":
	import sys
	from core.market_engine import MarketEngine
	from PyQt6.QtCore import QTimer
	from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout
	
	app = QApplication(sys.argv)
	win = ProgramTradingWindow()
	win.show()
	sys.exit(app.exec())
