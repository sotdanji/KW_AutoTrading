import pandas as pd
import datetime
import time
from .strategy_signal import process_data, process_minute_data, check_signal_at
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

class BacktestEngine(QThread):
	# Signals to update UI
	progress_updated = pyqtSignal(int, int) # current, total
	log_message = pyqtSignal(str)
	trade_executed = pyqtSignal(dict)
	finished_backtest = pyqtSignal(dict) # Summary (Renamed from 'finished' to avoid conflict with QThread.finished)

	def __init__(self, token, parent=None):
		super().__init__(parent)
		self.token = token
		self.running = False
		# Store arguments for threaded run
		self.args = None

	def setup_run(self, stock_list, start_date, end_date, config, preloaded_data=None, headless=False):
		"""Store arguments for the run() thread entry point"""
		self.args = (stock_list, start_date, end_date, config, preloaded_data, headless)

	def run(self):
		"""QThread entry point"""
		if not self.args:
			return
		self._run_internal(*self.args)

	def _run_internal(self, stock_list, start_date, end_date, config, preloaded_data=None, headless=False):
		self.running = True
		
		# 1. Data Preparation Phase
		market_data = {}
		if preloaded_data:
			market_data = preloaded_data.copy()
			
		print(f"[DEBUG] BacktestEngine.run - start. Initial market_data keys: {len(market_data)}", flush=True)
			
		# Calculate days_needed once
		today = datetime.date.today()
		if hasattr(start_date, 'toPyDate'):
			s_date_py = start_date.toPyDate()
		else:
			s_date_py = start_date
		days_needed = (today - s_date_py).days + 1000
		if days_needed < 200: days_needed = 200
		
		# [시스템 보강] 전략 타입에 따른 데이터 수집 분기
		data_type = config.get('data_type', 'daily')
		if not headless:
			self.log_message.emit(f"Strategy Type: {data_type.upper()}")

		# Determine stocks to fetch
		stocks_to_fetch = [s for s in stock_list if s not in market_data]
		
		if not headless and stocks_to_fetch:
			self.log_message.emit(f"Fetching data for {len(stocks_to_fetch)} stocks...")

		for idx, code in enumerate(stocks_to_fetch):
			if not self.running: break
			
			if not headless:
				self.progress_updated.emit(int((idx + 1)/len(stocks_to_fetch) * 50), 100)
				QApplication.processEvents()
				
			if data_type == 'minute':
				# [분봉 모드] 분봉 데이터를 가져와서 분석 (백테스트 기간만큼 페이지 확보)
				# days_needed는 일봉 기준이므로 이를 페이지 수로 변환하여 fetch
				fetched_df, error = process_minute_data(code, self.token, days=days_needed)
			else:
				# [일봉 모드] 기존 방식
				fetched_df, error = process_data(code, self.token, days=days_needed)
			
			if fetched_df is not None:
				print(f"[DEBUG] Fetched {code}: {len(fetched_df)} rows")
				
				# [신호 사전 계산 로직]
				# 전략 코드를 전체 DF에 대해 실행하여 'cond' 컬럼 확보
				try:
					import numpy as np
					import pandas as pd
					from shared.execution_context import get_execution_context
					
					# Execution Context 준비
					# 분봉 모드에서는 DayOpen, PreDayClose가 이미 process_minute_data에서 계산됨
					exec_globals = get_execution_context(fetched_df)
					local_vars = {}
					exec(config.get('strategy_code', ''), exec_globals, local_vars)
					
					if 'cond' in local_vars:
						cond_series = local_vars['cond']
						# Series가 아닐 경우 처리
						if not hasattr(cond_series, 'iloc'):
							cond_series = pd.Series([bool(cond_series)] * len(fetched_df), index=fetched_df.index)
						
						fetched_df['strategy_signal'] = cond_series
					else:
						fetched_df['strategy_signal'] = False
				except Exception as e:
					print(f"[ERROR] Strategy Pre-calc Failed ({code}): {e}")
					fetched_df['strategy_signal'] = False

				if data_type == 'minute':
					# [분봉 -> 일봉 요약] 시뮬레이션 코어 호환용
					# 매일 '첫 번째' 신호가 발생한 분의 가격을 추출
					# strategy_signal == True인 것들 중 각 날짜별 첫 행
					sig_rows = fetched_df[fetched_df['strategy_signal'] == True]
					
					# 일봉 요약 생성
					daily_df = fetched_df.groupby('date').agg({
						'open': 'first',
						'high': 'max',
						'low': 'min',
						'close': 'last',
						'volume': 'sum'
					})
					daily_df['date'] = daily_df.index
					
					# 신호 발생일 및 발생 가격 매핑
					if not sig_rows.empty:
						first_sig_per_day = sig_rows.groupby('date').first()
						daily_df['signal'] = daily_df.index.isin(first_sig_per_day.index)
						daily_df['minute_buy_price'] = first_sig_per_day['close'] # 시그널 발생 봉 종가 매수
					else:
						daily_df['signal'] = False
						daily_df['minute_buy_price'] = np.nan
						
					final_df = daily_df
				else:
					# [일봉 모드] 기존 정규화 및 인덱스 설정
					fetched_df['date_str'] = pd.to_datetime(fetched_df['date']).dt.strftime('%Y%m%d')
					fetched_df = fetched_df.drop_duplicates(subset=['date_str'])
					fetched_df.set_index('date_str', inplace=True)
					# signal 컬럼 매핑
					fetched_df['signal'] = fetched_df['strategy_signal']
					final_df = fetched_df

				market_data[code] = final_df

				
		# Benchmark 데이터 수집
		if self.running:
			# 1. KOSPI ('001')
			if 'BENCH_KOSPI' not in market_data:
				if not headless:
					self.log_message.emit("Benchmark(KOSPI) 수집 중...")
				bench_df, error = process_data("001", self.token, days=days_needed)
				if bench_df is not None:
					print(f"[DEBUG] Fetched BENCH_KOSPI: {len(bench_df)} rows")
					bench_df['date_str'] = pd.to_datetime(bench_df['date']).dt.strftime('%Y%m%d')
					# Drop duplicates before setting index to avoid issues
					bench_df = bench_df.drop_duplicates(subset=['date_str'])
					bench_df.set_index('date_str', inplace=True)
					market_data['BENCH_KOSPI'] = bench_df
				else:
					print(f"[ERROR] BENCH_KOSPI Fetch Failed: {error}")
			
			# 2. KOSDAQ ('101')
			if 'BENCH_KOSDAQ' not in market_data:
				if not headless:
					self.log_message.emit("Benchmark(KOSDAQ) 수집 중...")
				bench_df, error = process_data("101", self.token, days=days_needed)
				if bench_df is not None:
					print(f"[DEBUG] Fetched BENCH_KOSDAQ: {len(bench_df)} rows")
					bench_df['date_str'] = pd.to_datetime(bench_df['date']).dt.strftime('%Y%m%d')
					bench_df = bench_df.drop_duplicates(subset=['date_str'])
					bench_df.set_index('date_str', inplace=True)
					market_data['BENCH_KOSDAQ'] = bench_df
				else:
					print(f"[ERROR] BENCH_KOSDAQ Fetch Failed: {error}")
			
			# Rate limit
			if not headless:
				time.sleep(0.2)
				
		if not self.running: return

		# 2. Simulation Phase
		if not headless:
			self.log_message.emit("Running Simulation...")
			
		from .simulation_core import SimulationCore
		
		# Run Simulation
		def sim_cb(c, t):
			self.progress_updated.emit(50 + int(c/t * 50), 100)
		summary = SimulationCore.run(stock_list, start_date, end_date, config, market_data, progress_callback=sim_cb)
		
		# 3. Report Results
		if not headless:
			# Reconstruct trades for UI log (SimulationCore returns full trade list)
			for trade in summary['trades']:
				self.trade_executed.emit(trade)
				self.log_message.emit(f"{trade['status']} {trade['code']} ({trade['profit_pct']:.2f}%)")
				
			self.log_message.emit(f"========== 백테스트 완료 ==========")
			self.log_message.emit(f"총 손익: {summary['total_profit']:+,.0f}원 ({summary['return_pct']:+.2f}%)")
			self.log_message.emit(f"승률: {summary['win_rate']:.1f}%")
			self.log_message.emit(f"===================================")
			
		self.finished_backtest.emit(summary)
		self.running = False
		
	def stop(self):
		self.running = False

