import sys
import os

# Add parent directory to sys.path to import existing modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from buy_stock import fn_kt10000 as buy_api
from sell_stock import fn_kt10001 as sell_api
from check_bal import fn_kt00001 as balance_api
from check_bid import fn_ka10004 as price_api
from acc_val import fn_kt00004 as holdings_api
from stock_info import fn_ka10001 as info_api
from core.rate_limiter import RateLimiter
from get_setting import get_setting
try:
    from core.market_index import get_market_index as index_api
except ImportError:
    index_api = None

# Import Order Management (Lazy or direct)
# Note: Should create core/order_api.py? Or just direct import
# As files are in AT_Sig root (sibling), sys path added..
from get_outstanding import fn_kt00002 as outstanding_api
from cancel_order import fn_kt00003 as cancel_api # Fallback
from core.check_orderbook import get_orderbook as orderbook_api
from realized_pl import fn_ka10074 as realized_api

class BrokerAdapter:
    """
    BrokerAdapter
    
    A unified interface for Kiwoom API calls.
    Decouples business logic from specific API implementation details.
    """
    def __init__(self, token=None):
        self.token = token
        # Kiwoom API Limit: Conservative 3 req/sec to be safe
        self.rate_limiter = RateLimiter(rate_limit=3.0, time_window=1.0)
        self.use_demo = get_setting('use_demo', False)
        self.name_cache = {}
        self.market_cache = {}
        
        # [안실장 픽스] stock_master.json에서 정보를 미리 가져와 "Unknown" 방지
        from shared.stock_master import load_master_cache
        self.name_cache = load_master_cache()

    def set_token(self, token):
        """액세스 토큰 설정"""
        self.token = token

    def validate_session(self):
        """
        액세스 토큰 및 계좌 유효성 검증
        :return: (True, "") 또는 (False, "에러사유")
        """
        if not self.token:
            return False, "토큰이 설정되지 않았습니다."
        try:
            self.rate_limiter.wait_for_token()
            # 잔고 조회를 통해 세션 유효성 직접 확인
            balance = balance_api(token=self.token)
            if balance is not None:
                return True, f"계좌 연결 성공 (예수금: {int(balance):,}원)"
            return False, "계좌 메타데이터 조회 실패 (네트워크 또는 권한 문제)"
        except Exception as e:
            return False, f"세션 검증 중 예외 발생: {str(e)}"

    def buy(self, code, qty, price, type='03'):
        """
        매수 주문 실행
        :return: (return_code, return_msg)
        """
        if not self.token:
            raise ValueError("Token is not set")
        self.rate_limiter.wait_for_token()
        
        try:
            res = buy_api(stk_cd=code, ord_qty=str(qty), ord_uv=str(price), token=self.token, trde_tp=type)
            if isinstance(res, dict):
                 return res.get('return_code', '999'), res.get('return_msg', '응답 데이터 형식 오류')
            return '999', str(res)
        except Exception as e:
            return '999', f"API 호출 예외: {str(e)}"

    def sell(self, code, qty, price=0, type='3'):
        """
        매도 주문 실행
        :return: (return_code, return_msg)
        """
        if not self.token:
            raise ValueError("Token is not set")
        
        self.rate_limiter.wait_for_token()
        try:
            res = sell_api(stk_cd=code, ord_qty=str(qty), token=self.token) 
            if isinstance(res, dict):
                 return res.get('return_code', '999'), res.get('return_msg', '응답 데이터 형식 오류')
            return '999', str(res)
        except Exception as e:
            return '999', f"API 호출 예외: {str(e)}"

    def get_balance(self):
        """
        예수금 조회
        """
        if not self.token:
            return 0
        try:
            self.rate_limiter.wait_for_token()
            val = balance_api(token=self.token)
            return int(val) if val is not None else 0
        except:
            return 0

    def get_holdings(self, include_details=False):
        """
        보유 종목 현황 상세 조회
        :return: List of holding dicts
        """
        if not self.token:
            return []
        try:
            self.rate_limiter.wait_for_token()
            response = holdings_api(print_df=False, token=self.token)
            
            if isinstance(response, dict):
                if 'stk_acnt_evlt_prst' in response:
                    return response.get('stk_acnt_evlt_prst', [])
                elif response.get('return_code') != '0':
                    return None # API Error
            return None # Invalid response
        except Exception as e:
            print(f"Error in get_holdings: {e}")
            return None

    def get_account_data(self):
        """
        Get Full Account Data (Totals + Holdings)
        :return: Dict containing 'stk_acnt_evlt_prst' (list) and 'stk_acnt_evlt_tot' (totals)
        """
        if not self.token:
            raise ValueError("Token is not set")
        self.rate_limiter.wait_for_token()
        return holdings_api(print_df=False, token=self.token)



    def get_stock_name(self, code):
        """
        Get Stock Name
        :param code: Stock code
        :return: Stock Name (str)
        """
        # [Cache Check]
        if code in self.name_cache:
            return self.name_cache[code]

        if not self.token:
            raise ValueError("Token is not set")
        
        self.rate_limiter.wait_for_token()
        res = info_api(stk_cd=code, token=self.token)
        
        # [Fix] Parse name from dictionary response (Kiwoom REST API wraps in 'output')
        name = "Unknown"
        if isinstance(res, dict):
             data = res.get('output', res)
             name = data.get('stk_nm') or data.get('name') or data.get('hname') or "Unknown"
        
        # [Cache Update]
        if name and name != "Unknown":
             self.name_cache[code] = name
             
        return name

    def get_market_type(self, code):
        """
        종목의 시장 구분(KOSPI/KOSDAQ) 조회
        :return: "KOSPI" or "KOSDAQ" or "UNKNOWN"
        """
        if code in self.market_cache:
            return self.market_cache[code]
            
        if not self.token: return "UNKNOWN"
        
        try:
            self.rate_limiter.wait_for_token()
            res = info_api(stk_cd=code, token=self.token)
            if isinstance(res, dict):
                data = res.get('output', res)
                if isinstance(data, list) and len(data) > 0: data = data[0]
                
                # 키움 ka10001: mket_ds_cd 또는 stck_mket_div_cd 등 (API 버전에 따라 다름)
                mkt_cd = data.get('mket_ds_cd') or data.get('stck_mket_div_cd') or data.get('mrkt_tp')
                
                # 보통 '1'이 KOSPI, '2'가 KOSDAQ인 경우가 많으나 문자열 포함 여부로도 체크
                mkt_nm = str(data.get('mket_nm', '')).upper()
                
                if 'KOSPI' in mkt_nm or mkt_cd == '1':
                    self.market_cache[code] = "KOSPI"
                elif 'KOSDAQ' in mkt_nm or mkt_cd == '2':
                    self.market_cache[code] = "KOSDAQ"
                else:
                    self.market_cache[code] = "UNKNOWN"
                
                return self.market_cache[code]
        except:
            pass
        return "UNKNOWN"

    def get_market_index(self, market="KOSDAQ"):
        """
        Get Market Index (KOSPI/KOSDAQ)
        :param market: Market Name
        :return: {'price': float, 'rate': float}
        """
        if not self.token:
            raise ValueError("Token is not set")
        # Rate limit separate? Or shared? Shared is safer.
        self.rate_limiter.wait_for_token()
        # Note: index_api function call needs check
        # core/market_index.py defines: get_market_index(token, market="KOSPI")
        return index_api(self.token, market) if index_api else None
        
    def get_outstanding_orders(self, stk_cd):
        """
        Get Outstanding (Unfilled) Orders
        :return: List of orders
        """
        if not self.token:
            raise ValueError("Token is not set")
        self.rate_limiter.wait_for_token()
        return outstanding_api(stk_cd=stk_cd, token=self.token)

    def cancel_order(self, order_no, qty, stk_cd, type='4'): # 4: Buy Cancel
        """
        Cancel Order
        :param order_no: Original Order No
        :param qty: Cancel Quantity
        :param type: '3'(Sell Cancel) or '4'(Buy Cancel)
        """
        if not self.token:
             raise ValueError("Token is not set")
        self.rate_limiter.wait_for_token()
        return cancel_api(order_no, qty, stk_cd, token=self.token, buy_sell_tp=type)

    def get_orderbook(self, stk_cd):
        """
        Get Orderbook Summary (Total Ask/Bid Remain)
        :param stk_cd: Stock Code
        :return: {'total_ask': int, 'total_bid': int} or None
        """
        if not self.token:
            return None
        self.rate_limiter.wait_for_token()
        data = orderbook_api(stk_cd, token=self.token)
        if data:
            return {
                'total_ask': data.get('total_ask', 0),
                'total_bid': data.get('total_bid', 0)
            }
        return None

    def get_current_price(self, stk_cd):
        """
        Get Current Price (Best Ask Price)
        """
        if not self.token:
            return 0
        try:
            self.rate_limiter.wait_for_token()
            return price_api(stk_cd=stk_cd, token=self.token)
        except:
            return 0

    def get_realized_pl(self):
        """
        [ka10074] 당일 실현 손익 조회
        :return: (total_realized_pl, detail_list)
        """
        if not self.token:
            return 0, []
        try:
            self.rate_limiter.wait_for_token()
            res = realized_api(token=self.token)
            if res and res.get('return_code') == 0:
                # ka10074 필드: rlzt_pl (당일 실현 손익)
                # dt_rlzt_pl (세부 리스트)
                total = int(float(str(res.get('rlzt_pl', 0)).replace(',', '')))
                dtl = res.get('dt_rlzt_pl', [])
                return total, dtl
            return 0, []
        except:
             return 0, []

