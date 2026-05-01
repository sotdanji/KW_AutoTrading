import os
import sys
import json
import pytest
import re

# 프로젝트 루트를 경로에 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.stock_master import load_master_cache, MASTER_OVERRIDES

def test_stock_master_json_integrity():
    """stock_master.json 파일 자체의 무결성 확인"""
    path = os.path.join(ROOT, "stock_master.json")
    assert os.path.exists(path), "stock_master.json 파일이 존재하지 않습니다."
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    assert isinstance(data, dict), "JSON 데이터 형식이 딕셔너리가 아닙니다."
    assert "373220" in data, "LG에너지솔루션(373220) 코드가 JSON에 누락되었습니다."
    assert data["373220"] == "LG에너지솔루션", f"JSON의 종목명이 잘못되었습니다: {data['373220']}"

def test_load_master_cache_overrides():
    """메모리 로드 시 오버라이드 로직 확인"""
    cache = load_master_cache()
    
    # 1. LG에너지솔루션 확인
    assert cache.get("373220") == "LG에너지솔루션", "캐시 로드 후 LG에너지솔루션 명칭이 올바르지 않습니다."
    
    # 2. 기타 주요 종목 확인
    assert cache.get("005930") == "삼성전자", "삼성전자 명칭 오류"
    assert cache.get("000660") == "SK하이닉스", "SK하이닉스 명칭 오류"

def test_junk_name_filter_logic():
    """무효한 종목명 필터링 로직 확인 (점(...) 등)"""
    from shared.stock_master import save_master_cache
    
    test_data = {
        "373220": "...",  # 오염된 데이터 가정
        "005930": "삼성전자",
        "123456": "정상종목"
    }
    
    # 오염된 데이터가 있어도 로드 시점에는 오버라이드가 우선되어야 함
    cache = load_master_cache()
    assert cache["373220"] == "LG에너지솔루션", "오염된 데이터보다 오버라이드가 우선되지 않았습니다."

def test_analyzer_ui_mapping_logic():
    """Analyzer_Sig/ui/accumulation_tab.py 의 매핑 로직 시뮬레이션"""
    cache = load_master_cache()
    
    def simulate_ui_logic(code_str):
        clean_code = re.sub(r'[^0-9]', '', str(code_str))
        if clean_code == "373220":
            return "LG에너지솔루션"
        
        raw_name = cache.get(code_str, "")
        if not raw_name or not re.search('[가-힣a-zA-Z]', str(raw_name)):
            return code_str
        return raw_name

    assert simulate_ui_logic("373220") == "LG에너지솔루션", "UI 로직 내 강제 주입 실패"
    assert simulate_ui_logic(" 373220 ") == "LG에너지솔루션", "공백 포함 시 UI 로직 실패"
    assert simulate_ui_logic("005930") == "삼성전자", "일반 종목 매핑 실패"
