from state_manager import get_stock_state, update_stock_state, sync_state_with_balance
import time
import sys
from get_setting import cached_setting
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from datetime import datetime
from get_outstanding import fn_kt00002 as get_outstanding_orders
from history_manager import record_trade

# 당일 주문 불가 종목 캐시 (예: 거래정지 등)
untradable_stocks = set()
# 중복 주문 방지를 위한 실행 중 플래그 캐시 (5초 쿨타임)
processing_stocks = {}

def chk_n_sell(token=None, manual_mode=False, ui_callback=None, regime=None, acc_mgr=None, price_cache=None):
	"""
	보유 종목의 수익률을 체크하여 익절 또는 손절 실행 (Ms. Ahn Optimized)
	"""
	# 1. 설정 로드
	tp_steps = cached_setting('take_profit_steps', [])
	sl_steps = cached_setting('stop_loss_steps', [])
	
	# 기본값 설정
	if not tp_steps:
		old_tp_rate = cached_setting('take_profit_rate', 5.0)
		tp_steps = [{"rate": old_tp_rate, "ratio": 100.0, "enabled": True}]
	if not sl_steps:
		old_sl_rate = cached_setting('stop_loss_rate', -10.0)
		sl_steps = [{"rate": old_sl_rate, "ratio": 100.0, "enabled": True}]

	try:
		# 2. 잔고 조회
		raw_data = get_my_stocks(token=token)
		my_stocks = []
		is_valid_resp = False
		
		if isinstance(raw_data, dict):
			if 'stk_acnt_evlt_prst' in raw_data: # 정상적인 잔고 필드
				my_stocks = raw_data.get('stk_acnt_evlt_prst', [])
				is_valid_resp = True
		elif isinstance(raw_data, list):
			my_stocks = raw_data
			is_valid_resp = True
			
		if not is_valid_resp:
			return {'status': 'error', 'msg': '전고 데이터 형식 오류'}

		if not my_stocks:
			sync_state_with_balance([]) 
			return {'status': 'done', 'sold': False, 'count': 0}
			
		# Helper functions
		def get_any(item, keys, default='0'):
			for k in keys:
				if k in item and item[k] is not None:
					return str(item[k])
			return default

		def clean_val(v, default='0'):
			if not v: return default
			return str(v).replace(',', '').strip()

		def log_msg(msg):
			try:
				print(msg)
			except UnicodeEncodeError:
				try:
					# 인코딩 오류 시 이모지 제거 후 출력 시도
					print(msg.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
				except:
					pass
			if ui_callback:
				try: ui_callback("log", msg)
				except: pass

		# 상태 동기화
		current_codes = []
		for s in my_stocks:
			try:
				qty = int(float(clean_val(get_any(s, ['rmnd_qty', 'qty', 'hold_qty'], '0'))))
				if qty > 0:
					current_codes.append(s.get('stk_cd', '').replace('A', ''))
			except: continue
		sync_state_with_balance(current_codes)
			
		# [Optimization] Fetch ALL outstanding orders ONCE before loop (Avoid 429)
		all_outstandings = []
		try:
			all_outstandings = get_outstanding_orders(stk_cd='', token=token)
			if not all_outstandings: all_outstandings = []
		except Exception as e:
			log_msg(f"⚠️ [전체미체결조회 실패] {e}")
			
		# 3. 종목별 체크 루프
		sell_count = 0
		for stock in my_stocks:
			try:
				stock_code = stock.get('stk_cd', '').replace('A', '')
				stock_name = stock.get('stk_nm', stock_code)
				
				if not stock_code: continue
				if stock_code in untradable_stocks: continue

				# 수량 파악 (안실장 픽스: 주문 가능 수량 ord_psbl_qty 추가 확인)
				rmnd_qty = int(float(clean_val(get_any(stock, ['rmnd_qty', 'qty', 'hold_qty'], '0'))))
				# [안실장 픽스] ord_psbl_qty가 없거나 0일 경우 rmnd_qty를 기반으로 함 (단, 미체결이 없을 때만)
				ord_psbl_qty = int(float(clean_val(get_any(stock, ['ord_psbl_qty', 'can_sell_qty'], '0'))))
				
				if ord_psbl_qty <= 0 and rmnd_qty > 0:
					# 미체결을 한번 더 확인하여 진짜 주문 가능한지 판단
					# [Optimized] Use pre-fetched all_outstandings
					stock_outstandings = [o for o in all_outstandings if str(o.get('stk_cd', '')).replace('A', '') == stock_code]
					if not stock_outstandings:
						ord_psbl_qty = rmnd_qty
				
				# 보유 수량이 0이거나 주문 가능 수량이 0이면 유령 데이터이므로 스킵
				if rmnd_qty <= 0 or ord_psbl_qty <= 0: 
					continue

				# [안실장 픽스] 실시간 시세 캐시 연동 (REST API의 지연 가격 보정)
				cur_prc = 0
				if price_cache and stock_code in price_cache:
					cur_prc = float(price_cache[stock_code].get('price', 0))
					# log_msg(f"⚡ [RealTime] {stock_name}: 실시간 가격 {cur_prc:,}원 적용")
				
				if cur_prc <= 0:
					cur_prc = abs(float(clean_val(get_any(stock, ['cur_prc', 'now_prc', 'price'], '0'))))

				if cur_prc <= 0: continue # 가격 데이터가 없으면 비정상 데이터

				# [안실장 픽스] 수익률 재계산 (실시간 가격 기준)
				buy_avg = abs(float(clean_val(get_any(stock, ['pchs_avg_pric', 'buy_avg_pric', 'avg_prc'], '0'))))
				if buy_avg > 0:
					pl_rt = ((cur_prc - buy_avg) / buy_avg) * 100
				else:
					# 평단가가 없으면 기존 수익률 필드 활용
					pl_rt_str = clean_val(get_any(stock, ['evlu_pfls_rt', 'pl_rt', 'sunik_rt', 'rate', 'earning_rate'], '0.0'))
					pl_rt = float(pl_rt_str)

				# 상태 로드
				stock_state = get_stock_state(stock_code)
				current_sl_step = stock_state.get('sl_step', 0)
				current_tp_step = stock_state.get('tp_step', 0)
				max_prc = stock_state.get('max_price', 0.0)
				ts_count = stock_state.get('ts_count', 0)
				
				# 고점 갱신
				if cur_prc > max_prc:
					max_prc = cur_prc
					ts_count = 0 
					update_stock_state(stock_code, max_price=max_prc, ts_count=ts_count)

				# ATR 기반 가변 출구 전략 (Harness Meta)
				t_stop = stock_state.get('target_stop', 0.0)
				t_exit = stock_state.get('target_exit', 0.0)

				# 스마트 출구 전략 (안실장 Insight)
				from shared.market_status import MarketRegime
				smart_exit = False
				now = datetime.now()
				start_time = now.replace(hour=9, minute=0, second=10, microsecond=0)
				end_time = now.replace(hour=15, minute=20, second=0, microsecond=0)
				exit_reason = ""

				# A. 시장 폭락
				if regime and regime.get('regime') == MarketRegime.CRASH and start_time <= now <= end_time:
					smart_exit = True
					exit_reason = "🚨 [시장폭락] 패닉셀 탈출"

				# B. 본전 수호 (Trailing Breakeven)
				be_enabled = cached_setting('be_enabled', True)
				if not smart_exit and be_enabled and current_tp_step >= 1 and pl_rt <= 0.25:
					smart_exit = True
					exit_reason = "🛡️ [본전수호] 익절 후 하방 탈출"

				# C. 수익 보존 (Trailing Stop)
				ts_enabled = cached_setting('ts_enabled', False)
				if not smart_exit and ts_enabled and pl_rt >= cached_setting('ts_activation', 10.0):
					drop_from_peak = ((max_prc - cur_prc) / max_prc) * 100
					if drop_from_peak >= cached_setting('ts_drop', 3.0):
						ts_count += 1
						update_stock_state(stock_code, ts_count=ts_count)
						if ts_count >= cached_setting('ts_limit_count', 2):
							smart_exit = True
							exit_reason = f"📉 [수익보존] 고점대비 {drop_from_peak:.1f}% 하락"

				# 중복 주문 방지 (안실장 픽스 - 탭 Indentation)
				now_ts = time.time()
				if processing_stocks.get(stock_code, 0) > now_ts - 5.0:
					continue
				
				# 미체결 감지 보강 (중복 매도 방지)
				# [Optimized] Use pre-fetched all_outstandings
				stock_outstandings = [o for o in all_outstandings if str(o.get('stk_cd', '')).replace('A', '') == stock_code]
				if stock_outstandings:
					has_sell_order = any(str(o.get('sll_buy_tp', '')).strip() in ['1', '01', '매도'] for o in stock_outstandings)
					if has_sell_order:
						continue

				# 최종 판정
				should_sell = False
				sell_qty = 0
				msg_tag = ""

				if smart_exit:
					should_sell = True
					sell_qty = rmnd_qty
					msg_tag = exit_reason
				elif t_stop > 0 and cur_prc <= t_stop:
					should_sell = True
					sell_qty = rmnd_qty
					msg_tag = "🚨 [Harness] ATR 가변 손절"
				elif t_exit > 0 and cur_prc >= t_exit:
					should_sell = True
					sell_qty = rmnd_qty
					msg_tag = "🎯 [Harness] ATR 가변 익절"
				else:
					# 일반 손절 체크
					temp_sl = sl_steps
					if regime and regime.get('regime') == MarketRegime.BEAR:
						temp_sl = [{"rate": s['rate']+1.5, "ratio": s['ratio'], "enabled": s['enabled']} for s in sl_steps]
					
					if current_sl_step < len(temp_sl):
						step = temp_sl[current_sl_step]
						if step.get('enabled') and pl_rt <= step.get('rate'):
							should_sell = True
							sell_qty = int(rmnd_qty * (step['ratio']/100))
							msg_tag = f"{current_sl_step+1}차 손절"
					
					# 일반 익절 체크
					if not should_sell and current_tp_step < len(tp_steps):
						step = tp_steps[current_tp_step]
						if step.get('enabled') and pl_rt >= step.get('rate'):
							should_sell = True
							sell_qty = int(rmnd_qty * (step['ratio']/100))
							msg_tag = f"{current_tp_step+1}차 익절"

				if should_sell:
					# 최종 매도 수량 결정 (안실장 픽스: ord_psbl_qty와 비교하여 안전하게 산출)
					if sell_qty <= 0: sell_qty = ord_psbl_qty
					if sell_qty > ord_psbl_qty: sell_qty = ord_psbl_qty
					
					log_msg(f"📣 [매도감지] {stock_name}({stock_code}) {msg_tag} (수익률: {pl_rt:.2f}%)")
					
					if manual_mode:
						return {'status': 'manual_confirm', 'type': 'sell', 'code': stock_code, 'name': stock_name, 'qty': sell_qty}

					processing_stocks[stock_code] = time.time()
					
					# [안실장 근본 해결책] 매도 직전 실시간 잔고(kt00004) 교차 확인
					try:
						raw_rt = get_my_stocks(token=token)
						rt_stocks = raw_rt.get('stk_acnt_evlt_prst', []) if isinstance(raw_rt, dict) else raw_rt
						rt_bal = next((s for s in rt_stocks if s.get('stk_cd', '').replace('A', '') == stock_code), {})
						rt_qty = int(float(clean_val(get_any(rt_bal, ['ord_psbl_qty', 'can_sell_qty', 'rmnd_qty', 'qty'], '0'))))
					except Exception as e:
						log_msg(f"⚠️ [잔고재확인 실패] {e}")
						rt_qty = 0
					
					if rt_qty <= 0:
						log_msg(f"⚠️ [유령잔고감지] {stock_name}({stock_code}) 실제 주문 가능 수량이 0입니다. 스킵.")
						untradable_stocks.add(stock_code) # 오늘 하루 해당 종목은 더이상 조회하지 않음
						continue
					
					if sell_qty > rt_qty: sell_qty = rt_qty # 실제 수량에 맞게 보정
					
					res = sell_stock(stock_code, sell_qty, token=token, trde_tp='3')
					
					if str(res.get('return_code', '1')).strip() in ['0', '00']:
						log_msg(f"✅ {stock_name} 매도 주문 성공")
						sell_count += 1
						tel_send(f"[{msg_tag}] {stock_name} 처리 완료 ({pl_rt:.2f}%)")
						if "익절" in msg_tag: update_stock_state(stock_code, tp_step=current_tp_step+1)
						elif "손절" in msg_tag: update_stock_state(stock_code, sl_step=current_sl_step+1)
						
						# [안실장 픽스] 자동 매도 기록을 로컬 DB에 저장하여 UI 내역 매칭 보장
						record_trade(stock_code, 'sell', msg_tag, stock_name, cur_prc, sell_qty)
						
						if ui_callback:
							ui_callback("trade", {"time": datetime.now().strftime("%m/%d %H:%M:%S"), "type": "매도", "code": stock_code, "name": stock_name, "price": cur_prc, "qty": sell_qty, "msg": msg_tag})
					else:
						log_msg(f"❌ 매도 실패: {res.get('return_msg')}")

			except Exception as e:
				try:
					print(f"Error stock {stock_code}: {e}")
				except:
					pass
				continue
		
		return {'status': 'done', 'sold': sell_count > 0, 'count': sell_count}

	except Exception as e:
		print(f"Fatal error chk_n_sell: {e}")
		return False

if __name__ == "__main__":
	from login import fn_au10001
	chk_n_sell(token=fn_au10001())