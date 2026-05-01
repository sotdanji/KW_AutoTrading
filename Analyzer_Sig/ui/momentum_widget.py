import sys
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
							 QTableWidget, QTableWidgetItem, QHeaderView, 
							 QAbstractItemView, QApplication, QMainWindow)
from PyQt6.QtCore import Qt

# Add project root to sys.path if needed
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
	sys.path.insert(0, project_root)

class Momentum10MinWidget(QWidget):
	"""
	10분 등락률 (10Min Momentum) 위젯
	4개의 테이블(거래량/거래대금 과거/현재)를 표시합니다.
	"""
	def __init__(self, parent=None):
		super().__init__(parent)
		self.init_ui()

	def init_ui(self):
		main_layout = QHBoxLayout(self)
		main_layout.setContentsMargins(10, 10, 10, 10)
		main_layout.setSpacing(10)
		
		# Helper: Create momentum table panel
		def create_momentum_table(titleText):
			container = QWidget()
			container.setStyleSheet("background-color: #2D2D2D; border-radius: 6px;")
			l = QVBoxLayout(container)
			l.setContentsMargins(5, 5, 5, 5)
			
			title = QLabel(titleText)
			title.setAlignment(Qt.AlignmentFlag.AlignCenter)
			title.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
			l.addWidget(title)
			
			table = QTableWidget()
			table.setColumnCount(4)
			table.setHorizontalHeaderLabels(["No.", "종목명", "현재가", "등락률"])
			table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
			table.setColumnWidth(0, 35) # Rank
			table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) # Name
			table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Price
			table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Change
			table.verticalHeader().setVisible(False)
			table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
			table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
			table.setStyleSheet("""
				QTableWidget { background-color: #1E1E1E; gridline-color: #333; border: 0; }
				QHeaderView::section { background-color: #2D2D2D; color: white; border: 1px solid #333; padding: 2px; font-weight: bold; }
				QTableWidget::item { padding: 2px; font-size: 12px; }
			""")
			l.addWidget(table)
			
			# [안실장 픽스] 더블 클릭 시 HTS 차트 연동
			table.cellDoubleClicked.connect(self.on_cell_double_clicked)
			
			return container, table

		# 4개의 테이블 생성
		container1, self.table_past_vol = create_momentum_table("10분전 거래량 Top")
		container2, self.table_curr_vol = create_momentum_table("현재 거래량 Top")
		container3, self.table_past_val = create_momentum_table("10분전 거래대금 Top")
		container4, self.table_curr_val = create_momentum_table("현재 거래대금 Top")
		
		main_layout.addWidget(container1, 1)
		main_layout.addWidget(container2, 1)
		main_layout.addWidget(container3, 1)
		main_layout.addWidget(container4, 1)


	def update_data(self, m_data):
		if not m_data:
			return
		
		# [Fix] 데이터가 이전과 동일할 경우 UI 재갱신 방지
		if hasattr(self, "_last_m_data") and self._last_m_data == m_data:
			return
		
		self._last_m_data = m_data
		past_vol = m_data.get("past_vol", [])
		curr_vol = m_data.get("curr_vol", [])
		past_val = m_data.get("past_val", [])
		curr_val = m_data.get("curr_val", [])
		
		# Fill tables with comparison
		self._fill_momentum_table(self.table_past_vol, past_vol, compare_items=curr_vol, is_curr=False)
		self._fill_momentum_table(self.table_curr_vol, curr_vol, compare_items=past_vol, is_curr=True)
		self._fill_momentum_table(self.table_past_val, past_val, compare_items=curr_val, is_curr=False)
		self._fill_momentum_table(self.table_curr_val, curr_val, compare_items=past_val, is_curr=True)

	def _fill_momentum_table(self, table, items, compare_items=None, is_curr=True):
		table.setRowCount(0)
		
		compare_map = {}
		if compare_items:
			for idx, item in enumerate(compare_items):
				compare_map[item.get('name')] = idx
				
		for i, row_data in enumerate(items):
			table.insertRow(i)
			stock_name = str(row_data.get("name", ""))
			
			bg_color = "#333" # Default Rank BG
			txt_color = "white"
			
			if compare_items:
				if is_curr: # 현재 리스트 기준
					if stock_name not in compare_map:
						bg_color = "#D32F2F" # 신규 진입 (Red)
					else:
						past_idx = compare_map[stock_name]
						if i < past_idx: # 순위 상승
							bg_color = "#FFD700"; txt_color = "black"
						elif i > past_idx: # 순위 하락
							bg_color = "#2E7D32" # (Green)
				else: # 10분전 리스트 기준
					if stock_name not in compare_map:
						bg_color = "#1565C0" # 이탈 (Blue)
			
			# Rank
			lbl_rank = QLabel(f"{i+1}")
			lbl_rank.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
			lbl_rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
			lbl_rank.setStyleSheet(f"background-color: {bg_color}; color: {txt_color}; border-radius: 2px; font-weight: bold;")
			table.setCellWidget(i, 0, lbl_rank)
			
			# Name Widget
			name_widget = QWidget()
			name_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
			name_layout = QHBoxLayout(name_widget)
			name_layout.setContentsMargins(2, 0, 2, 0)
			name_layout.setSpacing(2)
			lbl_name = QLabel(stock_name); lbl_name.setStyleSheet("color: white;")
			name_layout.addWidget(lbl_name)
			
			if row_data.get("foreign_net", 0) > 0:
				lbl_f = QLabel("외"); lbl_f.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
				name_layout.addWidget(lbl_f)
			if row_data.get("inst_net", 0) > 0:
				lbl_i = QLabel("기"); lbl_i.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
				name_layout.addWidget(lbl_i)
				
			name_layout.addStretch()
			table.setCellWidget(i, 1, name_widget)
			
			# Price
			item_price = QTableWidgetItem(f"{row_data.get('price', 0):,}")
			item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			
			# [안실장 픽스] HTS 연동을 위한 메타데이터 저장
			code = row_data.get('code', '')
			if code:
				item_price.setData(Qt.ItemDataRole.UserRole, str(code))
				
			table.setItem(i, 2, item_price)
			
			# Rate
			rate_val = row_data.get("change", 0.0)
			lbl_rate = QLabel(f"{rate_val:.2f}")
			lbl_rate.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
			lbl_rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			color = "#FF5252" if rate_val > 0 else "#448AFF" if rate_val < 0 else "white"
			lbl_rate.setStyleSheet(f"color: {color}; font-weight: bold;")
			table.setCellWidget(i, 3, lbl_rate)

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

class MomentumWindow(QMainWindow):
	"""독립 실행용 10분 등락률 창"""
	def __init__(self, analyzer=None):
		super().__init__()
		self.setWindowTitle("Lead_Sig: 10분 등락률 (Independent)")
		self.resize(1100, 600)
		self.setStyleSheet("background-color: #121212; color: white;")
		
		from core.market_engine import MarketEngine
		from core.threads import DataThread
		
		self.analyzer = analyzer or MarketEngine(mode="REAL")
		
		central = QWidget()
		self.setCentralWidget(central)
		layout = QVBoxLayout(central)
		
		header = QHBoxLayout()
		title = QLabel("⏱️ 10분 등락률 (10Min Momentum)")
		title.setStyleSheet("font-size: 20px; font-weight: bold; color: #00E5FF;")
		header.addWidget(title)
		header.addStretch()
		self.status_lbl = QLabel("대기 중...")
		header.addWidget(self.status_lbl)
		layout.addLayout(header)
		
		self.widget = Momentum10MinWidget()
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
		if "momentum_10min" in data:
			self.widget.update_data(data["momentum_10min"])
		self.status_lbl.setText(f"최근 업데이트: {time.strftime('%H:%M:%S')}")

if __name__ == "__main__":
	import sys
	from core.market_engine import MarketEngine
	from PyQt6.QtCore import QTimer
	from PyQt6.QtWidgets import QApplication, QMainWindow
	
	app = QApplication(sys.argv)
	win = MomentumWindow()
	win.show()
	sys.exit(app.exec())
