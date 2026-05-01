"""
Parameter Optimization Dialog (Genetic Algorithm)

Allows users to configure and run GA optimization for strategy parameters.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
							 QPushButton, QGroupBox, QFormLayout, QSpinBox,
							 QDoubleSpinBox, QProgressBar, QTextEdit, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.ga_optimizer import GAOptimizer
import asyncio, websockets, json, os, sys

class ConditionFetchWorker(QThread):
	log_signal = pyqtSignal(str)
	finished_signal = pyqtSignal(list)
	
	def __init__(self, token, seq):
		super().__init__()
		self.token = token
		self.seq = seq

	def run(self):
		try:
			current_dir  = os.path.dirname(os.path.abspath(__file__))
			at_sig_dir   = os.path.normpath(os.path.join(current_dir, '..', '..', 'AT_Sig'))
			if at_sig_dir not in sys.path:
				sys.path.insert(0, at_sig_dir)
			from config import get_current_config
			conf	   = get_current_config()
			socket_url = conf.get('socket_url', 'wss://api.kiwoom.com:10000')
		except Exception:
			socket_url = 'wss://api.kiwoom.com:10000'

		ws_url = socket_url + '/api/dostk/websocket'
		codes = []

		async def _fetch():
			try:
				async with websockets.connect(ws_url) as ws:
					await ws.send(json.dumps({'trnm': 'LOGIN', 'token': self.token}))
					resp = json.loads(await ws.recv())
					if resp.get('return_code') != 0:
						self.log_signal.emit(f"[WS] 로그인 실패: {resp.get('return_msg')}")
						return

					self.log_signal.emit(f"조건식 종목을 실시간으로 수집합니다 (Seq: {self.seq})...")

					# 반드시 조건식 목록(CNSRLST) 조회가 선행되어야만 특정 번호 조회가 올바르게 작동 (키움 API 특성)
					await ws.send(json.dumps({'trnm': 'CNSRLST'}))
					while True:
						resp = json.loads(await ws.recv())
						if resp.get('trnm') == 'CNSRLST':
							break


					await ws.send(json.dumps({
						'trnm': 'CNSRREQ', 'seq': self.seq,
						'search_type': '1', 'stex_tp': 'K',
					}))

					try:
						while True:
							msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
							r = json.loads(msg)
							if r.get('trnm') == 'PING':
								await ws.send(msg); continue
							if r.get('trnm') in ('CNSRREQ', 'CNSR'):
								for item in r.get('data', r.get('output', [])):
									code = ''
									if isinstance(item, dict):
										code = (item.get('stk_cd') or item.get('jmcode') or item.get('code') or item.get('9001', ''))
									elif isinstance(item, str):
										code = item.strip()
									if code:
										codes.append(code.lstrip('A'))
								self.log_signal.emit(f"	→ {len(codes)}개 종목 확인 완료")
								break
					except asyncio.TimeoutError:
						self.log_signal.emit(f"	⚠ 타임아웃 (조회된 종목: {len(codes)}개)")
			except Exception as e:
				self.log_signal.emit(f"[WS] 오류: {e}")

		# PyQt Thread안에 이벤트 루프
		asyncio.run(_fetch())
		self.finished_signal.emit(codes)


class OptimizationDialog(QDialog):
	"""Dialog for parameter optimization setup and execution using Genetic Algorithm"""
	
	def __init__(self, parent=None, strategy_code=None, selected_cond=None, manual_code=None, mode_text=""):
		super().__init__(parent)
		self.setWindowTitle(f"전략 최적화: {mode_text}" if mode_text else "전략 최적화 (유전 알고리즘)")
		self.setMinimumWidth(500)
		self.setMinimumHeight(600)
		self.worker = None
		self.fetch_worker = None
		self.parent_ref = parent # Store parent reference for engine/token access
		self.strategy_code = strategy_code
		self.selected_cond = selected_cond
		self.manual_code = manual_code
		self.mode_text = mode_text
		
		self.setup_ui()
	
	def setup_ui(self):
		layout = QVBoxLayout(self)
		
		# Title
		title = QLabel("유전 알고리즘 파라미터 최적화")
		title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
		layout.addWidget(title)
		
		# 1. Parameter Ranges
		param_group = QGroupBox("탐색 범위 설정 (최소 ~ 최대)")
		param_layout = QFormLayout()
		
		# Stop Loss Range
		sl_box = QHBoxLayout()
		self.spin_sl_min = QDoubleSpinBox()
		self.spin_sl_min.setRange(0.1, 50.0)
		self.spin_sl_min.setValue(1.0)
		self.spin_sl_min.setSingleStep(0.1)
		
		self.spin_sl_max = QDoubleSpinBox()
		self.spin_sl_max.setRange(0.1, 50.0)
		self.spin_sl_max.setValue(10.0)
		self.spin_sl_max.setSingleStep(0.1)
		
		sl_box.addWidget(self.spin_sl_min)
		sl_box.addWidget(QLabel("~"))
		sl_box.addWidget(self.spin_sl_max)
		param_layout.addRow("손절 (SL):", sl_box)
		
		# Take Profit Range
		tp_box = QHBoxLayout()
		self.spin_tp_min = QDoubleSpinBox()
		self.spin_tp_min.setRange(0.1, 100.0)
		self.spin_tp_min.setValue(5.0)
		self.spin_tp_min.setSingleStep(0.1)
		
		self.spin_tp_max = QDoubleSpinBox()
		self.spin_tp_max.setRange(0.1, 100.0)
		self.spin_tp_max.setValue(30.0)
		self.spin_tp_max.setSingleStep(0.1)
		
		tp_box.addWidget(self.spin_tp_min)
		tp_box.addWidget(QLabel("~"))
		tp_box.addWidget(self.spin_tp_max)
		param_layout.addRow("익절 (TP):", tp_box)
		
		# Ratio Range
		ratio_box = QHBoxLayout()
		self.spin_ratio_min = QSpinBox()
		self.spin_ratio_min.setRange(1, 100)
		self.spin_ratio_min.setValue(10)
		self.spin_ratio_min.setSingleStep(5)
		
		self.spin_ratio_max = QSpinBox()
		self.spin_ratio_max.setRange(1, 100)
		self.spin_ratio_max.setValue(50)
		self.spin_ratio_max.setSingleStep(5)
		
		ratio_box.addWidget(self.spin_ratio_min)
		ratio_box.addWidget(QLabel("~"))
		ratio_box.addWidget(self.spin_ratio_max)
		param_layout.addRow("비중 (Ratio):", ratio_box)
		
		param_group.setLayout(param_layout)
		layout.addWidget(param_group)
		
		# 2. GA Settings
		ga_group = QGroupBox("GA 엔진 설정")
		ga_layout = QFormLayout()
		
		self.spin_pop = QSpinBox()
		self.spin_pop.setRange(4, 100)
		self.spin_pop.setValue(10)
		ga_layout.addRow("개체 수 (Population):", self.spin_pop)
		
		self.spin_gen = QSpinBox()
		self.spin_gen.setRange(1, 100)
		self.spin_gen.setValue(5)
		ga_layout.addRow("세대 수 (Generations):", self.spin_gen)
		
		ga_group.setLayout(ga_layout)
		layout.addWidget(ga_group)
		
		# 3. Progress
		progress_group = QGroupBox("진행 상황")
		progress_layout = QVBoxLayout()
		
		self.progress_bar = QProgressBar()
		self.progress_bar.setRange(0, 100)
		self.progress_bar.setValue(0)
		self.progress_bar.setFormat("대기 중...")
		progress_layout.addWidget(self.progress_bar)
		
		self.log_text = QTextEdit()
		self.log_text.setMaximumHeight(150)
		self.log_text.setReadOnly(True)
		progress_layout.addWidget(self.log_text)
		
		progress_group.setLayout(progress_layout)
		layout.addWidget(progress_group)
		
		# Buttons
		btn_layout = QHBoxLayout()
		
		self.btn_start = QPushButton("시작")
		self.btn_start.clicked.connect(self.on_start)
		self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_start.setStyleSheet("""
			QPushButton { background-color: #0088cc; color: #ffffff; font-weight: bold; border-radius: 4px; border: 1px solid #006699; padding: 5px 15px; }
			QPushButton:hover { background-color: #00aaff; }
			QPushButton:disabled { background-color: #333333; color: #666666; border: 1px solid #444444; }
		""")
		
		self.btn_stop = QPushButton("중단")
		self.btn_stop.clicked.connect(self.on_stop)
		self.btn_stop.setEnabled(False)
		self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_stop.setStyleSheet("""
			QPushButton { background-color: #cc3333; color: #ffffff; font-weight: bold; border-radius: 4px; border: 1px solid #992222; padding: 5px 15px; }
			QPushButton:hover { background-color: #ff4444; }
			QPushButton:disabled { background-color: #333333; color: #666666; border: 1px solid #444444; }
		""")
		
		self.btn_apply = QPushButton("결과 적용")
		self.btn_apply.clicked.connect(self.on_apply)
		self.btn_apply.setEnabled(False)
		self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
		self.btn_apply.setStyleSheet("""
			QPushButton { background-color: #00cc66; color: #ffffff; font-weight: bold; border-radius: 4px; border: 1px solid #00994d; padding: 5px 15px; }
			QPushButton:hover { background-color: #00ff80; }
			QPushButton:disabled { background-color: #333333; color: #666666; border: 1px solid #444444; }
		""")

		self.btn_close = QPushButton("닫기")
		self.btn_close.clicked.connect(self.reject)
		self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
		
		btn_layout.addWidget(self.btn_start)
		btn_layout.addWidget(self.btn_stop)
		btn_layout.addStretch()
		btn_layout.addWidget(self.btn_apply)
		btn_layout.addWidget(self.btn_close)
		
		layout.addLayout(btn_layout)
		
		self.best_result_params = None
	
	def on_start(self):
		"""Start optimization with unified target branch"""
		
		if not self.parent_ref or not hasattr(self.parent_ref, 'token'):
			self.log("오류: 메인 윈도우/토큰 참조를 찾을 수 없습니다.")
			return

		self.btn_start.setEnabled(False)
		self.btn_stop.setEnabled(True)
		self.btn_apply.setEnabled(False)
		self.progress_bar.setValue(0)
		self.progress_bar.setFormat("준비 중...")

		if self.manual_code:
			self.log(f"단일 종목({self.manual_code})을 대상으로 최적화를 시작합니다.")
			self.start_ga([self.manual_code])
		elif self.selected_cond:
			self.log("조건식 기반 최적화를 준비합니다. 대상 종목을 조회 중...")
			self.fetch_worker = ConditionFetchWorker(self.parent_ref.token, self.selected_cond)
			self.fetch_worker.log_signal.connect(self.log)
			self.fetch_worker.finished_signal.connect(self.start_ga)
			self.fetch_worker.start()
		else:
			self.log("전체 유니버스를 대상으로 최적화를 준비합니다.")
			stock_list = []
			if hasattr(self.parent_ref, 'universe_cache') and self.parent_ref.universe_cache:
				stock_list = self.parent_ref.universe_cache[:50] # 우선 속도를 위해 50개 제한
			if not stock_list:
				self.log("경고: 전종목 유니버스가 로드되지 않았습니다.\n(메인 화면에서 백테스트를 한 번 실행하세요)")
				self.btn_start.setEnabled(True)
				self.btn_stop.setEnabled(False)
				return
			self.start_ga(stock_list)

	def start_ga(self, stock_list):
		if not stock_list:
			self.log("최적화를 진행할 대상 종목이 없습니다. 중단합니다.")
			self.btn_start.setEnabled(True)
			self.btn_stop.setEnabled(False)
			return

		param_ranges = {
			'sl': (self.spin_sl_min.value(), self.spin_sl_max.value()),
			'tp': (self.spin_tp_min.value(), self.spin_tp_max.value()),
			'ratio': (self.spin_ratio_min.value(), self.spin_ratio_max.value()),
		}
		
		pop_size = self.spin_pop.value()
		generations = self.spin_gen.value()

		# Prepare dummy config basics
		base_config = {
			 'strategy_code': self.strategy_code if self.strategy_code else self.parent_ref.text_formula_preview.toPlainText()
		}
		
		if not base_config['strategy_code']:
			QMessageBox.warning(self, "오류", "전략 코드가 분실되었습니다.")
			self.btn_start.setEnabled(True)
			self.btn_stop.setEnabled(False)
			return

		start_date = self.parent_ref.date_start.date()
		end_date = self.parent_ref.date_end.date()

		self.log(f"최적화 엔진 개시: {len(stock_list)}개 종목 대상, {generations}세대 x {pop_size}개체")
		
		self.worker = GAOptimizer(
			self.parent_ref, # passing parent as engine provider
			stock_list,
			start_date,
			end_date,
			base_config,
			param_ranges,
			pop_size,
			generations
		)
		
		self.worker.progress_updated.connect(self.on_progress)
		self.worker.generation_finished.connect(self.on_generation_finished)
		self.worker.optimization_finished.connect(self.on_finished)
		
		self.worker.start()
	
	def on_stop(self):
		if self.worker:
			self.worker.stop()
			self.log("사용자에 의해 중단됨.")
		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
	
	def on_progress(self, current, total, msg):
		pct = int((current / total) * 100)
		self.progress_bar.setValue(pct)
		self.progress_bar.setFormat(f"진행률 {pct} - {msg}")
		
	def on_generation_finished(self, gen_idx, best_fitness, best_params):
		self.log(f"[세대 {gen_idx} 완료] 최고 수익률: {best_fitness:.2f}")
		self.log(f" - 파라미터: {best_params}")
		
	def on_finished(self, best_params, best_fitness):
		self.log("=== 최적화 완료 ===")
		self.log(f"최종 최고 수익률: {best_fitness:.2f}")
		self.log(f"최종 파라미터: {best_params}")
		
		self.best_result_params = best_params
		self.btn_start.setEnabled(True)
		self.btn_stop.setEnabled(False)
		self.btn_apply.setEnabled(True)
		self.progress_bar.setValue(100)
		self.progress_bar.setFormat("완료")
		
		QMessageBox.information(self, "완료", f"최적화가 완료되었습니다.\n최고 수익률: {best_fitness:.2f}")

	def on_apply(self):
		"""Apply best parameters to Main Window"""
		if self.parent_ref and self.best_result_params:
			p = self.best_result_params
			self.parent_ref.cond_spin_sl.setValue(p['sl'])
			self.parent_ref.cond_spin_tp.setValue(p['tp'])
			self.parent_ref.spin_ratio.setValue(p['ratio'])
			self.log("메인 화면에 파라미터를 적용했습니다.")
			self.accept()

	def log(self, message):
		self.log_text.append(message)
