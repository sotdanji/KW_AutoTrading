import pytest
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import StockItem
from trading_engine import TradingEngine

@pytest.fixture
def mock_engine():
    with patch('trading_engine.DataManager'), \
         patch('trading_engine.StrategyRunner'), \
         patch('trading_engine.RealTimeSearch'), \
         patch('trading_engine.BrokerAdapter'), \
         patch('trading_engine.concurrent.futures.ProcessPoolExecutor'), \
         patch('trading_engine.get_token', return_value="TEST_TOKEN"), \
         patch('trading_engine.tel_send'):
        engine = TradingEngine(ui_callback=MagicMock())
        # Mocking components
        engine.rt_search = MagicMock()
        engine.rt_search.seq_to_name = {"4": "테스트조건식"}
        engine.rt_search.register_sise = AsyncMock()
        engine.broker.get_stock_name = MagicMock(return_value="삼성전자")
        engine.warm_up_stocks = AsyncMock()
        engine.process_buy = AsyncMock()
        return engine

def test_stock_item_extraction_cnsrreq():
    """Test StockItem extraction from CNSRREQ (Initial List) format"""
    # Pattern 1: jmcode
    data = {"jmcode": "A005930", "stk_nm": "삼성전자"}
    item = StockItem.from_api_dict(data)
    assert item.code == "005930"
    assert item.name == "삼성전자"

    # Pattern 2: code
    data = {"code": "000660", "name": "SK하이닉스"}
    item = StockItem.from_api_dict(data)
    assert item.code == "000660"

def test_stock_item_extraction_real():
    """Test StockItem extraction from REAL (Real-time capture) format"""
    # Sample data based on user provide
    data = {
        'values': {
            '841': '4',
            '9001': '005930',
            '843': 'I',
            '20': '152028',
            '907': '2',
            '10': '75000',
            '12': '1.5',
            '13': '1000000'
        },
        'type': '02',
        'name': '조건검색',
        'item': '005930'
    }
    
    item = StockItem.from_api_dict(data)
    assert item.code == "005930"
    assert item.price == 75000
    assert item.change_rate == 1.5
    assert item.volume == 1000000

def test_handle_rt_message_real_packet(mock_engine):
    """Test that TradingEngine handles REAL packet and categories it as '실시간포착'"""
    # REAL Packet structure from user
    packet = {
        'trnm': 'REAL',
        'data': [
            {
                'values': {
                    '841': '4',
                    '9001': '005930',
                    '843': 'I',
                    '20': '152028',
                    '907': '2'
                },
                'type': '02',
                'name': '조건검색',
                'item': '005930'
            }
        ]
    }
    
    import asyncio
    asyncio.run(mock_engine.handle_rt_message(packet))
    
    # Check if ui_callback was called with 'captured' and '실시간포착'
    # Use any_call to find the specific signal in the mock calls
    captured_calls = [call for call in mock_engine.ui_callback.call_args_list if call[0][0] == "captured"]
    assert len(captured_calls) > 0
    found = False
    for call in captured_calls:
        data = call[0][1]
        if data["code"] == "005930" and data["msg"] == "실시간포착":
            found = True
            break
    assert found, "Could not find '실시간포착' message for code '005930' in ui_callback calls"

def test_handle_rt_message_cnsrreq_packet(mock_engine):
    """Test that TradingEngine handles CNSRREQ packet and categories it as '감시대기'"""
    packet = {
        'trnm': 'CNSRREQ',
        'seq': '4',
        'return_code': 0,
        'data': [
            {'jmcode': 'A005930'}
        ]
    }
    
    import asyncio
    asyncio.run(mock_engine.handle_rt_message(packet))
    
    # [UI Optimization] 초기 리스트(CNSRREQ)는 모든 모드에서 전광판 표시를 생략합니다.
    # 따라서 captured 이벤트가 없어야 함
    captured_calls = [call for call in mock_engine.ui_callback.call_args_list if call[0][0] == "captured"]
    assert len(captured_calls) == 0

