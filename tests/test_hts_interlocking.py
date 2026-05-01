import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QApplication

# Root 경로 추가
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

def test_hts_connector_admin_check():
	"""관리자 권한 확인 함수가 정상적으로 정의되어 있는지 확인"""
	from shared.hts_connector import is_admin
	assert callable(is_admin)
	res = is_admin()
	assert isinstance(res, bool)

def test_hts_window_search_functions():
	"""HTS 창 탐색 함수들이 존재하며 호출 가능한지 확인"""
	from shared.hts_connector import find_hts_window, find_0600_chart_window
	assert callable(find_hts_window)
	assert callable(find_0600_chart_window)
	
	# 실제 실행 환경은 아니더라도 None 혹은 HWND(int)를 반환해야 함
	res = find_hts_window()
	assert res is None or isinstance(res, int)

def test_at_sig_redirection():
	"""AT_Sig 내의 hts_connector가 shared 모듈로 정상 전달되는지 확인"""
	# AT_Sig/hts_connector.py가 shared에서 가져오는지 확인
	at_sig_path = os.path.join(ROOT, "AT_Sig")
	sys.path.append(at_sig_path)
	
	try:
		import AT_Sig.hts_connector as at_hts
		from shared.hts_connector import send_to_hts as shared_send
		
		# hts_connector.py 내에 send_to_hts가 정의되어 있거나 임포트되어 있어야 함
		assert hasattr(at_hts, 'send_to_hts')
		# 코드 비교는 어려우므로 존재 여부 위주로 확인
	finally:
		if at_sig_path in sys.path:
			sys.path.remove(at_sig_path)

def test_master_control_admin_logic():
	"""Master_Control의 관리자 권한 UI 로직이 에러 없이 실행되는지 확인"""
	from Master_Control import MasterControl
	
	# QApplication 인스턴스가 없으면 생성 (테스트용)
	app = QApplication.instance()
	if not app:
		app = QApplication(sys.argv)
	
	try:
		with patch('shared.hts_connector.is_admin', return_value=True):
			mc = MasterControl()
			assert hasattr(mc, 'admin_status')
			assert mc.admin_status is True
			assert "ADMIN" in mc.lbl_admin.text()
			
		with patch('shared.hts_connector.is_admin', return_value=False):
			mc2 = MasterControl()
			assert mc2.admin_status is False
			assert "NON-ADMIN" in mc2.lbl_admin.text()
	except Exception as e:
		pytest.fail(f"MasterControl initialization with admin logic failed: {e}")

def test_hts_interlock_binding_in_trading_ui():
    """AT_Sig UI에서 HTS 연동 이벤트가 바인딩되는지 확인"""
    # [안실장 픽스] config.py 충돌 방지를 위해 캐시 제거 및 경로 우선순위 조정
    at_sig_path = os.path.join(ROOT, "AT_Sig")
    if "config" in sys.modules:
        del sys.modules["config"]
    if at_sig_path not in sys.path:
        sys.path.insert(0, at_sig_path)
        
    from AT_Sig.trading_ui import TradingMainWindow
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        
    # [안실장 픽스] asyncio 루프 에러 방지를 위해 모든 배경 초기화 메서드 패치
    with patch('AT_Sig.trading_ui.TradingMainWindow.start_polling'), \
         patch('AT_Sig.trading_ui.TradingMainWindow.start_system_initialization'), \
         patch('AT_Sig.trading_ui.TradingMainWindow.periodic_update'), \
         patch('AT_Sig.trading_ui.TradingMainWindow.toggle_auto_refresh'):
         
        # UI 생성 시 init_hts_interlock이 호출됨
        with patch('AT_Sig.trading_ui.TradingMainWindow.init_hts_interlock') as mock_init:
            win = TradingMainWindow()
            mock_init.assert_called_once()
            win.close()
            win.deleteLater()
            
        # 실제 바인딩 함수 내 로직 존재 여부 확인
        win = TradingMainWindow()
        assert hasattr(win, 'on_trades_double_clicked')
        assert callable(win.on_trades_double_clicked)
        win.close()
        win.deleteLater()
    
    # 남은 이벤트 처리
    app.processEvents()
