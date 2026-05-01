import asyncio
import os
import sys
import json
import pandas as pd
from datetime import datetime

# 프로젝트 루트 및 AT_Sig 경로 설정
project_root = r"d:\AG\KW_AutoTrading"
at_sig_dir = os.path.join(project_root, "AT_Sig")

# sys.path 설정 (최우선 순위로 삽입하여 모듈 검색 보장)
if at_sig_dir not in sys.path:
	sys.path.insert(0, at_sig_dir)
if project_root not in sys.path:
	sys.path.insert(0, project_root)

# 이제 모듈 임포트 (AT_Sig 내부 모듈들)
try:
	from login import fn_au10001
	from data_manager import DataManager
	from strategy_runner import StrategyRunner
	from shared.indicators import TechnicalIndicators as TI
except ImportError as e:
	print(f"Import Error: {e}")
	print(f"Current sys.path: {sys.path}")
	sys.exit(1)

async def debug_amotech():
	print("--- Amotech (052710) Strategy Debug ---")
	stk_cd = "052710"
	
	# 1. 토큰 획득
	token = fn_au10001()
	if not token:
		print("Failed to get token")
		return

	# 2. 일봉 데이터 조회
	dm = DataManager()
	chart_data = dm.get_daily_chart(stk_cd, token=token, use_cache=False)
	
	if not chart_data:
		print("Failed to fetch chart data")
		return

	# 3. 전략 로직 (shared/strategies/에서 로드)
	# 파일명 수정: 02_전고음봉시가돌파(일봉).json
	st_path = os.path.join(project_root, 'shared', 'strategies', '02_전고음봉시가돌파(일봉).json')
	if not os.path.exists(st_path):
		print(f"Strategy file not found: {st_path}")
		# 파일 목록 출력 (디버깅용)
		st_dir = os.path.join(project_root, 'shared', 'strategies')
		if os.path.exists(st_dir):
			print(f"Available strategies in {st_dir}:")
			for f in os.listdir(st_dir):
				print(f" - {f}")
		return
		
	with open(st_path, 'r', encoding='utf-8') as f:
		st_json = json.load(f)
		strategy_code = st_json.get('python_code', '')

	# 4. 분석 실행
	sr = StrategyRunner()
	# 현재가 시뮬레이션 (마지막 데이터의 종가 기준)
	last_entry = chart_data[-1]
	current_price = float(last_entry.get('stck_prpr') or last_entry.get('close_prc') or last_entry.get('cur_prc', 0))
	
	print(f"Latest Chart Date: {last_entry.get('stck_bsop_date') or last_entry.get('trd_dt')}")
	print(f"Current Price: {current_price}")

	# 시그널 발생 여부 확인
	is_signal = sr.check_signal(stk_cd, token, strategy_code, current_price, min_bars=70)
	print(f"Signal Result: {is_signal}")

	# 최근 데이터 로직 상세 출력 (디버깅용)
	df = TI.preprocess_data(chart_data)
	if df is not None:
		from shared.execution_context import get_execution_context
		ctx = get_execution_context(df, day_open_override=current_price)
		
		# 전략 로직 수동 시뮬레이션
		C = ctx['C']; O = ctx['O']; H = ctx['H']; L = ctx['L']
		
		# 예시 인디케이터 계산 (전략 코드의 A1, A2, A3 참조)
		BBU = ctx['BBU'](20, 2)
		CCU = ctx['ema'](C, 20) + (ctx['atr'](20) * 2)
		
		A1 = ctx['sum'](C > BBU, 20) > 0
		A2 = ctx['sum'](C > CCU, 20) > 0
		A3 = (O.shift(2) < C.shift(2)) & (O.shift(1) <= C.shift(1)) & (O > C)
		
		B = (A1 | A2) & A3
		TargetLine = ctx['ValueWhen'](1, B, O)
		cond = ctx['CrossUp'](C, TargetLine)
		
		print("\nLast 10 Days Logic Check:")
		debug_df = pd.DataFrame({
			'Date': df.index,
			'Open': O,
			'Close': C,
			'BBU': BBU,
			'CCU': CCU,
			'A1': A1,
			'A2': A2,
			'A3': A3,
			'B': B,
			'TargetLine': TargetLine,
			'Cond': cond
		}).tail(10)
		print(debug_df.to_string())

if __name__ == "__main__":
	asyncio.run(debug_amotech())
