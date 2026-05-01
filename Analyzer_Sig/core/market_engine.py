"""
MarketEngine: Lead_Sig V4 통합 엔진

ThemeRadar(Top-Down 메인) + LeaderFinder(주도주 식별)를 조합하여
기존 MarketAnalyzer와 동일한 인터페이스를 제공합니다.

dashboard.py에서 import만 변경하면 작동하도록 설계되었습니다:
  from core.market_engine import MarketEngine as MarketAnalyzer
"""

import time
from core.data_fetcher import DataFetcher
from core.theme_radar import ThemeRadar
from core.leader_finder import LeaderFinder
from core.alert_manager import AlertManager
from core.logger import get_logger

from config import THEME_RANK_COUNT

logger = get_logger(__name__)

# 테마 캐시 유효 시간 (초)
THEME_CACHE_DURATION = 5


class MarketEngine:
	"""
	Lead_Sig V4 Top-Down 통합 엔진.
	
	Top-Down(테마 지수 직접 조회 → 전수조사)을 메인으로,
	Bottom-Up(시장 Top 200)을 교차검증 용도로 사용합니다.
	"""
	
	def __init__(self, mode="PAPER"):
		logger.info(f"[Engine] MarketEngine Top-Down 초기화 (mode={mode})")
		
		self.fetcher = DataFetcher(mode=mode)
		self.radar = ThemeRadar(self.fetcher)
		self.finder = LeaderFinder(self.fetcher)
		self.alert_manager = AlertManager()
		
		# 캐시
		self._theme_cache = None
		self._theme_cache_time = 0
		self._analysis_cache = {}       # {theme_name: ThemeAnalysisResult}
		self._analysis_cache_time = 0
		
		# 기존 호환용 (dashboard.py에서 self.analyzer.loader 등 참조 시)
		self.loader = _DummyLoader()
	
	def initialize_loader(self):
		"""
		기존 호환: PreMarketLoader 초기화.
		V4에서는 Top-Down 테마 스냅샷을 수집합니다.
		"""
		logger.info("[Engine] Top-Down 초기 스냅샷 수집 시작...")
		
		# 첫 스냅샷 수집 (이후 매 주기마다 추가 수집)
		success = self.radar.take_snapshot()
		
		if success:
			logger.info(f"[Engine] 초기 스냅샷 수집 완료 ({self.radar.snapshot_count}개 보유)")
		else:
			logger.warning("[Engine] 초기 스냅샷 수집 실패 - 다음 주기에 재시도")
		
		self.loader.is_initialized = True
	
	def get_ranked_data(self, category="Themes", limit=8):
		"""
		기존 호환: 테마 랭킹 데이터 반환.
		
		V4에서는 Top-Down(테마 지수) 기반이며,
		전수조사된 종목 + 교차검증 데이터를 포함합니다.
		"""
		if category == "Sectors":
			# V3에서는 섹터 랭킹을 제공하지 않음 (요청 시 빈 리스트)
			return []
		
		# 1. 새 스냅샷 수집
		self.radar.take_snapshot()
		
		# 2. 급류 테마 탐지
		hot_themes = self.radar.get_hot_themes(limit=limit)
		
		# 2.5 초기 폭발력/VI 감지 (장 초반 급등/거래량 집중)
		from concurrent.futures import ThreadPoolExecutor, as_completed
		import datetime
		
		# 장초반(09:00 ~ 10:00) 여부 확인 (테스트를 위해 주석처리 후 항시 동작 가능케 함)
		now = datetime.datetime.now()
		is_early_morning = (9 <= now.hour < 10)
		
		# (옵션) 장 초반에만 알람 발생시키려면 아래 주석 해제
		# if is_early_morning:
		new_alerts = []
		if hot_themes:
			def _check_spike(stock):
				code = stock.get('code')
				price = stock.get('price', 0)
				vol = stock.get('volume', 0)
				
				if code and price > 0 and vol > 0:
					vi_data = self.fetcher.get_stock_vi_and_vol_data(code, price, vol)
					return self.alert_manager.check_and_alert(stock, vi_data)
				return None

			# 상위 1~3개 테마의 대장주(top_members 의 상위 3개)만 추출 (초기 폭발력) 
			# 및 4~10위 후발주 추출 (낙수효과 순환매)
			spike_candidates = []
			spillover_candidates = []
			
			for t in hot_themes[:3]:
				members = t.get('top_members', [])
				spike_candidates.extend(members[:3])
				
				# 4위부터 10위까지의 후발주들
				if len(members) > 3:
					spillover_candidates.extend(members[3:10])
				
			with ThreadPoolExecutor(max_workers=5) as executor:
				# 1. 대장주 초기폭발 검사
				futures_spike = [executor.submit(_check_spike, s) for s in spike_candidates]
				for f in as_completed(futures_spike):
					try:
						msg = f.result()
						if msg:
							new_alerts.append(msg)
							logger.info(f"[Alert] {msg}")
					except Exception:
						pass
				
				# 2. 후발주 낙수효과 (순환매) 검사
				# 후발주 중에서 갑자기 거래량/호가 상승세가 강한 종목을 포착
				def _check_spillover(stock):
					code = stock.get('code')
					price = stock.get('price', 0)
					vol = stock.get('volume', 0)
					rate = stock.get('rate', 0.0)
					name = stock.get('name')
					
					# 후발주(4위 이하)인데도 등락률이 5% 이상으로 치고 올라오거나
					# 순간 거래량이 급증하는 경우 낙수효과로 판단
					if code and price > 0 and vol > 0:
						vi_data = self.fetcher.get_stock_vi_and_vol_data(code, price, vol)
						
						# 거래량 폭발(전일 대비 300% 이상) 이거나 등락률이 급등(5% 이상)
						# AlertManager를 재사용하되 커스텀 메시지를 전달
						is_vol_spike = vi_data.get('vol_ratio', 0) > 300.0
						if is_vol_spike or rate >= 5.0:
							
							import time
							now = time.time()
							last_alert = self.alert_manager.alert_cache.get(f"{code}_spillover", 0)
							if now - last_alert < self.alert_manager.cooldown_seconds:
								return None
							
							self.alert_manager.alert_cache[f"{code}_spillover"] = now
							
							causes = []
							if is_vol_spike: causes.append("거래량 300%↑")
							if rate >= 5.0: causes.append("등락률 5%↑")
							
							msg = f"[💧 낙수효과 포착] {name}({code}) | " + ", ".join(causes)
							return msg
					return None
					
				futures_spill = [executor.submit(_check_spillover, s) for s in spillover_candidates]
				for f in as_completed(futures_spill):
					try:
						msg = f.result()
						if msg:
							new_alerts.append(msg)
							logger.info(f"[Alert] {msg}")
					except Exception:
						pass

		# 3. UI 호환 형식으로 변환 (V4: 교차검증 + 전수조사 데이터 포함)
		result = []
		for theme in hot_themes:
			result.append({
				'name': theme['name'],
				'change': theme['rate'],
				'volume': theme.get('hot_member_count', 0),
				'score': theme['momentum_score'],
				'velocity': theme.get('velocity', 0),
				'acceleration': theme.get('acceleration', 0),
				'theme_code': theme.get('code', ''),
				'top_members': theme.get('top_members', None),
				'cohesion_ratio': theme.get('cohesion_ratio', 0),
				'cross_validated_count': theme.get('cross_validated_count', 0),
				'is_sector': False,
				'attention_score': theme['momentum_score'],  # UI 호환
				'momentum_score': theme['momentum_score']    # 트리맵 정렬용
			})
			
		if new_alerts:
			result.append({
				'is_system_alert': True,
				'messages': new_alerts
			})
		
		return result[:limit] if not new_alerts else result[:limit+1]
	
	def get_themes_cached(self):
		"""
		기존 호환: 캐시된 테마 데이터 반환 (5초 캐시).
		"""
		current_time = time.time()
		
		if (self._theme_cache is None or
			current_time - self._theme_cache_time > THEME_CACHE_DURATION):
			
			self._theme_cache = self.get_ranked_data("Themes", limit=10)
			self._theme_cache_time = current_time
		
		return self._theme_cache
	
	def get_theme_stocks_direct(self, theme_name):
		"""
		기존 호환: 특정 테마의 종목 리스트 (주도주 분석 포함).
		"""
		return self.get_lead_signals_for_theme(theme_name)
	
	def get_lead_signals_for_theme(self, theme_name):
		"""
		기존 호환: 특정 테마의 주도주 분석 결과 반환.
		
		LeaderFinder를 통해 3중 필터를 적용합니다.
		"""
		# 테마 가속도 정보 조회 (캐시에서)
		theme_rate = 0.0
		theme_accel = 0.0
		theme_code = ''
		top_members = None
		
		# 현재 캐시된 테마 데이터에서 정보 확인
		if self._theme_cache:
			for t in self._theme_cache:
				clean_name = t['name'].replace('(S)', '').strip()
				if clean_name == theme_name.replace('(S)', '').strip():
					theme_rate = t.get('change', 0)
					theme_accel = t.get('acceleration', 0)
					theme_code = t.get('theme_code', '')
					top_members = t.get('top_members', None)
					break
		
		# 코드가 없으면 Radar에서 조회
		if not theme_code:
			theme_code = self.radar.get_theme_code(theme_name)
		
		# [V5] 시장 지배력 계산을 위한 전체 시장 거래대금 확보
		total_market_value = 0
		if self.radar.snapshots:
			total_market_value = getattr(self.radar.snapshots[-1], 'total_market_value', 0)
		
		# LeaderFinder로 분석
		analysis = self.finder.analyze_theme(
			theme_name=theme_name,
			theme_rate=theme_rate,
			theme_acceleration=theme_accel,
			theme_code=theme_code,
			stocks=top_members,
			total_market_value=total_market_value
		)
		
		# 결과 반환 (기존 형식 호환: 종목 리스트)
		leaders = analysis.leaders if analysis.leaders else []
		
		# [Fix] 필터링 완전 철폐: 10개까지 무조건 보여줌 (하락장 대응)
		# "왜 종목이 적은가"에 대한 최종 해결: 등락률이 마이너스여도 테마 내 상대적 순위를 보여줌
		if not leaders:
			return []
			
		final = []
		for s in leaders[:10]: # 등락률 순 top 10
			final.append(s)
				
		return final
	
	def get_all_themes_for_stats(self):
		"""
		통계/전광판용: 전체 테마 데이터 반환.
		ThemeRadar의 최신 스냅샷에서 추출합니다.
		"""
		return self.radar.get_all_themes_snapshot()

	def get_10min_momentum_data(self, limit=30):
		"""
		[10분 등락률] 추적 전용 데이터 반환
		"""
		return self.radar.get_10min_momentum_data(limit=limit)

	def get_program_trading_data(self):
		"""
		[프로그램 매매] 상위 50 및 시장 추이 데이터 반환 (ka90003, ka90007)
		"""
		# [Fix] 수집 로직을 DataFetcher로 일원화하여 토큰 자동 갱신 보호 적용
		return self.fetcher.get_program_trading_data()

	def get_stock_program_trend(self, stk_cd):
		"""
		[종목별 프로그램] 시간별 추이 조회 (ka90008)
		"""
		if self.fetcher.mode == "PAPER":
			import random
			import datetime
			now = datetime.datetime.now()
			return [{
				"tm": (now - datetime.timedelta(minutes=i*1)).strftime("%H%M00"),
				"cur_prc": str(random.randint(50000, 60000)),
				"prm_netprps_amt": str(random.randint(-1000, 1000)),
				"prm_netprps_amt_irds": str(random.randint(-100, 100))
			} for i in range(20)]
			
		from shared.api import fetch_stock_program_trend_ka90008
		return fetch_stock_program_trend_ka90008(self.fetcher._get_host_url("REAL"), self.fetcher.token, stk_cd)

	def get_stock_daily_program_trend(self, stk_cd):
		"""
		[종목별 일별 프로그램] 추이 조회 (ka90013)
		"""
		if self.fetcher.mode == "PAPER":
			import random
			import datetime
			now = datetime.datetime.now()
			return [{
				"dt": (now - datetime.timedelta(days=i)).strftime("%Y%m%d"),
				"cur_prc": str(random.randint(50000, 60000)),
				"prm_netprps_amt": str(random.randint(-5000, 5000)),
				"prm_netprps_amt_irds": str(random.randint(-500, 500))
			} for i in range(10)]
			
		# ka90013: 종목일별프로그램매매추이
		from shared.api import fetch_stock_program_daily_ka90013
		return fetch_stock_program_daily_ka90013(self.fetcher._get_host_url("REAL"), stk_cd, self.fetcher.token, days=20)


class _DummyLoader:
	"""
	기존 호환용: PreMarketLoader 대체 더미.
	dashboard.py에서 self.analyzer.loader.is_initialized 등 참조 시 사용.
	"""
	def __init__(self):
		self.is_initialized = False
		self.daily_cache = {}
		self.market_universe = {}
	
	def initialize_universe(self):
		self.is_initialized = True
	
	def get_indicator_status(self, code, current_price):
		return {}
