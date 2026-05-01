"""
Settings Management Mixin
- 설정 로드/저장 (TP, SL, 매매 모드, 매매 방법 등)
- 조건식 관리 (로드, 선택, 재시작)
"""
import asyncio

from PyQt6.QtWidgets import QMessageBox

from get_setting import get_setting, update_setting, get_all_settings
from get_seq import get_condition_list, get_condition_stock_list
from login import fn_au10001 as get_token
import json
import os
import qasync


class SettingsMixin:
    """설정 로드/저장 및 조건식 관리 기능을 제공하는 Mixin"""

    # --- Settings Logic ---
    def load_all_settings(self):
        settings = get_all_settings()
        
        # Load TP
        tp_steps = settings.get('take_profit_steps', [])
        for i, ui in enumerate(self.tp_steps_ui):
            if i < len(tp_steps):
                ui['chk'].setChecked(tp_steps[i].get('enabled', False))
                ui['rate'].setValue(tp_steps[i].get('rate', 0.0))
                ui['ratio'].setValue(tp_steps[i].get('ratio', 0.0))
        
        # Load SL
        sl_steps = settings.get('stop_loss_steps', [])
        for i, ui in enumerate(self.sl_steps_ui):
            if i < len(sl_steps):
                ui['chk'].setChecked(sl_steps[i].get('enabled', False))
                ui['rate'].setValue(sl_steps[i].get('rate', 0.0))
                ui['ratio'].setValue(sl_steps[i].get('ratio', 0.0))

        # Basic Settings
        self.spin_buy_ratio.setValue(settings.get('buy_ratio', 3.0))
        self.spin_buy_amount.setValue(settings.get('buy_amount', 100000))
        self.spin_max_stock.setValue(settings.get('max_stock_count', 10))
        self.check_auto_start.setChecked(settings.get('auto_start', True))
        self.check_manual_buy.setChecked(settings.get('manual_buy', False))
        self.check_manual_sell.setChecked(settings.get('manual_sell', False))
        if hasattr(self, 'check_use_interest_formula'):
            self.check_use_interest_formula.setChecked(settings.get('use_interest_formula', False))
        
        # Load Trailing Stop & Breakeven
        self.chk_ts_enabled.setChecked(settings.get('ts_enabled', False))
        if hasattr(self, 'chk_be_enabled'):
            self.chk_be_enabled.setChecked(settings.get('be_enabled', False))
        
        self.spin_ts_activation.setValue(settings.get('ts_activation', 10.0))
        self.spin_ts_drop.setValue(settings.get('ts_drop', 3.0))
        self.spin_ts_limit.setValue(settings.get('ts_limit_count', 2))
        
        is_amount = (settings.get('buy_method', 'percent') == 'amount')
        self.radio_amount.setChecked(is_amount)
        self.radio_percent.setChecked(not is_amount)
        self.toggle_buy_method()
        
        is_paper = (settings.get('account_mode', 'PAPER') == 'PAPER')
        self.check_paper.setChecked(is_paper)
        
        # Trading Method
        mode = settings.get('trading_mode', 'cond_base')
        
        if mode == 'cond_stock_radar':
            self.btn_cond_stock_radar.setChecked(True)
        elif mode == 'acc_swing':
            self.btn_acc_swing.setChecked(True)
        elif mode == 'volatility_breakout':
            self.btn_vol_breakout.setChecked(True)
        else: 
            # Default or merged 'cond_base' / 'cond_only' / 'cond_strategy'
            self.btn_cond_base.setChecked(True)
        
        # Load Gap Recovery (formerly LW) Params
        self.spin_lw_lookback.setValue(settings.get('lw_lookback', 30))
        self.spin_lw_k.setValue(settings.get('lw_k', 0.5))
        # Load Auto-Switching Settings
        if hasattr(self, 'check_two_track'):
            self.check_two_track.setChecked(settings.get('use_two_track', False))
        if hasattr(self, 'check_15h_switch'):
            self.check_15h_switch.setChecked(settings.get('use_15h_switch', False))
        if hasattr(self, 'check_use_atr_risk'):
            self.check_use_atr_risk.setChecked(settings.get('use_atr_risk_management', False))
        
        # Condition
        seq_list = settings.get('search_seq_list', [])
        if not seq_list and settings.get('search_seq'):
            seq_list = [settings.get('search_seq')]
        self.update_conditions_label_with_names(seq_list)
        
        # Load Strategy List
        if hasattr(self, 'load_strategy_list'):
            self.load_strategy_list()

    def save_trading_mode(self):
        mode = "cond_base" # Default to merged mode
        if self.btn_cond_stock_radar.isChecked():
            mode = "cond_stock_radar"
        elif self.btn_acc_swing.isChecked():
            mode = "acc_swing"
        elif self.btn_vol_breakout.isChecked():
            mode = "volatility_breakout"
        
        # Determine strategy filter status based on selection and main mode
        strategy_selected = self.combo_strategy.currentText()
        use_strategy = (mode == "cond_base" and strategy_selected != "선택안함")

        update_setting('trading_mode', mode)
        update_setting('use_strategy_filter', use_strategy)
        update_setting('stock_radar_use', (mode == 'cond_stock_radar'))
        update_setting('acc_swing_use', (mode == 'acc_swing'))
        update_setting('volatility_breakout_use', (mode == 'volatility_breakout'))
        
        self.statusBar.showMessage(f"매매 모드 변경: {mode} (전략필터: {use_strategy})", 2000)

    def save_setting(self, key, value):
        update_setting(key, value)
        self.statusBar.showMessage(f"저장됨: {key}", 2000)

    def save_tp_settings(self):
        steps = []
        for ui in self.tp_steps_ui:
            rate = ui['rate'].value()
            steps.append({
                "enabled": ui['chk'].isChecked(),
                "rate": rate,
                "ratio": ui['ratio'].value()
            })
        update_setting('take_profit_steps', steps)

    def save_sl_settings(self):
        steps = []
        for ui in self.sl_steps_ui:
            rate = ui['rate'].value()
            steps.append({
                "enabled": ui['chk'].isChecked(),
                "rate": rate,
                "ratio": ui['ratio'].value()
            })
        update_setting('stop_loss_steps', steps)

    def toggle_buy_method(self):
        is_amount = self.radio_amount.isChecked()
        self.spin_buy_ratio.setEnabled(not is_amount)
        self.spin_buy_amount.setEnabled(is_amount)
        update_setting('buy_method', 'amount' if is_amount else 'percent')

    def save_account_setting(self):
        is_paper = self.check_paper.isChecked()
        account_mode = 'PAPER' if is_paper else 'REAL'
        current = get_setting('account_mode', 'PAPER')
        if current != account_mode:
            update_setting('account_mode', account_mode)
            QMessageBox.information(self, "알림", "계좌 모드가 변경되었습니다. 재시작 필요.")

    # --- Condition Logic ---
    @qasync.asyncSlot()
    async def load_conditions(self):
        try:
            token = get_token()
            data = await get_condition_list(token)
            if data:
                temp_list = []
                for item in data:
                    if isinstance(item, dict):
                        s = item.get('seq', '')
                        n = item.get('name', '')
                    else:
                        s = item[0]
                        n = item[1]
                    
                    try:
                        temp_list.append((int(s), str(n)))
                    except ValueError:
                        pass

                temp_list.sort(key=lambda x: x[0])
                temp_list = temp_list[:20]
                self.condition_list = [(str(s), n) for s, n in temp_list]
                
                # [공통 1차 필터] 장전관심종목 자동 감지 (모든 전략 모드)
                warmup_seqs = []
                
                for seq, n in temp_list:
                    name = str(n)
                    s_seq = str(seq)
                    if "장전관심" in name or "수동" in name:
                        warmup_seqs.append(s_seq)
                
                # 모든 모드 공통: 장전관심종목 선행 로딩 등록 (Warm-up)
                update_setting('warmup_seq_list', warmup_seqs)
                if warmup_seqs:
                    names_str = ", ".join([n for s, n in temp_list if str(s) in warmup_seqs])
                    self.append_log(f"⚡ [설정] 장전관심종목 감지됨: {names_str}")
                    
                    # [NEW] 즉시 조회 및 저장 로직 추가
                    # 장전(또는 실행 시점)에 해당 조건식의 종목을 가져와서 lead_watchlist.json에 저장
                    total_saved = 0
                    all_stocks = []
                    
                    for seq in warmup_seqs:
                         self.append_log(f"   ㄴ 장전관심종목({seq}) 조회 중...")
                         # 비동기로 조회 (순차적)
                         stock_data = await get_condition_stock_list(token, seq)
                         if stock_data:
                             for stock in stock_data:
                                 # 중복 방지와 KeyError 동시 방어
                                 if isinstance(stock, dict) and stock.get('code'):
                                     if not any(isinstance(s, dict) and s.get('code') == stock.get('code') for s in all_stocks):
                                         all_stocks.append(stock)
                             total_saved += len(stock_data)
                         # API Rate Limit 보호를 위해 조회 간 0.5초 대기
                         await asyncio.sleep(0.5)
                    
                    if all_stocks:
                        try:
                            # Save to lead_watchlist.json
                            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                            save_path = os.path.join(current_dir, "lead_watchlist.json")
                            with open(save_path, "w", encoding="utf-8") as f:
                                json.dump(all_stocks, f, indent=4, ensure_ascii=False)
                            self.append_log(f"✅ 장전관심종목 {len(all_stocks)}개 저장 완료 (파일: lead_watchlist.json)")
                        except Exception as e:
                            self.append_log(f"❌ 장전관심종목 파일 저장 실패: {e}")
                    else:
                        self.append_log("⚠️ 장전관심종목 조회 결과 없음 (장전이라 데이터가 없을 수 있음)")
                    
                # [중요] search_seq_list(감시 조건식)는 건드리지 않음.
                # StockRadar/LW 모드에서 실시간 감시가 필요한 경우, rt_search.py에서 런타임에 합쳐서 요청함.
                
                current = get_setting('search_seq_list', [])
                if not current and get_setting('search_seq'): current = [get_setting('search_seq')]
                self.update_conditions_label_with_names(current)
                self.append_log(f"조건식 목록 로드 완료 (상위 {len(self.condition_list)}개)")
        except Exception as e:
            self.append_log(f"조건식 로드 실패: {e}")

    def open_condition_dialog(self):
        if not self.condition_list:
            QMessageBox.warning(self, "오류", "조건식 목록이 없습니다.")
            return
        
        from trading_ui import ConditionSelectDialog
        current = get_setting('search_seq_list', [])
        dlg = ConditionSelectDialog(self.condition_list, current, self)
        if dlg.exec():
            old_seqs = set(current)
            new_seqs = set(dlg.result_seqs)
            
            update_setting('search_seq_list', dlg.result_seqs)
            self.update_conditions_label_with_names(dlg.result_seqs)
            self.append_log("감시 조건식 변경됨.")
            
            if old_seqs != new_seqs:
                if hasattr(self.chat_cmd, 'engine') and self.chat_cmd.engine.is_running:
                     asyncio.create_task(self.restart_engine_search())

    async def restart_engine_search(self):
        """실시간 검색 재시작 (조건식 변경 적용)"""
        self.append_log("🔄 조건식 변경으로 실시간 검색을 재시작합니다...")
        try:
             token = self.chat_cmd.engine.token
             if not token:
                 self.append_log("❌ 토큰이 없어 재시작 실패")
                 return
             
             success = await self.chat_cmd.engine.rt_search.start(token)
             
             if success:
                 self.append_log("✅ 실시간 검색 재시작 완료")
             else:
                 self.append_log("❌ 실시간 검색 재시작 실패")
                 
        except Exception as e:
            self.append_log(f"재시작 오류: {e}")

    def update_conditions_label_with_names(self, seq_list):
        if not seq_list:
            self.label_selected_conditions.setText("선택 없음")
            return
        
        display = []
        for seq in seq_list:
            name = next((n for s, n in self.condition_list if s == seq), "?")
            display.append(f"{seq}:{name}")
        
        self.label_selected_conditions.setText(", ".join(display[:3]) + ("..." if len(display)>3 else ""))
