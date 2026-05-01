import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication, QTableWidgetItem
from PyQt6.QtCore import Qt
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from AT_Sig.trading_ui import TradingMainWindow

# Create QApplication instance if not exists
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)


class TestUIUpdate(unittest.TestCase):
    """
    table_captured 컬럼 구조 (2024.04 리뉴얼):
      [0:시간, 1:종목코드, 2:종목명(축약), 3:포착가, 4:현재가, 5:매수목표가, 6:상태, 7:등락률]
    """

    def setUp(self):
        # Patch async initialization methods to prevent asyncio errors in test environment
        self.patcher_polling = patch('AT_Sig.trading_ui.TradingMainWindow.start_polling')
        self.patcher_init = patch('AT_Sig.trading_ui.TradingMainWindow.start_system_initialization')
        self.patcher_periodic = patch('AT_Sig.trading_ui.TradingMainWindow.periodic_update')
        self.patcher_toggle = patch('AT_Sig.trading_ui.TradingMainWindow.toggle_auto_refresh')
        
        self.mock_polling = self.patcher_polling.start()
        self.mock_init = self.patcher_init.start()
        self.mock_periodic = self.patcher_periodic.start()
        self.mock_toggle = self.patcher_toggle.start()
        
        self.window = TradingMainWindow()

    def tearDown(self):
        self.window.close()
        self.patcher_polling.stop()
        self.patcher_init.stop()
        self.patcher_periodic.stop()
        self.patcher_toggle.stop()

    def test_captured_event(self):
        """Test adding a captured stock"""
        data = {
            "code": "005930",
            "name": "삼성전자", # 4 chars (ok)
            "time": "10:00:00"
        }

        self.window.add_captured_stock(data)

        # Verify row added
        self.assertEqual(self.window.table_captured.rowCount(), 1)

        # Verify column values match current layout (0:시간, 1:종목코드, 2:종목명, 6:상태)
        today_md = datetime.now().strftime("%m/%d")
        self.assertEqual(self.window.table_captured.item(0, 0).text(), f"{today_md} 10:00:00")   # 시간
        self.assertEqual(self.window.table_captured.item(0, 1).text(), "005930")     # 종목코드
        self.assertEqual(self.window.table_captured.item(0, 2).text(), "삼성전자")    # 종목명
        self.assertEqual(self.window.table_captured.item(0, 6).text(), "대기")       # 상태

        # Test Duplicate — should not add duplicate
        self.window.add_captured_stock(data)
        self.assertEqual(self.window.table_captured.rowCount(), 1)

    def test_filter_update_event(self):
        """Test updating filter status"""
        # Pre-populate
        data = {"code": "000660", "name": "SK하이닉스", "time": "10:05:00"}
        self.window.add_captured_stock(data)

        # Update to 매수완료 (Green #4caf50)
        update_data = {"code": "000660", "status": "매수완료"}
        self.window.update_filter_status(update_data)

        # Verify status column (index 6)
        item = self.window.table_captured.item(0, 6)
        self.assertEqual(item.text(), "매수완료")
        self.assertEqual(item.foreground().color().name().lower(), "#4caf50")

        # Update to 에러 (Red #ff5252)
        update_data = {"code": "000660", "status": "에러발생"}
        self.window.update_filter_status(update_data)
        item = self.window.table_captured.item(0, 6)
        self.assertEqual(item.text(), "에러발생")
        self.assertEqual(item.foreground().color().name().lower(), "#ff5252")


if __name__ == '__main__':
    unittest.main()
