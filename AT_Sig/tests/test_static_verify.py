import pytest
import os

def test_static_code_verification():
    """파일 내용을 직접 읽어서 핵심 로직이 올바르게 구현되었는지 검수"""
    ui_path = "d:/AG/KW_AutoTrading/AT_Sig/trading_ui.py"
    engine_path = "d:/AG/KW_AutoTrading/AT_Sig/trading_engine.py"
    integrator_path = "d:/AG/KW_AutoTrading/Lead_Sig/core/integrator.py"

    # 1. UI 컬럼 및 인덱스 검증
    with open(ui_path, "r", encoding="utf-8") as f:
        ui_content = f.read()
        assert '["시간", "종목코드", "종목명", "포착가", "현재가", "매수목표가", "상태", "등락률"]' in ui_content
        assert "self.table_captured.setItem(row, 4, p_item)" in ui_content # 현재가
        assert "self.table_captured.setItem(row, 5, t_item)" in ui_content # 목표가
        assert "self.table_captured.setItem(row, 7, r_item)" in ui_content # 등락률
        assert "self.table_captured.setItem(row, 6, s_item)" in ui_content # 상태

    # 2. 엔진 수신 및 전송 데이터 검증
    with open(engine_path, "r", encoding="utf-8") as f:
        engine_content = f.read()
        assert "l_price = stock.get('price', 0)" in engine_content
        assert "l_ratio = stock.get('change', 0.0)" in engine_content
        assert "self._ensure_ui_captured(code, stk_name, msg=\"[Lead_Sig] 주도주/후발주\", price=l_price, ratio=l_ratio)" in engine_content
        assert "from history_manager import record_captured" in engine_content # 타겟 계산 시 저장 로직

    # 3. 인티그레이터 전송 데이터 검증
    with open(integrator_path, "r", encoding="utf-8") as f:
        integrator_content = f.read()
        assert "'price': stock_info.get('price', 0)" in integrator_content
        assert "'change': stock_info.get('change', 0.0)" in integrator_content

    print("✅ All static code verifications PASSED!")

if __name__ == "__main__":
    test_static_code_verification()
