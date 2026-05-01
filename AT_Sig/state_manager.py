import os
import sqlite3
import json
from datetime import datetime

# [안실장 유지보수 가이드] DB 경로를 루트의 data/ 폴더로 통합
def get_db_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    path = os.path.join(project_root, "data", "state.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

DB_PATH = get_db_path()
JSON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading_state.json')

def _init_db():
    """DB 및 테이블 초기화 및 WAL 모드 활성화 (미싱 컬럼 마이그레이션 포함)"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL") # [Optimization] 동시성 성능 향상
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_state (
                stk_cd TEXT PRIMARY KEY,
                tp_step INTEGER DEFAULT 0,
                sl_step INTEGER DEFAULT 0,
                max_price REAL DEFAULT 0.0,
                ts_count INTEGER DEFAULT 0,
                target_stop REAL DEFAULT 0.0,
                target_exit REAL DEFAULT 0.0,
                last_update TEXT
            )
        """)
        
        # [안실장 픽스] 기존 DB 사용자의 경우 컬럼이 없을 수 있으므로 체크 후 추가
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(stock_state)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'target_stop' not in columns:
            try:
                conn.execute("ALTER TABLE stock_state ADD COLUMN target_stop REAL DEFAULT 0.0")
            except: pass
        if 'target_exit' not in columns:
            try:
                conn.execute("ALTER TABLE stock_state ADD COLUMN target_exit REAL DEFAULT 0.0")
            except: pass
            
        conn.commit()

    # [Migration] 기존 JSON 데이터가 있으면 DB로 이전
    if os.path.exists(JSON_FILE):
        _migrate_from_json()

def _migrate_from_json():
    """JSON 파일의 데이터를 SQLite DB로 마이그레이션"""
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            with sqlite3.connect(DB_PATH) as conn:
                for code, s in data.items():
                    # 'step' 필드 하위 호화
                    tp = s.get('tp_step') or s.get('step', 0)
                    conn.execute("""
                        INSERT OR REPLACE INTO stock_state (stk_cd, tp_step, sl_step, max_price, ts_count, last_update)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (code, tp, s.get('sl_step', 0), s.get('max_price', 0.0), s.get('ts_count', 0), s.get('last_update')))
                conn.commit()
        
        # 마이그레이션 완료 후 파일명 변경 (백업)
        os.rename(JSON_FILE, JSON_FILE + '.bak')
        print(f"✅ 상태 데이터 마이그레이션 완료: JSON -> SQLite ({len(data)}건)")
    except Exception as e:
        print(f"⚠️ 마이그레이션 실패: {e}")

# 초기화 실행
_init_db()

def get_stock_state(stock_code):
    """특정 종목의 상태 조회"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM stock_state WHERE stk_cd = ?", (stock_code,))
            row = cursor.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        print(f"상태 조회 실패 ({stock_code}): {e}")
    
    return {'tp_step': 0, 'sl_step': 0, 'max_price': 0.0, 'ts_count': 0, 'target_stop': 0.0, 'target_exit': 0.0, 'last_update': None}

def update_stock_state(stock_code, tp_step=None, sl_step=None, max_price=None, ts_count=None, target_stop=None, target_exit=None):
    """특정 종목의 상태 업데이트 (로우 단위 원자적 업데이트)"""
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(DB_PATH) as conn:
            # 1. 존재 여부 확인 후 INSERT or UPDATE
            cursor = conn.execute("SELECT 1 FROM stock_state WHERE stk_cd = ?", (stock_code,))
            if not cursor.fetchone():
                conn.execute("INSERT INTO stock_state (stk_cd, last_update) VALUES (?, ?)", (stock_code, now))
            
            # 2. 동적 필드 업데이트
            updates = []
            params = []
            if tp_step is not None:
                updates.append("tp_step = ?")
                params.append(tp_step)
            if sl_step is not None:
                updates.append("sl_step = ?")
                params.append(sl_step)
            if max_price is not None:
                updates.append("max_price = ?")
                params.append(max_price)
            if ts_count is not None:
                updates.append("ts_count = ?")
                params.append(ts_count)
            
            if target_stop is not None:
                updates.append("target_stop = ?")
                params.append(target_stop)
            if target_exit is not None:
                updates.append("target_exit = ?")
                params.append(target_exit)
            
            updates.append("last_update = ?")
            params.append(now)
            params.append(stock_code)
            
            query = f"UPDATE stock_state SET {', '.join(updates)} WHERE stk_cd = ?"
            conn.execute(query, params)
            conn.commit()
    except Exception as e:
        print(f"상태 업데이트 실패 ({stock_code}): {e}")

def sync_state_with_balance(current_stock_codes):
    """현재 잔고에 없는 종목의 상태 제거 (DB 최적화)"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # 현재 잔고에 없는 종목 삭제
            placeholders = ', '.join(['?'] * len(current_stock_codes))
            if current_stock_codes:
                conn.execute(f"DELETE FROM stock_state WHERE stk_cd NOT IN ({placeholders})", current_stock_codes)
            else:
                conn.execute("DELETE FROM stock_state")
            conn.commit()
    except Exception as e:
        print(f"상태 동기화 실패: {e}")
