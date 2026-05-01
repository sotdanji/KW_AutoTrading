"""
ThemeRadar V4 (Top-Down 메인 엔진)

[발상의 전환] 기존 Bottom-Up(시장 Top 200 종목 → 테마 역추적) 방식에서
Top-Down(테마 지수 직접 조회 → 전 구성종목 전수조사) 방식으로 전면 개조.

Bottom-Up은 교차검증(스마트머니 데이터 병합) 용도로만 보조적으로 사용합니다.

흐름:
  1단계: ka90001 → 테마 지수 상위 15개 선정 (Top-Down 메인)
  2단계: ka90002 → 선정 테마의 전 구성종목 병렬 수집 (전수조사)
  3단계: ka10027/ka10032 → 시장 Top 200에서 수급 데이터 추출 → 테마 종목에 병합 (Bottom-Up 교차검증)
  4단계: 종합 스코어링 (등락률 + 동반상승 + 교차검증)
"""

import sys
import os
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.logger import get_logger

# shared 모듈 경로 추가
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
	sys.path.insert(0, _ROOT)

from shared.api import get_kw_token as _shared_get_kw_token, fetch_kw_data as _shared_fetch_kw_data, _get_host_url

logger = get_logger(__name__)

# 스캐닝 설정
TOP_VOL_LIMIT = 100      # 교차검증용: 거래대금 상위 N개
TOP_RATE_LIMIT = 100     # 교차검증용: 상승률 상위 N개
THEME_SCORE_MIN = 2.0    # 테마 최소 점수
HOT_THEME_LIMIT = 15     # 최종 선정 테마 수


class ThemeSnapshot:
	"""스냅샷 결과 (Top-Down + Bottom-Up 교차검증 반영)"""
	__slots__ = ['timestamp', 'themes', 'top_pool']

	def __init__(self, timestamp, themes, top_pool=None):
		self.timestamp = timestamp
		self.themes = themes  # {name: {score, top_stocks:[...]}}
		self.top_pool = top_pool or {} # {code: stock_dict} - 교차검증용


class ThemeRadar:
	"""
	V4 Top-Down 메인 엔진.
	
	테마 지수(ka90001)를 직접 조회하여 주도 테마를 선정하고,
	선정된 테마의 전 구성종목(ka90002)을 전수조사합니다.
	Bottom-Up(시장 Top 200)은 스마트머니 교차검증 용도로만 사용됩니다.
	"""

	def __init__(self, data_fetcher):
		self.fetcher = data_fetcher
		self.snapshots = []
		
		# DNA Map: { '005930': ['소프트웨어', '반도체'], ... }
		self.dna_map = {}
		# Theme Info Cache: { '반도체': 'tcode', ... }
		self._theme_code_cache = {}
		
		self.is_initialized = False
		self._init_lock = threading.Lock()

	@property
	def snapshot_count(self):
		return len(self.snapshots)

	@property
	def is_ready(self):
		return self.is_initialized

	def initialize_dna(self):
		"""
		[V4] 초기화: 테마 코드 캐시만 구축 (ka90001 1회 호출)
		
		V3에서는 142개 테마의 전 종목을 모두 가져와 DNA 역맵핑을 했지만,
		V4에서는 take_snapshot()이 매 주기마다 Top-Down으로 직접 조회하므로
		초기화는 테마 코드 캐시만 세팅하면 됩니다. (~2초)
		"""
		with self._init_lock:
			if self.is_initialized:
				return True
				
			logger.info("[Radar] 초기화: 테마 코드 캐시 구축 (경량)")
			
			# ka90001 1회 호출로 142개 테마의 이름-코드 매핑만 가져옴
			theme_map = self._fetch_all_themes_list()
			if not theme_map:
				logger.error("[Radar] 테마 목록을 불러오지 못했습니다.")
				return False
			
			# 테마 코드 캐시 세팅 (이것만 있으면 take_snapshot에서 ka90002 호출 가능)
			for t_name, t_code in theme_map.items():
				self._theme_code_cache[t_name] = t_code
				self.fetcher.theme_code_cache[t_name] = t_code
			
			self.is_initialized = True
			logger.info(f"[Radar] 초기화 완료! ({len(theme_map)}개 테마 코드 캐시 완료)")
			return True

	def take_snapshot(self):
		"""
		[V4 Top-Down 메인 엔진]
		
		1단계: [Top-Down] 테마 지수(ka90001) 직접 조회 → 상위 15개 테마 선정
		2단계: [전수조사] 선정된 테마의 전 구성종목(ka90002) 병렬 수집
		3단계: [Bottom-Up 교차검증] 시장 Top 200 종목에서 스마트머니(수급) 데이터 추출 → 테마 종목에 병합
		4단계: [스코어링] 테마별 종합 점수 산출
		5단계: [스냅샷 저장]
		"""
		if not self.is_ready:
			logger.warning("[Radar] DNA가 아직 초기화되지 않았습니다. 초기화 진행...")
			self.initialize_dna()
			if not self.is_ready:
				return False

		# ===================================================================
		# 1단계: [Top-Down] 테마 지수 직접 조회 (이것이 메인!)
		# ===================================================================
		td_themes = self.fetcher.get_theme_groups()
		if not td_themes:
			logger.error("[Radar] 테마 그룹 데이터를 가져오지 못했습니다.")
			return False
		
		# 등락률 순으로 이미 정렬되어 옴. 상위 15개 테마를 핵심 분석 대상으로 선정
		target_themes = td_themes[:HOT_THEME_LIMIT]
		logger.info(f"[Radar] 1단계 완료: Top-Down 테마 {len(target_themes)}개 선정 (1위: {target_themes[0]['name']} {target_themes[0]['change']:+.2f}%)")

		# ===================================================================
		# 2단계: [전수조사] 선정된 테마의 전 구성종목을 병렬로 가져옴
		# ===================================================================
		theme_full_data = {} # {theme_name: {info + members}}
		
		def fetch_theme_members(theme_info):
			t_name = theme_info['name']
			members = self.fetcher.get_theme_stocks(t_name)
			return t_name, theme_info, members
		
		with ThreadPoolExecutor(max_workers=10) as executor:
			futures = [executor.submit(fetch_theme_members, t) for t in target_themes]
			for f in as_completed(futures):
				try:
					t_name, t_info, members = f.result()
					theme_full_data[t_name] = {
						'info': t_info,
						'members': members if members else []
					}
				except Exception as e:
					logger.warning(f"[Radar] 테마 종목 수집 실패: {e}")
		
		logger.info(f"[Radar] 2단계 완료: {len(theme_full_data)}개 테마 전수조사 완료")
		
		# ===================================================================
		# 3단계: [Bottom-Up 교차검증] 시장 Top 종목에서 스마트머니 데이터 추출
		# ===================================================================
		all_stocks = self._fetch_all_market_stocks()
		top_pool = {}
		
		if all_stocks:
			valid_stocks = [s for s in all_stocks if s['price'] > 500]
			by_vol = sorted(valid_stocks, key=lambda x: x.get('trade_value', 0), reverse=True)[:TOP_VOL_LIMIT]
			by_rate = sorted(valid_stocks, key=lambda x: x['change'], reverse=True)[:TOP_RATE_LIMIT]
			top_pool = {s['code']: s for s in by_vol + by_rate}
			
			# 상위 50개 종목의 스마트머니(외국인/기관 수급) 조회
			def _fetch_investor(k, s):
				inv_data = self.fetcher.get_stock_investor_data(k)
				s['foreign_net'] = inv_data['foreign_net']
				s['inst_net'] = inv_data['inst_net']
				
			with ThreadPoolExecutor(max_workers=5) as executor:
				top_50_keys = list(top_pool.keys())[:50]
				futures = [executor.submit(_fetch_investor, k, top_pool[k]) for k in top_50_keys]
				for f in as_completed(futures): pass
			
			for k in top_pool:
				if 'foreign_net' not in top_pool[k]:
					top_pool[k]['foreign_net'], top_pool[k]['inst_net'] = 0, 0
		
		# 교차검증: 테마 종목에 스마트머니 데이터 병합
		for t_name, t_data in theme_full_data.items():
			for member in t_data['members']:
				code = member.get('code', '')
				if code in top_pool:
					pool_stock = top_pool[code]
					member['foreign_net'] = pool_stock.get('foreign_net', 0)
					member['inst_net'] = pool_stock.get('inst_net', 0)
					member['trade_value'] = pool_stock.get('trade_value', 0)
					# Top Pool에 있다 = 시장 전체에서도 주목받고 있다 (교차검증 통과)
					member['cross_validated'] = True
				else:
					member.setdefault('foreign_net', 0)
					member.setdefault('inst_net', 0)
					member.setdefault('trade_value', 0)
					member['cross_validated'] = False
		
		logger.info(f"[Radar] 3단계 완료: Bottom-Up 교차검증 병합 (Top Pool {len(top_pool)}개)")

		# ===================================================================
		# 4단계: [스코어링] 테마별 종합 점수 산출
		# ===================================================================
		hot_themes = []
		for t_name, t_data in theme_full_data.items():
			info = t_data['info']
			members = t_data['members']
			member_count = len(members)
			
			if member_count == 0:
				continue
			
			# 테마 지수 등락률 (Top-Down 원본 데이터)
			theme_rate = info['change']
			
			# 구성원 활력: 테마 내 양수 등락률 종목 비율
			rising_count = sum(1 for m in members if m.get('change', 0) > 0)
			cohesion_ratio = rising_count / member_count if member_count > 0 else 0
			
			# 교차검증 보너스: Top Pool에 많이 걸릴수록 진짜 핫 테마
			cross_count = sum(1 for m in members if m.get('cross_validated', False))
			cross_bonus = cross_count * 3.0  # 교차검증 종목 1개당 3점
			
			# 종합 스코어: 테마 등락률(60%) + 구성원 활력(20%) + 교차검증(20%)
			score = (theme_rate * 4.0) + (cohesion_ratio * 20.0) + cross_bonus
			
			hot_themes.append({
				'name': t_name,
				'code': info.get('theme_code', self._theme_code_cache.get(t_name, '')),
				'score': score,
				'member_count': member_count,
				'avg_rate': theme_rate,
				'cohesion_ratio': cohesion_ratio,
				'cross_validated_count': cross_count,
				'top_members': sorted(members, key=lambda x: x.get('change', 0), reverse=True)
			})
		
		hot_themes.sort(key=lambda x: x['score'], reverse=True)
		final_leaders = hot_themes[:HOT_THEME_LIMIT]

		# ===================================================================
		# 5단계: [스냅샷 저장]
		# ===================================================================
		snapshot = ThemeSnapshot(
			timestamp=time.time(),
			themes={t['name']: t for t in final_leaders},
			top_pool=top_pool
		)
		self.snapshots.append(snapshot)
		
		if final_leaders:
			top_t = final_leaders[0]
			logger.info(
				f"[Radar] 💥 Top-Down 스냅샷 완료: "
				f"[{top_t['name']}] {top_t['avg_rate']:+.2f}% "
				f"(종목 {top_t['member_count']}개, "
				f"동반상승 {top_t['cohesion_ratio']:.0%}, "
				f"교차검증 {top_t['cross_validated_count']}개, "
				f"점수 {top_t['score']:.1f})"
			)
			
		return True

	def get_hot_themes(self, limit=6):
		"""
		[V4.1] 하이브리드 주도테마 (수급형 4 + 급등형 2)
		"""
		if not self.snapshots:
			return []
			
		latest = self.snapshots[-1].themes
		theme_list = list(latest.values())
		
		# 1. 수급형(Money): score (종합 점수 중심)
		money_sorted = sorted(theme_list, key=lambda x: x['score'], reverse=True)
		
		# 2. 급등형(Rapid): avg_rate (테마 단순 등락률 중심)
		rapid_sorted = sorted(theme_list, key=lambda x: x['avg_rate'], reverse=True)
		
		results = []
		added_codes = set()
		
		def _format_theme(data, is_money):
			return {
				'name': data['name'],
				'code': data['code'],
				'change': data['avg_rate'],
				'rate': data['avg_rate'],
				'velocity': data.get('cohesion_ratio', 0),
				'acceleration': data['score'],
				'momentum_score': data['score'],
				'hot_member_count': data['member_count'],
				'top_members': data['top_members'],
				'cohesion_ratio': data.get('cohesion_ratio', 0),
				'cross_validated_count': data.get('cross_validated_count', 0),
				'is_sector': False
			}
			
		# 수급형 4개 추출
		for data in money_sorted:
			if len(results) >= 4: break
			if data['code'] not in added_codes:
				results.append(_format_theme(data, is_money=True))
				added_codes.add(data['code'])
				
		# 급등형 2개 추출 (수급형과 중복 제외)
		rapid_count = 0
		for data in rapid_sorted:
			if rapid_count >= 2: break
			if data['code'] not in added_codes:
				results.append(_format_theme(data, is_money=False))
				added_codes.add(data['code'])
				rapid_count += 1
				
		return results

	def get_all_themes_snapshot(self):
		"""
		[V4] 트리맵/전광판용 전체 테마 데이터.
		
		Top-Down으로 수집한 15개 테마를 모두 반환합니다.
		"""
		return self.get_hot_themes(limit=40)

	def get_theme_code(self, theme_name):
		return self._theme_code_cache.get(theme_name, '')

	def get_10min_momentum_data(self, limit=30):
		"""
		10분 전 스냅샷과 현재 스냅샷의 top_pool(시장 상위 종목)을 비교하여
		거래량/거래대금 순위 변동을 추적합니다.
		
		[V4.1] 대표님 요청: 10초 주기가 아닌, 정각 10분 단위로만 갱신되도록 고정.
		"""
		empty = {'past_vol': [], 'curr_vol': [], 'past_val': [], 'curr_val': []}
		
		if not self.snapshots:
			return empty

		# 10분 단위 정각 마크 계산 (예: 09:15 -> 09:10, 09:00)
		now_ts = self.snapshots[-1].timestamp
		curr_mark = (int(now_ts) // 600) * 600
		past_mark = curr_mark - 600
		
		# 각 마크 시점에 가장 인접한 스냅샷 찾기
		curr_snap = next((s for s in self.snapshots if s.timestamp >= curr_mark), None)
		past_snap = next((s for s in self.snapshots if s.timestamp >= past_mark), None)
		
		# 과도기 처리: 아직 10분 간격의 데이터가 충분하지 않은 경우
		if not past_snap or curr_snap == past_snap:
			# 시작점 vs 최신(실시간) 비교로 유연하게 대응
			past_snap = self.snapshots[0]
			curr_snap = self.snapshots[-1]
		
		curr_pool = list(curr_snap.top_pool.values())
		past_pool = list(past_snap.top_pool.values())
		
		def _sort_and_format(pool, key, limit):
			# ETF/ETN/스팩 필터링
			forbidden = ["KODEX", "TIGER", "KBSTAR", "ARIRANG", "KOSEF", "HANARO", 
						 "KINDEX", "ACE", "SOL", "TIMEFOLIO", "FOCUS", "TREX", 
						 "SMART", "마이티", "ETN", "스팩"]
			
			filtered = []
			for s in pool:
				name = s.get('name', '').upper()
				if not any(kw in name for kw in forbidden):
					filtered.append(s)
					
			sorted_pool = sorted(filtered, key=lambda x: x.get(key, 0), reverse=True)[:limit]
			
			result = []
			for s in sorted_pool:
				result.append({
					'signal_type': '',
					'code': s.get('code', ''),
					'name': s.get('name', ''),
					'price': s.get('price', 0),
					'change': s.get('change', 0.0),
					'foreign_net': s.get('foreign_net', 0),
					'inst_net': s.get('inst_net', 0)
				})
			return result
			
		return {
			'past_vol': _sort_and_format(past_pool, 'volume', limit),
			'curr_vol': _sort_and_format(curr_pool, 'volume', limit),
			'past_val': _sort_and_format(past_pool, 'trade_value', limit),
			'curr_val': _sort_and_format(curr_pool, 'trade_value', limit)
		}

	# ------------------ 내부 헬퍼 ------------------ #
	def _fetch_all_themes_list(self):
		"""
		DataFetcher를 통해 테마 리스트를 가져옵니다.
		이미 DataFetcher에 검증된 로직(get_theme_groups)이 있으므로 이를 활용합니다.
		"""
		themes = self.fetcher.get_theme_groups()
		if not themes:
			return {}

		theme_map = {}
		for t in themes:
			name = t.get('name')
			code = t.get('theme_code')
			if name and code:
				theme_map[name] = code
				
		return theme_map

	def _fetch_all_market_stocks(self):
		"""
		대표님의 놀라운 통찰을 반영하여 V3.1 업데이트 적용:
		전 종목을 조회하여 필터링하는 대신, 키움 API의 상위 랭킹(거래대금상위, 등락률상위)을
		직접 타격하여 수집 시간을 5~6초에서 0.5초 이내로 혁신적으로 단축합니다.
		"""
		if not self.fetcher.token:
			self.fetcher._request_token()

		from shared.api import fetch_data as _fetch_data
		host_url = _get_host_url(self.fetcher.mode)
		
		target_stocks = {} # 중복 제거용 dict

		def _parse_and_add(item):
			try:
				# '005930_AL' -> '005930'
				code = item.get('stk_cd', '').split('_')[0].strip()
				name = item.get('stk_nm', '').strip()
				
				# 가격이 이상하게 오는 경우 (예: -181800)
				raw_price = str(item.get('cur_prc', '0')).replace(',', '').replace('+', '').replace('-', '')
				if not raw_price.isdigit(): raw_price = '0'
				price = int(raw_price)
				
				raw_rate = str(item.get('flu_rt', '0')).replace('%', '').replace('+', '')
				rate = float(raw_rate)
				
				vol = int(str(item.get('now_trde_qty', '0')).replace(',', ''))
				trade_value = price * vol
				
				target_stocks[code] = {
					'code': code, 'name': name,
					'price': price, 'change': rate, 'volume': vol,
					'trade_value': trade_value
				}
			except Exception as e:
				pass

		# 1. 등락률 상위 (ka10027) - 200개 (2페이지)
		cont_yn = 'N'
		next_key = ''
		for _ in range(2):
			body_10027 = {'mrkt_tp':'000', 'sort_tp':'1', 'updown_incls':'1', 'trde_qty_cnd':'0000', 'stk_cnd':'0', 'crd_cnd':'0', 'pric_cnd':'0', 'trde_prica_cnd':'0', 'stex_tp':'3'}
			resp = _fetch_data(host_url, '/api/dostk/rkinfo', 'ka10027', body_10027, self.fetcher.token, cont_yn, next_key)
			if not resp: break
			for s in resp.json().get('pred_pre_flu_rt_upper', []):
				_parse_and_add(s)
			cont_yn = resp.headers.get('cont-yn', 'N')
			next_key = resp.headers.get('next-key', '')
			if cont_yn != 'Y' or not next_key: break

		# 2. 거래대금 상위 (ka10032) - 200개 (2페이지)
		cont_yn = 'N'
		next_key = ''
		for _ in range(2):
			body_10032 = {'mrkt_tp':'000', 'mang_stk_incls':'0', 'stex_tp':'3'}
			resp = _fetch_data(host_url, '/api/dostk/rkinfo', 'ka10032', body_10032, self.fetcher.token, cont_yn, next_key)
			if not resp: break
			for s in resp.json().get('trde_prica_upper', []):
				_parse_and_add(s)
			cont_yn = resp.headers.get('cont-yn', 'N')
			next_key = resp.headers.get('next-key', '')
			if cont_yn != 'Y' or not next_key: break

		# dict_values를 list로 변환하여 리턴 (전종목 조회 대신, 핵심 타겟만 넘김)
		return list(target_stocks.values())
