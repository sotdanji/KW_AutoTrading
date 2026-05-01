# -*- coding: utf-8 -*-
"""
FormulaValidator - 수식 변환 검증 도구

변환된 파이썬 코드의 구문, 의미, 타입, 실행 가능성을 자동으로 검증합니다.
"""

import ast
import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any
from shared.hangul_converter import HangulVariableConverter

# execution_context 임포트 (헬퍼 함수 풀 컨텍스트 사용)
try:
	from shared.execution_context import get_execution_context as _get_exec_ctx
except ImportError:
	_get_exec_ctx = None

class FormulaValidator:
	"""수식 변환 결과 검증 도구"""
	
	def __init__(self):
		self.validation_results = {}
		self.converter = HangulVariableConverter()
	
	def validate_syntax(self, python_code: str) -> Tuple[bool, str]:
		"""
		구문 검증: 파이썬 코드가 문법적으로 올바른지 확인
		
		Returns:
			(success: bool, message: str)
		"""
		try:
			ast.parse(python_code)
			return True, "✅ 구문 검증 성공"
		except SyntaxError as e:
			return False, f"❌ 구문 오류: Line {e.lineno}: {e.msg}"
		except Exception as e:
			return False, f"❌ 예외 발생: {type(e).__name__}: {e}"
	
	def validate_semantics(self, python_code: str) -> Tuple[bool, str]:
		"""
		의미 검증: 필요한 변수(df, TI 등)가 사용되고 있는지 확인
		
		Returns:
			(success: bool, message: str)
		"""
		required_vars = {'df'}
		optional_vars = {'TI', 'pd', 'np'}
		
		found_required = all(var in python_code for var in required_vars)
		
		if not found_required:
			missing = [var for var in required_vars if var not in python_code]
			return False, f"❌ 필수 변수 누락: {', '.join(missing)}"
		
		# 최종 결과 변수 확인
		if 'cond' not in python_code:
			return False, "❌ 최종 결과 변수 'cond'가 없습니다"
		
		return True, "✅ 의미 검증 성공"
	
	def validate_type(self, python_code: str, sample_df: pd.DataFrame = None) -> Tuple[bool, str]:
		"""
		타입 검증: 실행 결과가 올바른 타입(pd.Series)인지 확인
		
		Returns:
			(success: bool, message: str)
		"""
		if sample_df is None:
			sample_df = self._create_sample_data()
		
		try:
			# execution_context 우선 사용 (헬퍼 함수 포함)
			if _get_exec_ctx is not None:
				exec_globals = _get_exec_ctx(sample_df)
			else:
				from shared.indicators import TechnicalIndicators as TI
				exec_globals = {'df': sample_df, 'TI': TI, 'pd': pd, 'np': np}
			
			local_vars = {}
			exec(python_code, exec_globals, local_vars)
			
			if 'cond' not in local_vars:
				return False, "❌ 'cond' 변수가 생성되지 않았습니다"
			
			cond = local_vars['cond']
			
			if not isinstance(cond, pd.Series):
				return False, f"❌ 결과 타입 오류: {type(cond).__name__} (예상: Series)"
			
			# Boolean 또는 숫자형 Series 확인
			if cond.dtype not in [np.bool_, np.int64, np.float64, bool, int, float]:
				return False, f"❌ 결과 dtype 오류: {cond.dtype}"
			
			return True, f"✅ 타입 검증 성공 (Series, dtype: {cond.dtype})"
			
		except Exception as e:
			return False, f"❌ 타입 검증 실패: {type(e).__name__}: {e}"
	
	def validate_execution(self, python_code: str, sample_df: pd.DataFrame = None) -> Tuple[bool, str]:
		"""
		실행 검증: 코드가 실제로 실행 가능한지 확인
		
		Returns:
			(success: bool, message: str)
		"""
		if sample_df is None:
			sample_df = self._create_sample_data()
		
		try:
			# execution_context 우선 사용 (헬퍼 함수 포함)
			if _get_exec_ctx is not None:
				exec_globals = _get_exec_ctx(sample_df)
			else:
				from shared.indicators import TechnicalIndicators as TI
				exec_globals = {'df': sample_df, 'TI': TI, 'pd': pd, 'np': np}
			
			local_vars = {}
			exec(python_code, exec_globals, local_vars)
			
			if 'cond' in local_vars:
				cond = local_vars['cond']
				true_count = cond.sum() if hasattr(cond, 'sum') else 0
				return True, f"✅ 실행 성공 (신호 {true_count}회 발생)"
			else:
				return False, "❌ 'cond' 변수가 생성되지 않았습니다"
				
		except Exception as e:
			import traceback
			error_detail = traceback.format_exc()
			return False, f"❌ 실행 실패: {type(e).__name__}: {e}\n{error_detail}"
	
	def validate_all(self, python_code: str, sample_df: pd.DataFrame = None) -> Dict[str, Any]:
		"""
		전체 검증: 구문, 의미, 타입, 실행을 모두 검증
		
		Returns:
			{
				'syntax': (bool, str),
				'semantics': (bool, str),
				'type': (bool, str),
				'execution': (bool, str),
				'overall_success': bool
			}
		"""
		results = {}
		
		# 1. 구문 검증
		syntax_ok, syntax_msg = self.validate_syntax(python_code)
		results['syntax'] = (syntax_ok, syntax_msg)
		
		if not syntax_ok:
			# 구문 오류 시 나머지 검증 스킵
			results['semantics'] = (False, "⏭️  구문 오류로 스킵")
			results['type'] = (False, "⏭️  구문 오류로 스킵")
			results['execution'] = (False, "⏭️  구문 오류로 스킵")
			results['overall_success'] = False
			return results
		
		# 2. 의미 검증
		sem_ok, sem_msg = self.validate_semantics(python_code)
		results['semantics'] = (sem_ok, sem_msg)
		
		# 3. 타입 검증
		type_ok, type_msg = self.validate_type(python_code, sample_df)
		results['type'] = (type_ok, type_msg)
		
		# 4. 실행 검증
		exec_ok, exec_msg = self.validate_execution(python_code, sample_df)
		results['execution'] = (exec_ok, exec_msg)
		
		# 전체 성공 여부
		results['overall_success'] = all([syntax_ok, sem_ok, type_ok, exec_ok])
		
		return results
	
	def print_validation_results(self, results: Dict[str, Any]):
		"""검증 결과를 보기 좋게 출력"""
		print("\n" + "="*70)
		print(" " * 25 + "검증 결과")
		print("="*70)
		
		for key in ['syntax', 'semantics', 'type', 'execution']:
			if key in results:
				success, message = results[key]
				print(f"{message}")
		
		print("="*70)
		if results['overall_success']:
			print("🎉 모든 검증 통과!")
		else:
			print("⚠️  일부 검증 실패")
		print("="*70)
	
	def _create_sample_data(self, periods: int = 100) -> pd.DataFrame:
		"""테스트용 샘플 데이터 생성"""
		np.random.seed(42)
		dates = pd.date_range(start='2024-01-01', periods=periods, freq='D')
		returns = np.random.normal(0.001, 0.02, periods)
		price = 10000 * (1 + returns).cumprod()
		
		df = pd.DataFrame({
			'date': dates,
			'open': price * (1 + np.random.uniform(-0.01, 0.01, periods)),
			'high': price * (1 + np.random.uniform(0, 0.02, periods)),
			'low': price * (1 + np.random.uniform(-0.02, 0, periods)),
			'close': price,
			'volume': np.random.randint(100000, 1000000, periods),
			'amount': (price * np.random.randint(100000, 1000000, periods)) / 1_000_000 # 주가 * 거래량 (백만원 단위)
		})
		
		# Ensure price constraints
		df['high'] = df[['high', 'close']].max(axis=1)
		df['low'] = df[['low', 'close']].min(axis=1)
		
		return df


def main():
	"""검증 도구 테스트"""
	validator = FormulaValidator()
	
	# 테스트 코드
	test_codes = [
		("간단한 수식", "cond = df['close'] > df['close'].rolling(20).mean()"),
		("복합 수식", """BBU = df['close'].rolling(20).mean() + df['close'].rolling(20).std() * 2
cond = df['close'] > BBU"""),
		("구문 오류", "cond = df['close'] >"),  # 의도적 오류
	]
	
	for name, code in test_codes:
		print(f"\n{'='*70}")
		print(f"테스트: {name}")
		print(f"{'='*70}")
		
		results = validator.validate_all(code)
		validator.print_validation_results(results)


if __name__ == "__main__":
	main()
