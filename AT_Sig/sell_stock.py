import logging
from shared.api import fetch_data, generate_idempotency_key, REAL_HOST

# 주식 매도주문
def fn_kt10001(stk_cd, ord_qty, cont_yn='N', next_key='', token=None, trde_tp='3'):
	"""
	주식 매도주문 (kt10001)
	shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
	"""
	host_url = REAL_HOST
	endpoint = '/api/dostk/ordr'
	api_id = 'kt10001'

	params = {
		'dmst_stex_tp': 'KRX', # 국내거래소구분 KRX,NXT,SOR
		'stk_cd': stk_cd, # 종목코드 
		'ord_qty': str(int(float(str(ord_qty)))), # 주문수량 
		'ord_uv': '', # 주문단가 (시장가는 0/Empty)
		'trde_tp': trde_tp, 
		'cond_uv': '', # 조건단가 
	}

	# shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
	# 멱등성 키 생성
	idempotency_key = generate_idempotency_key()

	resp = fetch_data(host_url, endpoint, api_id, params, token, cont_yn, next_key, idempotency_key=idempotency_key)
	
	if resp and resp.status_code == 200:
		try:
			return resp.json()
		except Exception as e:
			logging.getLogger("AT_Sig.sell_stock").error(f"Error parsing sell response: {e}")
			
	return {'return_code': '999', 'return_msg': '네트워크 오류 또는 응답 없음'}

# 실행 구간
if __name__ == '__main__':
	fn_kt10001(stk_cd='005930', ord_qty='1', token=get_token())