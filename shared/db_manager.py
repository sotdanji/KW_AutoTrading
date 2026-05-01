import sqlite3
import os
import datetime
import pandas as pd
from shared.config import get_data_path

class DBManager:
	"""
	시스템 공용 데이터베이스 관리 클래스.
	관심 종목(watched_stocks), 성과 로그(performance_log), 일별 캐시(daily_summary)를 관리합니다.
	"""
	def __init__(self, db_name="analyzer.db"):
		# [안실장 유지보수 가이드] DB 경로를 중앙 data/ 폴더로 통합 (shared.config 사용)
		self.db_path = get_data_path(db_name)
		# data 디렉토리가 없으면 생성 (안전장치)
		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

	def _get_connection(self):
		return sqlite3.connect(self.db_path)

	def _init_db(self):
		"""DB 테이블 초기화"""
		conn = self._get_connection()
		cursor = conn.cursor()
		
		# 1. 포착 종목 테이블 (watched_stocks)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS watched_stocks (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				code TEXT NOT NULL,
				name TEXT NOT NULL,
				sector TEXT,
				found_price REAL,
				found_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
				is_active INTEGER DEFAULT 1,
				signal_type TEXT DEFAULT NULL,
				UNIQUE(code, found_at)
			)
		''')
		
		# [Migration] signal_type 컬럼 체크 및 추가
		try:
			cursor.execute("SELECT signal_type FROM watched_stocks LIMIT 1")
		except sqlite3.OperationalError:
			cursor.execute("ALTER TABLE watched_stocks ADD COLUMN signal_type TEXT DEFAULT NULL")
			conn.commit()
		
		# 2. 성과 로그 테이블 (performance_log)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS performance_log (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				stock_code TEXT NOT NULL,
				check_time TIMESTAMP DEFAULT (datetime('now', 'localtime')),
				current_price REAL,
				profit_rate REAL
			)
		''')
		
		# 3. 일별 캐시 데이터 테이블 (daily_summary)
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS daily_summary (
				code TEXT NOT NULL,
				date TEXT NOT NULL,
				close REAL,
				last_vol REAL,
				ma5 REAL,
				ma20 REAL, 
				ma60 REAL,
				bb_upper REAL,
				bb_lower REAL,
				high_ref REAL,
				updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
				PRIMARY KEY (code, date)
			)
		''')
		
		conn.commit()
		conn.close()

	def add_watched_stock(self, code, name, sector, price, signal_type=None):
		"""새로운 종목을 관심 리스트에 추가합니다."""
		conn = self._get_connection()
		cursor = conn.cursor()
		try:
			# 중복 체크
			cursor.execute('''
				SELECT id FROM watched_stocks 
				WHERE code = ? 
				  AND signal_type = ? 
				  AND date(found_at) = date('now', 'localtime')
			''', (code, signal_type))
			if cursor.fetchone():
				return False

			cursor.execute('''
				INSERT INTO watched_stocks (code, name, sector, found_price, signal_type, found_at)
				VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
			''', (code, name, sector, price, signal_type))
			conn.commit()
			return True
		except Exception as e:
			print(f"[DB Error] add_watched_stock: {e}")
			return False
		finally:
			conn.close()

	def get_active_stocks(self):
		"""현재 추적 중인(is_active=1) 모든 종목을 반환합니다."""
		conn = self._get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			SELECT code, name, sector, found_price, found_at, signal_type 
			FROM watched_stocks 
			WHERE is_active = 1
			ORDER BY found_at DESC
		''')
		rows = cursor.fetchall()
		result = [{"code": r[0], "name": r[1], "sector": r[2], "found_price": r[3], "found_at": r[4], "signal_type": r[5]} for r in rows]
		conn.close()
		return result

	def log_performance(self, code, current_price, profit_rate):
		"""종목의 성과를 기록합니다."""
		conn = self._get_connection()
		cursor = conn.cursor()
		try:
			cursor.execute('''
				INSERT INTO performance_log (stock_code, current_price, profit_rate, check_time)
				VALUES (?, ?, ?, datetime('now', 'localtime'))
			''', (code, current_price, profit_rate))
			conn.commit()
		except Exception as e:
			print(f"[DB Error] log_performance: {e}")
		finally:
			conn.close()

	def delete_old_records(self, days):
		"""지정된 일수 이전의 기록을 삭제합니다."""
		conn = self._get_connection()
		cursor = conn.cursor()
		deleted_count = 0
		try:
			cutoff_date_sql = f"date('now', '-{days} days', 'localtime')"
			cursor.execute(f"DELETE FROM watched_stocks WHERE date(found_at) <= {cutoff_date_sql}")
			deleted_count = cursor.rowcount
			conn.commit()
		except Exception as e:
			print(f"[DB Error] delete_old_records: {e}")
		finally:
			conn.close()
		return deleted_count

	def save_daily_cache(self, cache_data):
		"""일별 지표 캐시 저장"""
		conn = self._get_connection()
		cursor = conn.cursor()
		try:
			today_str = datetime.datetime.now().strftime("%Y%m%d")
			count = 0
			for code, df in cache_data.items():
				if df.empty: continue
				row = df.iloc[-1]
				date_val = row.get('date', today_str)
				cursor.execute('''
					INSERT OR REPLACE INTO daily_summary 
					(code, date, close, last_vol, ma5, ma20, ma60, bb_upper, bb_lower, high_ref, updated_at)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
				''', (code, date_val, float(row.get('close', 0)), float(row.get('volume', 0)),
					  float(row.get('MA_5', 0)), float(row.get('MA_20', 0)), float(row.get('MA_60', 0)),
					  float(row.get('BB_Upper', 0)), float(row.get('BB_Lower', 0)), float(row.get('High_Ref', 0))))
				count += 1
			conn.commit()
			return count
		except Exception as e:
			print(f"[DB Error] save_daily_cache: {e}")
			return 0
		finally:
			conn.close()

	def load_daily_cache(self):
		"""DB에서 캐시 로드"""
		conn = self._get_connection()
		cursor = conn.cursor()
		cache = {}
		try:
			cursor.execute("SELECT * FROM daily_summary")
			for r in cursor.fetchall():
				cache[r[0]] = {'date': r[1], 'close': r[2], 'volume': r[3], 'MA_5': r[4], 
							  'MA_20': r[5], 'MA_60': r[6], 'BB_Upper': r[7], 'BB_Lower': r[8], 'High_Ref': r[9]}
		except Exception as e:
			print(f"[DB Error] load_daily_cache: {e}")
		finally:
			conn.close()
		return cache
