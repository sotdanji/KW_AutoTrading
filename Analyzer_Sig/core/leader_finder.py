"""
LeaderFinder: 급류 테마 내 주도주 식별 모듈

3중 필터를 적용하여 "진짜 주도주"를 발굴합니다:
  Filter 1: 테마 가속도 (ThemeRadar → 이미 통과)
  Filter 2: 동반상승 확인 (Cohesion Check)
  Filter 3: 주도주 식별 (Leadership Score)
"""

from core.logger import get_logger

logger = get_logger(__name__)

# === 동반상승 판정 기준 ===
COHESION_MIN_CHANGE = 2.0     # 동반상승으로 인정할 최소 등락률 (%)
COHESION_MIN_COUNT = 3        # 최소 동반상승 종목 수
COHESION_MIN_RATIO = 0.15     # 최소 동반상승 비율 (종목수 대비)

# === 주도주 판정 기준 ===
LEADER_RATE_DOMINANCE_MIN = 1.2    # 등락률 지배력 최소값
LEADER_VOLUME_DOMINANCE_MIN = 0.10  # 거래대금 집중도 최소값 (10%)

# === 위험 신호 기준 ===
CAUTION_UPPER_WICK_MAX = 3.0   # 윗꼬리 비율 경고 (%)
CAUTION_GAP_START_MAX = 15.0   # 시가갭 과열 경고 (%)


class ThemeAnalysisResult:
	"""테마 분석 결과 구조체"""
	__slots__ = [
		'theme_name', 'theme_code', 'theme_rate', 'theme_acceleration',
		'is_valid', 'cohesion_ratio', 'rising_count', 'total_stocks',
		'leaders', 'rejection_reason'
	]
	
	def __init__(self, theme_name, theme_code='', theme_rate=0.0, theme_acceleration=0.0):
		self.theme_name = theme_name
		self.theme_code = theme_code
		self.theme_rate = theme_rate
		self.theme_acceleration = theme_acceleration
		self.is_valid = False
		self.cohesion_ratio = 0.0
		self.rising_count = 0
		self.total_stocks = 0
		self.leaders = []
		self.rejection_reason = ''


class LeaderFinder:
	"""
	급류 테마 내에서 3중 필터를 적용하여 주도주를 식별합니다.
	"""
	
	def __init__(self, data_fetcher):
		self.fetcher = data_fetcher
	
	def analyze_theme(self, theme_name, theme_rate=0.0, theme_acceleration=0.0, theme_code='', stocks=None, total_market_value=0):
		"""
		특정 테마의 구성 종목을 분석하여 주도주를 식별합니다.
		
		Args:
			theme_name: 테마 이름
			theme_rate: 테마 등락률
			theme_acceleration: 테마 가속도
			theme_code: 테마 코드
			stocks: 미리 포착된 주도주 리스트 (Bottom-Up 방식 지원)
			total_market_value: [V5] 시장 전체 거래대금 (마켓 지배력 계산용)
			
		Returns:
			ThemeAnalysisResult
		"""
		result = ThemeAnalysisResult(theme_name, theme_code, theme_rate, theme_acceleration)
		
		# 1. 종목 데이터 (입력받은 주도 종목 우선 사용, 없으면 API 조회)
		if stocks is None:
			stocks = self._fetch_theme_stocks(theme_name, theme_code)
		
		if not stocks:
			result.rejection_reason = '종목 데이터 없음'
			return result
		
		result.total_stocks = len(stocks)
		
		# 2. Filter 2: 동반상승 확인 (Cohesion Check) 
		# [Fix] 하락장 대응: 동반상승 기준(COHESION_MIN_CHANGE)을 테마 평균 등락률에 맞춰 유연하게 적용
		# 테마가 약할 때는 0.5%만 올라도 동반상승으로 인정
		dynamic_min_change = max(0.5, theme_rate * 0.5) if theme_rate > 0 else 0.5
		
		rising_stocks = [s for s in stocks if s['change'] >= dynamic_min_change]
		result.rising_count = len(rising_stocks)
		result.cohesion_ratio = len(rising_stocks) / len(stocks) if stocks else 0
		
		# 필터링 조건 완화
		if len(rising_stocks) < 2 and stocks is None: 
			result.rejection_reason = f'동반상승 부족 ({len(rising_stocks)})'
			result.leaders = self._score_stocks(stocks)
			return result
		
		# 3. Filter 3: 주도주 식별
		scored_stocks = self._score_stocks(stocks, total_market_value)
		result.leaders = scored_stocks
		result.is_valid = True
		
		if scored_stocks:
			top = scored_stocks[0]
			logger.info(
				f"[Leader] {theme_name} → 대장: {top['name']} "
				f"(등락률 {top['change']:.1f}%, 지배력 {top.get('rate_dominance', 0):.2f}, "
				f"집중도 {top.get('volume_dominance', 0):.1%})"
			)
		
		return result
	
	def analyze_themes_batch(self, hot_themes):
		"""
		여러 급류 테마를 일괄 분석합니다.
		
		Args:
			hot_themes: ThemeRadar.get_hot_themes() 결과 리스트
			
		Returns:
			list[ThemeAnalysisResult]: 유효한 결과만 (is_valid=True)
		"""
		results = []
		
		for theme in hot_themes:
			analysis = self.analyze_theme(
				theme_name=theme['name'],
				theme_rate=theme['rate'],
				theme_acceleration=theme.get('acceleration', 0.0),
				theme_code=theme.get('code', ''),
				stocks=theme.get('top_members', None) # Bottom-Up 에서 미리 뽑은 종목 대입
			)
			results.append(analysis)
		
		# 유효한 결과를 acceleration 순으로 정렬
		valid = [r for r in results if r.is_valid]
		invalid = [r for r in results if not r.is_valid]
		
		valid.sort(key=lambda x: x.theme_acceleration, reverse=True)
		
		logger.info(
			f"[Leader] 일괄 분석 완료: {len(hot_themes)}개 → "
			f"유효 {len(valid)}개, 탈락 {len(invalid)}개"
		)
		
		# 유효한 것 우선, 그 다음 무효한 것 (UI에서 참고 가능하도록)
		return valid + invalid
	
	def _score_stocks(self, stocks, total_market_value=0):
		"""
		종목별 주도력 점수를 계산합니다.
		
		주도력 = (등락률_지배력 × 거래대금_집중도) + (마켓_지배력 × 10)
		+ 캔들 품질 보정 (윗꼬리, 갭 패널티)
		"""
		if not stocks:
			return []
		
		# === 테마 전체 통계 계산 ===
		# 거래대금 = 가격 × 거래량
		total_trading_value = 0
		total_change = 0
		valid_count = 0
		
		for s in stocks:
			price = abs(s.get('price', 0))
			volume = s.get('volume', 0)
			trading_value = price * volume
			s['_trading_value'] = trading_value
			total_trading_value += trading_value
			
			change = s.get('change', 0)
			if change != 0:  # 0% 제외 (의미 없는 종목)
				total_change += change
				valid_count += 1
		
		avg_change = total_change / valid_count if valid_count > 0 else 1.0
		# 분모 폭발 방지: 평균 등락률의 절댓값이 최소 0.5%는 된다고 가정하여 지배력이 수백 배로 튀는 현상 방어
		if avg_change >= 0:
			avg_change = max(avg_change, 0.5)
		else:
			avg_change = min(avg_change, -0.5)
		
		# === 종목별 점수 계산 ===
		for s in stocks:
			change = s.get('change', 0)
			trading_value = s['_trading_value']
			price = abs(s.get('price', 0))
			high_p = abs(s.get('high', price))
			open_p = abs(s.get('open', price))
			
			# (1) 등락률 지배력: 이 종목이 테마 평균 대비 얼마나 강한가
			rate_dominance = change / avg_change if avg_change != 0 else 0
			
			# (2) 거래대금 집중도: 테마 전체 중 이 종목에 얼마나 돈이 집중되는가
			volume_dominance = trading_value / total_trading_value if total_trading_value > 0 else 0
			
			# (2.5) [V5] 마켓 지배력: 시장 전체 거래대금 대비 비중 (주도주급은 보통 0.5%~2% 차지)
			market_dominance = trading_value / total_market_value if total_market_value > 0 else 0
			
			# (3) 캔들 품질 (1.0 = 완벽, 0 감소 = 위험)
			candle_quality = 1.0
			
			# 윗꼬리 패널티: (고가-현재가)/현재가
			if price > 0:
				upper_wick = ((high_p - price) / price) * 100
				if upper_wick > CAUTION_UPPER_WICK_MAX:
					candle_quality *= 0.7  # 30% 감점
					s['is_caution'] = True
					s['caution_reason'] = f"윗꼬리 {upper_wick:.1f}%"
			else:
				upper_wick = 0
			
			# 시가갭 패널티: (시가-전일종가)/전일종가
			gap_start = 0
			if price > 0 and change != -100:
				prev_close = price / (1 + change / 100) if (1 + change / 100) != 0 else price
				if prev_close > 0:
					gap_start = ((open_p - prev_close) / prev_close) * 100
					if gap_start >= CAUTION_GAP_START_MAX:
						candle_quality *= 0.6  # 40% 감점
						s['is_caution'] = True
						reason = s.get('caution_reason', '')
						s['caution_reason'] = f"{reason}, 갭과열 {gap_start:.1f}%" if reason else f"갭과열 {gap_start:.1f}%"
			
			# === 최종 주도력 점수 ===
			# [V5] 테마 내 지배력 + 시장 지배력 가중치 합산
			leadership_score = (rate_dominance * volume_dominance * 100) + (market_dominance * 500)
			leadership_score *= candle_quality
			
			# 기존 UI 호환 점수
			momentum_score = max(0, change * (1 + volume_dominance * 2))
			close_score = momentum_score * candle_quality
			complex_score = (momentum_score + close_score) / 2
			
			# 결과 저장
			s['leadership_score'] = leadership_score
			s['rate_dominance'] = rate_dominance
			s['volume_dominance'] = volume_dominance
			s['market_dominance'] = market_dominance
			s['candle_quality'] = candle_quality
			s['momentum_score'] = momentum_score
			s['close_score'] = close_score
			s['complex_score'] = complex_score
			
			# === [NEW] 역할(Role) 판정: 대장 vs 후발주 ===
			if change >= 25.0:
				s['role'] = 'leader_overheat' # 상한가급 (관전용)
				s['role_name'] = '대장(과열)'
			elif change >= 15.0:
				s['role'] = 'leader'         # 주도주 (강력)
				s['role_name'] = '주도'
			elif 5.0 <= change < 15.0:
				s['role'] = 'target'         # 후발주 (추격 타겟)
				s['role_name'] = '후발'
			else:
				s['role'] = 'sleeper'        # 아직 조용함
				s['role_name'] = '대기'

			# 위험 플래그
			if not s.get('is_caution'):
				s['is_caution'] = False
				s['caution_reason'] = ''
			
			# 리더 플래그 (V3 로직 유지 + 역할 보강)
			s['is_leader'] = (
				(rate_dominance >= LEADER_RATE_DOMINANCE_MIN and
				volume_dominance >= LEADER_VOLUME_DOMINANCE_MIN and
				change >= COHESION_MIN_CHANGE) or (s['role'] == 'leader_overheat')
			)
			
			# 정리
			if '_trading_value' in s: del s['_trading_value']
		
		# 주도력 점수 내림차순 정렬
		stocks.sort(key=lambda x: x['leadership_score'], reverse=True)
		
		# === 신호 뱃지 할당 ===
		self._assign_badges(stocks)
		
		return stocks
	
	def _assign_badges(self, stocks):
		"""
		상위 종목에 신호 뱃지(signal_type)를 할당합니다.
		
		- king: 등락률 + 거래대금 모두 1위
		- breakout: 등락률 1위 (모멘텀형)
		- close: 안정성 1위 (종가배팅형)
		"""
		if not stocks:
			return
		
		# 모멘텀 1위 (등락률 기준)
		mom_top = max(stocks, key=lambda x: x.get('momentum_score', 0))
		# 안정성 1위 (캔들 품질 기준)
		close_top = max(stocks, key=lambda x: x.get('close_score', 0))
		
		for s in stocks:
			badges = []
			
			if s is mom_top and s.get('momentum_score', 0) > 0:
				badges.append('breakout')
			if s is close_top and s.get('close_score', 0) > 0:
				badges.append('close')
			
			if 'breakout' in badges and 'close' in badges:
				s['signal_type'] = 'king'
			elif 'breakout' in badges:
				s['signal_type'] = 'breakout'
			elif 'close' in badges:
				s['signal_type'] = 'close'
			else:
				s['signal_type'] = None
	
	def _fetch_theme_stocks(self, theme_name, theme_code=''):
		"""
		테마 구성 종목 조회 (ka90002).
		DataFetcher의 기존 메서드를 활용하되, enrich=False로 호출하여 API 절약.
		"""
		# 테마 코드가 없으면 캐시에서 검색
		if not theme_code:
			theme_code = self.fetcher.theme_code_cache.get(theme_name, '')
		else:
			# 코드 캐시 업데이트
			self.fetcher.theme_code_cache[theme_name] = theme_code
		
		# 기존 DataFetcher의 get_theme_stocks 활용
		stocks = self.fetcher.get_theme_stocks(theme_name)
		
		return stocks if stocks else []
