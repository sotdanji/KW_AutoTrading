# -*- coding: utf-8 -*-
import sys
import os
import json
import time

# [안실장 픽스] 스크립트 단독 실행 시 패키지 경로 인식 문제 해결
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
	sys.path.insert(0, project_root)

# 이제 절대 경로로 임포트 가능
try:
	from shared.api import fetch_data
except ImportError:
	# shared 내부에서 실행될 경우를 대비한 폴백
	from api import fetch_data

# Project root path
MASTER_FILE = os.path.join(project_root, "stock_master.json")

# [안실장 픽스] API 데이터 누락 시 보강을 위한 오버라이드 맵
MASTER_OVERRIDES = {}

def load_master_cache():
	"""Load stock_master.json cache."""
	data = {}
	if os.path.exists(MASTER_FILE):
		try:
			with open(MASTER_FILE, 'r', encoding='utf-8') as f:
				data = json.load(f)
			# [안실장 픽스] 로드 시점에 무의미한 점(...)이나 깨진 글자가 있다면 필터링
			clean_data = {}
			for code, name in data.items():
				if isinstance(name, str):
					if name.strip() in ["", ".", "..", "...", "....", "?", "Unknown", "…"] or "\ufffd" in name:
						continue
				clean_data[code] = name
			
			# 보호 종목 강제 오버라이드
			clean_data.update(MASTER_OVERRIDES)
			return clean_data
		except:
			pass
	
	# 강제 오버라이드 적용
	data.update(MASTER_OVERRIDES)
	return data

def save_master_cache(data):
	"""Save stock_master.json cache with validation."""
	if not data: return
	
	# 강제 오버라이드 보호
	data.update(MASTER_OVERRIDES)
	
	# [안실장 픽스] 깨진 글자(\ufffd 등) 또는 무의미한 점(...)이 캐시를 오염시키지 않도록 필터링
	clean_data = {}
	for code, name in data.items():
		if isinstance(name, str):
			if "\ufffd" in name or "\u05ba" in name:
				continue 
			if name.strip() in ["", ".", "..", "...", "....", "?", "Unknown", "…"]:
				continue
		clean_data[code] = name

	# 강제 오버라이드 최종 적용
	clean_data.update(MASTER_OVERRIDES)

	try:
		with open(MASTER_FILE, 'w', encoding='utf-8') as f:
			json.dump(clean_data, f, ensure_ascii=False, indent=2)
	except Exception as e:
		print(f"Error saving stock master: {e}")

def get_all_stocks(host_url, token, market='ALL'):
	"""
	Fetch all stocks from Kiwoom API (ka10099).
	market: 'KOSPI', 'KOSDAQ', 'ALL', 'MAP'
	"""
	cached_map = load_master_cache()
	if market == 'MAP' and cached_map:
		return cached_map

	is_map = (market == 'MAP')
	target_markets = ['0', '10'] if market in ['ALL', 'MAP'] else ([market] if market in ['0', '10'] else (['0'] if market == 'KOSPI' else ['10']))
	
	all_results = {} if is_map else []
	
	for m_code in target_markets:
		headers = {'api-id': 'ka10099', 'cont-yn': 'N', 'next-key': ''}
		params = {'mrkt_tp': m_code}
		
		while True:
			resp = fetch_data(host_url, '/api/dostk/stkinfo', 'ka10099', params, token, headers['cont-yn'], headers['next-key'])
			if not resp: break
			
			raw_content = resp.content
			data = None
			
			for enc in ['cp949', 'utf-8']:
				try:
					decoded = raw_content.decode(enc)
					if "005930" in decoded and "삼성전자" not in decoded:
						continue 
					
					import json
					temp_data = json.loads(decoded)
					stocks = temp_data.get('stk_info_list') or temp_data.get('output') or []
					if stocks:
						data = temp_data
						break
				except:
					continue
			
			if not data:
				try:
					import json
					data = json.loads(raw_content.decode('cp949', 'ignore'))
				except:
					break

			if not data: break
			stock_list = data.get('stk_info_list') or data.get('output') or data.get('list', [])
			
			for item in stock_list:
				code = item.get('code', '')
				hname = (item.get('name') or item.get('hname', '')).strip()
				
				if not hname or hname in [".", "..", "...", "?", "??", "???"] or "\ufffd" in hname:
					name = code
				else:
					name = hname
					
				if code:
					if is_map: all_results[code] = name
					else: all_results.append(code)
			
			cont_yn = resp.headers.get('cont-yn', 'N')
			next_key = resp.headers.get('next-key', '')
			if cont_yn != 'Y' or not next_key: break
			headers['cont-yn'] = cont_yn
			headers['next-key'] = next_key
			time.sleep(0.5)
			
	if is_map and all_results:
		for k, v in list(all_results.items()):
			if not v or v.strip() in ["", ".", "..", "...", "?"]:
				all_results[k] = k
		
		cached_map.update(all_results)
		save_master_cache(cached_map)
		
	return all_results

def get_stock_name(host_url, code, token):
	"""Get stock name by code, update cache if new."""
	cached_map = load_master_cache()
	if code in cached_map:
		name = cached_map[code]
		if name and name not in ["", ".", "..", "...", "?"]:
			return name
		
	from shared.api import fetch_stock_info
	info = fetch_stock_info(host_url, code, token)
	if info:
		out = info.get('output', {})
		name = (out.get('hname') or out.get('name', '')).strip()
		if not name or name in ["", ".", "..", "...", "?"]:
			name = code
			
		cached_map[code] = name
		save_master_cache(cached_map)
		return name
	return code

if __name__ == "__main__":
	try:
		conf = None
		try:
			from shared.config import get_api_config
			conf = get_api_config()
		except ImportError:
			print("❌ 오류: 설정 파일을 찾을 수 없습니다.")

		if conf:
			from shared.api import get_token
			token = get_token(conf['host_url'], conf['app_key'], conf['app_secret'])
			
			if token:
				 print("🔄 전 종목 마스터 업데이트 중...")
				 get_all_stocks(conf['host_url'], token, market='MAP')
				 print("✅ 업데이트 완료!")
			else:
				 print("❌ 오류: 토큰 발급 실패. API 키를 확인하세요.")
		else:
			 print("❌ 오류: 설정을 불러오지 못했습니다.")
	except Exception as e:
		print(f"❌ 실행 중 오류 발생: {e}")
