import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import asyncio

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_engine import TradingEngine

class TestTradingEngine(unittest.TestCase):
    def setUp(self):
        """test setup: mocks components"""
        # Patch dependencies BEFORE initializing TradingEngine
        self.patcher1 = patch('trading_engine.DataManager')
        self.patcher2 = patch('trading_engine.StrategyRunner')
        self.patcher3 = patch('trading_engine.RealTimeSearch')
        self.patcher4 = patch('trading_engine.BrokerAdapter')
        self.patcher5 = patch('trading_engine.concurrent.futures.ProcessPoolExecutor')
        self.patcher6 = patch('trading_engine.MarketStatusEngine')
        self.patcher7 = patch('trading_engine.tel_send') # Prevent telegram messages
        self.patcher8 = patch('trading_engine.get_token')

        self.MockDataManager = self.patcher1.start()
        self.MockStrategyRunner = self.patcher2.start()
        self.MockRealTimeSearch = self.patcher3.start()
        self.MockBrokerAdapter = self.patcher4.start()
        self.MockPool = self.patcher5.start()
        self.MockMarketStatusEngine = self.patcher6.start()
        self.MockTelSend = self.patcher7.start()
        self.MockGetToken = self.patcher8.start()

        # Create Engine instance
        self.engine = TradingEngine()
        
        # Replace internal components with specific mocks if needed for finer control
        self.engine.broker = self.MockBrokerAdapter.return_value
        self.engine.rt_search = self.MockRealTimeSearch.return_value
        self.engine.data_manager = self.MockDataManager.return_value
        
        # Mock rt_search.start to be an async mock
        self.engine.rt_search.start = AsyncMock(return_value=True)
        self.engine.rt_search.stop = AsyncMock()
        
        # Mock broker.validate_session to return (True, "Success") to fix unpack error
        self.engine.broker.validate_session.return_value = (True, "Success")

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()
        self.patcher5.stop()
        self.patcher6.stop()
        self.patcher7.stop()
        self.patcher8.stop()

    def test_init(self):
        """Test initialization"""
        self.assertIsNotNone(self.engine)
        self.assertIsNotNone(self.engine.pool)
        self.assertFalse(self.engine.is_running)

    @patch('trading_engine.asyncio.create_task')
    def test_start_success(self, mock_create_task):
        """Test start method success path"""
        def close_coro(coro, *args, **kwargs):
            coro.close()
            return MagicMock()
        mock_create_task.side_effect = close_coro
        self.MockGetToken.return_value = "TEST_TOKEN"
        # Run async test
        async def run_test():
            result = await self.engine.start()
            return result

        result = asyncio.run(run_test())
        
        self.assertTrue(result)
        self.assertTrue(self.engine.is_running)
        self.assertEqual(self.engine.token, "TEST_TOKEN")
        
        # Verify broker token set (by attribute or method)
        self.assertEqual(self.engine.broker.token, "TEST_TOKEN")
        
        # Verify RT search started
        self.engine.rt_search.start.assert_called_once()
        
        # Verify sell loop task created (CRITICAL: this proves we tried to start background task)
        # But since we mocked create_task, the actual loop didn't run effectively preventing infinite loop in test
        self.assertTrue(mock_create_task.called) 

    def test_start_fail_no_token(self):
        """Test start fail when no token"""
        self.MockGetToken.return_value = None
        
        async def run_test():
            return await self.engine.start()

        result = asyncio.run(run_test())
        self.assertFalse(result)
        self.assertFalse(self.engine.is_running)

    @patch('trading_engine.get_setting')
    def test_process_buy_logic(self, mock_get_setting):
        """Test buy logic"""
        # Setup Mocks
        mock_get_setting.side_effect = lambda key, default=None: {
            'manual_buy': False,
            'max_stock_count': 10,
            'buy_method': 'percent',
            'buy_ratio': 10.0
        }.get(key, default)

        # 1. Holdings: Empty
        self.engine.broker.get_holdings.return_value = []
        # 2. Balance: 1,000,000
        self.engine.broker.get_balance.return_value = 1000000
        # 3. Price: 10,000
        self.engine.broker.get_current_price.return_value = 10000
        self.engine.broker.get_stock_name.return_value = "TestStock"
        self.engine.broker.get_market_index.return_value = {'rate': 0.0}
        self.engine.broker.get_market_type.return_value = "KOSPI"
        self.engine.rt_search.price_cache = {}
        # 4. Buy result: Success (0)
        self.engine.broker.buy.return_value = (0, "Success")
        
        # [안실장 픽스] 시장 상황 매니저 모킹 (약세장 0.5배 가정)
        self.engine.signal_manager = MagicMock()
        self.engine.signal_manager.get_trading_multiplier.return_value = 0.5

        # Execute
        async def run_buy():
            self.engine.is_running = True
            self.engine._ensure_async_objects()
            await self.engine.process_buy("005930")
            
        asyncio.run(run_buy())

        # Verify
        # [안실장 미수방어 적용] 
        # Balance 1,000,000 * CASH_MARGIN(0.993) * 10% = 99,300 base
        # Multiplier 0.5 -> Final buy amount = 49,650
        # Qty = 49,650 // 10,000 = 4
        self.engine.broker.buy.assert_called_with("005930", 4, 0, "3")

    @patch('trading_engine.get_setting')
    def test_process_buy_crash_blocking(self, mock_get_setting):
        """Test buy blocking in CRASH regime"""
        # Setup Mocks
        mock_get_setting.side_effect = lambda key, default=None: {
            'manual_buy': False,
            'max_stock_count': 10,
            'buy_method': 'percent',
            'buy_ratio': 10.0
        }.get(key, default)

        # 1. Market Status: CRASH
        from shared.market_status import MarketRegime
        self.engine.current_regime = {'regime': MarketRegime.CRASH}
        
        # 2. Results Mocks
        self.engine.broker.get_holdings.return_value = []
        self.engine.broker.get_balance.return_value = 1000000
        
        # Execute
        async def run_buy():
            self.engine.is_running = True
            self.engine._ensure_async_objects()
            await self.engine.process_buy("005930")
            
        asyncio.run(run_buy())

        # Verify: buy should NEVER be called
        self.engine.broker.buy.assert_not_called()

if __name__ == '__main__':
    unittest.main()
