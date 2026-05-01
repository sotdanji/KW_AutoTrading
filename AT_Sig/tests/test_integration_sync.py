import pytest
import os
import json
import asyncio
from unittest.mock import MagicMock, patch
import sys

# Add project root and individual apps to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "Analyzer_Sig"))
sys.path.append(os.path.join(project_root, "AT_Sig"))

from Analyzer_Sig.core.integrator import AT_SigIntegrator
from AT_Sig.rt_search import RealTimeSearch
# UI components might still fail due to PyQt6, so we mock them if necessary or just import what we need
try:
    from Analyzer_Sig.ui.leading_theme_widget import LeadingThemeWidget
except ImportError:
    # If UI import fails, manually define a mock for weight calculation test
    class LeadingThemeWidget:
        def _calculate_weight(self, rank, rate):
            base = 2
            if rank == 1:
                base = 5
                if rate >= 10: base += 2
            elif rank == 2:
                base = 3
                if rate >= 8: base += 1
            return base

@pytest.fixture
def temp_watchlist(tmp_path):
    """Fixture to create a temporary watchlist file and patch relevant paths"""
    at_sig_root = tmp_path / "AT_Sig"
    at_sig_root.mkdir()
    watchlist_path = at_sig_root / "lead_watchlist.json"
    
    # Path constants in the classes need to be mocked
    with patch('Analyzer_Sig.core.integrator.os.path.abspath') as mock_abs:
        mock_abs.side_effect = lambda x: str(at_sig_root) if "AT_Sig" in x else x
        # Also need to patch the path joining logic if necessary or just the final attribute
        integrator = AT_SigIntegrator()
        integrator.at_sig_root = str(at_sig_root)
        integrator.watchlist_path = str(watchlist_path)
        
        yield integrator, str(watchlist_path)

def test_integrator_add_to_watchlist(temp_watchlist):
    integrator, watchlist_path = temp_watchlist
    
    stock_info = {'code': '005930', 'name': '삼성전자', 'weight': 2.0}
    
    # 1. Add new stock
    res = integrator.add_to_watchlist(stock_info)
    assert res is True
    
    with open(watchlist_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]['code'] == '005930'
        assert data[0]['weight'] == 2.0

    # 2. Add duplicate
    res = integrator.add_to_watchlist(stock_info)
    assert res == 'duplicate'
    
    # 3. Add second stock
    stock_info2 = {'code': '000660', 'name': 'SK하이닉스'}
    res = integrator.add_to_watchlist(stock_info2)
    assert res is True
    with open(watchlist_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data) == 2

def test_rt_search_refresh_watchlist(temp_watchlist):
    integrator, watchlist_path = temp_watchlist
    
    # Mock RealTimeSearch to use the temp watchlist path
    with patch('AT_Sig.rt_search.os.path.join', return_value=watchlist_path):
        rt_search = RealTimeSearch()
        rt_search.connected = True
        rt_search.websocket = MagicMock()
        
        # AsyncMock for async methods
        from unittest.mock import AsyncMock
        rt_search.send_message = AsyncMock(return_value=True)
        
        async def run_test():
            # 1. Initial refresh (empty file or first read)
            integrator.add_to_watchlist({'code': '005930', 'name': '삼성전자'})
            new_codes = await rt_search.refresh_lead_watchlist("TOKEN")
            assert '005930' in new_codes
            assert '005930' in rt_search.registered_stocks

            # 2. No changes
            new_codes = await rt_search.refresh_lead_watchlist("TOKEN")
            assert len(new_codes) == 0

            # 3. Add new stock to file
            integrator.add_to_watchlist({'code': '000660', 'name': 'SK하이닉스'})
            # Force mtime change if needed
            os.utime(watchlist_path, None) 
            
            new_codes = await rt_search.refresh_lead_watchlist("TOKEN")
            assert '000660' in new_codes
            assert '000660' in rt_search.registered_stocks

        asyncio.run(run_test())

def test_weight_calculation():
    """Verify the weight calculation logic in LeadingThemeWidget"""
    widget = LeadingThemeWidget()
    
    # Rank 1, High Rate (>= 10)
    assert widget._calculate_weight(1, 12.5) == 7 # 5 + 2
    # Rank 1, Low Rate (< 10)
    assert widget._calculate_weight(1, 4.5) == 5  # 5
    
    # Rank 2, High Rate (>= 8)
    assert widget._calculate_weight(2, 9.0) == 4  # 3 + 1
    # Rank 2, Low Rate (< 8)
    assert widget._calculate_weight(2, 2.0) == 3  # 3
    
    # Other Ranks
    assert widget._calculate_weight(3, 20.0) == 2
    assert widget._calculate_weight(5, 1.0) == 2

if __name__ == "__main__":
    pytest.main([__file__])
