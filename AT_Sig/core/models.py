from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class StockItem:
	"""시스템 내부에서 사용하는 표준 주식 정보 데이터 모델"""
	code: str
	name: str = "Unknown"
	price: int = 0
	change_rate: float = 0.0
	volume: int = 0
	source: str = "Condition"  # Condition, Theme, RealTime 등
	raw_data: Dict = field(default_factory=dict)
	
	@classmethod
	def from_api_dict(cls, data: dict, source: str = "Condition") -> Optional['StockItem']:
		"""Kiwoom API의 다양한 dict 형식을 StockItem으로 정규화"""
		if not data: return None
		if not isinstance(data, dict): return None
		
		# 1. 코드 추출
		code = (data.get('jmcode') or data.get('stk_cd') or data.get('code') or 
				data.get('item') or data.get('iscd') or data.get('thema_code') or data.get('thema_cd') or '')
		code = str(code).replace('A', '').strip()
		
		if not code: return None
		
		# 2. 이름 추출
		name = (data.get('stk_nm') or data.get('name') or data.get('hname') or 
				data.get('knam') or data.get('thema_nm') or data.get('stk_name') or "Unknown")
		
		# [Fix] 키움 API에서 '조건검색' 등의 불필요한 이름이 전송되는 경우 Unknown 처리
		if name in ['조건검색', '종목명', 'None', 'NULL', '주식체결', '주식기세', '관심종목', '실시간시세']:
			name = "Unknown"
		
		price, change_rate, volume = 0, 0.0, 0

		# 3. 실시간 데이터(values) 필드 (WebSocket)
		vals = data.get('values')
		if vals:
			try:
				# FID 10(현재가), 12(등락율), 13(누적거래량)
				p_str = str(vals.get('10', '0')).replace(',', '').strip()
				price = abs(int(float(p_str))) if p_str else 0
				
				r_str = str(vals.get('12', '0.00')).replace(',', '').strip()
				change_rate = float(r_str) if r_str else 0.0
				
				v_str = str(vals.get('13', '0')).replace(',', '').strip()
				volume = int(float(v_str)) if v_str else 0
			except: pass
		else:
			# 4. REST API 필드 대응 (ka10001 등)
			try:
				def clean_num(val):
					if not val: return '0'
					# +, -, , 제거하여 순수 숫자만 남김
					return str(val).replace('+', '').replace('-', '').replace(',', '').strip()

				# 가격 추출 (대표님 샘플: repl_pric, high_pric, cur_prc 등 다양한 필드 대응)
				p_raw = (data.get('stk_prc') or data.get('repl_pric') or data.get('high_pric') or
						 data.get('now_prc') or data.get('cur_prc') or data.get('curr_prc') or 
						 data.get('now') or data.get('price') or data.get('last_price') or
						 data.get('pric') or data.get('curr') or data.get('last') or '0')
				price = abs(int(float(clean_num(p_raw))))
				
				# 등락률 추출 (대표님 샘플: flu_rt)
				r_raw = (data.get('flu_rt') or data.get('prc_cls') or data.get('rate') or 
						 data.get('change_rate') or data.get('fluct_rt') or data.get('rt') or 
						 data.get('ratio') or data.get('fluct') or data.get('yield') or '0.00')
				change_rate = float(str(r_raw).replace('+', '').replace(',', '').replace('%', '').strip())
				
				# 거래량 추출 (대표님 샘플: trde_qty)
				v_raw = (data.get('trde_qty') or data.get('vol') or data.get('volume') or data.get('acml_vol') or '0')
				volume = int(float(clean_num(v_raw)))
			except: pass

		return cls(code=code, name=name, price=price, change_rate=change_rate, volume=volume, source=source, raw_data=data)

	@classmethod
	def from_api_list(cls, data: list, source: str = "Condition") -> Optional['StockItem']:
		"""['005930', '삼성전자'] 형태의 리스트 형식을 정규화"""
		if not data or not isinstance(data, (list, tuple)): return None
		
		code = str(data[0]).replace('A', '').strip()
		name = str(data[1]) if len(data) >= 2 else "Unknown"
		
		if not code: return None
		return cls(code=code, name=name, source=source)
