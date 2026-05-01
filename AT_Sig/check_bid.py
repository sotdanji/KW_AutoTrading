from shared.api import fetch_data

# 주식호가요청
def fn_ka10004(stk_cd, cont_yn='N', next_key='', token=None):
	"""
	주식호가요청 (ka10004)
	shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
	"""
	host_url = "https://api.kiwoom.com"
	endpoint = '/api/dostk/mrkcond'
	api_id = 'ka10004'

	params = {
		'stk_cd': stk_cd, 
	}

	# shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
	resp = fetch_data(host_url, endpoint, api_id, params, token, cont_yn, next_key)
	
	sel_fpr_bid = 0
	if resp and resp.status_code == 200:
		try:
			data = resp.json()
			sel_fpr_bid_raw = data.get('sel_fpr_bid', '0')
			sel_fpr_bid = abs(float(str(sel_fpr_bid_raw).replace(',', '')))
		except (ValueError, TypeError, Exception):
			sel_fpr_bid = 0

	return sel_fpr_bid

# 실행 구간
if __name__ == '__main__':
	fn_ka10004('005930', token=get_token())