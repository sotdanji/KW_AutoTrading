import sys
import os
import time
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
							 QLabel, QPushButton, QFrame, QTextEdit, 
							 QTableWidget, QTableWidgetItem, QHeaderView, 
							 QMessageBox, QApplication, QMainWindow)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QTextCursor

# Add project root to sys.path if needed
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
	sys.path.insert(0, project_root)

from shared.db_manager import DBManager
from core.integrator import AT_SigIntegrator
from core.logger import get_logger

logger = get_logger(__name__)

class LeadingThemeWidget(QWidget):
	"""
	실시간 주도테마 위젯
	8개의 테마 패널을 표시합니다. (로그창 제거됨)
	"""
	def __init__(self, db_manager=None, integrator=None, parent=None):
		super().__init__(parent)
		self.db_manager = db_manager or DBManager()
		self.integrator = integrator or AT_SigIntegrator()
		self.auto_panels = []
		self.init_ui()

	def init_ui(self):
		main_layout = QVBoxLayout(self)
		main_layout.setContentsMargins(5, 5, 5, 5)
		main_layout.setSpacing(10)
		
		# === 1. Upper Area (8 Theme Panels, 4x2 Grid) ===
		upper_area = QWidget()
		upper_layout = QVBoxLayout(upper_area)
		upper_layout.setContentsMargins(0, 0, 0, 0)
		upper_layout.setSpacing(5)
		
		grid_layout = QGridLayout()
		grid_layout.setSpacing(5)
		
		self.auto_panels = []
		for i in range(8):
			if i < 4:
				rank_text = f"수급 {i + 1}위"
			elif i < 6:
				rank_text = f"급등 {i - 3}위"
			elif i == 6:
				rank_text = "거래대금"
			else:
				rank_text = "거래량"
				
			panel = self.create_auto_monitor_panel(rank_text)
			row = i // 4
			col = i % 4
			grid_layout.addWidget(panel, row, col)
			self.auto_panels.append(panel)
			
		upper_layout.addLayout(grid_layout)
		main_layout.addWidget(upper_area) # 이제 전체 영역 차지

	def create_auto_monitor_panel(self, rank_text):
		frame = QFrame()
		frame.setStyleSheet("background-color: #2D2D2D; border: 1px solid #444; border-radius: 6px;")
		layout = QVBoxLayout(frame)
		layout.setContentsMargins(5, 5, 5, 5)
		layout.setSpacing(2)
		
		header = QHBoxLayout()
		rank_lbl = QLabel(rank_text)
		rank_lbl.setFixedSize(55, 20)
		rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
		rank_lbl.setStyleSheet("background-color: #FFD700; color: black; border-radius: 3px; font-weight: bold; font-size: 11px;")
		
		name_lbl = QLabel("-")
		name_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 13px; margin-left: 5px;")
		
		change_lbl = QLabel("-")
		change_lbl.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 12px;")
		
		btn_db = QPushButton("💾")
		btn_db.setFixedSize(24, 20)
		btn_db.setToolTip("DB 저장")
		btn_db.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_db.setStyleSheet("background-color: #333; color: white; border-radius: 3px; font-size: 11px;")
		
		btn_at = QPushButton("⚡")
		btn_at.setFixedSize(24, 20)
		btn_at.setToolTip("AT_Sig 감시")
		btn_at.setCursor(Qt.CursorShape.PointingHandCursor)
		btn_at.setStyleSheet("background-color: #444; color: #00E5FF; border-radius: 3px; font-size: 11px; font-weight: bold;")
		
		btn_db.clicked.connect(lambda _, p=frame: self.add_batch_from_panel(p, "db"))
		btn_at.clicked.connect(lambda _, p=frame: self.add_batch_from_panel(p, "atsig"))
		
		header.addWidget(rank_lbl)
		header.addWidget(name_lbl)
		header.addStretch()
		header.addWidget(change_lbl)
		header.addWidget(btn_db)
		header.addWidget(btn_at)
		layout.addLayout(header)
		
		table = QTableWidget()
		table.setColumnCount(4)
		table.setHorizontalHeaderLabels(["신호", "종목명", "현재가", "등락률"])
		table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
		table.setColumnWidth(0, 30)
		table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
		table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
		table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
		table.setColumnWidth(3, 50)
		
		table.verticalHeader().setVisible(False)
		table.verticalHeader().setDefaultSectionSize(20)
		table.setStyleSheet("""
			QTableWidget { background-color: #1E1E1E; gridline-color: #2D2D2D; border: 0; outline: none; }
			QHeaderView::section { background-color: #252526; color: #BBB; padding: 1px; border: 0; font-size: 10px; font-weight: bold; }
			QTableWidget::item { padding: 0px 2px; font-size: 11px; }
		""")
		table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
		table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
		
		# [안실장 픽스] 더블 클릭 시 HTS 차트 연동
		table.cellDoubleClicked.connect(self.on_cell_double_clicked)
		
		layout.addWidget(table)
		frame.widgets = {"name": name_lbl, "change": change_lbl, "table": table}
		return frame

	def update_auto_panels(self, top8_data):
		if not top8_data:
			return

		for i, panel in enumerate(self.auto_panels):
			if i >= len(top8_data):
				panel.widgets["name"].setText("-")
				panel.widgets["change"].setText("-")
				panel.widgets["table"].setRowCount(0)
				continue
				
			data = top8_data[i]
			panel.widgets["name"].setText(data['name'])
			
			rate = data['change']
			color = "#FF5252" if rate > 0 else "#448AFF" if rate < 0 else "white"
			sign = "+" if rate > 0 else ""
			panel.widgets["change"].setText(f"{sign}{rate:.2f}")
			panel.widgets["change"].setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")
			
			stocks = data.get('stocks', [])
			if stocks is None: stocks = []
			panel.current_stocks = stocks
			panel.current_theme_name = data['name']
			
			table = panel.widgets["table"]
			table.setRowCount(0)
			
			limit = 12 if i >= 6 else 10
			for row_idx, stock in enumerate(stocks[:limit]):
				table.insertRow(row_idx)
				
				# Signal Logic
				sig_type = stock.get('signal_type')
				role = stock.get('role', 'sleeper')
				lbl_sig = QLabel()
				lbl_sig.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
				lbl_sig.setAlignment(Qt.AlignmentFlag.AlignCenter)
				if sig_type == "king": lbl_sig.setText("👑")
				elif sig_type == "breakout": lbl_sig.setText("🔴") 
				elif sig_type == "close": lbl_sig.setText("🔵")
				else:
					if role == 'leader_overheat': lbl_sig.setText("🔥")
					elif role == 'leader': lbl_sig.setText("🚀")
					elif role == 'target': lbl_sig.setText("🎯")
					else: lbl_sig.setText("·")
				table.setCellWidget(row_idx, 0, lbl_sig)

				# Name Widget
				name_widget = QWidget()
				name_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
				name_layout = QHBoxLayout(name_widget)
				name_layout.setContentsMargins(2, 0, 2, 0)
				name_layout.setSpacing(2)
				lbl_name = QLabel(stock['name'])
				lbl_name.setStyleSheet("color: white; font-size: 11px;")
				name_layout.addWidget(lbl_name)
				
				if role != 'sleeper':
				   role_name = stock.get('role_name', '대기')
				   lbl_role = QLabel(role_name[:2])
				   r_style = "font-size: 8px; border-radius: 2px; padding: 0px 2px; font-weight: bold; color: white;"
				   if role == 'leader_overheat': r_style += "background-color: #D32F2F;"
				   elif role == 'leader': r_style += "background-color: #E64A19;"
				   elif role == 'target': r_style += "background-color: #2E7D32;"
				   lbl_role.setStyleSheet(r_style)
				   name_layout.addWidget(lbl_role)
				name_layout.addStretch()
				table.setCellWidget(row_idx, 1, name_widget)
				
				# Price
				item_price = QTableWidgetItem(f"{stock['price']:,}")
				item_price.setForeground(QColor("white"))
				item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
				
				# [안실장 픽스] HTS 연동을 위한 메타데이터 저장
				item_price.setData(Qt.ItemDataRole.UserRole, stock['code'])
				
				table.setItem(row_idx, 2, item_price)
				
				# Rate
				s_rate = stock['change']
				lbl_rate = QLabel(f"{s_rate:+.2f}")
				lbl_rate.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
				lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
				lbl_rate.setFixedWidth(45)
				bg_col = "#CC3333" if role != 'target' else "#2E7D32" if s_rate > 0 else "#3333CC" if s_rate < 0 else "#1E1E1E"
				lbl_rate.setStyleSheet(f"background-color: {bg_col}; color: white; border-radius: 3px; font-weight: bold; font-size: 10px;")
				table.setCellWidget(row_idx, 3, lbl_rate)

				# Auto Save to Local DB
				if sig_type in ["king", "breakout", "close"] or role == 'target':
					self.db_manager.add_watched_stock(
						code=stock['code'],
						name=stock['name'],
						sector=data['name'], 
						price=stock['price'],
						signal_type=sig_type if sig_type else role
					)

				# [NEW] Auto Transfer to AT_Sig (주도/후발)
				if role in ['leader', 'leader_overheat', 'target']:
					# Calculate weight based on theme rank (i+1) and theme change rate
					weight = self._calculate_weight(i + 1, data['change'])
					stock_info = stock.copy()
					stock_info['weight'] = weight
					stock_info['sector'] = data['name']
					
					# add_to_watchlist internally handles duplicate check
					res = self.integrator.add_to_watchlist(stock_info)
					# Only log for fresh additions
					if res is True:
						self.append_log(f"⚡ [자동전송] {stock['name']}({stock['code']}) -> AT_Sig (가중치:{weight})")

	def on_cell_double_clicked(self, row, col):
		"""테이블 더블 클릭 시 HTS 연동 (어느 열이든 해당 행의 코드 추출)"""
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

	def append_log(self, text):
		"""통합 로그 탭으로 메시지 위임"""
		logger.info(f"[Theme] {text}")

	def _calculate_weight(self, rank, rate):
		"""
		가중치 계산 로직 (V3)
		- 1위: 기본 5, 등락 10% 이상시 +2
		- 2위: 기본 3, 등락 8% 이상시 +1
		- 그 외: 기본 2
		"""
		base = 2
		if rank == 1:
			base = 5
			if rate >= 10: base += 2
		elif rank == 2:
			base = 3
			if rate >= 8: base += 1
		return base

	def add_batch_from_panel(self, panel, target="db"):
		stocks = getattr(panel, 'current_stocks', [])
		theme_name = getattr(panel, 'current_theme_name', 'Unknown')
		if not stocks:
			QMessageBox.warning(self, "알림", "패널에 추가할 종목 리스트가 없습니다.")
			return

		cnt = min(len(stocks), 10)
		if target == "atsig":
			msg = f"[{theme_name}] 테마 상위 {cnt}개 종목을 모두\n[⚡ AT_Sig 자동매매 감시 리스트]에 추가하시겠습니까?\n\n* 순위/등락률에 따라 매수 비중이 자동 조절됩니다."
		else:
			msg = f"[{theme_name}] 테마 상위 {cnt}개 종목을 모두\n[💾 로컬 관심 DB]에만 저장하시겠습니까?"

		reply = QMessageBox.question(self, '일괄 추가', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
		if reply == QMessageBox.StandardButton.Yes:
			added_cnt = 0
			dup_cnt = 0
			for i in range(cnt):
				stock = stocks[i]
				stock['sector'] = theme_name
				
				# 1. DB Save
				self.db_manager.add_watched_stock(stock['code'], stock['name'], theme_name, stock['price'], stock.get('signal_type'))
				
				# 2. AT_Sig Add
				if target == "atsig":
					rank = i + 1
					rate = stock.get('change', 0)
					weight = self._calculate_weight(rank, rate)
					
					stock_with_weight = stock.copy()
					stock_with_weight['weight'] = weight
					
					res = self.integrator.add_to_watchlist(stock_with_weight)
					if res is True: added_cnt += 1
					elif res == 'duplicate': dup_cnt += 1
				else:
					added_cnt += 1
			QMessageBox.information(self, "결과", f"추가 완료: {added_cnt}건 (중복 {dup_cnt}건)")

class LeadingThemeWindow(QMainWindow):
	"""독립 실행용 주도테마 창"""
	def __init__(self, analyzer=None):
		super().__init__()
		self.setWindowTitle("Lead_Sig: 실시간 주도테마 (Independent)")
		self.resize(1100, 750)
		self.setStyleSheet("background-color: #121212; color: white;")
		
		from core.market_engine import MarketEngine
		from core.threads import StartupThread, DataThread, QThandler
		
		self.analyzer = analyzer or MarketEngine(mode="REAL")
		self.db_manager = DBManager()
		self.integrator = AT_SigIntegrator()
		
		central = QWidget()
		self.setCentralWidget(central)
		layout = QVBoxLayout(central)
		
		header = QHBoxLayout()
		title_lbl = QLabel("🔥 실시간 주도테마 (Top 8)")
		title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #00E5FF;")
		header.addWidget(title_lbl)
		header.addStretch()
		self.status_lbl = QLabel("초기화 중...")
		header.addWidget(self.status_lbl)
		layout.addLayout(header)
		
		self.widget = LeadingThemeWidget(self.db_manager, self.integrator)
		layout.addWidget(self.widget)
		
		self.timer = QTimer()
		self.timer.timeout.connect(self.request_update)
		self.data_thread = None
		
		self.startup = StartupThread(self.analyzer, self.db_manager)
		self.startup.status_signal.connect(self.status_lbl.setText)
		self.startup.finished_signal.connect(self.on_startup_done)
		self.startup.start()
		
		# 독립 실행 시에도 통합 로깅 사용 가능하도록 지원
		self.handler = QThandler(lambda msg: None) # 묵음 처리 혹은 터미널 출력
		logging.getLogger().addHandler(self.handler)

	def on_startup_done(self, success):
		if success:
			self.status_lbl.setText("준비 완료")
			self.request_update()
			self.timer.start(10000)
		else:
			self.status_lbl.setText("초기화 실패")

	def request_update(self):
		if self.data_thread and self.data_thread.isRunning(): return
		from core.threads import DataThread
		self.data_thread = DataThread(self.analyzer)
		self.data_thread.data_ready.connect(self.on_data_received)
		self.data_thread.start()

	def on_data_received(self, data):
		if "top8_themes_data" in data:
			self.widget.update_auto_panels(data["top8_themes_data"])
		if "system_alerts" in data:
			for msg in data["system_alerts"]:
				logging.info(f"[Alert] {msg}")
		self.status_lbl.setText(f"최근 업데이트: {time.strftime('%H:%M:%S')}")

	def closeEvent(self, event):
		if hasattr(self, 'handler'):
			logging.getLogger().removeHandler(self.handler)
		event.accept()

if __name__ == "__main__":
	from PyQt6.QtWidgets import QApplication
	from core.market_engine import MarketEngine
	from PyQt6.QtCore import QTimer
	import logging
	
	app = QApplication(sys.argv)
	win = LeadingThemeWindow()
	win.show()
	sys.exit(app.exec())
