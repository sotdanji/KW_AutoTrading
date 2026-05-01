"""
Account Management Mixin
- 계좌 정보 갱신 (보유 종목, 수익률, 총 자산)
- 자동 갱신 토글
- 일괄 매도 (Panic Sell)
- 텔레그램 테스트
"""
import asyncio

from PyQt6.QtWidgets import QTableWidgetItem, QMessageBox
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor

from login import fn_au10001 as get_token
from sell_stock import fn_kt10001 as sell_stock
from get_setting import get_setting
from tel_send import tel_send
import qasync


class AccountMixin:
    """계좌 관리 및 일괄 매도 기능을 제공하는 Mixin"""

    def _get_any(self, item, keys, default=0):
        """다양한 API 필드명 중 존재하는 값을 파싱하여 정수로 반환"""
        for k in keys:
            if k in item:
                raw = item[k]
                if raw is None: continue
                try: return int(float(str(raw).replace(',', '')))
                except: continue
        return default

    def update_account_info(self):
        """계좌 정보 갱신 (Sync Wrapper)"""
        if self.account_update_task and not self.account_update_task.done():
            return
            
        self.account_update_task = asyncio.create_task(self._update_account_info_impl())
        self.account_update_task.add_done_callback(lambda t: None)

    async def _update_account_info_impl(self):
        """계좌 정보 갱신"""
        try:
            from acc_val import fn_kt00004
            token = self.broker.token
            if not token:
                 # 조용히 리턴하여 무한 로그 발생 방지
                 return

            loop = asyncio.get_event_loop()
            full_data = await loop.run_in_executor(None, self.broker.get_account_data)
            # [ADD] ka10077 실현 손익 데이터 별도 조회
            realized_data = await loop.run_in_executor(None, self.broker.get_realized_pl)
            total_realized_from_api, _ = realized_data if realized_data else (0, [])

            # 테이블 즉시 클리어 (데이터를 받은 직후 최신화를 위해)
            self.table_holdings.setRowCount(0)

            data_list = []
            totals_data = None
            
            if isinstance(full_data, dict):
                data_list = full_data.get('stk_acnt_evlt_prst', [])
                totals_list = full_data.get('stk_acnt_evlt_tot', [])
                if totals_list:
                    totals_data = totals_list[0]
                elif 'tot_pur_amt' in full_data or 'tdy_lspft' in full_data or 'aset_evlt_amt' in full_data:
                    # [kt00004 전용] 요약 정보가 Root에 직접 있는 경우 처리
                    totals_data = full_data
            elif isinstance(full_data, list):
                data_list = full_data
            
            
            if not data_list and not totals_data:
                # 데이터가 완전히 없는 경우 라벨 초기화 후 종료
                # self.append_log("계좌 정보 데이터 없음")
                self.lbl_total_buy.setText("0원")
                self.lbl_total_val.setText("0원")
                self.lbl_total_asset.setText("0원")
                self.lbl_return_rate.setText("0.00")
                self.lbl_realized_pl.setText("0원")
                return
                
            # Helper for clean parsing
            def parse_int(val):
                if not val: return 0
                return int(float(str(val).replace(',', '')))
                
            def parse_float(val):
                if not val: return 0.0
                return float(str(val).replace(',', ''))

            # Calculate Totals from list (Fallback)
            calc_total_buy = 0
            calc_total_val = 0
            calc_total_pl = 0

            for i, item in enumerate(data_list):
                try:
                    if i == 0:
                        pass # Debug log removed
                    
                    qty = self._get_any(item, ['rmnd_qty', 'qty', 'hold_qty'])
                    ord_psbl_qty = self._get_any(item, ['ord_psbl_qty', 'can_sell_qty'])
                    
                    if qty <= 0 or ('ord_psbl_qty' in item and ord_psbl_qty <= 0):
                        continue # 수량이 없거나 전량 매도(주문가능수량 0)된 종목은 스킵
                    
                    cur_prc = self._get_any(item, ['cur_prc', 'stck_prc', 'now_prc', 'prc'])
                    
                    pchs = self._get_any(item, ['pchs_amt', 'buy_amt', 'tot_buy_amt', 'pur_amt'])
                    evlu = self._get_any(item, ['evlu_amt', 'eval_amt', 'tot_eval_amt', 'evlt_amt'])
                    pl = self._get_any(item, ['evlu_pfls_amt', 'evlu_erng_amt', 'pfls_amt', 'pl_amt'])
                    avg_price = self._get_any(item, ['pchs_avg_pric', 'buy_avg_pric', 'avg_prc', 'my_avg'])

                    # Calculation / Verification Logic
                    if avg_price > 0 and qty > 0:
                         calc_pchs = avg_price * qty
                         if pchs == 0: 
                             pchs = calc_pchs

                    if cur_prc > 0 and qty > 0:
                         calc_evlu = cur_prc * qty
                         if evlu == 0:
                             evlu = calc_evlu
                    
                    if pl == 0 and (evlu != 0 and pchs != 0):
                        pl = evlu - pchs

                    if pchs == 0 and evlu != 0:
                         pchs = evlu - pl
                         if qty > 0 and avg_price == 0:
                             avg_price = pchs // qty
                    
                    if evlu == 0 and pchs != 0:
                         evlu = pchs + pl

                    if avg_price == 0 and qty > 0 and pchs > 0:
                        avg_price = pchs // qty
                        pl = evlu - pchs
                        
                    if pchs == 0 and evlu != 0:
                         pchs = evlu - pl
                         if qty > 0 and avg_price == 0:
                             avg_price = pchs // qty

                    # Totals Update
                    calc_total_buy += pchs
                    calc_total_val += evlu
                    calc_total_pl += pl
                    
                    # Table Row
                    row = self.table_holdings.rowCount()
                    self.table_holdings.insertRow(row)
                    
                    stk_cd = item.get('stk_cd', '').replace('A', '')
                    stk_nm = item.get('stk_nm', '')
                    # Map stock name if unknown or numeric code
                    if not stk_nm or stk_nm == stk_cd:
                         stk_nm = self.stock_name_map.get(stk_cd, stk_nm)

                    # [안실장 픽스] 종목명 5자 제한 로직 적용
                    display_name = stk_nm[:5] if len(stk_nm) > 5 else stk_nm
                    name_item = QTableWidgetItem(display_name)
                    name_item.setToolTip(stk_nm) # 툴팁에 전체 이름 보관

                    pl_rt_str = item.get('pl_rt', '0.00')
                    
                    try:
                        pl_rt = float(pl_rt_str)
                    except:
                        pl_rt = (pl / pchs * 100) if pchs > 0 else 0.0
                    
                    i_code = QTableWidgetItem(stk_cd)
                    i_code.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    self.table_holdings.setItem(row, 0, i_code)
                    
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    self.table_holdings.setItem(row, 1, name_item)
                    
                    i_rate = QTableWidgetItem(f"{pl_rt:+.2f}")
                    i_rate.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if pl_rt > 0: i_rate.setForeground(QColor("#ff3333"))
                    elif pl_rt < 0: i_rate.setForeground(QColor("#00aaff"))
                    self.table_holdings.setItem(row, 2, i_rate)
                    
                    i_pl = QTableWidgetItem(f"{pl:+,}")
                    i_pl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if pl > 0: i_pl.setForeground(QColor("#ff3333"))
                    elif pl < 0: i_pl.setForeground(QColor("#00aaff"))
                    self.table_holdings.setItem(row, 3, i_pl)
                    
                    i_qty = QTableWidgetItem(f"{qty:,}")
                    i_qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table_holdings.setItem(row, 4, i_qty)
                    
                    i_avg = QTableWidgetItem(f"{avg_price:,}")
                    i_avg.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table_holdings.setItem(row, 5, i_avg)
                    
                    i_cur = QTableWidgetItem(f"{cur_prc:,}")
                    i_cur.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table_holdings.setItem(row, 6, i_cur)

                except Exception:
                    continue
            
            # Determine Final Totals
            final_buy = calc_total_buy
            final_val = calc_total_val
            final_pl = calc_total_pl
            
            return_rate = (final_pl / final_buy * 100) if final_buy > 0 else 0.0
            
            # [ka10077 우선 적용]
            realized_pl = total_realized_from_api

            if totals_data:
                api_buy = self._get_any(totals_data, ['tot_pchs_amt', 'tot_pur_amt', 'pchs_amt'])
                api_val = self._get_any(totals_data, ['tot_evlu_amt', 'aset_evlt_amt', 'evlu_amt'])
                api_pl = self._get_any(totals_data, ['tot_evlu_pfls_amt', 'evlu_pfls_amt']) 
                
                # API에서 제공하는 수익률이 있다면 우선 사용
                api_rate = parse_float(totals_data.get('evlu_pfls_rt') or totals_data.get('tot_evlu_pfls_rt') or totals_data.get('tdy_lspft_rt') or 0.0)
                if api_rate != 0: return_rate = api_rate

                # [kt00004 백업용] 
                if realized_pl == 0:
                    realized_val = (totals_data.get('tdy_rlzt_pl') or totals_data.get('rlzt_pl') or 
                                    totals_data.get('tdy_lspft') or totals_data.get('thst_pfls_amt') or 0)
                    realized_pl = parse_int(realized_val)

                if api_buy > 0: final_buy = api_buy
                if api_val > 0: final_val = api_val
                if api_pl != 0: final_pl = api_pl

            # Update UI Labels
            self.lbl_total_buy.setText(f"{final_buy:,.0f}원")
            
            pl_color = "#ff3333" if final_pl > 0 else "#00aaff"
            if final_pl == 0: pl_color = "#ffffff"
            self.lbl_total_val.setText(f"{final_pl:,.0f}원")
            self.lbl_total_val.setStyleSheet(f"color: {pl_color}; font-size: 14px; font-weight: bold;")
            
            self.lbl_total_asset.setText(f"{final_val:,.0f}원")
            
            self.lbl_return_rate.setText(f"{return_rate:+.2f}")
            rate_color = "#ff3333" if return_rate > 0 else "#00aaff"
            if return_rate == 0: rate_color = "#ffffff"
            self.lbl_return_rate.setStyleSheet(f"color: {rate_color}; font-size: 14px; font-weight: bold;")

            realized_color = "#ff3333" if realized_pl > 0 else "#00aaff"
            if realized_pl == 0: realized_color = "#ffffff"
            self.lbl_realized_pl.setText(f"{realized_pl:,.0f}원")
            self.lbl_realized_pl.setStyleSheet(f"color: {realized_color}; font-size: 14px; font-weight: bold;")
            
            # [보정] 마지막 갱신 시간 표시 (사용자 확신 제공)
            import datetime
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            if hasattr(self, 'check_auto_refresh'):
                self.check_auto_refresh.setText(f"10초 자동갱신 (최근: {now_str})")

            # self.append_log("계좌 정보 갱신 완료")
            
        except Exception as e:
            self.append_log(f"계좌 정보 갱신 오류: {e}")

        # [수정] 무한 루프 방지를 위해 여기서 toggle 호출 삭제
        # self.check_auto_refresh.setChecked(True)
        # self.toggle_auto_refresh()

    def toggle_auto_refresh(self):
        """자동 갱신 토글"""
        if self.check_auto_refresh.isChecked():
            if not hasattr(self, 'account_timer'):
                self.account_timer = QTimer(self)
                self.account_timer.timeout.connect(self.update_account_info)
            self.account_timer.start(10000) # 10 seconds
            # self.append_log("계좌 정보 자동 갱신 시작 (10초)")
        else:
            if hasattr(self, 'account_timer'):
                self.account_timer.stop()
            self.append_log("계좌 정보 자동 갱신 중지")

    def send_telegram_test(self):
        """텔레그램 테스트 발송"""
        try:
            res = tel_send("🔔 [테스트] 텔레그램 연동 성공!")
            if res and res.get('ok'):
                QMessageBox.information(self, "성공", "테스트 메시지를 발송했습니다.")
                self.append_log("텔레그램 테스트 발송 성공")
            else:
                 QMessageBox.warning(self, "실패", f"발송 실패: {res}")
                 self.append_log(f"텔레그램 발송 실패: {res}")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"오류 발생: {e}")
            self.append_log(f"텔레그램 오류: {e}")

    def open_telegram_help(self):
        """설정 가이드 도움말 (웹 브라우저)"""
        import webbrowser
        url = "https://www.youtube.com/watch?v=y4km5VRwV24"
        
        reply = QMessageBox.question(self, "설정 가이드 영상", 
            "키움증권 REST API 신청 및 텔레그램 봇 설정을 포함한\n'자동매매 제작 및 세팅 가이드' 영상을 여시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open(url)

    @qasync.asyncSlot()
    async def panic_sell_all(self):
        """일괄 매도 (Panic)"""
        reply = QMessageBox.question(self, "비상 매도", 
                                     "⚠️ 경고: 현재 보유 중인 모든 종목을 시장가로 매도합니다.\n이 작업은 되돌릴 수 없습니다.\n정말 진행하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.append_log("🚨 일괄 매도(Panic) 시작...")
        
        try:
            from acc_val import fn_kt00004
            token = getattr(self, 'broker', None).token if hasattr(self, 'broker') else None
            if not token:
                self.append_log("일괄 매도 실패: 토큰 없음")
                return

            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: fn_kt00004(token=token))
            
            data_list = res.get('stk_acnt_evlt_prst', []) if isinstance(res, dict) else []
            
            if not data_list:
                self.append_log("매도할 보유 종목이 없습니다.")
                QMessageBox.information(self, "알림", "보유 종목이 없습니다.")
                return
            
            count = 0
            for item in data_list:
                # [FIX] 종목코드의 'A' 접두어 제거 (REST API 주문 규격 준수)
                stk_cd = item.get('stk_cd', '').replace('A', '')
                stk_nm = item.get('stk_nm', '')
                qty = item.get('rmnd_qty', '')
                
                if not stk_cd or not qty or int(float(str(qty))) <= 0:
                    continue
                
                self.append_log(f"{stk_nm}({stk_cd}) {int(float(str(qty)))}주 매도 실행 중...")
                from sell_stock import fn_kt10001 as sell_stock
                res = await loop.run_in_executor(None, lambda code=stk_cd, q=qty: sell_stock(code, q, token=token))
                
                # Check for success (return_code 0 or '0')
                is_success = False
                if res == '0' or res == 0: is_success = True
                elif isinstance(res, dict) and (res.get('return_code') == 0 or res.get('return_code') == '0'): is_success = True

                if is_success:
                    self.append_log(f"✅ {stk_nm} 매도 주문 완료")
                    count += 1
                    
                    # 1. 파일 저장
                    from history_manager import record_trade
                    cur_prc = self._get_any(item, ['cur_prc', 'stck_prc', 'now_prc', 'prc'])
                    sell_qty = int(float(str(qty)))
                    
                    # 1. 파일 저장
                    record_trade(stk_cd, 'sell', "일괄매도", stk_nm, cur_prc, sell_qty)
                    
                    # 2. UI 갱신 신호 발생
                    if hasattr(self, 'sig_trade'):
                        from datetime import datetime
                        trade_data = {
                            'time': datetime.now().strftime('%m/%d %H:%M:%S'),
                            'code': stk_cd,
                            'name': stk_nm,
                            'type': '매도(일괄)',
                            'price': cur_prc,
                            'qty': sell_qty,
                            'msg': 'Panic Sell'
                        }
                        self.sig_trade.emit(trade_data)
                elif isinstance(res, dict) and res.get('return_code') == 20: 
                     is_demo = get_setting('use_demo', False)
                     msg = res.get('return_msg', '')
                     if '장이 열리지않는' in msg and is_demo:
                         self.append_log(f"⚠️ {stk_nm} (모의투자) 장외 거래 불가: {msg}")
                     else:
                         self.append_log(f"⛔ {stk_nm} 장이 열리지 않았습니다.")
                else:
                     self.append_log(f"❌ {stk_nm} 매도 실패: {res}")
                
                await asyncio.sleep(0.2)
                
            self.append_log(f"일괄 매도 완료: 총 {count} 종목 주문됨")
            QMessageBox.information(self, "완료", f"일괄 매도 작업을 완료했습니다.\n(주문 {count}건)")
            
            await self._update_account_info_impl()
            
        except Exception as e:
            self.append_log(f"일괄 매도 중 오류: {e}")
            QMessageBox.critical(self, "오류", f"일괄 매도 오류: {e}")

    def init_account_mixin_logic(self):
        """보유 종목 테이블 우클릭 메뉴 연결"""
        if hasattr(self, 'table_holdings'):
            self.table_holdings.customContextMenuRequested.connect(self.on_holdings_context_menu)

    def on_holdings_context_menu(self, pos):
        """보유 종목 테이블 우클릭 시 즉시 매도 확인 팝업 표시"""
        # 클릭한 위치의 행 찾기
        index = self.table_holdings.indexAt(pos)
        if not index.isValid():
            return
            
        row = index.row()
        code = self.table_holdings.item(row, 0).text()
        name = self.table_holdings.item(row, 1).text()

        # 중간 메뉴 없이 즉시 매도 로직 실행 (확인 팝업은 내부에서 뜸)
        asyncio.create_task(self.sell_selected_stock(code, name, row))

    async def sell_selected_stock(self, code, name, row):
        """선택 종목 개별 매도 로직"""
        # 잔고 수량 확인
        qty_str = self.table_holdings.item(row, 4).text().replace(',', '')
        try:
            qty = int(float(qty_str))
        except:
            qty = 0

        if qty <= 0:
            QMessageBox.warning(self, "경고", "매도할 수량이 없습니다.")
            return

        reply = QMessageBox.question(self, "개별 매도 확인", 
                                     f"[{name}] 종목 {qty}주를 시장가로 즉시 매도하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.append_log(f"🔔 [{name}] 개별 매도 주문 시도...")
        
        try:
            token = getattr(self, 'broker', None).token if hasattr(self, 'broker') else None
            # sell_stock = fn_kt10001
            from sell_stock import fn_kt10001
            
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: fn_kt10001(code, qty, token=token))
            
            # success check
            is_success = False
            if res == '0' or res == 0: is_success = True
            elif isinstance(res, dict) and (res.get('return_code') == 0 or res.get('return_code') == '0'): is_success = True

            if is_success:
                self.append_log(f"✅ [{name}] 개별 매도 완료 (시장가)")
                
                # 거래 기록
                from history_manager import record_trade
                from datetime import datetime
                
                # 현재가 가져오기
                price_str = self.table_holdings.item(row, 6).text().replace(',', '')
                price = int(float(price_str))
                
                record_trade(code, 'sell', "수동매도", name, price, qty)
                
                if hasattr(self, 'sig_trade'):
                    self.sig_trade.emit({
                        'time': datetime.now().strftime('%m/%d %H:%M:%S'),
                        'code': code,
                        'name': name,
                        'type': '매도(수동)',
                        'price': price,
                        'qty': qty,
                        'msg': 'Manual Context Sell'
                    })
                
                # [안실장 픽스] 매도 성공 시 UI 즉시 대응 (Stale Data 방지)
                if hasattr(self, 'table_holdings'):
                    for r in range(self.table_holdings.rowCount()):
                        if self.table_holdings.item(r, 1).text() == code:
                            self.table_holdings.removeRow(r)
                            break
                await asyncio.sleep(1.0)
                await self._update_account_info_impl()
            else:
                self.append_log(f"❌ [{name}] 매도 실패: {res}")
                QMessageBox.critical(self, "실패", f"매도 주문 실패: {res}")
                
        except Exception as e:
            self.append_log(f"매도 중 오류: {e}")
            QMessageBox.critical(self, "오류", f"매도 실행 중 오류 발생: {e}")
