import logging
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from core.logger import get_logger

logger = get_logger(__name__)

class QThandler(QObject, logging.Handler):
	msg_signal = pyqtSignal(str)
	
	def __init__(self, slot):
		QObject.__init__(self)
		logging.Handler.__init__(self)
		self.msg_signal.connect(slot)
		self.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', '%H:%M:%S'))

	def emit(self, record):
		try:
			msg = self.format(record)
			self.msg_signal.emit(msg)
		except Exception:
			# 로깅 실패로 인해 전체 프로그램이 죽는 것을 방지
			pass

class StartupThread(QThread):
	"""
	Application Startup Task (Heavy Lifting)
	Runs PreMarketLoader to fetch/load historical data.
	"""
	status_signal = pyqtSignal(str)
	index_ready = pyqtSignal(dict)
	finished_signal = pyqtSignal(bool)

	def __init__(self, analyzer, db_manager):
		super().__init__()
		self.analyzer = analyzer
		self.db_manager = db_manager

	def run(self):
		try:
			# [Prioritize] Fetch market indices first to show in sidebar immediately
			self.status_signal.emit("시장 지수 로딩 중...")
			indices = self.analyzer.fetcher.get_market_indices()
			self.index_ready.emit(indices)
			
			# [NEW] 10일 넘은 자료 자동 삭제
			self.status_signal.emit("오래된 데이터 정리 중...")
			deleted = self.db_manager.delete_old_records(10)
			if deleted > 0:
				logger.info(f"Auto-cleanup: Deleted {deleted} records older than 10 days.")
			
			self.status_signal.emit("Top-Down 엔진 초기화 중...")
			self.analyzer.initialize_loader()
			
			self.status_signal.emit("엔진 준비 완료.")
			self.finished_signal.emit(True)
		except Exception as e:
			logger.error(f"Startup Thread Failed: {e}")
			self.status_signal.emit(f"초기화 오류: {e}")
			self.finished_signal.emit(False)


class DataThread(QThread):
	data_ready = pyqtSignal(dict)
	status_signal = pyqtSignal(str)

	def __init__(self, analyzer, sector_state=None, theme_state=None):
		super().__init__()
		self.analyzer = analyzer
		self.sector_state = sector_state # {"view": "Overview", "selected": None}
		self.theme_state = theme_state   # {"view": "Overview", "selected": None}
		self._stop_flag = False


	def run(self):
		import time
		while not self._stop_flag:
			try:
				# 상위 10개 테마 캐싱 조회
				themes_raw = self.analyzer.get_themes_cached()
				
				system_alerts = []
				themes = []
				for t in themes_raw:
					if t.get('is_system_alert'):
						system_alerts.extend(t.get('messages', []))
					else:
						themes.append(t)
				
				all_themes = self.analyzer.get_all_themes_for_stats()
				top6_themes = themes[:6]
				top8_data = []
				
				for i, theme in enumerate(top6_themes):
					t_name = theme['name']
					t_stocks = self.analyzer.get_theme_stocks_direct(t_name)
					if t_stocks:
						t_stocks.sort(key=lambda x: x.get('change', 0), reverse=True)
					
					top8_data.append({
						"rank": i + 1,
						"name": t_name,
						"change": theme['change'],
						"stocks": t_stocks
					})
				
				momentum_10min = self.analyzer.get_10min_momentum_data(limit=30)
				program_trading = self.analyzer.get_program_trading_data()
				
				# 12종목 모멘텀 데이터 주입
				val_stocks = momentum_10min.get('curr_val', [])[:12]
				vol_stocks = momentum_10min.get('curr_vol', [])[:12]
				
				val_rate = sum(s.get('change', 0) for s in val_stocks) / len(val_stocks) if val_stocks else 0.0
				vol_rate = sum(s.get('change', 0) for s in vol_stocks) / len(vol_stocks) if vol_stocks else 0.0
				
				top8_data.append({
					"rank": 7,
					"name": "💰 거래대금 TOP",
					"change": val_rate,
					"stocks": val_stocks
				})
				
				top8_data.append({
					"rank": 8,
					"name": "🔥 거래량 TOP",
					"change": vol_rate,
					"stocks": vol_stocks
				})
				
				result = {
					"themes": top6_themes,
					"themes_all": all_themes,
					"top8_themes_data": top8_data,
					"momentum_10min": momentum_10min,
					"program_trading": program_trading,
					"system_alerts": system_alerts,
					"indices": self.analyzer.fetcher.get_market_indices()
				}
					
				self.data_ready.emit(result)
				
				# 10초 대기 (중간 정지 체크)
				for _ in range(100):
					if self._stop_flag: break
					time.sleep(0.1)
					
			except Exception as e:
				import traceback
				logger.error(f"DataThread Error: {e}\n{traceback.format_exc()}")
				self.status_signal.emit(f"FETCH_ERROR")
				time.sleep(5)
