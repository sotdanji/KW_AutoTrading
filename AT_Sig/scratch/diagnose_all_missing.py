import os
import sys
import pandas as pd
import json
from datetime import datetime

# 프로젝트 루트 및 AT_Sig 경로 설정
scratch_dir = os.path.dirname(os.path.abspath(__file__))
at_sig_dir = os.path.dirname(scratch_dir)
project_root = os.path.dirname(at_sig_dir)

# 우선순위: 시본 프로젝트 루트 -> AT_Sig 루트
if at_sig_dir not in sys.path:
    sys.path.insert(0, at_sig_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 이제 상대 경로 없이 임포트 시도
try:
    from strategy_runner import StrategyRunner
    from data_manager import DataManager
    from login import fn_au10001 as get_token
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def dry_run_diagnose(code, name):
	print(f"--- [진단 시작] {name} ({code}) ---")
	
	try:
		token = get_token()
		if not token:
			print("❌ 토큰 발급 실패")
			return

		# 1. 활성화된 전략 로드
		settings_path = os.path.join(at_sig_dir, 'settings.json')
		if not os.path.exists(settings_path):
			# 대안 경로
			settings_path = os.path.join(project_root, 'AT_Sig', 'settings.json')
			
		with open(settings_path, 'r', encoding='utf-8') as f:
			settings = json.load(f)
		
		strategy_name = settings.get('active_strategy', '02_전고음봉시가돌파(일봉)')
		strategy_dir = os.path.join(project_root, 'shared', 'strategies')
		strategy_path = os.path.join(strategy_dir, f"{strategy_name}.json")
		
		if not os.path.exists(strategy_path):
			print(f"Error: Strategy file not found: {strategy_path}")
			return

		with open(strategy_path, 'r', encoding='utf-8') as f:
			strategy_data = json.load(f)
		
		strategy_code = strategy_data.get('python_code', '')
		print(f"Strategy: {strategy_name}")

		# 2. 데이터 로드
		dm = DataManager()
		chart_data = dm.get_daily_chart(code, token, use_cache=False)
		
		if not chart_data:
			print("Error: Chart data loading failed")
			return
		
		print(f"Data Points: {len(chart_data)}")

		# 3. 전략 평가 시뮬레이션
		from shared.indicators import TechnicalIndicators as TI
		from shared.execution_context import get_execution_context
		
		df = TI.preprocess_data(chart_data)
		if df is None or df.empty:
			print("Error: Data Preprocess Failed")
			return

		# 현재가 (데이터의 마지막 종가 사용)
		current_price = df.iloc[-1]['close']
		print(f"Current Price (Close): {current_price:,.0f}")
		
		exec_globals = get_execution_context(df)
		local_vars = {}
		
		# 전략 코드 실행
		exec(strategy_code, exec_globals, local_vars)
		
		if 'cond' in local_vars:
			cond = local_vars['cond']
			is_signal = bool(cond.iloc[-1]) if hasattr(cond, 'iloc') else bool(cond)
			score = local_vars.get('score', 0)
			
			target = local_vars.get('TargetLine', 0)
			if hasattr(target, 'iloc'): target = target.iloc[-1]
			
			msg = local_vars.get('msg', 'No Msg')
			
			print(f"RESULT: {'[SIGNAL!!]' if is_signal else '[NO SIGNAL]'}")
			print(f"   - Score: {score}")
			print(f"   - TargetLine: {target:,.0f}")
			print(f"   - Msg: {msg}")
			
			if not is_signal:
				# 미체결 사유 분석
				last_c = df.iloc[-1]['close']
				if last_c <= target:
					print(f"   Reason: Price ({last_c:,.0f}) <= TargetLine ({target:,.0f}) [Breakout Fail]")
				if score < 7:
					print(f"   Reason: Score ({score}) < 7")
		else:
			print("Error: 'cond' variable not found in strategy execution")
			
	except Exception as e:
		import traceback
		print(f"Error occurred for {name}: {e}")
		traceback.print_exc()

if __name__ == "__main__":
	# 요청하신 종목들 일괄 진단
	stocks = [
		("062040", "산일전기"),
		("039610", "화성밸브"),
		("032640", "LG유플러스"),
		("432720", "퀄리타스반도체"),
		("368770", "파이버프로")
	]
	
	for code, name in stocks:
		dry_run_diagnose(code, name)
		print("=" * 60)
