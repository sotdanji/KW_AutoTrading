import pandas as pd
from shared.api import fetch_data

# 계좌평가현황요청
def fn_kt00004(print_df=False, cont_yn='N', next_key='', token=None):
	"""
	계좌평가현황요청 (kt00004)
	shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
	"""
	host_url = "https://api.kiwoom.com"
	endpoint = '/api/dostk/acnt'
	api_id = 'kt00004'

	params = {
		'qry_tp': '0', # 상장폐지조회구분 0:전체, 1:상장폐지종목제외
		'dmst_stex_tp': 'KRX', # 국내거래소구분 KRX:한국거래소,NXT:넥스트트레이드
	}

	# shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
	resp = fetch_data(host_url, endpoint, api_id, params, token, cont_yn, next_key)
	
	if resp and resp.status_code == 200:
		try:
			res_json = resp.json()
			# KIS API 특성상 성공(0)이어도 데이터가 비어있을 수 있음.
			if 'stk_acnt_evlt_prst' in res_json:
				stk_acnt_evlt_prst = res_json['stk_acnt_evlt_prst']
				
				if print_df and stk_acnt_evlt_prst:
					df = pd.DataFrame(stk_acnt_evlt_prst)[['stk_cd', 'stk_nm', 'pl_rt', 'rmnd_qty', 'ord_psbl_qty']]
					pd.set_option('display.unicode.east_asian_width', True)
					print(df.to_string(index=False))

				return res_json
		except Exception as e:
			import logging
			logging.getLogger("AT_Sig.acc_val").error(f"Error parsing holdings: {e}")
	
	# 실패 시 빈 리스트 구조 반환
	return {'stk_acnt_evlt_prst': []}

# 실행 구간
if __name__ == '__main__':
	fn_kt00004(True, token=get_token())