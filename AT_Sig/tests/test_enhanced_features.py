import pytest
import sys
import os
import pandas as pd
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.market_status import MarketStatusEngine, MarketRegime
from shared.accumulation_manager import AccumulationManager
from stock_radar import StockRadar
from check_n_sell import chk_n_sell

@pytest.fixture
def mock_db_connection():
    with patch('shared.accumulation_manager.sqlite3.connect') as mock_connect:
        yield mock_connect

def test_market_regime_logic():
    """Test MarketStatusEngine basic logic with mock data"""
    # Create sample data for 120 days
    dates = pd.date_range(end='2024-03-01', periods=120).strftime('%Y%m%d').tolist()
    # Scenario: Steady uptrend
    prices = [1000 + i*10 for i in range(120)]
    df = pd.DataFrame({'close': prices}, index=dates)
    
    engine = MarketStatusEngine(token="TEST")
    
    # Mocking get_index_chart
    with patch('shared.market_status.fetch_index_chart', return_value=df.to_dict('records')):
        regime_info = engine.get_current_regime()
        assert regime_info['regime'] in [MarketRegime.BULL, MarketRegime.SIDEWAYS]

def test_accumulation_quality_premium():
    """Test premium broker detection"""
    acc_mgr = AccumulationManager()
    
    # Mock database data
    mock_df = pd.DataFrame([
        {'broker_name': '모건스탠리', 'net_buy_qty': 10000, 'is_foreign': 1},
        {'broker_name': '키움증권', 'net_buy_qty': 5000, 'is_foreign': 0}
    ])
    
    with patch('pandas.read_sql_query', return_value=mock_df):
        with patch.object(AccumulationManager, '_get_connection', return_value=MagicMock()):
            quality = acc_mgr.get_accumulation_quality("005930")
            assert quality['is_premium'] is True
            assert "프리미엄" in quality['desc']
            assert "모건스탠리" in quality['top_broker']

def test_stock_radar_momentum_explosion():
    """Test StockRadar momentum detection with mock API returns"""
    radar = StockRadar(token="TEST")
    
    # Mock 1: fetch_minute_chart_ka10080 (Explosion scenario: 500% spike)
    # df.iloc[0]['vol'] = 5000, df.iloc[1:11]['vol'] = 1000
    mock_min_data = [{'vol': 5000}] + [{'vol': 1000} for _ in range(15)]
    
    # Mock 2: cached real-time data
    mock_cached_rt = {
        'strength': '150',     # Strong strength
        'total_ask': '3000',   # > total_bid -> order book ratio 3.0
        'total_bid': '1000',
        'volume': '5000'       # Current volume to compare against avg_vol (1000)
    }
    
    class AsyncMockResponse:
        def __init__(self, json_data, status=200):
            self.json_data = json_data
            self.status = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def json(self):
            return self.json_data
            
    def mock_post_side_effect(url, **kwargs):
        if 'mchart' in url:
            return AsyncMockResponse({'output': mock_min_data})
        return AsyncMockResponse({}, status=404)

    with patch('aiohttp.ClientSession.post', side_effect=mock_post_side_effect):
        import asyncio
        loop = asyncio.get_event_loop()
        analysis = loop.run_until_complete(radar.analyze_momentum("005930", cached_rt=mock_cached_rt))
        
        # density_ratio: current / avg = 5000 / 1000 = 500.0 (500%)
        # density_score = min(500 / 20, 40) = min(25, 40) = 25
        # strength_score = min((150 - 100)/1, 30) = 30
        # order_book_ratio = 3000 / 1000 = 3 => +30 score
        # total_score = 25 + 30 + 30 = 85 >= 60 -> passes assert
        assert analysis['score'] >= 60
        assert bool(analysis['is_exploding']) is True
        assert 'msg' in analysis

def test_smart_exit_on_crash():
    """Test chk_n_sell triggers smart exit during CRASH"""
    mock_token = "TEST"
    
    # Mock holdings: 1 stock
    mock_holdings = {
        'stk_acnt_evlt_prst': [{
            'stk_cd': '005930',
            'stk_nm': '삼성전자',
            'rmnd_qty': '100',
            'pl_rt': '2.0', # In profit
            'evlu_pfls_amt': '10000',
            'pchs_amt': '500000',
            'cur_prc': '5100',
            'now_prc': '5100'
        }]
    }
    
    # Mock regime: CRASH
    regime = {'regime': MarketRegime.CRASH}
    
    # Mock time to be during trading hours (10:00 AM)
    mock_now = datetime(2024, 3, 18, 10, 0, 0)
    
    with patch('check_n_sell.get_my_stocks', return_value=mock_holdings), \
         patch('check_n_sell.sell_stock', return_value={'return_code': '0'}) as mock_sell, \
         patch('check_n_sell.tel_send'), \
         patch('check_n_sell.get_stock_state', return_value={}), \
         patch('check_n_sell.datetime') as mock_datetime:
        
        mock_datetime.now.return_value = mock_now
        # Also need replace to work for start_time/end_time calculation inside chk_n_sell
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        # Execute
        chk_n_sell(token=mock_token, regime=regime)
        
        # Verify: Should sell 100 shares despite being in profit
        mock_sell.assert_called_once()
        args, kwargs = mock_sell.call_args
        assert args[0] == '005930'
        assert args[1] == 100

if __name__ == '__main__':
    pytest.main([__file__])
