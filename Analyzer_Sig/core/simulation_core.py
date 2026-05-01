import pandas as pd
import datetime
import numpy as np
from shared.market_status import MarketRegime

class SimulationCore:
	"""
	Pure Python Backtest Simulation Engine.
	Decoupled from PyQt for multiprocessing compatibility.
	"""
	
	@staticmethod
	def run(stock_list, start_date, end_date, config, market_data, progress_callback=None):
		"""
		Run backtest for list of stocks.
		"""
		# Date Conversion safe check
		if hasattr(start_date, 'toPyDate'):
			s_date = start_date.toPyDate()
		else:
			s_date = start_date
			
		if hasattr(end_date, 'toPyDate'):
			e_date = end_date.toPyDate()
		else:
			e_date = end_date
			
		delta = e_date - s_date
		date_range = [s_date + datetime.timedelta(days=i) for i in range(delta.days + 1)]
		
		# Portfolio State
		cash = config.get('deposit', 10000000)
		initial_deposit = cash
		holdings = {} # {code: {'qty': 0, 'buy_price': 0, 'buy_date': ''}}
		trades = []
		
		# Pre-filter valid stocks (Must have data)
		valid_stocks = [res for res in stock_list if res in market_data]
		
		# Strategy Preparation
		strategy_code = config.get('strategy_code', '').strip()
		
		# Pre-calculate signals if strategy exists
		# To optimize, we add 'signal' column to dataframe copies
		# Note: In multiprocessing, make sure not to mutate shared memory destructively if possible, 
		# but here market_data is likely passed as copy or COW.
		# 1. Prepare Data & Signals
		processed_data = {}
		
		# Explicitly include benchmarks in processed_data for comparison later
		for b_key in ['BENCH_KOSPI', 'BENCH_KOSDAQ']:
			if b_key in market_data:
				processed_data[b_key] = market_data[b_key]
		
		for code in valid_stocks:
			df = market_data[code]
			if df.empty: continue
			
			# We work on a view or copy to set signals
			# If strategy_code is provided, compute signals
			if strategy_code:
				try:
					# Context needed for exec? 
					# We need a standardized way to calc signal faster.
					# For now, simplistic approach:
					# Re-implementing Safe Execution Context is heavy.
					# We assume params are simple. 
					
					# Optimization: Vectorized Signal Calculation?
					# This is hard with arbitrary python code string.
					# We will stick to the loop check or pre-calc if possible.
					# Since existing engine did `exec` per Stock, let's do it here per stock (Vectorized potentially)
					
					# BUT, "Condition" usually depends on current row.
					# Most Kiwoom formulas are vectorized naturally (Series > Series).
					
					from shared.execution_context import get_execution_context
					exec_context = get_execution_context(df)
					local_vars = {}
					local_vars.update(exec_context)
					
					exec(strategy_code, {}, local_vars)
					
					if 'cond' in local_vars:
						cond = local_vars['cond']
						# Safe copy only once
						df = df.copy()
						
						if isinstance(cond, pd.Series):
							# [Look-ahead Bias Fix]
							# General signals (calculated based on Close) should be executed on Next Open.
							# Therefore, we SHIFT the signal by 1 day.
							# Today's signal -> Becomes Tomorrow's Action
							
							# However, if 'target_price' strategy (Intraday Breakout), 
							# the signal is usually 'Close > Target' (which is retroactive)
							# OR 'High > Target' (Intraday).
							# If usage is 'High > Target', we buy at Target TODAY.
							
							is_intraday = 'target_price' in local_vars
							
							if is_intraday:
								# Intraday Strategy: No Shift (Signal implies 'Trade Today' condition met)
								df['signal'] = cond.fillna(False)
							else:
								# End-of-Day Strategy: Shift 1 Day (Trade Tomorrow Open)
								df['signal'] = cond.shift(1).fillna(False)
							
						# Check for target_price (Larry Williams Support)
						if 'target_price' in local_vars:
							tp_series = local_vars['target_price']
							if isinstance(tp_series, pd.Series):
								df['target_price'] = tp_series
						
						processed_data[code] = df
				except Exception as e:
					# Strategy Error, skip functionality or treat as False
					print(f"[ERROR] Strategy Execution Failed for {code}: {e}")
					import traceback
					traceback.print_exc()
					processed_data[code] = df.copy()
					processed_data[code]['signal'] = False
			else:
				# No Strategy -> Buy on first day (Logic from original)
				processed_data[code] = df
		
		
		# Simulation Loop
		daily_values = []
		simulation_dates = [] # To sync with charted dates
		
		for idx, current_date in enumerate(date_range):
			if progress_callback: progress_callback(idx + 1, len(date_range))
			date_str = current_date.strftime("%Y%m%d")
			simulation_dates.append(date_str)
			
			# --- [안실장 신규] 당일 시장 상황(Market Regime) 판단 ---
			current_regime = MarketRegime.SIDEWAYS
			kospi_df = processed_data.get('BENCH_KOSPI')
			kosdaq_df = processed_data.get('BENCH_KOSDAQ')
			
			def calculate_regime(df, d_str):
				if df is None or d_str not in df.index: return MarketRegime.SIDEWAYS
				try:
					# 20일 이평선 기준 이격도 계산 (백테스트용 간략 버전)
					idx = df.index.get_loc(d_str)
					if idx < 20: return MarketRegime.SIDEWAYS
					
					hist_prices = df['close'].iloc[idx-20:idx+1]
					ma20 = hist_prices.mean()
					curr = df.at[d_str, 'close']
					disparity = (curr / ma20) * 100
					
					if disparity < 95: return MarketRegime.CRASH
					if curr < ma20: return MarketRegime.BEAR
					return MarketRegime.BULL # 정배열 등 복잡한 조건은 생략하고 단순화
				except: return MarketRegime.SIDEWAYS

			kospi_regime = calculate_regime(kospi_df, date_str)
			kosdaq_regime = calculate_regime(kosdaq_df, date_str)
			
			# 보수적 적용 (하나라도 폭락이면 폭락)
			if kospi_regime == MarketRegime.CRASH or kosdaq_regime == MarketRegime.CRASH:
				current_regime = MarketRegime.CRASH
			elif kospi_regime == MarketRegime.BEAR or kosdaq_regime == MarketRegime.BEAR:
				current_regime = MarketRegime.BEAR
			elif kospi_regime == MarketRegime.BULL and kosdaq_regime == MarketRegime.BULL:
				current_regime = MarketRegime.BULL
			else:
				current_regime = MarketRegime.SIDEWAYS
			
			# 1. Processing Holdings (Sell)
			active_codes = list(holdings.keys()) # Copy keys
			for code in active_codes:
				pos = holdings[code]
				df = processed_data.get(code)
				if df is None or date_str not in df.index: continue
				
				# Fast lookup
				try:
					row_close = df.at[date_str, 'close']
					row_open = df.at[date_str, 'open']
					row_high = df.at[date_str, 'high']
					row_low = df.at[date_str, 'low']
				except KeyError:
					 continue
				
				# Setup Variables
				sl = config.get('sl', -3.0)
				tp = config.get('tp', 6.0)
				exit_on_open = config.get('exit_on_open', False)
				
				# [안실장 신규] 지수 상황에 따른 전략 조정
				if current_regime == MarketRegime.BEAR:
					sl = sl + 1.5 # 약세장에서는 손절 폭을 타이트하게 (-3 -> -1.5)
				
				reason = ""
				sold = False
				sell_price = row_close
				
				# [안실장 신규] 폭락장 긴급 청산
				if current_regime == MarketRegime.CRASH:
					reason = "Market Crash Emergency Exit"
					sold = True
					sell_price = row_open # 시가에 즉시 던짐
				
				# A. Time-based Exit (Sell on Next Day Open)
				# If we bought yesterday (or before), and exit_on_open is True, sell at Open today.
				if exit_on_open and pos['buy_date'] != date_str:
					reason = "Market Open Exit"
					sold = True
					sell_price = row_open
				
				# B. Stop Loss / Take Profit (Intraday check)
				if not sold:
					# Check SL with Low (Did prices hit SL during the day?)
					profit_rate_low = (row_low - pos['buy_price']) / pos['buy_price'] * 100
					# Check TP with High (Did prices hit TP during the day?)
					profit_rate_high = (row_high - pos['buy_price']) / pos['buy_price'] * 100
					
					# [Priority Check] 
					# 1. Stop Loss first (Conservative approach)
					if profit_rate_low <= -abs(sl):
						reason = "Stop Loss"
						sold = True
						# In realistic slippage, we sell at our SL limit price or Open if gapped down
						sell_price = min(row_open, pos['buy_price'] * (1 - abs(sl)/100.0))
					
					# 2. Take Profit if not sold by SL
					elif profit_rate_high >= tp:
						reason = "Take Profit"
						sold = True
						# Sell at TP limit price or Open if gapped up
						sell_price = max(row_open, pos['buy_price'] * (1 + tp/100.0))

					# 3. If no intraday triggers, check Close-based trigger (EOD)
					else:
						current_profit_rate = (row_close - pos['buy_price']) / pos['buy_price'] * 100
						if current_profit_rate <= -abs(sl):
							reason = "Stop Loss (EOD)"
							sold = True
							sell_price = row_close
						elif current_profit_rate >= tp:
							reason = "Take Profit (EOD)"
							sold = True
							sell_price = row_close
					
					# Apply slippage to the determined sell_price
					slippage = config.get('slippage', 0.0)
					sell_price = sell_price * (1.0 - slippage)


				if sold:
					sell_amount_raw = sell_price * pos['qty']
					
					# [Refined] Apply Sell Costs
					# From UI: total commission/tax is provided
					SELL_COST_RATE = config.get('commission', 0.00215)
					net_sell_amount = sell_amount_raw * (1 - SELL_COST_RATE)
					
					cash += net_sell_amount
					
					# Accurate Profit %: (Net Sell - Total Buy Cost) / Total Buy Cost
					# Use stored buy_cost if available, else derive (backward compat)
					buy_cost = pos.get('buy_cost', pos['buy_price'] * pos['qty'])
					
					real_profit_pct = ((net_sell_amount - buy_cost) / buy_cost) * 100
					
					trade = {
						'code': code,
						'buy_date': pos['buy_date'],
						'sell_date': date_str,
						'buy_price': pos['buy_price'],
						'sell_price': sell_price,
						'profit_pct': real_profit_pct,
						'status': reason
					}
					trades.append(trade)
					del holdings[code]

			# 2. Processing Requests (Buy)
			# [안실장 신규] 폭락장에서는 매수 금지
			if cash > 0 and current_regime != MarketRegime.CRASH:
				# Iterate valid stocks
				for code in valid_stocks:
					if code in holdings: continue
					
					df = processed_data.get(code)
					if df is None: continue
					
					# Fast lookup existence
					if date_str not in df.index: continue
					
					# Signal Check
					has_signal = False
					
					if strategy_code:
						try:
							# Use .at for scalar lookup (Fastest)
							# bool() conversion check
							sig_val = df.at[date_str, 'signal']
							has_signal = bool(sig_val)
						except:
							has_signal = False
					else:
						# Buy & Hold (Buy Once) logic
						 pass # Complex to track 'bought_once' without state. 
						 # For GA, we usually have a strategy. 
						 # If no strategy, GA is meaningless. 
						 # We ignore "Buy & Hold" logic for GA optimization context mostly, 
						 # OR we can assume simple buy on start.
						 # Let's support simple Start Buy:
						 if len(trades) == 0 and len(holdings) == 0:
							 # Just buy first available
							 has_signal = True
					
					if has_signal:
						# [Look-ahead Bias Fix] Execute at Open
						# Because signal was shifted (T-1), we execute at T Open.
						buy_price = df.at[date_str, 'open']
						
						# Larry Williams Logic Support (Buy at Target Price)
						if 'target_price' in df.columns:
							target_p = df.at[date_str, 'target_price']
							open_p = df.at[date_str, 'open']
							if not pd.isna(target_p):
								# If open is already higher than target (Gap Up), buy at open
								buy_price = max(target_p, open_p)
						
						# [분봉 전략 보강] 장중 특정 시점 매수가 존재 시 우선 적용
						if 'minute_buy_price' in df.columns:
							m_buy_p = df.at[date_str, 'minute_buy_price']
							if not pd.isna(m_buy_p) and m_buy_p > 0:
								buy_price = m_buy_p
								
						# Apply slippage
						slippage = config.get('slippage', 0.0)
						buy_price = buy_price * (1.0 + slippage)
						
						ratio = config.get('ratio', 10.0) / 100
						invest_amt = cash * ratio
						
						# Min check
						if invest_amt < buy_price: continue
						
						qty = int(invest_amt // buy_price)
						
						# Buy Fee: 0.015% (Kiwoom standard) - We use default or allow modification
						BUY_FEE = 0.00015
						
						if qty > 0:
							cost = qty * buy_price
							total_cost = cost * (1 + BUY_FEE)
							
							if cash >= total_cost:
								cash -= total_cost
								holdings[code] = {
									'qty': qty,
									'buy_price': buy_price, # Record raw price for stat
									'buy_cost': total_cost, # Record total cost for accurate PnL
									'buy_date': date_str
								}
								
								# --- [안실장 픽스] 당일 매수 후 당일 익절/손절(Same-day Exit) 체크 추가 ---
								row_high = df.at[date_str, 'high']
								row_low = df.at[date_str, 'low']
								row_close = df.at[date_str, 'close']
								
								sl_val = config.get('sl', -3.0)
								tp_val = config.get('tp', 6.0)
								
								if current_regime == MarketRegime.BEAR:
									sl_val = sl_val + 1.5
									
								sold_immediately = False
								imm_sell_price = row_close
								imm_reason = ""
								
								if row_low <= buy_price * (1 - abs(sl_val)/100.0):
									imm_reason = "Stop Loss (Same-day)"
									imm_sell_price = buy_price * (1 - abs(sl_val)/100.0)
									sold_immediately = True
								elif row_high >= buy_price * (1 + tp_val/100.0):
									imm_reason = "Take Profit (Same-day)"
									imm_sell_price = buy_price * (1 + tp_val/100.0)
									sold_immediately = True
								
								if sold_immediately:
									SELL_COST_RATE = config.get('commission', 0.00215)
									net_sell_amount = (imm_sell_price * qty) * (1 - SELL_COST_RATE)
									cash += net_sell_amount
									real_profit_pct = ((net_sell_amount - total_cost) / total_cost) * 100
									trades.append({
										'code': code,
										'buy_date': date_str, 'sell_date': date_str,
										'buy_price': buy_price, 'sell_price': imm_sell_price,
										'profit_pct': real_profit_pct, 'status': imm_reason
									})
									del holdings[code]
								
			# Record current day's total portfolio value (Cash + Holdings)
			total_val = float(cash)
			for h_code, h_pos in holdings.items():
				h_df = processed_data.get(h_code)
				if h_df is not None and date_str in h_df.index:
					val = h_df.at[date_str, 'close']
					total_val += float(h_pos['qty'] * (val if not pd.isna(val) else h_pos['buy_price']))
				else:
					total_val += float(h_pos['qty'] * h_pos['buy_price'])
			
			# Ensure total_val is not NaN
			if pd.isna(total_val):
				total_val = daily_values[-1] if daily_values else initial_deposit
				
			daily_values.append(total_val)

		# 3. Final Liquidate
		for code, pos in holdings.items():
			df = processed_data.get(code)
			if df is not None and not df.empty:
				last_price = df['close'].iloc[-1]
				cash += pos['qty'] * last_price
				
		# 4. Summary Calculation
		final_balance = cash
		total_profit = final_balance - initial_deposit
		return_pct = (total_profit / initial_deposit) * 100 if initial_deposit > 0 else 0
		
		# MDD Calculation
		mdd = 0
		drawdown_series = []
		portfolio_returns = []
		
		if daily_values:
			val_series = pd.Series(daily_values)
			peaks = val_series.cummax()
			dd_series = (val_series - peaks) / peaks * 100
			mdd = dd_series.min()
			drawdown_series = dd_series.fillna(0).tolist()
			portfolio_returns = ((val_series - initial_deposit) / initial_deposit * 100).fillna(0).tolist()
			
		# 5. Benchmark return calculation
		bench_kospi = []
		bench_kosdaq = []
		
		if daily_values:
			# Match lengths of all series to simulation_dates
			for b_key, b_label, b_list in [('BENCH_KOSPI', 'KOSPI', bench_kospi), ('BENCH_KOSDAQ', 'KOSDAQ', bench_kosdaq)]:
				b_df = processed_data.get(b_key)
				start_p = None
				
				for d_str in simulation_dates:
					if b_df is not None and d_str in b_df.index:
						curr_p = b_df.at[d_str, 'close']
						if isinstance(curr_p, pd.Series): curr_p = curr_p.iloc[0]
						
						if start_p is None and not pd.isna(curr_p) and curr_p > 0:
							start_p = curr_p
						
						if start_p:
							b_list.append((curr_p - start_p) / start_p * 100)
						else:
							b_list.append(0.0)
					else:
						# Carry over last known value or 0.0
						b_list.append(b_list[-1] if b_list else 0.0)
			
			# Final Safety: Trim/Pad to match daily_values length
			target_len = len(daily_values)
			for b_label, b_list in [('KOSPI', bench_kospi), ('KOSDAQ', bench_kosdaq)]:
				while len(b_list) < target_len:
					b_list.append(b_list[-1] if b_list else 0.0)
				if len(b_list) > target_len:
					del b_list[target_len:]
		
		# Stats data check
		print(f"[DEBUG] Simulation Length: {len(daily_values)}", flush=True)


		
		# Stats
		total_trades = len(trades)
		winning_trades = [t for t in trades if t['profit_pct'] > 0]
		losing_trades = [t for t in trades if t['profit_pct'] <= 0]
		
		win_count = len(winning_trades)
		loss_count = len(losing_trades)
		win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
		
		avg_profit = sum(t['profit_pct'] for t in winning_trades) / win_count if win_count > 0 else 0
		avg_loss = sum(t['profit_pct'] for t in losing_trades) / loss_count if loss_count > 0 else 0
		avg_return = sum(t['profit_pct'] for t in trades) / total_trades if total_trades > 0 else 0
		
		# Max consecutive losses
		max_consecutive_loss = 0
		current_consecutive = 0
		for trade in trades:
			if trade['profit_pct'] <= 0:
				current_consecutive += 1
				max_consecutive_loss = max(max_consecutive_loss, current_consecutive)
			else:
				current_consecutive = 0

		summary = {
			'initial_deposit': initial_deposit,
			'final_cash': final_balance,
			'total_profit': total_profit,
			'return_pct': return_pct,
			'total_trades': total_trades,
			'win_count': win_count,
			'loss_count': loss_count,
			'win_rate': win_rate,
			'avg_profit': avg_profit,
			'avg_loss': avg_loss,
			'avg_return': avg_return,
			'max_consecutive_loss': max_consecutive_loss,
			'mdd': mdd,
			'drawdown_series': drawdown_series,
			'portfolio_returns': portfolio_returns,
			'bench_kospi': bench_kospi,
			'bench_kosdaq': bench_kosdaq,
			'trades': trades
		}
		
		return summary
