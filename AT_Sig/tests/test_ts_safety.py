import unittest
from unittest.mock import patch, MagicMock
from AT_Sig.check_n_sell import chk_n_sell

class TestTrailingStop(unittest.TestCase):
    def setUp(self):
        self.token = "test_token"
        self.ui_callback = MagicMock()
        
    @patch('AT_Sig.check_n_sell.get_my_stocks')
    @patch('AT_Sig.check_n_sell.cached_setting')
    @patch('AT_Sig.check_n_sell.get_stock_state')
    @patch('AT_Sig.check_n_sell.update_stock_state')
    @patch('AT_Sig.check_n_sell.sell_stock')
    @patch('AT_Sig.check_n_sell.tel_send')
    def test_ts_safety_buffer_trigger(self, mock_tel, mock_sell, mock_update, mock_get_state, mock_setting, mock_get_stocks):
        """TS 활성화 후 하락폭 도달 시 Safety Buffer 미만이면 즉시 청산되는지 테스트"""
        # 1. 설정 구성
        mock_setting.side_effect = lambda key, default: {
            'take_profit_steps': [],
            'stop_loss_steps': [],
            'ts_enabled': True,
            'ts_activation': 5.0,
            'ts_drop': 2.0,
            'ts_limit_count': 1,
            'ts_safety_buffer': 4.0
        }.get(key, default)
        
        # 2. 보유 종목 (수익률 4.5% 상황, 고점 10000원 -> 현재 9800원 = 2% 하락)
        # 하지만 safety buffer가 5.0(활성) -> 4.0(버퍼)인데 4.5%면 버퍼 위이므로 1회 확인만 해야함
        # 만약 현재 수익률이 3.5%라면 버퍼 미만이므로 즉시 청산
        
        mock_get_stocks.return_value = {
            'stk_acnt_evlt_prst': [{
                'stk_cd': '005930',
                'stk_nm': '삼성전자',
                'rmnd_qty': '10',
                'cur_prc': '9350', # 매수가 9000원 가정
                'pchs_amt': '90000',
                'evlu_pfls_amt': '3500', # 수익금 3500원 (약 3.8%)
                'pl_rt': '3.8' 
            }]
        }
        
        mock_get_state.return_value = {
            'max_price': 10000.0, # 고점 대비 현재(9350)는 6.5% 하락
            'ts_count': 0
        }
        
        # 실행
        chk_n_sell(token=self.token, ui_callback=self.ui_callback)
        
        # 검증: pl_rt(3.8) < safety_buffer(4.0) 이므로 즉시 매도 호출되어야 함
        mock_sell.assert_called_once()
        args, kwargs = mock_sell.call_args
        self.assertEqual(args[0], '005930')

if __name__ == '__main__':
    unittest.main()
