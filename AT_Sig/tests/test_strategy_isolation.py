
import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

# 프로젝트 루트(d:\AG\KW_AutoTrading)를 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # d:\AG\KW_AutoTrading
if project_root not in sys.path:
    sys.path.append(project_root)

from AT_Sig.get_setting import get_setting, update_setting

class TestStrategyIsolation(unittest.TestCase):
    def setUp(self):
        self.settings_path = os.path.join(project_root, "AT_Sig", "settings.json")
        # 테스트 전 원래 설정 백업
        with open(self.settings_path, 'r', encoding='utf-8') as f:
            self.original_settings = json.load(f)

    def tearDown(self):
        # 테스트 후 설정 복구
        with open(self.settings_path, 'w', encoding='utf-8') as f:
            json.dump(self.original_settings, f, ensure_ascii=False, indent=2)

    def test_start_trading_isolation(self):
        """매매 시작 시 검증 탭의 코드가 settings.json에 유입되지 않는지 테스트"""
        from AT_Sig.trading_ui import TradingMainWindow
        from PyQt6.QtWidgets import QApplication
        
        # GUI 없이 테스트하기 위해 Mocking
        app = QApplication.instance() or QApplication([])
        ui = TradingMainWindow()
        
        # 1. 검증 탭(에디터)에 임시 코드 입력
        test_code = "# THIS IS A TEST CODE THAT SHOULD NOT BE SAVED"
        ui.text_formula_preview.setPlainText(test_code)
        
        # 2. 기존 settings.json의 active_strategy_code 확인
        old_active_code = get_setting('active_strategy_code')
        
        # 3. 매매 시작 호출 (실제 엔진 시작은 Mock 처리)
        with patch.object(ui.chat_cmd, 'start', return_value=True):
            import asyncio
            # qasync 환경이므로 동기적으로 슬롯 호출 시뮬레이션
            # 실제로는 코드가 삭제되었으므로 update_setting이 호출되지 않아야 함
            ui.start_trading()
            
        # 4. 결과 검증: active_strategy_code가 유지되어야 함 (test_code로 바뀌면 안됨)
        new_active_code = get_setting('active_strategy_code')
        self.assertEqual(old_active_code, new_active_code, "검증 탭의 코드가 매매 시작 시 settings.json을 오염시켰습니다!")
        self.assertNotEqual(test_code, new_active_code)

if __name__ == "__main__":
    unittest.main()
