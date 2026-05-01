# -*- coding: utf-8 -*-
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
							 QTableWidget, QTableWidgetItem, QHeaderView, 
							 QGroupBox, QGridLayout, QFrame, QPushButton)

class AccumulationTab(QWidget):
	"""
	주도주 매집분석 스캐너 위젯 (렌더링 최적화 버전)
	"""
	scan_requested = pyqtSignal()

	def __init__(self, acc_mgr, stock_name_map):
		super().__init__()
		self.acc_mgr = acc_mgr
		self.stock_name_map = stock_name_map
		self.last_results = {} # 검색용 데이터 보관
		self.init_ui()

	def init_ui(self):
		layout = QVBoxLayout(self)
		layout.setContentsMargins(15, 15, 15, 15)
		layout.setSpacing(10)
		
		# 🟢 메인 그룹박스 (제목 없이 생성하여 커스텀 헤더 사용)
		main_group = QGroupBox()
		main_layout = QVBoxLayout(main_group)
		
		# --- 커스텀 헤더 (제목 + 버튼) ---
		header_layout = QHBoxLayout()
		title_lbl = QLabel("📊 종목별 매집 현황 (Daily Accumulation Tracker)")
		title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #DAA520;")
		header_layout.addWidget(title_lbl)
		
		header_layout.addStretch() # 중간을 띄워줌
		
		self.btn_run_scan = QPushButton("🔍 매집 자동 스캔")
		self.btn_run_scan.setFixedWidth(160)
		self.btn_run_scan.setMinimumHeight(32)
		self.btn_run_scan.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_run_scan.setStyleSheet("""
			QPushButton {
				background-color: #2e7d32; 
				color: white; 
				font-weight: bold; 
				font-size: 12px;
				border-radius: 4px;
			}
			QPushButton:hover { background-color: #388e3c; }
			QPushButton:disabled { background-color: #444; color: #888; }
		""")
		self.btn_run_scan.clicked.connect(self.scan_requested.emit)
		header_layout.addWidget(self.btn_run_scan)
		
		main_layout.addLayout(header_layout)
		
		# 🟡 종합 현황 테이블
		self.table_acc = QTableWidget()
		self.table_acc.setColumnCount(11)
		self.table_acc.setHorizontalHeaderLabels([
			"순위", "종목코드", "종목명", "점수", "당일", "누적", "매집비", "기관", "외인", "주요창구", "유형"
		])
		self.table_acc.verticalHeader().setVisible(False)
		
		# 헤더 스타일 설정 (11개 컬럼 최적화)
		header = self.table_acc.horizontalHeader()
		header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive) # 사용자가 조절 가능하게
		
		# 고정 너비 및 확장 설정
		self.table_acc.setColumnWidth(0, 45)  # 순위
		self.table_acc.setColumnWidth(1, 65)  # 종목코드
		self.table_acc.setColumnWidth(2, 130) # 종목명 (확장)
		self.table_acc.setColumnWidth(3, 50)  # 점수
		self.table_acc.setColumnWidth(4, 65)  # 당일
		self.table_acc.setColumnWidth(5, 65)  # 누적
		
		header.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch) # 유형 (나머지 공간 채움)
		
		self.table_acc.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
		self.table_acc.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
		self.table_acc.setStyleSheet("background-color: #1e1e1e; gridline-color: #333;")
		self.table_acc.itemClicked.connect(self.on_row_selected)
		self.table_acc.itemDoubleClicked.connect(self.on_row_double_clicked)
		
		main_layout.addWidget(self.table_acc)
		layout.addWidget(main_group, 7)
		
		# 🔴 상세 점수판
		detail_layout = QHBoxLayout()
		self.score_group = QGroupBox("항목별 상세 점수 (Score Details)")
		grid = QGridLayout(self.score_group)
		self.score_labels = {}
		cats = ["매집량", "연속성", "쌍끌이", "프로그램", "창구특성", "추세가중"]
		for idx, cat in enumerate(cats):
			lbl = QLabel(f"• {cat}:")
			lbl.setStyleSheet("color: #aaa;")
			val = QLabel("0.0")
			val.setStyleSheet("color: #DAA520; font-weight: bold;")
			grid.addWidget(lbl, idx // 2, (idx % 2) * 2)
			grid.addWidget(val, idx // 2, (idx % 2) * 2 + 1)
			self.score_labels[cat] = val
		
		detail_layout.addWidget(self.score_group, 4)
		
		# 창구 정보
		self.broker_group = QGroupBox("상위 매집 창구")
		broker_vbox = QVBoxLayout(self.broker_group)
		self.table_brokers = QTableWidget()
		self.table_brokers.setColumnCount(2)
		self.table_brokers.setHorizontalHeaderLabels(["증권사", "순매수량"])
		self.table_brokers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		broker_vbox.addWidget(self.table_brokers)
		detail_layout.addWidget(self.broker_group, 6)
		
		layout.addLayout(detail_layout, 3)

	def update_table(self, target_results):
		"""분석 결과를 테이블에 화려하게 렌더링"""
		# [안실장 픽스] 데이터 정합성을 위해 마스터 데이터 실시간 재로드 (종목명 복구용)
		try:
			from shared.stock_master import load_master_cache
			self.stock_name_map = load_master_cache()  # self.stock_names -> self.stock_name_map 동기화
		except: pass

		self.table_acc.setRowCount(0)
		
		# 점수 순 정렬
		target_results.sort(key=lambda x: x['score'], reverse=True)
		self.last_results = {res['code']: res for res in target_results} # 빠른 조회를 위해 딕셔너리화

		import re
		re_junk = re.compile('[가-힣a-zA-Z]') # 미리 컴파일하여 속도 향상

		for idx, res in enumerate(target_results):
			row = self.table_acc.rowCount()
			self.table_acc.insertRow(row)
			
			code_str = str(res.get('code', '')).strip()
			raw_name = self.stock_name_map.get(code_str, "")
			
			# 한글이나 영문이 있는 경우만 이름으로 인정
			name = raw_name if raw_name and re_junk.search(str(raw_name)) else code_str
			
			# 1. 기본 정보
			self.table_acc.setItem(row, 0, QTableWidgetItem(str(idx + 1)))
			self.table_acc.setItem(row, 1, QTableWidgetItem(code_str))
			
			# 종목명 5자 제한 (UI 가독성 보정)
			short_name = name[:5] if len(name) > 5 else name
			display_name = short_name # 별표 제거
			
			name_item = QTableWidgetItem(display_name)
			# 툴팁에는 항상 전체 이름 표시
			name_item.setToolTip(f"{name} (매집 점수: {res['score']:.1f})")
			
			# [안실장 픽스] HTS 연동을 위한 메타데이터 저장
			name_item.setData(Qt.ItemDataRole.UserRole, code_str)
			
			if res['score'] >= 85: 
				name_item.setForeground(QColor("#DAA520"))
			
			self.table_acc.setItem(row, 2, name_item)
			
			# 2. 점수 및 등락률 (당일/누적 분리)
			score_item = QTableWidgetItem(f"{res['score']:.1f}")
			score_item.setForeground(QColor("#FFD700"))
			self.table_acc.setItem(row, 3, score_item)
			
			# 당일 등락
			td_chg = res.get('today_change_rt', 0)
			td_item = QTableWidgetItem(f"{td_chg:+.2f}")
			if td_chg > 0: td_item.setForeground(QColor("#ff3333"))
			elif td_chg < 0: td_item.setForeground(QColor("#3388ff"))
			self.table_acc.setItem(row, 4, td_item)

			# 누적(30일) 변동
			cum_chg = res.get('price_change_rt', 0)
			cum_item = QTableWidgetItem(f"{cum_chg:+.2f}")
			if cum_chg > 0: cum_item.setForeground(QColor("#CC0000"))
			elif cum_chg < 0: cum_item.setForeground(QColor("#0066CC"))
			self.table_acc.setItem(row, 5, cum_item)
			
			# 3. 수급 디테일
			self.table_acc.setItem(row, 6, QTableWidgetItem(f"{res['acc_ratio']:.2f}"))
			self.table_acc.setItem(row, 7, QTableWidgetItem(f"{res['inst_days']}일"))
			self.table_acc.setItem(row, 8, QTableWidgetItem(f"{res['frgn_days']}일"))
			
			# 4. 창구 및 유형
			broker = res.get('top_broker', '-')
			broker_item = QTableWidgetItem(broker)
			if any(kw in broker for kw in ["JP모건", "모건스탠리", "골드만", "CS", "UBS"]):
				broker_item.setForeground(QColor("#00E5FF"))
			self.table_acc.setItem(row, 9, broker_item)
			
			# 공략 유형 조합
			types = []
			if res.get('is_breakout'): types.append("🚀돌파")
			if res.get('is_below_avg'): types.append("🛡️안전")
			if res.get('is_yin_dual_buy'): types.append("☯️쌍매")
			if res.get('is_volume_dry'): types.append("⌛건조")
			
			type_item = QTableWidgetItem(" ".join(types) if types else "-")
			if len(types) >= 2: type_item.setForeground(QColor("#DAA520"))
			self.table_acc.setItem(row, 10, type_item)

	def on_row_selected(self, item):
		"""테이블 행 클릭 시 하단 상세 정보 갱신"""
		row = item.row()
		code_item = self.table_acc.item(row, 1)
		if not code_item: return
		
		code = code_item.text()
		res = self.last_results.get(code)
		if res:
			self._update_detail_panels(res)

	def on_row_double_clicked(self, item):
		"""더블 클릭 시 HTS 차트 연동"""
		code = item.data(Qt.ItemDataRole.UserRole)
		if not code:
			row = item.row()
			code_item = self.table_acc.item(row, 1)
			if code_item: code = code_item.text()
		
		if code:
			try:
				from shared.hts_connector import send_to_hts
				send_to_hts(str(code))
			except: pass

	def _update_detail_panels(self, res):
		"""하단 스코어보드 및 창구 테이블 갱신"""
		# 1. 항목별 상세 점수 (AccumulationManager는 한글 키를 사용함)
		details = res.get('score_details', {})
		
		# 매핑 (데이터 내의 한글 키를 그대로 라벨에 반영)
		cats = ["매집량", "연속성", "쌍끌이", "프로그램", "창구특성", "추세가중"]
		
		for cat in cats:
			if cat in self.score_labels:
				val = details.get(cat, 0.0) # 한글 키로 직접 조회
				label = self.score_labels[cat]
				label.setText(f"{val:.1f}")
				# 점수가 높으면 색상 강조
				if val >= 15: label.setStyleSheet("color: #ff3333; font-weight: bold;")
				elif val >= 10: label.setStyleSheet("color: #DAA520; font-weight: bold;")
				else: label.setStyleSheet("color: #cccccc; font-weight: bold;")

		# 2. 상위 매집 창구 리스트 (DB에서 최신 전체 창구 데이터 조회)
		code = res.get('code')
		self.table_brokers.setRowCount(0)
		
		if code:
			brokers = self.acc_mgr.get_top_brokers(code)
			for i, b in enumerate(brokers[:20]): # 상위 20개 표시
				self.table_brokers.insertRow(i)
				b_name = b.get('broker_name', '-')
				b_qty = b.get('net_buy_qty', 0)
				
				name_item = QTableWidgetItem(b_name)
				# 외인 창구 여부 체크 (is_foreign 필드 활용 또는 이름 검색)
				if b.get('is_foreign') == 1 or any(kw in b_name for kw in ["JP모건", "모건스탠리", "골드만", "CS", "UBS", "메릴린치"]):
					name_item.setForeground(QColor("#00E5FF"))
				
				self.table_brokers.setItem(i, 0, name_item)
				
				# 수량/매집비 표시 (수량이 1000 이하면 매집비 비율로 간주하여 처리)
				if abs(b_qty) < 1000 and abs(b_qty) > 0:
					qty_str = f"{b_qty:.2f}"
				else:
					qty_str = f"{b_qty:,}"
				
				qty_item = QTableWidgetItem(qty_str)
				qty_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
				if b_qty > 0: qty_item.setForeground(QColor("#ff3333"))
				elif b_qty < 0: qty_item.setForeground(QColor("#00aaff"))
				
				self.table_brokers.setItem(i, 1, qty_item)
