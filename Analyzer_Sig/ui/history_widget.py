from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, 
							 QLabel, QPushButton, QHBoxLayout, QMessageBox, QMainWindow)
from PyQt6.QtCore import Qt, QTimer
import time
import datetime

class HistoryWidget(QWidget):
	def load_data(self, fetch_prices=False, recent_only=False):
		"""
		DB에서 데이터를 불러와 테이블을 갱신합니다.
		fetch_prices=True 일 경우 실시간 시세를 조회하여 수익률을 계산합니다.
		recent_only=True 일 경우 최근 3일(당일 포함) 종목에 한해 시세를 조회합니다.
		"""
		# 기존 진행 중인 업데이트 체인 차단
		self.current_update_id = getattr(self, 'current_update_id', 0) + 1
		this_update_id = self.current_update_id
		
		if not self.db_manager:
			return

		# 탭 컨벤션 준수 (MUST use Tabs)
		self.table.setUpdatesEnabled(False)
		self.table.blockSignals(True)
		
		# 결과를 멤버 변수에 저장 (Batch 처리를 위해)
		self.current_stocks = self.db_manager.get_active_stocks()
		print(f"[History] Loading {len(self.current_stocks)} active stocks from DB")
		
		self.table.setRowCount(0) # Clear Rows
		self.table.clearContents() # Clear All items
		self.table.setRowCount(len(self.current_stocks))
		
		# 1. 우선 DB 데이터로 테이블을 빠르게 구성 (가격은 '-'로 표시)
		for i, stock in enumerate(self.current_stocks):
			# 시간 포맷팅
			time_str = stock['found_at']
			code = stock['code']
			name = stock['name']
			sector = stock['sector']
			found_price = float(stock['found_price']) if stock['found_price'] else 0
			sig_type = stock.get('signal_type')
			
			# 신호 아이콘 매핑
			sig_icon = ""
			if sig_type == "king": sig_icon = "👑"
			elif sig_type == "breakout": sig_icon = "🔴"
			elif sig_type == "close": sig_icon = "🔵"
			
			# 0: Signal
			sig_item = QTableWidgetItem(sig_icon)
			sig_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
			self.table.setItem(i, 0, sig_item)
			
			self.table.setItem(i, 1, QTableWidgetItem(str(time_str)))
			self.table.setItem(i, 2, QTableWidgetItem(code))
			self.table.setItem(i, 3, QTableWidgetItem(name))
			self.table.setItem(i, 4, QTableWidgetItem(sector))
			
			# 5: Found Price
			found_price_fmt = f"{int(found_price):,}" if found_price > 100 else f"{found_price:.2f}"
			found_rate_item = QTableWidgetItem(found_price_fmt)
			found_rate_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			self.table.setItem(i, 5, found_rate_item)
			
			# 6: Current Price (Initial Placeholder)
			curr_str = "-"
			curr_price_item = QTableWidgetItem(curr_str)
			curr_price_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			self.table.setItem(i, 6, curr_price_item)
			
			# 7: Profit Rate (Initial Placeholder)
			profit_str = "-"
			profit_item = QTableWidgetItem(profit_str)
			profit_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
			self.table.setItem(i, 7, profit_item)
			
		self.table.blockSignals(False)
		self.table.setUpdatesEnabled(True)
		self.table.viewport().update()

		# 2. 시세 갱신 요청이 있는 경우, 5개씩 끊어서 업데이트 시작
		if fetch_prices and self.analyzer:
			# Batch 업데이트 개시
			self._update_price_batch(0, recent_only=recent_only, update_id=this_update_id)

	def _update_price_batch(self, start_idx, recent_only=False, update_id=0):
		"""
		5개씩 끊어서 시세를 조회하고 테이블을 갱신합니다.
		"""
		# 최신 업데이트 요청이 아니면 중단
		if update_id != self.current_update_id:
			return

		if not hasattr(self, 'current_stocks') or not self.current_stocks:
			return

		# 최근 3일 기준 날짜 계산 (YYYY-MM-DD)
		limit_date = (datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%Y-%m-%d") if recent_only else None

		batch_size = 5 # UI 블로킹 방지를 위해 배치 사이즈 축소 (22 -> 5)
		end_idx = min(start_idx + batch_size, len(self.current_stocks))
		
		# Batch Processing
		for i in range(start_idx, end_idx):
			stock = self.current_stocks[i]
			code = stock['code']
			found_price = float(stock['found_price']) if stock['found_price'] else 0
			found_at = stock['found_at'] # YYYY-MM-DD HH:MM:SS
			
			# 최근 3일 필터링 (최근 3일이 아니면 시세 조회 스킵)
			if recent_only and limit_date and found_at < limit_date:
				continue
				
			current_price = 0
			try:
				# 개별 시세 조회 (ka10005 사용)
				current_info = self.analyzer.fetcher._fetch_stock_quote(code)
				if current_info:
					# [FIX] '+' 기호가 포함된 가격 문자열 처리 (isdigit은 '+', '-'를 숫자로 인식 안 함)
					c_p = str(current_info.get('close_pric', '')).replace(',', '').strip()
					
					# 기호를 제거한 순수 숫자 부분 확인
					clean_cp = c_p.replace('+', '').replace('-', '')
					if clean_cp and clean_cp.isdigit():
						current_price = abs(int(c_p))
					
					if current_price == 0:
						print(f"[History] Price is 0 or missing for {code}. Data: {current_info}")
				else:
					print(f"[History] Failed to fetch quote for {code}")
				
				# 속도 제한 (메인 스레드이므로 아주 짧게 가져감)
				time.sleep(0.02)
				
			except Exception as e:
				print(f"[History Error] {code}: {e}")
			
			# UI Update (Row i)
			if current_price > 0:
				# 6: Current Price
				self.table.setItem(i, 6, QTableWidgetItem(f"{current_price:,.0f}"))
				self.table.item(i, 6).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
				
				# 7: Profit Rate
				profit_rate = 0
				if found_price > 0:
					profit_rate = ((current_price - found_price) / found_price) * 100
				
				# [Change] 가독성 개선: 상승만 삼각형, 하락은 마이너스(-)
				text = ""
				if profit_rate > 0:
					text = f"▲ {profit_rate:.2f}"
				else:
					# 0이거나 음수인 경우 표준 표기 (음수는 자동으로 - 붙음)
					text = f"{profit_rate:.2f}"
				
				profit_item = QTableWidgetItem(text)
				profit_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
				
				# 텍스트 색상을 흰색으로 고정
				profit_item.setForeground(Qt.GlobalColor.white)
				
				self.table.setItem(i, 7, profit_item)
				
		# Force redraw for this batch
		self.table.viewport().update()

		# Next Batch Scheduling
		if end_idx < len(self.current_stocks):
			# 다음 배치는 100ms 후에 실행 (UI 응답성 확보)
			QTimer.singleShot(100, lambda: self._update_price_batch(end_idx, recent_only=recent_only, update_id=update_id))

	def __init__(self, db_manager, analyzer, parent=None):
		super().__init__(parent)
		self.db_manager = db_manager
		self.analyzer = analyzer
		
		# [NEW] 자동 갱신 타이머 (1분)
		self.refresh_timer = QTimer(self)
		self.refresh_timer.timeout.connect(self._auto_refresh)
		
		self.layout = QVBoxLayout(self)
		self.layout.setContentsMargins(20, 20, 20, 20)
		
		# 헤더 (Title + Buttons)
		header_layout = QHBoxLayout()
		
		title = QLabel("🔍 추적 종목 관리 (Tracking Room)")
		title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00E5FF;")
		header_layout.addWidget(title)
		
		header_layout.addStretch()
		
		# 새로고침 버튼
		refresh_btn = QPushButton("🔄 새로고침 (시세 갱신)")
		refresh_btn.setFixedSize(140, 30)
		refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
		refresh_btn.setStyleSheet("""
			QPushButton { background-color: #333; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; }
			QPushButton:hover { background-color: #444; border-color: #00E5FF; }
		""")
		refresh_btn.clicked.connect(lambda: self.load_data(fetch_prices=True))
		header_layout.addWidget(refresh_btn)
		
		# 정리 버튼
		cleanup_btn = QPushButton("🗑️ 정리")
		cleanup_btn.setFixedSize(80, 30)
		cleanup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
		cleanup_btn.setStyleSheet("""
			QPushButton { background-color: #333; color: white; border: 1px solid #555; border-radius: 4px; font-weight: bold; margin-left: 10px; }
			QPushButton:hover { background-color: #552222; border-color: #FF4444; }
		""")
		cleanup_btn.clicked.connect(self.cleanup_data)
		header_layout.addWidget(cleanup_btn)
		
		self.layout.addLayout(header_layout)
		
		# 테이블
		self.table = QTableWidget()
		self.table.setColumnCount(8) 
		self.table.setHorizontalHeaderLabels(["신호", "시간", "종목코드", "종목명", "발굴 섹터", "포착가격", "현재가", "수익률"])
		self.table.setStyleSheet("""
			QTableWidget {
				background-color: #2D2D2D;
				gridline-color: #444;
				border: none;
				color: #EEE;
			}
			QHeaderView::section {
				background-color: #333;
				color: #DDD;
				padding: 6px;
				border: 1px solid #444;
				font-weight: bold;
			}
			QTableWidget::item {
				padding: 5px;
			}
			QTableWidget::item::selected {
				background-color: #3D3D3D;
			}
		""")
		self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		# 신호 컬럼은 작게 고정
		self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
		
		self.table.verticalHeader().setVisible(False)
		self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
		self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
		
		# [안실장 픽스] 더블 클릭 시 HTS 차트 연동
		self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
		
		self.layout.addWidget(self.table)
		
		# 초기 데이터 로드 (시세 미조회)
		self.load_data(fetch_prices=False)

	def on_table_double_clicked(self, item):
		"""더블 클릭 시 HTS 연동"""
		row = item.row()
		# 종목코드는 2번 컬럼
		code_item = self.table.item(row, 2)
		if code_item:
			code = code_item.text().strip()
			if code:
				try:
					from shared.hts_connector import send_to_hts
					send_to_hts(str(code))
				except: pass

	def _auto_refresh(self):
		"""자동 갱신: 최근 3일 종목만 시세 조회"""
		print("[History] Auto-refreshing recent 3-day stocks...")
		self.load_data(fetch_prices=True, recent_only=True)

	def start_auto_refresh(self):
		"""타이머 시작 (1분)"""
		if not self.refresh_timer.isActive():
			self.refresh_timer.start(60000)
			print("[History] Auto-refresh timer started (60s)")

	def stop_auto_refresh(self):
		"""타이머 중지"""
		if self.refresh_timer.isActive():
			self.refresh_timer.stop()
			print("[History] Auto-refresh timer stopped")

	def cleanup_data(self):
		"""오래된 데이터 정리"""
		from PyQt6.QtWidgets import QInputDialog
		
		days, ok = QInputDialog.getInt(self, "데이터 정리", 
									 "며칠이 지난 데이터를 정리(삭제)하시겠습니까?\n(30 입력 시: 오늘로부터 30일 이전 데이터 모두 삭제)", 
									 value=30, min=1, max=3650)
		
		if ok:
			deleted = self.db_manager.delete_old_records(days)
			QMessageBox.information(self, "완료", f"{days}일 이전의 데이터 {deleted}건을 영구 삭제했습니다.")
			self.load_data(fetch_prices=False) # Explicitly reload
			self.table.viewport().update() # Force redraw

class TrackingRoomWindow(QMainWindow):
	"""독립 실행용 추적실 창"""
	def __init__(self, db_manager=None, analyzer=None):
		super().__init__()
		self.setWindowTitle("Lead_Sig: 추적실 (Independent)")
		self.resize(1100, 700)
		self.setStyleSheet("background-color: #121212; color: white;")
		
		from core.market_engine import MarketEngine
		from shared.db_manager import DBManager
		
		self.analyzer = analyzer or MarketEngine(mode="REAL")
		self.db_manager = db_manager or DBManager()
		
		central = QWidget()
		self.setCentralWidget(central)
		layout = QVBoxLayout(central)
		
		header = QHBoxLayout()
		title_lbl = QLabel("🕵️ 추적 종목 관리 (Tracking Room)")
		title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #00E5FF;")
		header.addWidget(title_lbl)
		header.addStretch()
		layout.addLayout(header)
		
		self.widget = HistoryWidget(self.db_manager, self.analyzer)
		layout.addWidget(self.widget)
		
		self.widget.load_data(fetch_prices=True, recent_only=True)
		self.widget.start_auto_refresh()

	def closeEvent(self, event):
		self.widget.stop_auto_refresh()
		event.accept()

if __name__ == "__main__":
	import sys
	from PyQt6.QtWidgets import QApplication
	from core.market_engine import MarketEngine
	from shared.db_manager import DBManager
	
	app = QApplication(sys.argv)
	win = TrackingRoomWindow()
	win.show()
	sys.exit(app.exec())
