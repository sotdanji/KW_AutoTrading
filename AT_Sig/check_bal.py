from shared.api import fetch_data

# 예수금상세현황요청
def fn_kt00001(cont_yn='N', next_key='', token=None):
	"""
	예수금상세현황요청 (kt00001)
	shared.api.fetch_data를 활용하여 연결 안정성을 확보합니다.
	"""
	host_url = "https://api.kiwoom.com" # Default REAL, fallback logic in fetch_data/mode if needed
	endpoint = '/api/dostk/acnt'
	api_id = 'kt00001'
	
	params = {
		'qry_tp': '3', # 조회구분 3:추정조회, 2:일반조회
	}

	# shared.api.fetch_data는 내부적으로 Session 재사용 및 10054 대응 Retry 로직을 포함함
	resp = fetch_data(host_url, endpoint, api_id, params, token, cont_yn, next_key)
	
	entry = 0
	if resp and resp.status_code == 200:
		try:
			res_json = resp.json()
			ret_code = str(res_json.get('return_code', '999')).strip()
			
			# [안실장 픽스] 실전/모의 계좌 응답 필드 통합 처리
			output = res_json.get('output', {})
			if isinstance(output, list) and len(output) > 0: 
				output = output[0]
			elif not isinstance(output, dict):
				output = {}
			
			def parse_v(v):
				if v is None or v == '': return 0
				try:
					return int(float(str(v).replace(',', '').strip()))
				except:
					return 0

			# 필드 우선순위 (실전 계좌 대응 강화)
			val1 = parse_v(output.get('n_pchs_possible_amt'))
			val2 = parse_v(res_json.get('100stk_ord_alow_amt'))
			val3 = parse_v(output.get('ord_alow_amt')) or parse_v(res_json.get('ord_alow_amt'))
			val4 = parse_v(output.get('dnca_tot_amt')) or parse_v(res_json.get('entr'))
			
			entry = val1 or val2 or val3 or val4
			
			if ret_code in ['0', '00', '000']:
				return entry
		except Exception as e:
			import logging
			logging.getLogger("AT_Sig.check_bal").error(f"Error parsing balance: {e}")
			
	return entry


# 실행 구간
if __name__ == '__main__':
	fn_kt00001(token=get_token())