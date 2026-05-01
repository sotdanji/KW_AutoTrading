import json
import os
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_history.json')

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"History load failed: {e}")
        return {}

def cleanup_history(history, days_to_keep=30):
    """
    오래된 거래 내역 삭제 (기본 30일)
    """
    try:
        current_date = datetime.now()
        keys_to_remove = []
        
        for date_str in history.keys():
            try:
                # 날짜 형식 'YYYY-MM-DD' 파싱
                record_date = datetime.strptime(date_str, '%Y-%m-%d')
                delta = current_date - record_date
                if delta.days > days_to_keep:
                    keys_to_remove.append(date_str)
            except ValueError:
                # 날짜 형식이 아니면 무시 (혹은 삭제?)
                continue
                
        if keys_to_remove:
            print(f"[History Cleanup] Removing old records: {keys_to_remove}")
            for k in keys_to_remove:
                del history[k]
                
    except Exception as e:
        print(f"History cleanup error: {e}")

def save_history(history):
    # 저장 전 정리
    cleanup_history(history)
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"History save failed: {e}")


def get_today_str():
    return datetime.now().strftime('%Y-%m-%d')

def record_trade(code, trade_type, msg="", name="", price=0, qty=0):
    """
    거래 기록 저장
    trade_type: 'buy', 'sell'
    """
    history = load_history()
    today = get_today_str()
    
    if today not in history:
        history[today] = {}
        
    if code not in history[today]:
        history[today][code] = []
        
    # [안실장 픽스] 종목명이 깨졌거나 점(.)인 경우 마스터 캐시 참조
    if not name or name.strip() in ["", ".", "..", "...", "?"]:
        from shared.stock_master import load_master_cache
        master = load_master_cache()
        name = master.get(code, name if name else code)

    history[today][code].append({
        'type': trade_type,
        'time': datetime.now().strftime('%m/%d %H:%M:%S'),
        'name': name,
        'price': price,
        'qty': qty,
        'msg': msg
    })
    
    save_history(history)

def load_today_history():
    """
    오늘 날짜의 모든 거래 내역 반환 (시간순 정렬됨)
    Returns: list of dict
    """
    history = load_history()
    today = get_today_str()
    
    if today not in history:
        return []
        
    # Flatten dict {code: [trades], ...} to list [trade, ...]
    all_trades = []
    for code, trades in history[today].items():
        for t in trades:
            # UI 호환을 위해 code도 포함
            t_copy = t.copy()
            t_copy['code'] = code
            all_trades.append(t_copy)
            
    # 시간순 정렬
    all_trades.sort(key=lambda x: x['time'])
    return all_trades

def was_sold_today(code):
    """
    오늘 해당 종목을 매도한 이력이 있는지 확인
    """
    history = load_history()
    today = get_today_str()
    
    if today not in history:
        return False
        
    if code not in history[today]:
        return False
        

    # 매도 이력 검색
    for trade in history[today][code]:
        if 'sell' in trade['type'] or '매도' in trade['type']:
            return True
            
    return False


# --- [안실장 신규] 포착 종목 이력 관리 ---
CAPTURED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'captured_history.json')

def load_captured():
    """전체 포착 이력 데이터 로드"""
    if not os.path.exists(CAPTURED_FILE):
        return {}
    try:
        with open(CAPTURED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Captured history load failed: {e}")
        return {}

def save_captured(captured):
    """포착 이력 데이터 저장 전 정리 및 파일 쓰기"""
    # 7일 이상 된 데이터 정리
    try:
        current_date = datetime.now()
        keys_to_remove = []
        for date_str in captured.keys():
            try:
                record_date = datetime.strptime(date_str, '%Y-%m-%d')
                if (current_date - record_date).days > 7:
                    keys_to_remove.append(date_str)
            except: continue
        for k in keys_to_remove:
            del captured[k]
    except: pass

    try:
        with open(CAPTURED_FILE, 'w', encoding='utf-8') as f:
            json.dump(captured, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Captured history save failed: {e}")

def record_captured(code, data):
    """종목 포착 정보 기록 (중복 방지를 위해 코드 단위로 저장)"""
    captured_hist = load_captured()
    today = get_today_str()
    if today not in captured_hist:
        captured_hist[today] = {}
    
    # [안실장 픽스] 포착 로그 내 종목명 무결성 확보
    name = data.get('name', '')
    if not name or name.strip() in ["", ".", "..", "...", "?"]:
        from shared.stock_master import load_master_cache
        master = load_master_cache()
        data['name'] = master.get(code, name if name else code)

    captured_hist[today][code] = data
    save_captured(captured_hist)

def cleanup_invalid_captured():
    """포착가 정보가 없는 (--- 또는 0) 유효하지 않은 데이터를 DB에서 영구 삭제"""
    captured_hist = load_captured()
    today = get_today_str()
    if today not in captured_hist:
        return
        
    invalid_codes = []
    for code, data in captured_hist[today].items():
        price = str(data.get('price', '0')).replace(',', '').strip()
        code_clean = str(code).replace('A', '').strip()
        
        # 1. 가격 정보가 없거나 (---)
        # 2. 종목 코드가 6자리가 아닌 경우 (비표준 코드)
        if price in ["---", "0", "0.0"] or len(code_clean) != 6:
            invalid_codes.append(code)
            
    if invalid_codes:
        print(f"[History Cleanup] Removing {len(invalid_codes)} invalid captured stocks (No Price or Bad Code)")
        for code in invalid_codes:
            del captured_hist[today][code]
        save_captured(captured_hist)

def load_today_captured():
    """오늘 포착된 모든 종목 리스트 반환 (유효성 검사 포함)"""
    cleanup_invalid_captured() # 조회 전 무결성 정리
    captured_hist = load_captured()
    today = get_today_str()
    if today not in captured_hist:
        return []
    # 딕셔너리 값들을 리스트로 변환하여 반환
    return list(captured_hist[today].values())

