import logging
import datetime
from enum import Enum
from typing import Dict, List, Any
import pandas as pd

from .api import fetch_index_chart
from .config import get_api_config # config.py가 shared에 있는지 확인 필요

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
	BULL = "강세장"      # 공격적 매수, 수익 극대화
	SIDEWAYS = "횡보장"  # 박스권 대응, 매집주 위주
	BEAR = "약세장"      # 보수적 매매, 비중 축소
	CRASH = "폭락장"     # 매수 중단, 현금 확보

class MarketStatusEngine:
	"""
	지수 데이터(KOSPI, KOSDAQ)를 분석하여 현재 시장의 상태(Regime)를 판단하는 엔진.
	이 상태는 전체 자동매매 시스템의 공격성과 청산 전략의 기준이 됩니다.
	"""
	def __init__(self, token: str, mode: str = "PAPER"):
		self.token = token
		self.mode = mode
		from .config import get_api_config # 로컬 임포트로 순환 참조 방지 가능성 대비
		self.config = get_api_config()
		self.host_url = self.config['host_url']

	def get_current_regime(self) -> Dict[str, Any]:
		"""
		코스피와 코스닥 지수를 종합 분석하여 현재 시장 상태를 반환합니다.
		"""
		try:
			kospi_data = fetch_index_chart(self.host_url, "001", self.token, days=120)
			kosdaq_data = fetch_index_chart(self.host_url, "101", self.token, days=120)

			if not kospi_data or not kosdaq_data:
				logger.error("지수 데이터를 가져오는데 실패했습니다.")
				return self._default_status()

			kospi_status = self._analyze_index(kospi_data, "KOSPI")
			kosdaq_status = self._analyze_index(kosdaq_data, "KOSDAQ")

			# 두 지수 중 더 안 좋은 쪽을 기준으로 보수적 판단 (안전 우선)
			# 점수화 (Bull: 3, Sideways: 2, Bear: 1, Crash: 0)
			score_map = {
				MarketRegime.BULL: 3,
				MarketRegime.SIDEWAYS: 2,
				MarketRegime.BEAR: 1,
				MarketRegime.CRASH: 0
			}

			kospi_score = score_map[kospi_status['regime']]
			kosdaq_score = score_map[kosdaq_status['regime']]

			final_regime = MarketRegime.BEAR
			if kospi_score >= 3 and kosdaq_score >= 3:
				final_regime = MarketRegime.BULL
			elif kospi_score >= 2 and kosdaq_score >= 2:
				final_regime = MarketRegime.SIDEWAYS
			elif kospi_score == 0 or kosdaq_score == 0:
				final_regime = MarketRegime.CRASH
			else:
				final_regime = MarketRegime.BEAR

			return {
				'regime': final_regime,
				'kospi': kospi_status,
				'kosdaq': kosdaq_status,
				'timestamp': datetime.datetime.now().isoformat()
			}

		except Exception as e:
			logger.exception(f"Market Status 분석 중 오류 발생: {e}")
			return self._default_status()

	def _analyze_index(self, data: List[Dict], name: str) -> Dict[str, Any]:
		"""
		단일 지수 데이터를 분석하여 추세 및 이격을 계산합니다.
		"""
		df = pd.DataFrame(data)
		# [안실장 유지보수] 가격 컬럼 자동 감지 (날짜 컬럼 혼동 방지)
		close_col = None
		# [안실장 픽스] api.py에서 정규화된 'close_prc' 우선 참조
		priority_cols = ['close_prc', 'inds_cur_prc', 'clpr', 'stck_prpr', 'cur_prc']
		for pc in priority_cols:
			if pc in df.columns:
				close_col = pc
				break
		
		if not close_col:
			exclude_keywords = ['dt', 'date', '일자', 'time', '시간', 'seq']
			potential_cols = [c for c in df.columns if not any(k in c.lower() for k in exclude_keywords)]
			close_col = potential_cols[0] if potential_cols else df.columns[0]

		# Robust numeric conversion
		if df[close_col].dtype == object:
			df[close_col] = pd.to_numeric(df[close_col].astype(str).str.replace(',', ''), errors='coerce')
		else:
			df[close_col] = pd.to_numeric(df[close_col], errors='coerce')

		# [안실장 픽스] 데이터 정제 유효성 검사 (NaN 제거)
		df = df.dropna(subset=[close_col]).reset_index(drop=True)
		
		if df.empty:
			return {'name': name, 'price': 0, 'ma20': 0, 'disparity_20': 100, 'regime': MarketRegime.SIDEWAYS}

		df = df.sort_index(ascending=False).reset_index(drop=True)

		# api.py의 fetch_index_chart는 extend로 쌓으므로 순서 확인
		# 보통 API는 최신순으로 줌. 이평선 계산을 위해 과거->최신 순으로 변경
		df = df.iloc[::-1].reset_index(drop=True)

		# [안실장 가이드] 비정상 데이터 방어 (지수는 0이나 음수일 수 없으므로 오판 방지)
		current_price = df[close_col].iloc[-1]
		if current_price <= 0:
			# 데이터가 비정상이면 이전 데이터 중 정상인 것을 찾음
			valid_prices = df[df[close_col] > 0][close_col]
			if not valid_prices.empty:
				current_price = valid_prices.iloc[-1]
			else:
				return {
					'name': name, 'price': 0, 'ma20': 0, 'disparity_20': 100, 'regime': MarketRegime.SIDEWAYS
				}

		ma20 = df[close_col].rolling(window=20).mean().iloc[-1]
		ma60 = df[close_col].rolling(window=60).mean().iloc[-1]
		
		# 이평선 값이 비정상이면 분석 불가
		if ma20 <= 0:
			return {'name': name, 'price': current_price, 'ma20': 0, 'disparity_20': 100, 'regime': MarketRegime.SIDEWAYS}

		disparity_20 = (current_price / ma20) * 100
		
		# Regime 판단 로직
		# [안실장 고도화] 폭락장: 20일선 아래 5% 이상 이격 (패닉셀 구간)
		# 단, 이격도가 너무 낮으면 (예: 50% 미만) 데이터 오류로 보고 폭락에서 제외 (안전장치)
		if 50 < disparity_20 < 95:
			regime = MarketRegime.CRASH
		# 2. 강세장: 현재가 > 20일선 > 60일선 (정배열 초입 이상)
		elif current_price > ma20 and ma20 > ma60:
			regime = MarketRegime.BULL
		# 3. 약세장: 20일선 아래 2% 이상 이격 (조금 더 여유를 둠)
		elif disparity_20 < 98:
			regime = MarketRegime.BEAR
		# 4. 횡보장: 그 외 (20일선 근처 등)
		else:
			regime = MarketRegime.SIDEWAYS

		return {
			'name': name,
			'price': round(current_price, 2),
			'ma20': round(ma20, 2),
			'disparity_20': round(disparity_20, 2),
			'regime': regime
		}

	def _default_status(self) -> Dict[str, Any]:
		return {
			'regime': MarketRegime.BEAR, # 데이터 없을 땐 보수적으로
			'kospi': None,
			'kosdaq': None,
			'timestamp': datetime.datetime.now().isoformat(),
			'error': True
		}
