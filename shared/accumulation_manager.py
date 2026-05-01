import sqlite3
import os
import datetime
import pandas as pd
import time
import logging
from shared.api import (fetch_brokerage_data, fetch_investor_trends, fetch_investor_details_ka10059, 
						fetch_stock_basic_info, fetch_stock_program_daily_ka90013)
from shared.config import get_api_config, get_data_path

class AccumulationManager:
	"""
	매집 분석(Accumulation Analysis) 전용 데이터 관리 클래스.
	투자자 동향(ka10059) 및 거래원(ka10042) 데이터를 수집하고 분석합니다.
	"""
	def __init__(self, db_name="accumulation.db"):
		# [안실장 가이드] 관제 센터(Master_Control)와 데이터 동기화를 위해 중앙 data 폴더를 사용합니다.
		self.db_path = get_data_path(db_name)
		self._init_db()
		# [FIX] 하위 호환성을 위해 메서드 알리아싱 제공
		self.get_stock_analysis_result = self.calculate_metrics
		print(f"[Core] Shared AccumulationManager loaded. (DB: {self.db_path})")

	def _get_connection(self):
		return sqlite3.connect(self.db_path)

	def _init_db(self):
		"""DB 테이블 초기화"""
		conn = self._get_connection()
		cursor = conn.cursor()
		
		# 1. 투자자별 순매수 데이터 (Foreign/Institutional Trends)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS investor_trends (
				code TEXT,
				date TEXT,
				foreign_net_qty INTEGER,
				inst_net_qty INTEGER,
				program_net_qty INTEGER,
				close_price REAL,
				volume INTEGER,
				PRIMARY KEY (code, date)
			)
		''')
		
		# 2. 당일 주요 거래원(창구) 스냅샷 (Brokerage Snapshot)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS brokerage_snapshot (
				code TEXT,
				date TEXT,
				broker_name TEXT,
				net_buy_qty INTEGER,
				is_foreign INTEGER,
				PRIMARY KEY (code, date, broker_name)
			)
		''')
		
		# 3. 기간별 누적 거래원 합계 (Brokerage Period Totals - ka10042)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS brokerage_period_totals (
				code TEXT,
				broker_name TEXT,
				net_buy_qty INTEGER,
				is_foreign INTEGER,
				rank INTEGER,
				last_updated TEXT,
				PRIMARY KEY (code, broker_name)
			)
		''')
		
		# [안실장 가이드] 기존 DB 스키마 마이그레이션 (rank 컬럼 추가)
		try:
			cursor.execute("ALTER TABLE brokerage_period_totals ADD COLUMN rank INTEGER")
		except: pass
		try:
			cursor.execute("ALTER TABLE brokerage_period_totals ADD COLUMN last_updated TEXT")
		except: pass
		
		# 4. 주식 기본 정보 (유통주식수, 상장주식수 등)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS stock_basic_info (
				code TEXT PRIMARY KEY,
				floating_shares INTEGER,
				circulating_shares INTEGER,
				circulating_ratio REAL,
				last_updated TEXT
			)
		''')
		
		# 5. 일별 분석 결과 기록 (Daily Analysis Results)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS daily_analysis_results (
				code TEXT,
				date TEXT,
				score REAL,
				acc_ratio REAL,
				inst_days INTEGER,
				frgn_days INTEGER,
				is_breakout INTEGER,
				is_below_avg INTEGER,
				is_yin_dual_buy INTEGER,
				is_volume_dry INTEGER,
				PRIMARY KEY (code, date)
			)
		''')
		
		# 6. 포착된 종목 풀 (Captured Stock Pool for recycling)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS captured_pool (
				code TEXT,
				date TEXT,
				source TEXT,
				PRIMARY KEY (code, date)
			)
		''')
		
		# 인덱스 생성
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_investor_trends_code ON investor_trends (code)')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_brokerage_code ON brokerage_snapshot (code)')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_date ON daily_analysis_results (date)')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_score ON daily_analysis_results (score)')
		
		conn.commit()
		conn.close()

	def save_analysis_result(self, code, metrics):
		"""매집 분석 결과를 DB에 저장합니다"""
		today = datetime.datetime.now().strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			conn.execute('''
				INSERT OR REPLACE INTO daily_analysis_results 
				(code, date, score, acc_ratio, inst_days, frgn_days, 
				 is_breakout, is_below_avg, is_yin_dual_buy, is_volume_dry)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			''', (
				code, today, metrics['score'], metrics['acc_ratio'], 
				metrics['inst_days'], metrics['frgn_days'],
				1 if metrics.get('is_breakout') else 0,
				1 if metrics.get('is_below_avg') else 0,
				1 if metrics.get('is_yin_dual_buy') else 0,
				1 if metrics.get('is_volume_dry') else 0
			))
			conn.commit()
		except Exception as e:
			print(f"Error saving result for {code}: {e}")
		finally:
			conn.close()

	def get_recent_high_score_stocks(self, days_limit=5, score_limit=80):
		"""최근 N일 이내에 분석된 종목 중 스코어가 M점 이상인 종목 리스트 반환"""
		past_date = (datetime.datetime.now() - datetime.timedelta(days=days_limit)).strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			query = f"""
				SELECT DISTINCT code FROM daily_analysis_results 
				WHERE date >= '{past_date}' AND score >= {score_limit}
			"""
			df = pd.read_sql_query(query, conn)
			return df['code'].tolist()
		except Exception as e:
			print(f"Error getting high score stocks: {e}")
			return []
		finally:
			conn.close()

	def add_to_captured_pool(self, code, source="Condition"):
		"""포착된 종목을 DB 풀에 기록"""
		today = datetime.datetime.now().strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			conn.execute('''
				INSERT OR REPLACE INTO captured_pool (code, date, source)
				VALUES (?, ?, ?)
			''', (code, today, source))
			conn.commit()
		except Exception as e:
			print(f"Error adding to captured pool: {e}")
		finally:
			conn.close()

	def get_captured_pool_codes(self, days_limit=30):
		"""최근 N일간 포착된 종목 풀 리스트 반환"""
		past_date = (datetime.datetime.now() - datetime.timedelta(days=days_limit)).strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			query = f"SELECT DISTINCT code FROM captured_pool WHERE date >= '{past_date}'"
			df = pd.read_sql_query(query, conn)
			return df['code'].tolist()
		except Exception:
			return []
		finally:
			conn.close()

	def get_stock_analysis_result(self, code):
		"""특정 종목의 최신 매집 분석 결과를 DB에서 조회"""
		conn = self._get_connection()
		try:
			query = f"SELECT * FROM daily_analysis_results WHERE code = '{code}' ORDER BY date DESC LIMIT 1"
			df = pd.read_sql_query(query, conn)
			if not df.empty:
				return df.iloc[0].to_dict()
			return None
		except Exception as e:
			print(f"Error getting analysis result for {code}: {e}")
			return None
		finally:
			conn.close()

	def has_today_data(self, code):
		"""해당 종목의 데이터가 오늘 이미 수집되었는지 확인"""
		today = datetime.datetime.now().strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			q1 = f"SELECT count(*) FROM investor_trends WHERE code = '{code}' AND date = '{today}'"
			q2 = f"SELECT count(*) FROM brokerage_period_totals WHERE code = '{code}' AND last_updated LIKE '{today}%'"
			has_trends = pd.read_sql_query(q1, conn).iloc[0,0] > 0
			has_brokers = pd.read_sql_query(q2, conn).iloc[0,0] > 0
			return has_trends and has_brokers
		except Exception:
			return False
		finally:
			conn.close()

	def has_any_analysis_for_day(self, date_str):
		"""특정 날짜에 대한 분석 결과가 존재하는지 확인"""
		conn = self._get_connection()
		try:
			query = f"SELECT count(*) FROM daily_analysis_results WHERE date = '{date_str}'"
			df = pd.read_sql_query(query, conn)
			return int(df.iloc[0, 0]) > 0
		except Exception:
			return False
		finally:
			conn.close()

	def update_accumulation_data(self, code, token, days=30):
		"""매집 데이터를 API로 수집하여 DB에 저장"""
		conf = get_api_config()
		host_url = conf['host_url']
		trends = fetch_investor_details_ka10059(host_url, code, token, days=days)
		if not trends:
			trends = fetch_investor_trends(host_url, code, token, days=days)
			
		if trends:
			conn = self._get_connection()
			for t in trends:
				dt = t.get('dt') or t.get('date') or t.get('stck_bsop_date')
				if not dt: continue
				def to_int(v):
					if not v or str(v).strip() == "": return 0
					s = str(v).replace(',', '').strip()
					if s.startswith('--'): s = '-' + s[2:]
					try: return int(float(s))
					except: return 0
				f_qty = to_int(t.get('frgnr_invsr') or t.get('for_netprps') or t.get('frgnr_daly_nettrde') or t.get('ntby_qty_frgn_ivst'))
				i_qty = to_int(t.get('orgn') or t.get('orgn_netprps') or t.get('orgn_daly_nettrde') or t.get('ntby_qty_orgn_ivst'))
				p_qty = to_int(t.get('prm') or t.get('ntby_qty_prgm'))
				raw_close = str(t.get('cur_prc') or t.get('close_pric') or t.get('stck_prpr') or 0).replace(',', '')
				close = abs(float(raw_close))
				vol = to_int(t.get('acc_trde_qty') or t.get('trde_qty') or t.get('acml_tr_vol'))
				conn.execute('''
					INSERT OR REPLACE INTO investor_trends 
					(code, date, foreign_net_qty, inst_net_qty, program_net_qty, close_price, volume)
					VALUES (?, ?, ?, ?, ?, ?, ?)
				''', (code, dt, f_qty, i_qty, p_qty, close, vol))
			conn.commit()
			conn.close()
			
			try:
				prm_conn = self._get_connection()
				prm_data = fetch_stock_program_daily_ka90013(host_url, code, token, days=days)
				if prm_data:
					updated_count = 0
					for p in prm_data:
						p_dt = p.get('dt') or p.get('date')
						if not p_dt: continue
						p_qty_val = to_int(p.get('prm_netprps_qty') or 0)
						res = prm_conn.execute('UPDATE investor_trends SET program_net_qty = ? WHERE code = ? AND date = ?', (p_qty_val, code, p_dt))
						if res.rowcount > 0: updated_count += 1
					prm_conn.commit()
				prm_conn.close()
			except: pass

		try:
			from shared.api import fetch_brokerage_rank_ka10038, fetch_brokerage_period_ka10042
			now = datetime.datetime.now()
			ed_dt = now.strftime("%Y%m%d")
			st_dt = (now - datetime.timedelta(days=days+10)).strftime("%Y%m%d")
			dt_val = '19' if days <= 20 else '39'
			period_brokerage = fetch_brokerage_rank_ka10038(host_url, code, token, st_dt, ed_dt, dt=dt_val)
			if not period_brokerage:
				period_brokerage = fetch_brokerage_period_ka10042(host_url, code, token, st_dt, ed_dt)
			if period_brokerage:
				conn = self._get_connection()
				conn.execute("DELETE FROM brokerage_period_totals WHERE code = ?", (code,))
				for i, b in enumerate(period_brokerage[:10]):
					name = b.get('mmcm_nm') or b.get('mem_nm') or b.get('member_nm') or b.get('trad_nm')
					qty_val = b.get('acc_netprps_qty') or b.get('ntby_qty') or 0
					qty = 0
					if str(qty_val).strip() in ["", "0", "None"]:
						if b.get('rank'):
							try: qty = 1100 - (int(b.get('rank')) * 100)
							except: qty = 0
					else:
						try: qty = int(str(qty_val).replace(',', '').replace('+', ''))
						except: qty = 0
					if name:
						name = name.strip()
						b_rank = int(b.get('rank') or (i + 1))
						is_frgn = 1 if any(kw in name for kw in ["JP모건", "모건스탠리", "골드만", "맥쿼리", "메릴린치", "CS", "UBS", "노무라", "씨티", "도이치", "에스지", "HSBC"]) else 0
						conn.execute('''
							INSERT OR REPLACE INTO brokerage_period_totals 
							(code, broker_name, net_buy_qty, is_foreign, rank, last_updated)
							VALUES (?, ?, ?, ?, ?, ?)
						''', (code, name, qty, is_frgn, b_rank, now.strftime("%Y%m%d %H:%M")))
				conn.commit()
				conn.close()
		except: pass

		basic_info = fetch_stock_basic_info(host_url, code, token)
		if basic_info:
			today_str = datetime.datetime.now().strftime("%Y%m%d")
			conn = self._get_connection()
			conn.execute('INSERT OR REPLACE INTO stock_basic_info (code, floating_shares, circulating_shares, circulating_ratio, last_updated) VALUES (?, ?, ?, ?, ?)',
						(code, basic_info['floating_shares'], basic_info['circulating_shares'], basic_info['circulating_ratio'], today_str))
			conn.commit()
			conn.close()

	def calculate_metrics(self, code, days=30):
		"""매집비 및 수급 점수 계산"""
		conn = self._get_connection()
		df = pd.read_sql_query(f"SELECT * FROM investor_trends WHERE code = '{code}' ORDER BY date DESC LIMIT {days}", conn)
		circ_df = pd.read_sql_query(f"SELECT circulating_shares FROM stock_basic_info WHERE code = '{code}'", conn)
		circulating_shares = circ_df['circulating_shares'].iloc[0] if not circ_df.empty else 0
		conn.close()
		if df.empty: return {'acc_ratio': 0, 'inst_days': 0, 'frgn_days': 0, 'score': 0}
		df = df.sort_values(by='date', ascending=True).reset_index(drop=True)
		total_buy = df['foreign_net_qty'].sum() + df['inst_net_qty'].sum()
		if circulating_shares > 0: acc_ratio = (total_buy / circulating_shares * 100)
		else:
			total_vol = df['volume'].sum()
			acc_ratio = (total_buy / total_vol * 100) if total_vol > 0 else 0
		inst_days = len(df[df['inst_net_qty'] > 0])
		frgn_days = len(df[df['foreign_net_qty'] > 0])
		weights = [0.2 + 1.3 * (i / max(1, len(df) - 1)) for i in range(len(df))]
		w_inst = sum(weights[i] for i, r in df.iterrows() if r['inst_net_qty'] > 0)
		w_frgn = sum(weights[i] for i, r in df.iterrows() if r['foreign_net_qty'] > 0)
		dual_days = len(df[(df['inst_net_qty'] > 0) & (df['foreign_net_qty'] > 0)])
		prog_bonus = 5 if df.tail(3)['program_net_qty'].sum() > 0 else 0
		price_change_rt = 0
		today_change_rt = 0
		if len(df) >= 2:
			price_change_rt = (df.iloc[-1]['close_price'] - df.iloc[0]['close_price']) / df.iloc[0]['close_price'] * 100 if df.iloc[0]['close_price'] > 0 else 0
			today_change_rt = (df.iloc[-1]['close_price'] - df.iloc[-2]['close_price']) / df.iloc[-2]['close_price'] * 100 if df.iloc[-2]['close_price'] > 0 else 0
		alpha_bonus = 0
		if acc_ratio >= 1.0:
			if price_change_rt <= -5.0: alpha_bonus = 15
			elif price_change_rt <= 0.0: alpha_bonus = 10
			elif price_change_rt <= 2.0: alpha_bonus = 5
			elif price_change_rt >= 10.0 and acc_ratio >= 2.0: alpha_bonus = 15
			elif price_change_rt >= 5.0 and acc_ratio >= 1.5: alpha_bonus = 10
		s_acc = min(acc_ratio * 6, 30)
		s_inst = min(w_inst * 1.5, 15)
		s_frgn = min(w_frgn * 1.5, 15)
		s_dual = min(dual_days * 2.0, 10)
		
		broker_bonus = 0
		conn = self._get_connection()
		broker_df = pd.read_sql_query(f"SELECT * FROM brokerage_period_totals WHERE code = '{code}' ORDER BY net_buy_qty DESC", conn)
		conn.close()
		if not broker_df.empty:
			top_3 = broker_df.head(3)
			if any(top_3['is_foreign'] == 1):
				broker_bonus = 10 if top_3.iloc[0]['is_foreign'] == 1 else 7
			elif any(broker_df['is_foreign'] == 1): broker_bonus = 3
		score = s_acc + s_inst + s_frgn + s_dual + prog_bonus + alpha_bonus + broker_bonus
		is_breakout = (score > 75 and price_change_rt >= 5.0)
		total_buy_qty = sum(max(0, r['inst_net_qty']) + max(0, r['foreign_net_qty']) for _, r in df.iterrows())
		total_buy_amt = sum((max(0, r['inst_net_qty']) + max(0, r['foreign_net_qty'])) * r['close_price'] for _, r in df.iterrows())
		avg_buy_price = (total_buy_amt / total_buy_qty) if total_buy_qty > 0 else 0
		is_below_avg = (avg_buy_price > 0 and df.iloc[-1]['close_price'] <= avg_buy_price * 1.03 and score >= 40)
		is_yin_dual = False
		if len(df) >= 3:
			for i in range(1, min(7, len(df))):
				idx = -i
				if df.iloc[idx]['close_price'] <= df.iloc[idx-1]['close_price'] and (df.iloc[idx]['inst_net_qty'] > 0 and df.iloc[idx]['foreign_net_qty'] > 0):
					is_yin_dual = True
					break
		is_vol_dry = False
		if len(df) >= 6:
			avg_v = df['volume'].rolling(window=6).mean().iloc[-1]
			if df.iloc[-1]['volume'] > 0 and df.iloc[-1]['volume'] <= avg_v * 0.5 and acc_ratio >= 0.5: is_vol_dry = True
		return {
			'acc_ratio': round(acc_ratio, 2), 'inst_days': inst_days, 'frgn_days': frgn_days,
			'price_change_rt': round(price_change_rt, 2), 'today_change_rt': round(today_change_rt, 2),
			'score': round(min(score, 100), 1), 
			'score_details': {
				'매집량': round(s_acc, 1),
				'연속성': round(s_inst + s_frgn, 1),
				'쌍끌이': round(s_dual, 1),
				'프로그램': round(prog_bonus, 1),
				'창구특성': round(broker_bonus, 1),
				'추세가중': round(alpha_bonus, 1)
			},
			'is_breakout': is_breakout, 'is_below_avg': is_below_avg,
			'is_yin_dual_buy': is_yin_dual, 'is_volume_dry': is_vol_dry, 'avg_buy_price': avg_buy_price,
			'top_broker': broker_df.iloc[0]['broker_name'] if not broker_df.empty else "-"
		}

	def get_accumulation_quality(self, code: str) -> dict:
		"""창구 질 분석 통합 반환"""
		res = self.calculate_metrics(code)
		score = res.get('score', 0) if res else 0
		conn = self._get_connection()
		try:
			df = pd.read_sql_query(f"SELECT * FROM brokerage_period_totals WHERE code = '{code}' ORDER BY net_buy_qty DESC LIMIT 1", conn)
			if df.empty: return {'is_premium': False, 'desc': "매집분석 데이터 없음", 'score': score, 'top_broker': ""}
			top_broker = df.iloc[0]['broker_name'] or "알수없음"
			PREMIUM_HOUSES = ["모건스탠리", "JP모건", "골드만", "맥쿼리", "메릴린치", "CS", "UBS", "노무라"]
			INSTITUTIONAL_HOUSES = ["연기금", "미래에셋", "삼성", "한국투자", "신한투자", "KB증권"]
			is_premium = False
			if any(h in top_broker for h in PREMIUM_HOUSES):
				is_premium = True
				prefix = "💎 [프리미엄]"
			elif any(h in top_broker for h in INSTITUTIONAL_HOUSES):
				is_premium = True
				prefix = "🏛️ [기관메이저]"
			else: prefix = "📊 [국내주력]"
			return {'is_premium': is_premium, 'desc': f"{prefix} {top_broker} (점수:{score})", 'score': score, 'top_broker': top_broker}
		except: return {'is_premium': False, 'desc': "", 'score': score, 'top_broker': ""}
		finally: conn.close()

	def get_top_brokers(self, code):
		conn = self._get_connection()
		df = pd.read_sql_query(f"SELECT * FROM brokerage_period_totals WHERE code = '{code}' ORDER BY rank ASC", conn)
		conn.close()
		return df.to_dict('records')
	
	def is_holding_position(self, code, lookback=20):
		"""세력이 물량을 보유(홀딩) 중인지 판단 (이탈 조짐 체크)"""
		conn = self._get_connection()
		try:
			df = pd.read_sql_query(f"SELECT foreign_net_qty, inst_net_qty FROM investor_trends WHERE code = '{code}' ORDER BY date DESC LIMIT {lookback}", conn)
			if df.empty or len(df) < 5: return False
			total_net = df['foreign_net_qty'].sum() + df['inst_net_qty'].sum()
			recent_net = df.head(3)['foreign_net_qty'].sum() + df.head(3)['inst_net_qty'].sum()
			return total_net > 0 and not (recent_net < 0 and abs(recent_net) > total_net * 0.3)
		except: return False
		finally: conn.close()

	def get_active_accumulation_stocks(self, score_limit=70, days=10, limit=100):
		"""최근 고득점 종목 중 세력 이탈이 없는 '살아있는' 종목들 추출"""
		past_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
		conn = self._get_connection()
		try:
			query = f"SELECT DISTINCT code FROM daily_analysis_results WHERE date >= '{past_date}' AND score >= {score_limit} LIMIT {limit}"
			codes = pd.read_sql_query(query, conn)['code'].tolist()
			return [code for code in codes if self.is_holding_position(code)]
		except: return []
		finally: conn.close()
