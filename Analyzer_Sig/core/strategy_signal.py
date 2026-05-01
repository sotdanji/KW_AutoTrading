from .daily_chart import get_daily_chart, get_daily_chart_continuous
from .minute_chart import get_minute_chart_continuous
from shared.indicators import TechnicalIndicators as TI
import numpy as np
import pandas as pd

def process_data(stk_cd, token, days=200):
	"""
	Fetches and preprocesses data for a stock.
	Returns: (DataFrame, None) on success, (None, error_message) on failure.
	"""
	# Use continuous query to fetch all required historical data
	# Index codes (KOSPI 001, KOSDAQ 101) have 3 digits
	if len(stk_cd) == 3:
		from .daily_chart import get_index_chart_continuous
		chart_data = get_index_chart_continuous(stk_cd, token=token, days=days)
	else:
		chart_data = get_daily_chart_continuous(stk_cd, token=token, days=days)
	
	if not chart_data:
		return None, f"API returned no data for {stk_cd}"
	
	# Relax data length check (especially for indices or new stocks)
	if len(chart_data) < 10:
		return None, f"Insufficient data: got {len(chart_data)} days"
	
	df = TI.preprocess_data(chart_data)
	if df is None:
		return None, f"Data preprocessing failed for {stk_cd}"
	
	# Calculate Indicators in Advance
	C = df['close']
	H = df['high']
	L = df['low']
	V = df['volume']
	O = df['open']
	
	# BB
	df['bbu'], _, _ = TI.bbands(C, 20, 2)
	
	# ATR & CCU
	atr20 = TI.atr(H, L, C, 20)
	c20_ema = TI.ema(C, 20)
	df['ccu'] = c20_ema + (atr20 * 2)
	
	# MACD
	df['macd'], df['macd_sig'] = TI.macd(C)
	
	# Stochastic
	_, df['slow_k'] = TI.stochastics_slow(H, L, C, 12, 5, 5)
	df['slow_d'] = TI.ema(df['slow_k'], 5)
	
	# CCI
	df['cci'] = TI.cci(H, L, C, 14)
	df['cci_sig'] = TI.ema(df['cci'], 9)
	
	# RSI
	df['rsi'] = TI.rsi(C, 14)
	df['rsi_sig'] = TI.ema(df['rsi'], 9)
	
	# DMI
	df['dip'], df['dim'] = TI.dmi(H, L, C, 14)
	
	# OBV
	df['obv'] = TI.obv(C, V)
	df['obv_sig'] = TI.ema(df['obv'], 9)
	
	# MFI
	df['mfi'] = TI.mfi(H, L, C, V, 14)
	
	# SAR
	df['sar'] = TI.sar(H, L)
	
	# MA
	df['ma10'] = TI.sma(C, 10)
	df['ma60'] = TI.sma(C, 60)
	
	return df, None  # Success: return (DataFrame, None)

def process_minute_data(stk_cd, token, days=5):
	"""
	Fetches and preprocesses MINUTE data for a stock.
	days: approximate number of days to fetch (1 day approx 381 bars)
	"""
	# 90 days of minute data is huge (~34k bars). Let's use max_pages effectively.
	# If 1 page = 600 bars, then days=5 needs ~3 pages. days=90 needs ~60 pages.
	needed_pages = max(5, int(days * 381 / 500)) 
	chart_data = get_minute_chart_continuous(stk_cd, token, tick='1', max_pages=needed_pages)
	
	if not chart_data:
		return None, f"No minute data for {stk_cd}"
		
	# Convert to DataFrame
	df = pd.DataFrame(chart_data)
	
	# Mapping based on get_minute_chart headers (which uses Kiwoom raw keys if not normalized)
	# In minute_chart.py, get_minute_chart returns raw 'stk_min_pole_chart_qry'
	# Let's normalize it to be compatible with TI.preprocess_data or manual mapping.
	
	# Field Mapping: stk_min_pole_chart_qry has [cntr_tm, open_pric, high_pric, low_pric, cur_prc, trde_qty, acc_trde_qty]
	# Some columns might be missing if different TR is used.
	rename_map = {
		'cntr_tm': 'dt',
		'open_pric': 'open',
		'high_pric': 'high',
		'low_pric': 'low',
		'cur_prc': 'close',
		'trde_qty': 'volume'
	}
	df.rename(columns=rename_map, inplace=True)
	
	# Convert numeric
	for col in ['open', 'high', 'low', 'close', 'volume']:
		if col in df.columns:
			df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
			
	# Sort by time
	df = df.sort_values('dt').reset_index(drop=True)
	
	# Add derived fields for strategy compatibility
	# time (HHMMSS)
	df['time'] = df['dt'].astype(str).str[8:].astype(int)
	df['date'] = df['dt'].astype(str).str[:8]
	
	# DayOpen (시가) - Group by date
	df['DayOpen'] = df.groupby('date')['open'].transform('first')
	
	# PreDayClose (전일종가)
	# This is tricky with only minute data. But we can shift group-wise.
	daily_closes = df.groupby('date')['close'].last().shift(1)
	df['PreDayClose'] = df['date'].map(daily_closes).fillna(df['open']) # Fallback to today's open if no yesterday
	
	# Add indicators if needed (BB, MACD etc)
	C = df['close']
	df['bbu'], _, _ = TI.bbands(C, 20, 2)
	
	return df, None

def check_signal_at(df, idx):
	"""
	Checks signal at a specific dataframe index.
	df: Preprocessed DataFrame with indicators
	idx: The index to check (must be >= 2 for lookback)
	"""
	if idx < 2 or idx >= len(df):
		return False
		
	row = df.iloc[idx]
	prev1 = df.iloc[idx-1]
	prev2 = df.iloc[idx-2]
	
	C = df['close']
	O = df['open']
	
	# === [1] Target Line Logic ===
	# A1: Break BBU (Last 3 candles including current)
	# Note: When backtesting, 'current' is 'idx'.
	# Check if (idx-2, idx-1, idx) satisfy.
	
	# Vectorized logic in previous verify was:
	# (C.shift(2) > bbu.shift(2)) | ...
	# Here we access row values directly.
	
	cond_a1 = (prev2['close'] > prev2['bbu']) or \
			  (prev1['close'] > prev1['bbu']) or \
			  (row['close'] > row['bbu'])
			  
	cond_a2 = (prev2['close'] > prev2['ccu']) or \
			  (prev1['close'] > prev1['ccu']) or \
			  (row['close'] > row['ccu'])
			  
	cond_a3 = (prev2['open'] < prev2['close']) and \
			  (prev1['open'] <= prev1['close']) and \
			  (row['open'] > row['close'])
			  
	# cond_b checks if the "Pattern" occurred at 'idx'.
	# BUT, the strategy is:
	# 1. Find the MOST RECENT pattern (cond_b == True) in the past (before 'idx').
	# 2. Get that candle's Open as TargetLine.
	# 3. Check if 'idx' Close > TargetLine (and PrevClose <= TargetLine).
	
	# So we need to search backwards from idx-1.
	target_date_idx = -1
	for i in range(idx-1, 1, -1): # Scan backwards
		r = df.iloc[i]
		p1 = df.iloc[i-1]
		p2 = df.iloc[i-2]
		
		c_a1 = (p2['close'] > p2['bbu']) or (p1['close'] > p1['bbu']) or (r['close'] > r['bbu'])
		c_a2 = (p2['close'] > p2['ccu']) or (p1['close'] > p1['ccu']) or (r['close'] > r['ccu'])
		c_a3 = (p2['open'] < p2['close']) and (p1['open'] <= p1['close']) and (r['open'] > r['close'])
		
		if (c_a1 or c_a2) and c_a3:
			target_date_idx = i
			break
			
	if target_date_idx == -1:
		return False
		
	target_line = df.iloc[target_date_idx]['open']
	
	# === [2] 10 Indicators Score ===
	score = 0
	if row['macd'] > row['macd_sig']: score += 1
	if row['slow_k'] > row['slow_d']: score += 1
	if row['cci'] > row['cci_sig']: score += 1
	if row['rsi'] > row['rsi_sig']: score += 1
	if row['dip'] > row['dim']: score += 1
	if row['close'] > row['ma10']: score += 1
	if row['obv'] > row['obv_sig']: score += 1
	if row['mfi'] > 50: score += 1
	if row['close'] > row['sar']: score += 1
	if row['close'] > row['ma60']: score += 1
	
	# === [3] Final Check ===
	cond_cross_up = (prev1['close'] <= target_line) and (row['close'] > target_line)
	
	if score >= 7 and cond_cross_up:
		return True
		
	return False

def check_signal(stk_cd, token):
	"""
	Legacy wrapper for instant check (uses latest data).
	"""
	df = process_data(stk_cd, token)
	if df is None or len(df) == 0: return False
	return check_signal_at(df, len(df)-1)
