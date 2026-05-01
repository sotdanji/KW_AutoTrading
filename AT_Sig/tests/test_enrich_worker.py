import asyncio
import unittest
from unittest.mock import MagicMock, patch
from AT_Sig.trading_engine import TradingEngine

class TestEnrichmentWorker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = TradingEngine()
        self.engine.token = "test_token"
        self.engine.api_session = MagicMock()
        self.engine._ensure_async_objects()
        
    @patch('AT_Sig.trading_engine.get_stock_info_async')
    async def test_enrichment_retry_logic(self, mock_get_info):
        """에러 발생 시 Enrichment Worker가 지정된 횟수만큼 재시도하는지 테스트"""
        # 1. 첫 호출 시 에러 발생 시뮬레이션
        mock_get_info.side_effect = Exception("API Connection Timeout")
        
        # 2. 큐에 종목 추가
        await self.engine.enrich_queue.put((10, "005930", 0))
        
        # 3. 워커가 한 번 실행되도록 유도 (태스크 캔슬 전까지 실행)
        # 실제 워커는 무한 루프이므로, 재시도 로직이 큐에 다시 넣는 것을 확인
        # 여기서는 워커 내부 로직을 부분적으로 검증하기 위해 짧게 대기
        
        # 워커 태스크는 __init__ 시점에 이미 생성되어 있을 수 있으므로 정리 후 재생성
        if self.engine.enrich_worker_task:
            self.engine.enrich_worker_task.cancel()
            
        self.engine.enrich_worker_task = asyncio.create_task(self.engine._enrichment_worker())
        
        await asyncio.sleep(0.5) # 워커가 처리할 시간 부여
        
        # 큐를 확인하여 재시도 카운트가 증가된 채로 다시 들어갔는지 확인
        retry_item = await self.engine.enrich_queue.get()
        self.assertEqual(retry_item[1], "005930")
        self.assertGreater(retry_item[2], 0)
        
        self.engine.enrich_worker_task.cancel()

if __name__ == '__main__':
    unittest.main()
