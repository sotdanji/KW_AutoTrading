import sys
import os
import shutil
import asyncio
import json
import re
from datetime import datetime, time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QTabWidget,
    QGroupBox, QGridLayout, QHeaderView, QStatusBar, QRadioButton, QSpinBox, QButtonGroup,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QMessageBox, QFrame, QSplitter, QLineEdit,
    QFileDialog, QProgressBar
)
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, Qt, pyqtSlot, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QFont, QColor, QIcon, QMovie, QPixmap
import qasync
import base64

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import Core Modules
from get_setting import get_setting, update_setting, get_all_settings
from chat_command import ChatCommand
from get_seq import get_condition_list
from login import fn_au10001 as get_token
from shared.market_hour import MarketHour
from buy_stock import fn_kt10000 as buy_stock
from sell_stock import fn_kt10001 as sell_stock
from state_manager import update_stock_state
from tel_send import tel_send

# Import New Core Modules
try:
    from shared.formula_parser import FormulaParser
    from shared.hangul_converter import HangulVariableConverter
except ImportError:
    print("Warning: Core modules not found. Strategy features may be disabled.")

from core.broker_adapter import BrokerAdapter

# Import UI Styles
try:
    from shared.ui.styles import DARK_THEME_QSS
except ImportError:
    DARK_THEME_QSS = "" # Fallback if style missing

# Import Mixins

from shared.ui.strategy_mixin import StrategyMixin

from ui.account_mixin import AccountMixin

from ui.settings_mixin import SettingsMixin




class LogSignal(QObject):
    """Log Signal - Redirect stdout to GUI"""
    log_received = pyqtSignal(str)

    def write(self, text):
        if text.strip():
            self.log_received.emit(str(text))
    
    def flush(self):
        pass


class ConditionSelectDialog(QDialog):
    """Condition Selection Dialog"""
    def __init__(self, condition_list, selected_seqs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("조건검색식 선택")
        self.resize(400, 250)
        self.condition_list = condition_list
        self.selected_seqs = selected_seqs
        self.result_seqs = []
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        guide = QLabel("감시할 조건검색식을 선택하세요 (최대 3개)")
        guide.setStyleSheet("color: #cccccc; font-weight: bold;")
        layout.addWidget(guide)
        
        # 3 Comboboxes
        self.combos = []
        for i in range(3):
            h_layout = QHBoxLayout()
            label = QLabel(f"{i+1}번 필터:")
            label.setStyleSheet("color: #a0a0a0;")
            h_layout.addWidget(label)
            
            combo = QComboBox()
            combo.addItem("선택 안 함", "") 
            
            # Fill List
            for item in self.condition_list:
                try:
                    if isinstance(item, dict):
                        seq = str(item.get('seq', ''))
                        name = str(item.get('name', ''))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                         seq = str(item[0])
                         name = str(item[1])
                    else:
                        continue # Skip invalid format
                    
                    if seq and name:
                        if "장전관심" in name or "수동" in name:
                            continue
                        combo.addItem(f"[{seq}] {name}", seq)
                except Exception as e:
                    print(f"Error parsing condition item: {item} -> {e}")
                    continue
            
            h_layout.addWidget(combo)
            layout.addLayout(h_layout)
            self.combos.append(combo)
            
        # Set previous values
        for i, seq in enumerate(self.selected_seqs):
            if i < 3:
                index = self.combos[i].findData(seq)
                if index >= 0:
                    self.combos[i].setCurrentIndex(index)
        
        layout.addStretch()
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def accept(self):
        self.result_seqs = []
        seen = set()
        for combo in self.combos:
            seq = combo.currentData()
            if seq and seq not in seen:
                self.result_seqs.append(seq)
                seen.add(seq)
        super().accept()


class TradingMainWindow(StrategyMixin, AccountMixin, SettingsMixin, QMainWindow):

    """Main Trading Window with Sidebar and Tabs"""
    
    # Thread-Safe Signals
    sig_trade = pyqtSignal(dict)
    sig_captured = pyqtSignal(dict)
    sig_filter = pyqtSignal(dict)
    sig_confirm = pyqtSignal(dict)
    sig_settings = pyqtSignal(dict)
    sig_market = pyqtSignal(dict) # [안실장 픽스] 실시간 지수 신호 추가

    def __init__(self):
        super().__init__()
        
        # Connect Signals
        self.sig_trade.connect(self.handle_trade_and_refresh)
        self.sig_captured.connect(self.add_captured_stock)
        self.sig_filter.connect(self.update_filter_status)
        self.sig_confirm.connect(lambda d: self.show_confirmation_dialog(d.get('type', 'buy') if d else 'buy', d) if d else None)
        self.sig_settings.connect(self.update_settings_ui)
        self.sig_market.connect(self.update_market_dashboard) # 지수 핸들러 연결

        self.chat_cmd = ChatCommand(ui_callback_func=self.handle_engine_event)
        self.condition_list = []
        self.stock_name_map = {} # Stock Code -> Name mapping
        self.broker = BrokerAdapter()
        self.engine = None # Initialize engine attribute
        
        # Scheduling Variables
        self.today_started = False
        self.today_stopped = False
        self.last_check_date = None
        self.disconnect_count = 0 # Track consecutive disconnections
        self._is_starting = False # [안실장] 중복 시작 방지 가드
        
        # [안실장 유지보수 가이드] 시장 신호 매니저 초기화 및 체크 타이머 설정
        from shared.signal_manager import MarketSignalManager
        self.signal_manager = MarketSignalManager()
        self.last_signal_check = 0
        
        # Telegram Polling (Async)
        self.polling_task = None
        self.account_update_task = None # Task Tracker
        QTimer.singleShot(100, self.start_polling)
        
        # UI Initialization
        self.init_ui()
        
        # [NEW] Mixin Logic Initialization
        if hasattr(self, 'init_account_mixin_logic'):
            self.init_account_mixin_logic()
        
        # [HTS 연동] 더블 클릭 연동 초기화
        self.init_hts_interlock()
        
        # Apply Dark Theme
        self.setStyleSheet(DARK_THEME_QSS)
        
        # Log Redirection
        self.log_signal = LogSignal()
        self.log_signal.log_received.connect(self.append_log)
        sys.stdout = self.log_signal
        
        # Load Settings
        self.load_all_settings()
        
        # Timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.periodic_update)
        self.update_timer.start(1000)
        
        self.append_log("시스템 초기화 중...")
        # Start ordered initialization
        QTimer.singleShot(100, self.start_system_initialization)

    def start_system_initialization(self):
        """시스템 비동기 초기화 진입점"""
        asyncio.create_task(self._init_sequence())

    async def _init_sequence(self):
        """순차적 초기화: 토큰발급 -> 거래내역 로드 -> 조건식 로드"""
        try:
            # 1. Token Issuance (Run in thread to prevent UI freeze)
            self.append_log("토큰 발급(로그인) 시도 중...")
            from login import fn_au10001 as get_token
            loop = asyncio.get_event_loop()
            token = await loop.run_in_executor(None, get_token)
            
            if token:
                self.broker.set_token(token)
                
                # [안실장] 서버 모드 로그 상세화
                from config import get_current_config
                conf = get_current_config()
                mode_str = "실전 서버 (REAL)" if "mock" not in conf['host_url'].lower() else "모의 서버 (MOCK)"
                self.append_log(f"✅ 토큰 발급 완료. [{mode_str}] 연결됨.")
                
                # 2. Account Info (Dashboard)
                await self._update_account_info_impl()
                user_name = getattr(self.broker, 'user_name', '')
                title_name = f" - {user_name}" if user_name else ""
                
                if self.broker.use_demo:
                    self.setWindowTitle(f"AT_Sig Trading System{title_name} (모의투자)")
                else:
                    self.setWindowTitle(f"AT_Sig Trading System{title_name} (실투자)")

                # [UI 스타일 개선] 체크박스 가시성 확보 (검은 배경 대응)
                self.setStyleSheet("""
                    QWidget {
                        background-color: #2b2b2b;
                        color: #ffffff;
                        font-family: 'Malgun Gothic';
                    }
                    QCheckBox {
                        spacing: 5px;
                        color: #ffffff;
                    }
                    QCheckBox::indicator {
                        width: 13px;
                        height: 13px;
                        background-color: #ffffff;
                        border: 1px solid #5a5a5a;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #4CAF50;
                        border: 1px solid #4CAF50;
                    }
                    QTableWidget {
                        gridline-color: #5a5a5a;
                        background-color: #1e1e1e;
                        alternate-background-color: #2b2b2b;
                    }
                    QHeaderView::section {
                        background-color: #3b3b3b;
                        color: white;
                        border: 1px solid #5a5a5a;
                    }
                    /* Tab Bar Styling for Visibility */
                    QTabWidget::pane { border: 1px solid #444; }
                    QTabBar::tab {
                        background: #333;
                        color: #aaa;
                        padding: 8px 20px;
                        border-top-left-radius: 4px;
                        border-top-right-radius: 4px;
                        margin-right: 2px;
                    }
                    QTabBar::tab:selected {
                        background: #555;
                        color: #00aaff;
                        font-weight: bold;
                        border-bottom: 2px solid #00aaff;
                    }
                    QTabBar::tab:hover {
                        background: #444;
                        color: #fff;
                    }
                """)
            else:
                self.append_log("토큰 발급 실패: 키움 Open API 포털에서 지정단말기/IP 등록 여부를 확인하거나 AppKey를 점검하세요.")
                if hasattr(self, 'sidebar_progress'):
                    self.sidebar_progress.hide()
                self.label_status.setText("오류(발급실패)")
                self.label_status.setStyleSheet("color: #ff0000; font-weight: bold;")
                return

            # 2. Load Stock Master Names
            await self.load_stock_master()

            # 3. Load History (Safe to use broker now)
            await self.load_daily_history()
            
            # [안실장 픽스] 3.5. 오늘 포착된 종목 리스트 복구
            await self.load_captured_history()
            
            # 4. Load Conditions (await으로 완료 보장 → warmup_seq_list 설정 후 엔진 시작)
            await self.load_conditions()
            
            self.append_log("시스템 모든 준비 완료.")
            
            # 초기 로딩 표시 숨기기
            if hasattr(self, 'sidebar_progress'):
                self.sidebar_progress.hide()

            # 4. Check Auto Start (Post-Login)
            if self.check_auto_start.isChecked() and MarketHour.is_market_open_time():
                if not self._is_starting and (not self.engine or not self.engine.is_running):
                    self.append_log("⏳ 자동실행 설정됨: 장중이므로 즉시 매매를 시작합니다.")
                    # Use a slight delay to ensure UI is fully rendered
                    await asyncio.sleep(1)
                    await self.start_trading(initial_token=token)
                    self.today_started = True # [안실장] 초기화 시 시작해도 플래그 설정
            
        except Exception as e:
            self.append_log(f"초기화 중 오류 발생: {e}")

    async def load_stock_master(self):
        """종목 마스터 데이터(코드:명칭) 로드 - [안실장 픽스] 보호 로직 통합 버전"""
        try:
            from shared.stock_master import load_master_cache
            # [안실장 픽스] 직접 json.load 대신 오버라이드 및 필터링이 포함된 공용 로더 사용
            self.stock_name_map = load_master_cache()
            self.append_log(f"📦 종목명 마스터 로드 완료 ({len(self.stock_name_map)}개 종목)")
        except Exception as e:
            self.append_log(f"⚠️ 종목 마스터 로드 오류: {e}")

    async def load_captured_history(self):
        """오늘 포착된 종목 리스트 불러오기"""
        try:
            from history_manager import load_today_captured
            captured_list = load_today_captured()
            
            if not captured_list:
                return

            for item in captured_list:
                # add_captured_stock는 dict를 인자로 받음
                self.add_captured_stock(item)
                
            self.append_log(f"📡 오늘 포착된 종목 {len(captured_list)}건 리스트를 복구했습니다.")
        except Exception as e:
            self.append_log(f"포착 내역 로드 실패: {e}")

    @qasync.asyncSlot()
    async def load_daily_history(self):
        """오늘 거래 내역 불러오기 (Local + API Merge)"""
        try:
            # 1. Local History Load (Load All saved history)
            from history_manager import load_history
            history_data = load_history() # returns {date: {code: [trades], ...}}
            
            local_trades = []
            for date_str, stocks in history_data.items():
                for code, trades in stocks.items():
                    for t in trades:
                        t_copy = t.copy()
                        t_copy['code'] = code
                        t_copy['date'] = date_str # YYYY-MM-DD
                        local_trades.append(t_copy)

            # Map local trades by key for matching (Date included for historical matching)
            # Key: (date_yyyymmdd, code, type_str, qty, price) -> msg (Strategy Name)
            local_map = {}
            for t in local_trades:
                # Normalize values
                code = t.get('code', '')
                type_str = t.get('type', '') # 매수/매도
                qty = str(int(float(str(t.get('qty', 0)).replace(',', ''))))
                price = str(int(float(str(t.get('price', 0)).replace(',', ''))))
                date_key = t.get('date', '').replace('-', '') # YYYY-MM-DD -> YYYYMMDD
                
                # Simplify type for robust key matching
                simple_type = 'buy' if '매수' in type_str or 'buy' in type_str.lower() else 'sell'
                
                key = (date_key, code, simple_type, qty, price)
                # Store the most descriptive message or strategy name
                local_map[key] = t.get('msg', '')

            # 2. API History Load (Today + Past)
            from get_order_history import get_combined_history
            token = self.broker.token if hasattr(self, 'broker') and self.broker else None
            
            # Run in executor to avoid blocking UI
            loop = asyncio.get_running_loop()
            api_trades = await loop.run_in_executor(None, lambda: get_combined_history(token=token))
            
            final_trades_list = []
            today_md = datetime.now().strftime("%m/%d")
            matched_local_keys = set()

            # Process API Trades
            for at in api_trades:
                code = at.get('stk_cd', '').replace('A', '') # Remove 'A' prefix if present
                name = at.get('stk_nm', '')
                type_raw = at.get('io_tp_nm', '') # 매수/매도/..
                qty = str(int(float(str(at.get('trde_qty_jwa_cnt', '0')).replace(',', ''))))
                price = str(int(float(str(at.get('trde_unit', '0')).replace(',', ''))))
                time_str = at.get('proc_tm', '') # HH:MM:SS or HHMMSS
                date_raw = at.get('trde_dt', '') # YYYYMMDD
                
                # Format Date (Month/Day)
                md_prefix = f"{date_raw[4:6]}/{date_raw[6:8]}" if len(date_raw) == 8 else today_md

                # Format Time
                clean_time = time_str.replace(':', '')
                if len(clean_time) == 6:
                     time_formatted = f"{md_prefix} {clean_time[:2]}:{clean_time[2:4]}:{clean_time[4:]}"
                else:
                     time_formatted = f"{md_prefix} {time_str}"

                simple_type = 'buy' if any(w in type_raw.lower() for w in ['매수', 'buy']) else 'sell'
                
                # Match against local map (Date-sensitive)
                key = (date_raw, code, simple_type, qty, price)
                msg = local_map.get(key)
                if msg:
                    matched_local_keys.add(key)
                else:
                    msg = "수동/기타매수" if simple_type == 'buy' else "수동/기타매도"

                trade_item = {
                    'time': time_formatted,
                    'code': code,
                    'name': name,
                    'type': type_raw,
                    'price': price,
                    'qty': qty,
                    'msg': msg
                }
                final_trades_list.append(trade_item)

            # 3. Add unmatched local trades (Ensures immediate visibility)
            for key, msg in local_map.items():
                if key not in matched_local_keys:
                    # Find original local trade item
                    # key format: (date_yyyymmdd, code, simple_type, qty, price)
                    lt = None
                    for t in local_trades:
                        t_date = t.get('date', '').replace('-', '')
                        t_code = t.get('code', '')
                        t_type = 'buy' if any(w in t.get('type','').lower() for w in ['매수', 'buy']) else 'sell'
                        t_qty = str(int(float(str(t.get('qty', 0)).replace(',', ''))))
                        t_price = str(int(float(str(t.get('price', 0)).replace(',', ''))))
                        
                        if (t_date == key[0] and t_code == key[1] and t_type == key[2] and 
                            t_qty == key[3] and t_price == key[4]):
                            lt = t
                            break
                    
                    if lt:
                        # Ensure time is formatted correctly for local trades
                        orig_time = lt.get('time', '')
                        date_raw = lt.get('date', '').replace('-', '') # YYYYMMDD
                        md_pref = f"{date_raw[4:6]}/{date_raw[6:8]}" if len(date_raw) == 8 else today_md
                        
                        if '/' not in orig_time: 
                            lt['time'] = f"{md_pref} {orig_time}"
                        
                        # Normalize price for display
                        p_val = lt.get('price', 0)
                        lt['price'] = f"{int(float(str(p_val).replace(',',''))):,}" if str(p_val).replace('.','').replace(',','').isdigit() else str(p_val)
                        
                        final_trades_list.append(lt)
            
            self.append_log(f"거래내역 로드 완료 (API:{len(api_trades)}건, 로컬병합 포함)")
            
            # Sort by time (Ascending: Oldest first)
            final_trades_list.sort(key=lambda x: x.get('time', ''), reverse=False)

            self.table_trades.setRowCount(0)
            for t in final_trades_list:
                row = self.table_trades.rowCount()
                self.table_trades.insertRow(row)
                
                # Fetch and Map Data
                code = t.get('code', '').replace('A', '')
                name = t.get('name', '')
                if not name or name == 'Unknown' or name == code:
                    name = self.stock_name_map.get(code, name)

                # [안실장 픽스] 종목명 5자 제한 로직
                display_name = name[:5] if len(name) > 5 else name
                name_item = QTableWidgetItem(display_name)
                name_item.setToolTip(name)

                # ["시간", "종목코드", "종목명", "구분", "체결가", "수량", "비고"]
                i_time = QTableWidgetItem(t.get('time', ''))
                i_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 0, i_time)
                
                i_code = QTableWidgetItem(code)
                i_code.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 1, i_code)
                
                i_name = QTableWidgetItem(display_name)
                i_name.setToolTip(name)
                i_name.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 2, i_name)
                
                type_str = t.get('type', '')
                i_type = QTableWidgetItem(type_str)
                i_type.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                if any(w in type_str.lower() for w in ['매수', 'buy']): 
                    i_type.setForeground(QColor("#ff3333"))
                elif any(w in type_str.lower() for w in ['매도', 'sell']): 
                    i_type.setForeground(QColor("#00aaff"))
                self.table_trades.setItem(row, 3, i_type)
                
                price_val = t.get('price', 0)
                try:
                    p_clean = str(price_val).replace(',', '').strip()
                    if p_clean and p_clean.replace('.', '').replace('-', '').isdigit():
                        price_str = f"{int(float(p_clean)):,}"
                    else:
                        price_str = str(price_val)
                except:
                    price_str = str(price_val)
                
                i_price = QTableWidgetItem(price_str)
                i_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 4, i_price)
                
                # 수량 포맷팅 및 정렬
                qty_val = t.get('qty', 0)
                try:
                    q_val = int(float(str(qty_val).replace(',', '')))
                    qty_str = f"{q_val:,}"
                except:
                    qty_str = str(qty_val)
                    
                i_qty = QTableWidgetItem(qty_str)
                i_qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 5, i_qty)
                
                i_msg = QTableWidgetItem(t.get('msg', ''))
                i_msg.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.table_trades.setItem(row, 6, i_msg)
            
            # [안실장] 시간순 정렬이므로 로드 직후 가장 아래(최신)로 스크롤
            self.table_trades.scrollToBottom()
                
        except Exception as e:
            self.append_log(f"거래 내역 로드 실패: {e}")
            import traceback
            traceback.print_exc()

    def init_ui(self):
        self.setWindowTitle("Sotdanji AutoTrading System")
        
        # Set Window Icon if available
        logo_path_svg = os.path.join(current_dir, "resources", "logo.svg")
        logo_path_png = os.path.join(current_dir, "resources", "logo.png")
        
        if os.path.exists(logo_path_svg):
            self.setWindowIcon(QIcon(logo_path_svg))
        elif os.path.exists(logo_path_png):
            self.setWindowIcon(QIcon(logo_path_png))
            
        self.resize(1280, 800)
        self.setMinimumSize(1280, 800)
        
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. Left Sidebar
        self.sidebar = self.create_sidebar()
        main_layout.addWidget(self.sidebar)
        
        # 2. Main Content (Tabs)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        # Tab 1: Dashboard
        self.tab_dashboard = self.create_dashboard_tab()
        self.tabs.addTab(self.tab_dashboard, "📊 대시보드")
        
        # Tab 2: Strategy
        self.tab_strategy = QWidget()
        self.setup_strategy_tab()
        self.tabs.addTab(self.tab_strategy, "📋 전략 코드 검증")
        
        # Tab 3: Settings
        self.tab_settings = self.create_settings_tab()
        self.tabs.addTab(self.tab_settings, "⚙️ 설정")
        
        main_layout.addWidget(self.tabs)
        
        # [안실장 유지보수 가이드] 공용 상태바 적용 (StandardStatusBar)
        from shared.ui.widgets import StandardStatusBar
        from shared.market_hour import MarketHour
        from config import get_current_config
        
        self.statusBar = StandardStatusBar()
        self.setStatusBar(self.statusBar)
        
        # 초기 상태 설정
        conf = get_current_config()
        self.statusBar.set_server_mode(is_real=(conf.get('host_url') == "https://api.kiwoom.com"))
        
        market = MarketHour()
        m_status, m_open = market.get_market_status_text()
        self.statusBar.update_market_status(m_status, is_open=m_open)
        self.statusBar.set_connection_status(False) # 초기값

    def create_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background-color: #1a1a1a; border-right: 1px solid #333;")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 20, 15, 20)
        layout.setSpacing(15)
        
        # --- Header (Logo + Title) 개편 ---
        header_container = QFrame()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 10)
        header_layout.setSpacing(15)

        header_layout.addStretch() # 좌측 여백 추가로 중앙 정렬

        # 1. Logo
        logo_label = QLabel()
        # [중앙 관리] CI는 workspace root의 shared/assets 폴더에서 관리합니다.
        ws_root = os.path.dirname(current_dir)
        logo_path_svg = os.path.join(ws_root, "shared", "assets", "logo.svg")
        logo_path_png = os.path.join(ws_root, "shared", "assets", "logo.png")
        
        pixmap = None
        if os.path.exists(logo_path_svg):
            pixmap = QIcon(logo_path_svg).pixmap(65, 65)
        elif os.path.exists(logo_path_png):
            pixmap = QPixmap(logo_path_png).scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)

        if pixmap and not pixmap.isNull():
            logo_label.setPixmap(pixmap)
            logo_label.setFixedWidth(70)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            # Fallback if no logo
            logo_label.setText("S")
            logo_label.setFixedSize(60, 60)
            logo_label.setStyleSheet("""
                background-color: #DAA520; color: black; font-weight: bold; 
                font-size: 32px; border-radius: 8px;
            """)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        header_layout.addWidget(logo_label)

        # 2. Title Text (Two Lines)
        text_container = QVBoxLayout()
        text_container.setSpacing(0)
        
        label_at_sig = QLabel("AT_Sig")
        label_at_sig.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff; line-height: 1.2;")
        
        label_sub = QLabel("AutoTrading")
        label_sub.setStyleSheet("font-size: 13px; color: #aaaaaa; font-weight: 500; letter-spacing: 0.5px;")
        
        text_container.addWidget(label_at_sig)
        text_container.addWidget(label_sub)
        header_layout.addLayout(text_container)
        
        header_layout.addStretch() # 우측 여백 추가로 중앙 정렬

        layout.addWidget(header_container)
        
        # Status Card
        status_box = QFrame()
        status_box.setStyleSheet("background-color: #252526; border-radius: 5px; padding: 10px;")
        sb_layout = QVBoxLayout(status_box)
        
        # System Status
        self.label_status = QLabel("준비")
        self.label_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3;")
        self.label_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(self.label_status)
        
        # Market Operating Status
        market_layout = QHBoxLayout()
        market_layout.addWidget(QLabel("장 운영:"))
        self.label_market_status = QLabel("-")
        self.label_market_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        market_layout.addWidget(self.label_market_status)
        sb_layout.addLayout(market_layout)

        # [안실장 신규] Market Regime Status (시장 국면 전용 라벨)
        regime_layout = QHBoxLayout()
        regime_layout.addWidget(QLabel("시장 국면:"))
        self.label_market_cond = QLabel("-")
        self.label_market_cond.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.label_market_cond.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        regime_layout.addWidget(self.label_market_cond)
        sb_layout.addLayout(regime_layout)
        
        # Socket Status
        ws_layout = QHBoxLayout()
        ws_layout.addWidget(QLabel("웹소켓:"))
        self.label_ws_status = QLabel("미연결")
        self.label_ws_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.label_ws_status.setStyleSheet("color: #FF5722;")
        ws_layout.addWidget(self.label_ws_status)
        sb_layout.addLayout(ws_layout)
        
        layout.addWidget(status_box)
        
        # Controls
        layout.addSpacing(10)
        
        # Button Style (Dark Gray -> Light Gray Hover)
        btn_style = """
            QPushButton {
                background-color: #666666; 
                color: #ffffff; 
                border: 1px solid #888888; 
                border-radius: 5px; 
                font-weight: bold; 
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #777777;
                border: 1px solid #aaaaaa;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #333333; 
                color: #777777;
                border: 1px solid #444444;
            }
        """
        
        # Custom Start Button Style (Gold for Prosperity)
        start_btn_style = """
            QPushButton {
                background-color: #DAA520; 
                color: #000000; 
                border: 1px solid #B8860B; 
                border-radius: 5px; 
                font-weight: bold; 
                font-size: 17px;
            }
            QPushButton:hover {
                background-color: #FFD700;
                border: 1px solid #DAA520;
            }
            QPushButton:pressed {
                background-color: #B8860B;
            }
            QPushButton:disabled {
                background-color: #333333; 
                color: #777777;
                border: 1px solid #444444;
            }
        """

        self.btn_start = QPushButton("▶ 자동매매 시작")
        self.btn_start.setObjectName("btn_run") 
        self.btn_start.setMinimumHeight(45)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet(start_btn_style)
        self.btn_start.clicked.connect(self.start_trading)
        layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("⏹ 중지")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setStyleSheet(btn_style)
        self.btn_stop.clicked.connect(self.stop_trading)
        layout.addWidget(self.btn_stop)

        # Panic Button
        self.btn_panic = QPushButton("⚠️ 일괄 매도 (Panic)")
        self.btn_panic.setObjectName("btn_panic")
        self.btn_panic.setMinimumHeight(40)
        self.btn_panic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_panic.setStyleSheet("""
            QPushButton { background-color: #aa0000; color: white; font-weight: bold; border: 1px solid #ff0000; }
            QPushButton:hover { background-color: #ff0000; }
            QPushButton:pressed { background-color: #880000; }
        """)
        self.btn_panic.clicked.connect(self.panic_sell_all)
        layout.addWidget(self.btn_panic)
        
        # (Quick Settings moved to bottom)
        self.check_auto_start = QCheckBox("장중 자동매매 자동실행")
        self.check_paper = QCheckBox("모의투자 모드")
        
        # --- 심플 로딩 표시 대신 프로그레스바 추가 ---

        # --- 심플 로딩 표시 대신 프로그레스바 추가 ---
        self.sidebar_progress = QProgressBar()
        self.sidebar_progress.setRange(0, 0) # Indeterminate mode
        self.sidebar_progress.setFixedHeight(5)
        self.sidebar_progress.setTextVisible(False)
        self.sidebar_progress.setStyleSheet("""
            QProgressBar { border: 1px solid #444; border-radius: 2px; background: #222; }
            QProgressBar::chunk { background: #00aaff; border-radius: 2px; }
        """)
        layout.addWidget(self.sidebar_progress)
        # --------------------------

        layout.addStretch()
        
        # [상용 로직] 하단 빠른 설정 (로그인/종료 위 배치)
        lbl_quick = QLabel("빠른 설정")
        lbl_quick.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(lbl_quick)

        # Custom Checkbox Style (상용 앱 통합 스타일)
        check_style = """
            QCheckBox { font-weight: bold; color: #e0e0e0; spacing: 8px; font-size: 13px; margin-bottom: 5px; }
            QCheckBox::indicator { 
                width: 18px; height: 18px; 
                border: 1px solid #ffffff; 
                border-radius: 3px; 
                background-color: #2D2D2D;
            }
            QCheckBox::indicator:checked { 
                background-color: #00aaff; 
                border-color: #00aaff;
            }
            QCheckBox::indicator:unchecked:hover {
                border-color: #00aaff;
            }
        """
        # 모의투자 모드 전용 스타일 (색상 강조)
        mock_check_style = check_style.replace("#e0e0e0", "#00E5FF")

        self.check_auto_start.setStyleSheet(check_style)
        self.check_auto_start.setToolTip("체크 시, 장 시작 시간(09:00)이 되면 자동으로 매매를 시작합니다.")
        self.check_auto_start.stateChanged.connect(
             lambda: self.save_setting('auto_start', self.check_auto_start.isChecked())
        )
        layout.addWidget(self.check_auto_start)

        self.check_paper.setStyleSheet(mock_check_style)
        self.check_paper.setToolTip("체크 시 모의투자로 동작하며, 해제 시 실계좌로 주문이 전송됩니다.\n주의: 변경 시 프로그램을 재시작해야 적용됩니다.")
        self.check_paper.stateChanged.connect(self.save_account_setting)
        layout.addWidget(self.check_paper)
        
        layout.addSpacing(10)
        
        # Exit
        btn_exit = QPushButton("종료")
        btn_exit.setMinimumHeight(35)
        btn_exit.clicked.connect(self.close)
        btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exit.setStyleSheet("""
            QPushButton { 
                background-color: #d32f2f; 
                color: white; 
                border: 1px solid #c62828; 
                border-radius: 5px;
                font-weight: bold; 
                font-size: 16px; 
            }
            QPushButton:hover { 
                background-color: #ff5252; 
                border: 1px solid #ff867c;
            }
            QPushButton:pressed { 
                background-color: #b71c1c; 
            }
        """)
        layout.addWidget(btn_exit)
        
        return sidebar

    def create_dashboard_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # [안실장 픽스] 대시보드 상단 실시간 시장 지수 전광판 추가
        self.lbl_market_info = QLabel("지수 로딩 중... (엔진을 시작하세요)")
        self.lbl_market_info.setStyleSheet("""
            background-color: #333333; 
            color: #00aaff; 
            padding: 8px; 
            font-weight: bold; 
            font-size: 13px;
            border-bottom: 2px solid #00aaff;
            margin-bottom: 5px;
        """)
        self.lbl_market_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_market_info)
        
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 1. Monitoring Tabs (Top)
        self.monitor_tabs = QTabWidget()
        
        # Captured
        tab_captured = QWidget()
        l_captured = QVBoxLayout(tab_captured)
        l_captured.setContentsMargins(0, 0, 0, 0)
        from shared.ui.widgets import StandardStockTable
        self.table_captured = StandardStockTable(["시간", "종목코드", "종목명", "포착가", "현재가", "매수목표가", "상태", "등락률"])
        self.table_captured.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        l_captured.addWidget(self.table_captured)
        self.monitor_tabs.addTab(tab_captured, "📡 포착 종목")
        
        # Holdings
        tab_holdings = QWidget()
        l_holdings = QVBoxLayout(tab_holdings)
        l_holdings.setContentsMargins(5, 5, 5, 5) # 약간의 여백 추가
        from shared.ui.widgets import StandardStockTable
        self.table_holdings = StandardStockTable(["코드", "종목명", "수익률", "평가손익", "잔고수량", "평단가", "현재가"])
        self.table_holdings.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        l_holdings.addWidget(self.table_holdings)

        # [안주인 이동] 계좌 상세 정보 (Settings -> Holdings 하단으로 이동)
        grp_acc = QGroupBox("계좌 상세 정보")
        l_acc = QGridLayout()
        
        # Styles (Redefined for this context)
        value_style = "color: #ffffff; font-size: 14px; font-weight: bold;"
        btn_sub_style = "background-color: #555; color: white; border-radius: 4px; padding: 4px; font-weight: bold;"
        
        # Row 0
        l_acc.addWidget(QLabel("총 매입금액:"), 0, 0); l_acc.addWidget(QLabel("총 평가손익:"), 0, 2)
        self.lbl_total_buy = QLabel("0원"); self.lbl_total_buy.setStyleSheet(value_style)
        self.lbl_total_val = QLabel("0원"); self.lbl_total_val.setStyleSheet(value_style)
        l_acc.addWidget(self.lbl_total_buy, 0, 1); l_acc.addWidget(self.lbl_total_val, 0, 3)
        
        # Row 1
        l_acc.addWidget(QLabel("총 평가금액:"), 1, 0); l_acc.addWidget(QLabel("수익률:"), 1, 2)
        self.lbl_total_asset = QLabel("0원"); self.lbl_total_asset.setStyleSheet(value_style)
        self.lbl_return_rate = QLabel("0.00"); self.lbl_return_rate.setStyleSheet("color: #00aaff; font-size: 14px; font-weight: bold;")
        l_acc.addWidget(self.lbl_total_asset, 1, 1); l_acc.addWidget(self.lbl_return_rate, 1, 3)
        
        # Row 2 (Realized P/L)
        l_acc.addWidget(QLabel("실현 손익:"), 2, 0)
        self.lbl_realized_pl = QLabel("0원"); self.lbl_realized_pl.setStyleSheet(value_style)
        l_acc.addWidget(self.lbl_realized_pl, 2, 1)

        # Refresh Control (Right Side)
        v_refresh = QVBoxLayout()
        v_refresh.setContentsMargins(10, 0, 0, 0)
        btn_refresh_acc = QPushButton("🔄 정보갱신(수동)")
        btn_refresh_acc.clicked.connect(self.update_account_info)
        btn_refresh_acc.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh_acc.setStyleSheet(btn_sub_style)
        v_refresh.addWidget(btn_refresh_acc)
        
        self.check_auto_refresh = QCheckBox("10초 자동갱신")
        self.check_auto_refresh.setStyleSheet("color: #aaa; font-size: 11px;")
        self.check_auto_refresh.stateChanged.connect(self.toggle_auto_refresh)
        self.check_auto_refresh.setChecked(True)
        v_refresh.addWidget(self.check_auto_refresh)
        v_refresh.addStretch()
        
        l_acc.addLayout(v_refresh, 0, 4, 3, 1)
        grp_acc.setLayout(l_acc)
        l_holdings.addWidget(grp_acc)

        self.monitor_tabs.addTab(tab_holdings, "💼 보유 잔고")
        
        # Trades
        tab_trades = QWidget()
        l_trades = QVBoxLayout(tab_trades)
        l_trades.setContentsMargins(0, 0, 0, 0)
        self.table_trades = StandardStockTable(["시간", "종목코드", "종목명", "구분", "체결가", "수량", "비고"])
        self.table_trades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        l_trades.addWidget(self.table_trades)
        self.monitor_tabs.addTab(tab_trades, "📜 거래 내역")
        
        splitter.addWidget(self.monitor_tabs)
        
        # 2. Logs (Bottom)
        log_group = QWidget()
        l_log = QVBoxLayout()
        l_log.setContentsMargins(0, 5, 0, 0)
        l_log.setSpacing(2)
        
        # Log Toolbar
        log_tool_layout = QHBoxLayout()
        log_tool_layout.setContentsMargins(10, 0, 5, 0)
        
        # Custom Title Label to replace GroupBox Title
        log_title = QLabel("실시간 로그")
        log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #dddddd;")
        log_tool_layout.addWidget(log_title)
        
        log_tool_layout.addStretch()
        # [UI Style] Button Style (Light Gray for Visibility)
        btn_style = """
            QPushButton {
                background-color: #666666; 
                color: #ffffff; 
                border: 1px solid #888888; 
                border-radius: 4px; 
                font-weight: bold; 
                font-size: 12px;
                padding: 2px 5px;
            }
            QPushButton:hover {
                background-color: #777777;
                border: 1px solid #aaaaaa;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """

        btn_clear_log = QPushButton("지우기")
        btn_clear_log.setFixedSize(50, 22)
        btn_clear_log.clicked.connect(lambda: self.log_text.clear())
        btn_clear_log.setStyleSheet(btn_style)
        btn_clear_log.setCursor(Qt.CursorShape.PointingHandCursor)
        log_tool_layout.addWidget(btn_clear_log)
        
        self.btn_pause_log = QPushButton("정지")
        self.btn_pause_log.setFixedSize(50, 22)
        self.btn_pause_log.setCheckable(True)
        self.btn_pause_log.clicked.connect(self.toggle_log_pause)
        self.btn_pause_log.setStyleSheet(btn_style)
        self.btn_pause_log.setCursor(Qt.CursorShape.PointingHandCursor)
        log_tool_layout.addWidget(self.btn_pause_log)
        
        l_log.addLayout(log_tool_layout)

        from shared.ui.widgets import StandardLogWindow
        self.log_text = StandardLogWindow()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setStyleSheet("""
            background-color: #0e0e0e; 
            color: #00ff00; 
            border: none;
        """)
        self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        l_log.addWidget(self.log_text)
        log_group.setLayout(l_log)
        splitter.addWidget(log_group)
        
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        
        layout.addWidget(splitter)
        return widget

    def create_settings_tab(self):
        widget = QWidget()
        scroll_layout = QVBoxLayout(widget)
        
        # [UI Style] GroupBox Style (Visible Boundaries)
        widget.setStyleSheet("""
            QGroupBox {
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
                background-color: #2b2b2b;
                color: #00aaff;
            }
        """)
        
        # [UI Style] Define Checkbox Style Early
        check_style = """
            QCheckBox { color: #e0e0e0; spacing: 5px; }
            QCheckBox::indicator { width: 18px; height: 18px; border-radius: 3px; border: 1px solid #555; background-color: #333; }
            QCheckBox::indicator:checked { background-color: #00aaff; border: 1px solid #00aaff; }
            QCheckBox::indicator:unchecked:hover { border: 1px solid #777; }
        """
        
        # [UI Style] Button Style (Light Gray for Visibility)
        btn_style = """
            QPushButton {
                background-color: #666666; 
                color: #ffffff; 
                border: 1px solid #888888; 
                border-radius: 5px; 
                font-weight: bold; 
                font-size: 13px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #777777;
                border: 1px solid #aaaaaa;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """

        # 0. Trading Method Settings
        # 0. Trading Method Settings
        grp_method = QGroupBox("매매 방법 선택")
        l_method = QHBoxLayout()
        
        # [UI Style] Mode Button Style
        mode_btn_style = """
            QPushButton { background-color: #444; color: #eee; border: 1px solid #555; border-radius: 4px; padding: 5px; }
            QPushButton:checked { background-color: #00aaff; color: white; font-weight: bold; border: 1px solid #00aaff; }
            QPushButton:hover { border: 1px solid #888; }
        """

        self.btn_cond_base = QPushButton("조건검색 기반 매매")
        self.btn_cond_base.setCheckable(True)
        self.btn_cond_base.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cond_base.setMinimumHeight(40)
        self.btn_cond_base.setStyleSheet(mode_btn_style)
        self.btn_cond_base.setToolTip("조건검색식에 포착된 종목을 매매합니다.\n아래에서 전략을 선택하면 '검증 후 매수', 선택 안 하면 '즉시 매수'합니다.")
        
        self.btn_cond_stock_radar = QPushButton("관심종목 가속도 공략")
        self.btn_cond_stock_radar.setCheckable(True)
        self.btn_cond_stock_radar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cond_stock_radar.setMinimumHeight(40)
        self.btn_cond_stock_radar.setStyleSheet(mode_btn_style)
        self.btn_cond_stock_radar.setToolTip("장전관심종목으로 등록된 종목들 중\n실시간 수급 가속도가 붙는 종목을 공략합니다.")

        self.btn_acc_swing = QPushButton("매집 맥점 공략 (Swing)")
        self.btn_acc_swing.setCheckable(True)
        self.btn_acc_swing.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_acc_swing.setMinimumHeight(40)
        self.btn_acc_swing.setStyleSheet(mode_btn_style)
        self.btn_acc_swing.setToolTip("매집 분석에서 포착된 4가지 유형\n(돌파, 평단이하, 쌍끌이, 거래량급감)을 실시간 추적합니다.")

        self.btn_vol_breakout = QPushButton("변동성 마디 공략 (ATR)")
        self.btn_vol_breakout.setCheckable(True)
        self.btn_vol_breakout.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol_breakout.setMinimumHeight(40)
        self.btn_vol_breakout.setStyleSheet(mode_btn_style)
        self.btn_vol_breakout.setToolTip("ATR(변동성) 기반의 마디 가격을 계산하여\n정확한 돌파 타점에 진입하는 새로운 매매법입니다.")

        # Grouping for mutual exclusion
        self.bg_method = QButtonGroup(self)
        self.bg_method.addButton(self.btn_cond_base)
        self.bg_method.addButton(self.btn_cond_stock_radar)
        self.bg_method.addButton(self.btn_acc_swing)
        self.bg_method.addButton(self.btn_vol_breakout)
        
        # Connect signals
        self.bg_method.buttonClicked.connect(self.save_trading_mode)

        l_method.addWidget(self.btn_cond_base)
        l_method.addWidget(self.btn_cond_stock_radar)
        l_method.addWidget(self.btn_acc_swing)
        l_method.addWidget(self.btn_vol_breakout)
        
        grp_method.setLayout(l_method)
        scroll_layout.addWidget(grp_method)
        
        # 1. Condition Settings
        grp_cond = QGroupBox("조건검색식 선택")
        l_cond = QHBoxLayout()
        l_cond.addWidget(QLabel("감시 조건식:"))
        self.label_selected_conditions = QLabel("선택된 조건식 없음")
        self.label_selected_conditions.setStyleSheet("font-weight: bold; color: #00aaff;")
        l_cond.addWidget(self.label_selected_conditions, 1)
        btn_sel = QPushButton("조건식 선택")
        btn_sel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sel.setStyleSheet(btn_style)
        btn_sel.clicked.connect(self.open_condition_dialog)
        l_cond.addWidget(btn_sel)

        # [안주인 고도화] 관심종목 검색식 활용 체크박스 추가
        l_cond.addSpacing(15)
        self.check_use_interest_formula = QCheckBox("관심종목 검색식 활용")
        self.check_use_interest_formula.setStyleSheet(check_style)
        self.check_use_interest_formula.setToolTip("체크 시 0번(장전관심), 1번(수동관심) 검색식도\n포착 및 자동매매 대상에 포함합니다.")
        self.check_use_interest_formula.stateChanged.connect(lambda: self.save_setting('use_interest_formula', self.check_use_interest_formula.isChecked()))
        l_cond.addWidget(self.check_use_interest_formula)
        grp_cond.setLayout(l_cond)
        scroll_layout.addWidget(grp_cond)

        # 0.5. Select Strategy Combo
        grp_strategy_sel = QGroupBox("전략 선택")
        l_strategy_sel = QHBoxLayout()
        l_strategy_sel.addWidget(QLabel("선택 전략:"))
        self.combo_strategy = QComboBox()
        self.combo_strategy.setMinimumWidth(200)
        self.combo_strategy.currentTextChanged.connect(self.save_strategy_selection)
        l_strategy_sel.addWidget(self.combo_strategy)
        
        btn_refresh_strategies = QPushButton("🔄 새로고침")
        btn_refresh_strategies.setStyleSheet(btn_style)
        btn_refresh_strategies.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh_strategies.clicked.connect(self.load_strategy_list)
        l_strategy_sel.addWidget(btn_refresh_strategies)
        
        # [UI Guide] 안내 문구 추가
        guide_label = QLabel("   ※ '선택안함' 시 조건검색 포착 즉시 매수 진행")
        guide_label.setStyleSheet("color: #aaaaaa; font-style: italic; font-size: 12px;")
        l_strategy_sel.addWidget(guide_label)
        
        l_strategy_sel.addStretch()
        
        grp_strategy_sel.setLayout(l_strategy_sel)
        scroll_layout.addWidget(grp_strategy_sel)
        
        # 2. Trading Logic Settings (TP/SL) - Split into two boxes
        h_trade_layout = QHBoxLayout()
        
        # TP Group
        grp_tp = QGroupBox("익절 (수익률% / 비중%)")
        l_tp = QVBoxLayout(grp_tp)
        tp_grid = QGridLayout()
        # tp_grid.setVerticalSpacing(8) # 여유 있는 간격
        # tp_grid.addWidget(QLabel("익절 (수익률% / 비중%)"), 0, 0, 1, 4) # 제거: 그룹박스 제목으로 대체
        self.tp_steps_ui = []
        for i in range(3):
            lbl = QLabel(f"{i+1}차")
            chk = QCheckBox()
            chk.setFixedSize(24, 24)
            chk.setStyleSheet(check_style) # Apply Style
            rate = QDoubleSpinBox()
            rate.setRange(0, 1000); rate.setSingleStep(0.1)
            rate.setDecimals(1) # 소수점 1자리 (e.g., 6.0%)
            rate.setFixedWidth(95)
            ratio = QDoubleSpinBox()
            ratio.setRange(0, 100)
            ratio.setDecimals(0) # 정수 (e.g., 50%)
            ratio.setFixedWidth(90)
            
            tp_grid.addWidget(lbl, i+1, 0, Qt.AlignmentFlag.AlignCenter)
            tp_grid.addWidget(chk, i+1, 1, Qt.AlignmentFlag.AlignCenter)
            tp_grid.addWidget(rate, i+1, 2)
            tp_grid.addWidget(ratio, i+1, 3)
            
            step_ui = {'chk': chk, 'rate': rate, 'ratio': ratio}
            self.tp_steps_ui.append(step_ui)
            
            chk.stateChanged.connect(self.save_tp_settings)
            rate.valueChanged.connect(self.save_tp_settings)
            ratio.valueChanged.connect(self.save_tp_settings)
            
        tp_grid.setRowStretch(4, 1) # 하단 공간 확보 (수동 개입 설정 방식)
        l_tp.addLayout(tp_grid)
            
        # SL Group
        grp_sl = QGroupBox("손절 (손실률% / 비중%)")
        l_sl = QVBoxLayout(grp_sl)
        sl_grid = QGridLayout()
        self.sl_steps_ui = []
        for i in range(3):
            lbl = QLabel(f"{i+1}차")
            chk = QCheckBox()
            chk.setFixedSize(24, 24)
            chk.setStyleSheet(check_style) # Apply Style
            rate = QDoubleSpinBox()
            rate.setRange(-100, 0); rate.setSingleStep(0.1) # 0.1단위 정밀 조정
            rate.setDecimals(1) # 소수점 1자리 (e.g., -6.0%)
            rate.setFixedWidth(95)
            ratio = QDoubleSpinBox()
            ratio.setRange(0, 100)
            ratio.setDecimals(0) # 정수 (e.g., 100%)
            ratio.setFixedWidth(90)
            
            sl_grid.addWidget(lbl, i+1, 0, Qt.AlignmentFlag.AlignCenter)
            sl_grid.addWidget(chk, i+1, 1, Qt.AlignmentFlag.AlignCenter)
            sl_grid.addWidget(rate, i+1, 2)
            sl_grid.addWidget(ratio, i+1, 3)
            
            step_ui = {'chk': chk, 'rate': rate, 'ratio': ratio}
            self.sl_steps_ui.append(step_ui)
            
            chk.stateChanged.connect(self.save_sl_settings)
            rate.valueChanged.connect(self.save_sl_settings)
            ratio.valueChanged.connect(self.save_sl_settings)
        
        sl_grid.setRowStretch(4, 1) # 하단 공간 확보 (수동 개입 설정 방식)
        l_sl.addLayout(sl_grid)
        
        # [NEW] TS Group (Trailing Stop)
        grp_ts = QGroupBox("수익 보존 (Trailing Stop)")
        l_ts = QHBoxLayout(grp_ts) # Horizontal to split params and enable stack
        
        # 1. Parameters (Vertical 3 Rows)
        ts_grid = QGridLayout()
        ts_grid.setContentsMargins(0, 0, 0, 0)
        ts_grid.setHorizontalSpacing(3)
        
        # Row 1: Activation
        ts_grid.addWidget(QLabel("작동 시작 수익률:"), 0, 0)
        self.spin_ts_activation = QDoubleSpinBox()
        self.spin_ts_activation.setRange(0, 1000); self.spin_ts_activation.setValue(10.0)
        self.spin_ts_activation.setDecimals(1); self.spin_ts_activation.setSingleStep(0.1)
        self.spin_ts_activation.valueChanged.connect(lambda v: self.save_setting('ts_activation', v))
        self.spin_ts_activation.setMinimumWidth(80)
        ts_grid.addWidget(self.spin_ts_activation, 0, 1)
        
        # Row 2: Drop
        ts_grid.addWidget(QLabel("고점 대비 하락폭:"), 1, 0)
        self.spin_ts_drop = QDoubleSpinBox()
        self.spin_ts_drop.setRange(0, 50); self.spin_ts_drop.setValue(3.0)
        self.spin_ts_drop.setDecimals(1); self.spin_ts_drop.setSingleStep(0.1)
        self.spin_ts_drop.valueChanged.connect(lambda v: self.save_setting('ts_drop', v))
        self.spin_ts_drop.setMinimumWidth(80)
        ts_grid.addWidget(self.spin_ts_drop, 1, 1)
        
        # Row 3: Delay Count
        ts_grid.addWidget(QLabel("지연 확인 횟수:"), 2, 0)
        self.spin_ts_limit = QSpinBox()
        self.spin_ts_limit.setSuffix(" 회"); self.spin_ts_limit.setRange(1, 10); self.spin_ts_limit.setValue(2)
        self.spin_ts_limit.setToolTip("일시적 급락에 털리지 않도록, 연속 n회 이상 조건을 만족할 때만 매도합니다.")
        self.spin_ts_limit.valueChanged.connect(lambda v: self.save_setting('ts_limit_count', v))
        self.spin_ts_limit.setMinimumWidth(80)
        ts_grid.addWidget(self.spin_ts_limit, 2, 1)
        
        l_ts.addLayout(ts_grid, 1)
        
        # 2. Enable Toggle Stack (Right side)
        v_enable = QVBoxLayout()
        v_enable.setContentsMargins(5, 0, 0, 0)
        v_enable.setSpacing(2)
        
        self.chk_ts_enabled = QCheckBox() # No text for vertical alignment
        self.chk_ts_enabled.setFixedSize(24, 24)
        self.chk_ts_enabled.setStyleSheet(check_style)
        self.chk_ts_enabled.toggled.connect(lambda v: self.save_setting('ts_enabled', v))
        
        lbl_ginung = QLabel("TS"); lbl_ginung.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        lbl_hwal = QLabel("활성화"); lbl_hwal.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        
        v_enable.addStretch()
        v_enable.addWidget(self.chk_ts_enabled, 0, Qt.AlignmentFlag.AlignCenter)
        v_enable.addWidget(lbl_ginung, 0, Qt.AlignmentFlag.AlignCenter)
        v_enable.addWidget(lbl_hwal, 0, Qt.AlignmentFlag.AlignCenter)
        v_enable.addStretch()
        
        l_ts.addLayout(v_enable)

        # 3. Breakeven Toggle Stack (Far Right)
        v_be = QVBoxLayout()
        v_be.setContentsMargins(10, 0, 0, 0)
        v_be.setSpacing(2)
        
        self.chk_be_enabled = QCheckBox()
        self.chk_be_enabled.setFixedSize(24, 24)
        self.chk_be_enabled.setStyleSheet(check_style)
        self.chk_be_enabled.setToolTip("익절 1차 달성 후 매수가 부근(+0.25%)으로 가격 회귀 시 즉시 본전 청산합니다.")
        self.chk_be_enabled.toggled.connect(lambda v: self.save_setting('be_enabled', v))
        
        lbl_bon = QLabel("본전"); lbl_bon.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        lbl_sasu = QLabel("사수"); lbl_sasu.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        
        v_be.addStretch()
        v_be.addWidget(self.chk_be_enabled, 0, Qt.AlignmentFlag.AlignCenter)
        v_be.addWidget(lbl_bon, 0, Qt.AlignmentFlag.AlignCenter)
        v_be.addWidget(lbl_sasu, 0, Qt.AlignmentFlag.AlignCenter)
        v_be.addStretch()
        
        l_ts.addLayout(v_be)
        
        # [레이아웃 밸선 재정비] 대표님 지정 황금비 3.5 : 3.5 : 3
        h_trade_layout.setSpacing(10) # 그룹 박스 간의 간격
        h_trade_layout.addWidget(grp_tp, 35)
        h_trade_layout.addWidget(grp_sl, 35)
        h_trade_layout.addWidget(grp_ts, 30)
        
        scroll_layout.addLayout(h_trade_layout)
        
        # Combined Buy & Manual & LW Settings (3 Columns)
        h_buy_manual_lw = QHBoxLayout()
        
        # 3. Buy Settings
        grp_buy = QGroupBox("매수 설정")
        l_buy = QGridLayout()
        # l_buy.setVerticalSpacing(5)  # 시스템 기본 간격 사용
        
        l_buy.addWidget(QLabel("최대 보유 종목:"), 0, 0)
        self.spin_max_stock = QDoubleSpinBox()
        self.spin_max_stock.setDecimals(0)
        self.spin_max_stock.setRange(1, 50)
        self.spin_max_stock.setValue(10)
        self.spin_max_stock.setToolTip("동시에 보유할 수 있는 최대 종목 수입니다.\n보유 종목이 이 수에 도달하면 추가 매수를 하지 않습니다.")
        self.spin_max_stock.valueChanged.connect(lambda v: self.save_setting('max_stock_count', int(v)))
        l_buy.addWidget(self.spin_max_stock, 0, 1, 1, 2) # Span 2 columns
        
        # Radio Button Style for Visibility
        radio_style = """
            QRadioButton { color: #e0e0e0; font-weight: bold; spacing: 5px; }
            QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 2px solid #999; background-color: #333; }
            QRadioButton::indicator:checked { background-color: #00aaff; border: 2px solid #00aaff; }
            QRadioButton::indicator:unchecked:hover { border: 2px solid #bbb; }
        """
        
        l_buy.addWidget(QLabel("매수 기준:"), 1, 0)
        self.radio_percent = QRadioButton("비중(%)")
        self.radio_amount = QRadioButton("금액(원)")
        self.radio_percent.setStyleSheet(radio_style)
        self.radio_amount.setStyleSheet(radio_style)
        self.radio_percent.toggled.connect(self.toggle_buy_method)
        self.radio_amount.toggled.connect(self.toggle_buy_method)
        
        l_buy.addWidget(self.radio_percent, 1, 1)
        l_buy.addWidget(self.radio_amount, 1, 2)
        
        l_buy.addWidget(QLabel("설정값:"), 2, 0)
        self.spin_buy_ratio = QDoubleSpinBox()
        self.spin_buy_ratio.setRange(0, 100)
        self.spin_buy_ratio.setToolTip("현재 예수금 대비 매수할 비중(%)입니다.\n예: 10% 설정 시 예수금이 1,000만원이면 100만원 어치 매수합니다.")
        self.spin_buy_ratio.valueChanged.connect(lambda v: self.save_setting('buy_ratio', v))
        
        self.spin_buy_amount = QSpinBox()
        self.spin_buy_amount.setSuffix("원"); self.spin_buy_amount.setRange(10000, 1000000000); self.spin_buy_amount.setSingleStep(10000)
        self.spin_buy_amount.setToolTip("종목당 고정 매수 금액입니다.\n설정된 금액만큼 매수 주문을 넣습니다.")
        self.spin_buy_amount.valueChanged.connect(lambda v: self.save_setting('buy_amount', v))
        
        l_buy.addWidget(self.spin_buy_ratio, 2, 1)
        l_buy.addWidget(self.spin_buy_amount, 2, 2)
        
        l_buy.setRowStretch(3, 1) # 하단 공간 확보 (수동 개입 설정 방식)
        
        grp_buy.setLayout(l_buy)
        h_buy_manual_lw.addWidget(grp_buy, 1)
        
        # 4. Manual Control Settings
        grp_manual = QGroupBox("수동 개입 설정")
        l_manual = QGridLayout() # Use Grid for alignment
        
        self.check_manual_buy = QCheckBox("수동 매수 허용")
        self.check_manual_buy.setStyleSheet(check_style)
        self.check_manual_buy.setToolTip("체크 시, 매수 신호가 발생했을 때 즉시 주문하지 않고\n확인 팝업을 띄웁니다.")
        self.check_manual_buy.stateChanged.connect(lambda: self.save_setting('manual_buy', self.check_manual_buy.isChecked()))
        
        # User requested shifting: Manual Buy -> Row 1, Manual Sell -> Row 2
        # This compensates for visual staggering where Row 1 appeared aligned with Row 0
        l_manual.addWidget(self.check_manual_buy, 1, 0, Qt.AlignmentFlag.AlignLeft)
        
        self.check_manual_sell = QCheckBox("수동 매도 허용")
        self.check_manual_sell.setStyleSheet(check_style)
        self.check_manual_sell.setToolTip("체크 시, 매도 신호가 발생했을 때 즉시 주문하지 않고\n확인 팝업을 띄웁니다.")
        self.check_manual_sell.stateChanged.connect(lambda: self.save_setting('manual_sell', self.check_manual_sell.isChecked()))
        l_manual.addWidget(self.check_manual_sell, 2, 0, Qt.AlignmentFlag.AlignLeft)
        
        # Spacer to push items up
        l_manual.setRowStretch(3, 1)
        
        grp_manual.setLayout(l_manual)
        h_buy_manual_lw.addWidget(grp_manual, 1)
        
        # 5. Larry Williams Strategy Settings (Moved Here)
        # 5. 자동 매매 모드 전환 설정 (3단계 하이브리드 파이프라인)
        grp_auto_switch = QGroupBox("자동 매매 모드 전환 설정")
        l_auto = QGridLayout()
        
        # 10시 전환 (가속도 공략)
        self.check_two_track = QCheckBox("10시 이후 '가속도 공략'으로 자동 전환")
        self.check_two_track.setStyleSheet(check_style)
        self.check_two_track.setToolTip("체크 시 오전 10시가 경과하면 현재 매매법을 중단하고\n실시간 수급이 붙는 '가속도 공략' 모드로 자동 전환합니다.")
        self.check_two_track.stateChanged.connect(lambda: self.save_setting('use_two_track', self.check_two_track.isChecked()))
        l_auto.addWidget(self.check_two_track, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        
        # 15시 전환 (매집 맥점 공략)
        self.check_15h_switch = QCheckBox("15시 이후 '매집 맥점 공략'으로 자동 전환")
        self.check_15h_switch.setStyleSheet(check_style)
        self.check_15h_switch.setToolTip("체크 시 오후 3시(15:00)가 경과하면 현재 매매법을 중단하고\n종가 배팅 및 스윙에 유리한 '매집 맥점 공략' 모드로 자동 전환합니다.")
        self.check_15h_switch.stateChanged.connect(lambda: self.save_setting('use_15h_switch', self.check_15h_switch.isChecked()))
        l_auto.addWidget(self.check_15h_switch, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        # ATR 기반 리스크 관리 (전역 설정)
        self.check_use_atr_risk = QCheckBox("모든 매매에 ATR 기반 리스크 관리 적용")
        self.check_use_atr_risk.setStyleSheet(check_style)
        self.check_use_atr_risk.setToolTip("체크 시 모든 매매(조건검색, 가속도 등)에서 고정 % 손절 대신\nATR(변동성) 기반의 동적 손절/익절 로직을 사용합니다.")
        self.check_use_atr_risk.stateChanged.connect(lambda: self.save_setting('use_atr_risk_management', self.check_use_atr_risk.isChecked()))
        l_auto.addWidget(self.check_use_atr_risk, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)

        # Hidden but retained for compatibility
        self.spin_gap_minute = QSpinBox(); self.spin_gap_minute.hide()
        self.spin_lw_lookback = QSpinBox(); self.spin_lw_lookback.hide()
        self.spin_lw_k = QDoubleSpinBox(); self.spin_lw_k.hide()
        
        grp_auto_switch.setLayout(l_auto)
        h_buy_manual_lw.addWidget(grp_auto_switch, 1)
        
        scroll_layout.addLayout(h_buy_manual_lw)
        
        scroll_layout.addSpacing(20)

        # Placeholder for Future Strategy
        grp_future = QGroupBox("추가 전략 설정 (준비 중)")
        grp_future.setMinimumHeight(70) # 높이 대폭 축소
        l_future = QVBoxLayout()
        l_future.addWidget(QLabel("이 공간은 향후 추가될 전략 설정을 위해 비워둔 공간입니다."))
        grp_future.setLayout(l_future)
        scroll_layout.addWidget(grp_future)
        
        scroll_layout.addSpacing(20)
        
        scroll_layout.addSpacing(20)
        
        # 6. Telegram Settings (Moved up from index 5)
        
        # 6. Telegram Settings
        grp_tel = QGroupBox("텔레그램 설정")
        l_tel = QHBoxLayout()
        btn_test_tel = QPushButton("🔔 텔레그램 테스트 발송")
        btn_test_tel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_tel.setStyleSheet(btn_style)
        btn_test_tel.clicked.connect(self.send_telegram_test)
        l_tel.addWidget(btn_test_tel)
        
        btn_tel_help = QPushButton("❓ 도움말")
        btn_tel_help.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_tel_help.setMaximumWidth(80)
        btn_tel_help.setStyleSheet(btn_style)
        btn_tel_help.clicked.connect(self.open_telegram_help)
        l_tel.addWidget(btn_tel_help)
        
        l_tel.addStretch()
        grp_tel.setLayout(l_tel)
        scroll_layout.addWidget(grp_tel)
        
        scroll_layout.addStretch()
        return widget

    # setup_strategy_tab, on_convert_formula, get_strategies_dir, save_strategy,

    # load_strategy_popup, import_strategy_popup, load_strategy_file,

    # reset_strategy_input, delete_strategy_popup, validate_converted_code,

    # show_formula_help

    # → Moved to ui/strategy_mixin.py (StrategyMixin)



    # --- Core Logic & Events ---

    def handle_engine_event(self, type, data):
        # [안실장 픽스] Thread-safe event emission with None-safe Guard
        if data is None and type != 'log': # Log data could be None if just a separator, but usually not
            return

        if type == 'confirm':
            self.sig_confirm.emit(data)
        elif type == 'captured':
            self.sig_captured.emit(data)
        elif type == 'filter_update':
            self.sig_filter.emit(data)
        elif type == 'trade':
            self.sig_trade.emit(data)
        elif type == 'settings_updated':
            self.sig_settings.emit(data)
        elif type == 'market_update':
            self.sig_market.emit(data) # [안실장 픽스] 지수 신호 분배
        
        # Log event is handled by LogSignal (stdout redirection)
        if type == 'log':
            pass

    def handle_trade_and_refresh(self, data):
        """매매 성공 시 내역 추가 및 대시보드 강제 갱신"""
        self.add_trade_row(data)
        # 매매 직후 0.5초 뒤 계좌 정보 갱신 (서버 반영 시간 고려)
        QTimer.singleShot(500, self.update_account_info)

    def update_market_dashboard(self, data):
        """시장 지수 및 엔진 상태를 대시보드/사이드바에 실시간 표시"""
        if not data or not isinstance(data, dict):
            return

        regime = data.get('regime', '-')
        k_val = data.get('kospi', '-')
        q_val = data.get('kosdaq', '-')
        mult = data.get('multiplier', 1.0)
        
        # 1. 사이드바 업데이트
        if hasattr(self, 'label_market_cond'):
            self.label_market_cond.setText(regime)
            if regime in ['폭락장', 'CRASH', '약세장', 'BEAR']:
                self.label_market_cond.setStyleSheet("color: #ff3333; font-weight: bold;")
            elif regime in ['강세장', 'BULL']:
                self.label_market_cond.setStyleSheet("color: #00ff00; font-weight: bold;")
            else:
                self.label_market_cond.setStyleSheet("color: #4CAF50; font-weight: bold;")

        # 2. 대시보드 전용 지수 라벨이 있다면 업데이트 (없으면 스킵)
        if hasattr(self, 'lbl_market_info'):
            info_str = f"KOSPI: {k_val} | KOSDAQ: {q_val} | 매수배율: {mult}x"
            self.lbl_market_info.setText(info_str)
            
        # [안실장 픽스] 상태바에도 시장 국면 표시
        if hasattr(self, 'statusBar') and self.statusBar:
            # StandardStatusBar는 showMessage 대신 set_message 또는 showMessage(QMainWindow 기본) 가능성 있음
            # 기존 코드(1742행)가 set_message를 썼으므로 호환성 체크 후 showMessage 호출
            try:
                self.statusBar.showMessage(f"시장환경 분석됨: {regime} (배율:{mult}x)", 5000)
            except:
                if hasattr(self.statusBar, 'set_message'):
                    self.statusBar.set_message(f"시장분류: {regime}", color="#00ff00")

    def update_settings_ui(self, data):
        """엔진단에서 변경된 설정을 UI 탭 (Radio/Button)에 즉각 시각 반영"""
        if not data or not isinstance(data, dict):
            return
            
        mode = data.get('mode')
        if mode == 'cond_stock_radar':
            self.btn_cond_stock_radar.setChecked(True)
            if hasattr(self, 'check_two_track'):
                self.check_two_track.setChecked(False)
                self.check_two_track.setEnabled(False)

    def add_captured_stock(self, data):
        """포착된 종목을 테이블에 추가"""
        if not data or not isinstance(data, dict):
            return
            
        raw_code = str(data.get('code', '')).strip()
        code = raw_code.replace('A', '') # Clean Code
        if not code: return

        # Name Extraction & Safety (Apply Master Map)
        raw_name = data.get('name', 'Unknown')
        if isinstance(raw_name, dict):
             name = str(raw_name.get('name', str(raw_name)))
        else:
             name = str(raw_name)
             
        # [NEW] Master Map lookup if name is unknown or numeric code
        if name == 'Unknown' or name == code:
             name = self.stock_name_map.get(code, name)

        time_val = data.get('time')
        if not time_val:
            time_str = datetime.now().strftime("%m/%d %H:%M:%S")
        else:
            time_str = str(time_val)
            # 날짜 정보(/)가 없는 경우 처리
            if '/' not in time_str:
                if '-' in time_str: # YYYY-MM-DD HH:MM:SS 대응
                    try:
                        dt_obj = datetime.strptime(time_str[:19], "%Y-%m-%d %H:%M:%S")
                        time_str = dt_obj.strftime("%m/%d %H:%M:%S")
                    except:
                        # 변환 실패 시 하이픈을 슬래시로 변경 시도
                        time_str = time_str.replace('-', '/')
                else: # HH:MM:SS 만 있는 경우
                    today_md = datetime.now().strftime("%m/%d")
                    time_str = f"{today_md} {time_str}"
        price = str(data.get('price', '0'))
        ratio = str(data.get('ratio', '0.00'))
        target_val = str(data.get('target', '-'))

        # [안실장 픽스] 데이터 클린징 및 천단위 콤마 포맷팅
        price = data.get('price', '0')
        try:
            p_clean = str(price).replace(',', '').strip()
            if p_clean and p_clean.replace('.', '').replace('-', '').isdigit():
                price = f"{int(float(p_clean)):,}"
            elif p_clean in ["조회중", "0", "None", ""]:
                price = "---"
        except:
            price = "---"
            
        target_val = data.get('target', '-')
        try:
            t_clean = str(target_val).replace(',', '').strip()
            if t_clean and t_clean.replace('.', '').isdigit():
                target_val = f"{int(float(t_clean)):,}"
            elif t_clean in ["조회중", "0", "None", "", "-"]:
                target_val = "-"
        except:
            target_val = "-"

        # 중복 확인 (Code is now at index 1)
        clean_target = code.replace('A', '')
        for row in range(self.table_captured.rowCount()):
            item = self.table_captured.item(row, 1) # Code index 1 after swap
            if item:
                cell_code = item.text().strip().replace('A', '')
                if cell_code == clean_target:
                    return # 이미 존재

        row = self.table_captured.rowCount()
        self.table_captured.insertRow(row)
        
        # [안실장 픽스] 종목명 5자 제한 로직
        display_name = name[:5] if len(name) > 5 else name
        name_item = QTableWidgetItem(display_name)
        name_item.setToolTip(name)

        # ["시간", "종목코드", "종목명", "포착가", "현재가", "매수목표가", "상태", "등락률"]
        status_text = str(data.get('status', '대기'))
        self.table_captured.setItem(row, 0, QTableWidgetItem(time_str))
        self.table_captured.setItem(row, 1, QTableWidgetItem(code)) # 종목코드
        self.table_captured.setItem(row, 2, name_item) # 종목명 (축약)
        self.table_captured.setItem(row, 3, QTableWidgetItem(price)) # 포착가 (고정)
        self.table_captured.setItem(row, 4, QTableWidgetItem(price)) # 현재가 (실시간 갱신용)
        self.table_captured.setItem(row, 5, QTableWidgetItem(target_val)) # 매수목표가
        self.table_captured.setItem(row, 6, QTableWidgetItem(status_text)) # 상태
        self.table_captured.setItem(row, 7, QTableWidgetItem(ratio)) # 등락률
        
        # Alignment (Optimized for readability)
        for col in range(8):
            it = self.table_captured.item(row, col)
            if it: 
                # [안실장 픽스] 데이터 성격에 따른 정렬 최적화
                if col in [1, 2]: # 종목코드, 종목명
                     it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                elif col in [3, 4, 5, 7]: # 포착가, 현재가, 목표가, 등락률 (숫자/금액)
                     it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else: # 시간, 상태 (중앙)
                     it.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)

        # Force immediate visual update
        self.table_captured.viewport().update()
        self.table_captured.scrollToBottom()

    def update_filter_status(self, data):
        """Warm-up 또는 실시간 시세 수신 시 종목 정보 업데이트"""
        if not data or not isinstance(data, dict):
            return
            
        raw_code = str(data.get('code', '')).strip()
        code = raw_code.replace('A', '') # Clean Code
        if not code: return

        found = False
        clean_target = code
        for row in range(self.table_captured.rowCount()):
            item = self.table_captured.item(row, 1) # [Swap] Code index 1
            if item:
                cell_code = item.text().strip().replace('A', '')
                if cell_code == clean_target:
                    # 1. Name Update (Enrichment)
                    new_name = data.get('name')
                    # Fallback to Master Map if unknown
                    if not new_name or str(new_name) == 'Unknown' or str(new_name) == code:
                         new_name = self.stock_name_map.get(code, new_name)

                    if new_name and str(new_name) != 'Unknown':
                        # [안실장 픽스] 종목명 5자 제한 로직
                        display_name = str(new_name)[:5] if len(str(new_name)) > 5 else str(new_name)
                        n_item = QTableWidgetItem(display_name)
                        n_item.setToolTip(str(new_name))
                        
                        n_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        self.table_captured.setItem(row, 2, n_item) # [Swap] Name index 2

                    # 2. Price Update
                    price_str = str(data.get('price', ''))
                    if price_str and price_str != 'None':
                        try:
                            if price_str.replace(',', '').replace('.', '').isdigit() or (price_str.startswith('-') and price_str[1:].isdigit()):
                                p_val = int(float(price_str.replace(',', '')))
                                p_item = QTableWidgetItem(f"{p_val:,}")
                            else:
                                p_item = QTableWidgetItem(price_str) # '---' or '조회중' 그대로 표시
                            
                            p_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                            # [안실장 픽스] 포착가(3번)는 유지하고 현재가(4번)만 실시간 갱신
                            self.table_captured.setItem(row, 4, p_item)
                        except: pass

                    # 3. Rate Update (Support both 'rate' and 'ratio' keys)
                    rate = data.get('rate') or data.get('ratio')
                    if rate is not None:
                        try:
                            # Handle both string (e.g. "1.5%") and float (e.g. 1.5)
                            r_str = str(rate).replace('%', '').strip()
                            r_val = float(r_str)
                            r_item = QTableWidgetItem(f"{r_val:+.2f}")
                            r_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                            if r_val > 0: r_item.setForeground(QColor("#ff3333"))
                            elif r_val < 0: r_item.setForeground(QColor("#00aaff"))
                            self.table_captured.setItem(row, 7, r_item) # 등락률은 7번 인덱스
                        except: pass

                    # 4. Target Price Update
                    target = data.get('target')
                    if target is not None:
                        try:
                            t_clean = str(target).replace(',', '').strip()
                            if t_clean and t_clean.replace('.', '').isdigit():
                                t_str = f"{int(float(t_clean)):,}"
                            else:
                                t_str = str(target)
                        except:
                            t_str = str(target)
                            
                        if t_str in ["조회중", "0", "None"]:
                            t_str = "-"
                        t_item = QTableWidgetItem(t_str)
                        t_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        self.table_captured.setItem(row, 5, t_item) # 목표가는 5번 인덱스

                    # 5. Status Update [CRITICAL FIX]
                    status = data.get('status')
                    if status:
                        s_item = QTableWidgetItem(str(status))
                        s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
                        
                        # [안실장 픽스] 상태별 컬러 강조
                        if status == "매수완료":
                            s_item.setForeground(QColor("#4CAF50")) # Green
                            s_item.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
                        elif "주문" in status or "승인" in status:
                            s_item.setForeground(QColor("#FFD700")) # Gold
                        elif "거절" in status or "취소" in status or "에러" in status:
                            s_item.setForeground(QColor("#FF5252")) # Red
                        
                        self.table_captured.setItem(row, 6, s_item) # 상태는 6번 인덱스

                    found = True
                    break
        return found

    # --- HTS Interlock ---
    
    def init_hts_interlock(self):
        """HTS 연동 기능 초기화 (더블 클릭 이벤트 바인딩)"""
        if hasattr(self, 'table_captured'):
            self.table_captured.itemDoubleClicked.connect(self.on_captured_double_clicked)
        if hasattr(self, 'table_holdings'):
             self.table_holdings.itemDoubleClicked.connect(self.on_holdings_double_clicked)
        if hasattr(self, 'table_trades'):
             self.table_trades.itemDoubleClicked.connect(self.on_trades_double_clicked)

    def on_captured_double_clicked(self, item):
        """포착종목 테이블 더블 클릭 시 HTS 차트 연동"""
        row = item.row()
        # 종목코드는 1번 컬럼 (Clean Code)
        code_item = self.table_captured.item(row, 1)
        if code_item:
            from hts_connector import send_to_hts
            send_to_hts(code_item.text())

    def on_holdings_double_clicked(self, item):
        """보유종목 테이블 더블 클릭 시 HTS 차트 연동"""
        row = item.row()
        # 보유종목의 종목코드는 0번 컬럼
        code_item = self.table_holdings.item(row, 0)
        if code_item:
            from hts_connector import send_to_hts
            send_to_hts(code_item.text())

    def on_trades_double_clicked(self, item):
        """거래내역 테이블 더블 클릭 시 HTS 차트 연동"""
        row = item.row()
        # 거래내역의 종목코드는 1번 컬럼
        code_item = self.table_trades.item(row, 1)
        if code_item:
            from hts_connector import send_to_hts
            send_to_hts(code_item.text())


    def check_market_signal(self):
        """Lead_Sig로부터 전달된 시장 신호를 확인하고 반영"""
        try:
            if not hasattr(self, 'signal_manager'):
                return
                
            signal = self.signal_manager.load_signal()
            if not signal:
                return

            msg = signal.get("message", "")
            regime = signal.get("regime", "NEUTRAL")
            
            # 상태바에 신호 표시
            color = "#00FF7F" if regime == "BULL" else "#FF5252" if regime == "BEAR" else "#aaaaaa"
            if hasattr(self, 'statusBar') and hasattr(self.statusBar, 'set_message'):
                self.statusBar.set_message(f"[시장신호] {msg}", color=color)
            
            # 매매 배중Multiplier 확인 (향후 전략 엔진에서 참조 가능하도록 준비)
            multiplier = self.signal_manager.get_trading_multiplier()
            if multiplier != 1.0:
                self.append_log(f"⚠️ 시장 상황 감지에 따른 매매 강도 조정: {multiplier}배", color="#FFD700")

        except Exception as e:
            print(f"Error checking market signal: {e}")

    def append_log(self, text, color=None):
        """StandardLogWindow를 통한 공통 로깅 위임"""
        if hasattr(self, 'log_text') and hasattr(self.log_text, 'append_log'):
            self.log_text.append_log(text)
        else:
            # Fallback if widget is not yet initialized or replaced
            self.log_text.append(str(text))

    def toggle_log_pause(self):
        """로그 일시 정지 토글"""
        is_paused = self.btn_pause_log.isChecked()
        if is_paused:
            self.btn_pause_log.setText("재개")
            self.btn_pause_log.setStyleSheet("background-color: #aa6600; color: white; border: 1px solid #ffaa00; border-radius: 4px; font-weight: bold; font-size: 11px;")
        else:
            self.btn_pause_log.setText("정지")
            # Restore original style
            btn_style = """
                QPushButton {
                    background-color: #666666; color: #ffffff; border: 1px solid #888888; border-radius: 4px; font-weight: bold; font-size: 12px;
                }
            """
            self.btn_pause_log.setStyleSheet(btn_style)
            
        if hasattr(self, 'log_text') and hasattr(self.log_text, 'set_paused'):
            self.log_text.set_paused(is_paused)

    def load_strategy_list(self,):
        """콤보박스에 전략 목록 로딩"""
        if not hasattr(self, 'combo_strategy'):
            return
        
        current_sel = self.combo_strategy.currentText()
        if not current_sel:
            current_sel = get_setting('active_strategy', "선택안함")
            
        self.combo_strategy.blockSignals(True)
        self.combo_strategy.clear()
        self.combo_strategy.addItem("선택안함")
        
        s_dir = self.get_strategies_dir()
        if os.path.exists(s_dir):
            files = [f for f in os.listdir(s_dir) if f.endswith('.json')]
            files.sort()
            for f in files:
                self.combo_strategy.addItem(f)
                
        idx = self.combo_strategy.findText(current_sel)
        if idx >= 0:
            self.combo_strategy.setCurrentIndex(idx)
        else:
            self.combo_strategy.setCurrentIndex(0)
        self.combo_strategy.blockSignals(False)
            
    def save_strategy_selection(self, text):
        if text and text != "선택안함":
            # [안실장 픽스] 무조건 확장자를 포함하도록 강제
            if not text.endswith('.json'):
                text += '.json'
            self.save_setting('active_strategy', text)
            # 전략 선택이 바뀌면 전략 필터 사용 여부(use_strategy_filter)도 갱신되어야 함
            if hasattr(self, 'save_trading_mode'):
                self.save_trading_mode()


    @pyqtSlot(dict)
    def add_trade_row(self, data):
        """거래 내역 테이블에 행 추가"""
        # print(f"DEBUG UI: add_trade_row called with {data}")
        if not isinstance(data, dict):
            print(f"DEBUG UI: add_trade_row received invalid data type: {type(data)}")
            return

        try:
            row = self.table_trades.rowCount()
            self.table_trades.insertRow(row)
        
            # ["시간", "종목코드", "종목명", "구분", "체결가", "수량", "비고"]
            time_str = str(data.get('time', ''))
            code = str(data.get('code', '')).replace('A', '')
            name = str(data.get('name', ''))
            # Map stock name if unknown or numeric code
            if not name or name == 'Unknown' or name == code:
                 name = self.stock_name_map.get(code, name)

            type_str = str(data.get('type', ''))
            
            # Price Formatting (Standardized: Thousand-separator, No decimals)
            price_val = data.get('price', '')
            try:
                # Remove common non-numeric chars and format
                clean_price = str(price_val).replace(',', '').strip()
                if clean_price and clean_price.replace('.', '').replace('-', '').isdigit():
                    price = f"{int(float(clean_price)):,}"
                else:
                    price = str(price_val)
            except:
                price = str(price_val)
                
            qty = str(data.get('qty', ''))
            msg = str(data.get('msg', ''))
            
            # Items
            i_time = QTableWidgetItem(time_str)
            i_code = QTableWidgetItem(code)
            i_name = QTableWidgetItem(name)
            i_type = QTableWidgetItem(type_str)
            i_price = QTableWidgetItem(price)
            i_qty = QTableWidgetItem(qty)
            i_msg = QTableWidgetItem(msg)
            
            # Color Coding
            if any(w in type_str.lower() for w in ["매수", "buy"]):
                color = QColor("#ff3333") # Red for Buy
                i_type.setForeground(color)
            elif any(w in type_str.lower() for w in ["매도", "sell"]):
                color = QColor("#00aaff") # Blue for Sell
                i_type.setForeground(color)
                
            # Alignment (Optimized for readability)
            i_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            i_code.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            i_name.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            i_type.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            i_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            i_qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            i_msg.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                
            self.table_trades.setItem(row, 0, i_time)
            self.table_trades.setItem(row, 1, i_code)
            self.table_trades.setItem(row, 2, i_name)
            self.table_trades.setItem(row, 3, i_type)
            self.table_trades.setItem(row, 4, i_price)
            self.table_trades.setItem(row, 5, i_qty)
            self.table_trades.setItem(row, 6, i_msg)
            
            # [안실장] 시간순 정렬이므로 아래로 자동 스크롤
            self.table_trades.scrollToBottom()
            # print(f"DEBUG UI: add_trade_row finished for row {row}")
        except Exception as e:
            print(f"DEBUG UI: add_trade_row ERROR: {e}")
            import traceback
            traceback.print_exc()


    # load_all_settings, save_trading_mode, save_setting, save_tp_settings,

    # save_sl_settings, toggle_buy_method, save_account_setting,

    # load_conditions, open_condition_dialog, restart_engine_search,

    # update_conditions_label_with_names

    # → Moved to ui/settings_mixin.py (SettingsMixin)



    # --- Trading Logic Wrappers ---
    @qasync.asyncSlot()
    async def start_trading(self, initial_token=None):
        # [안실장] 중복 실행 방지 가드
        if self._is_starting:
            self.append_log("⚠️ 이미 매매 시작 프로세스가 진행 중입니다.")
            return
            
        if self.chat_cmd.engine and self.chat_cmd.engine.is_running:
            self.append_log("ℹ️ 엔진이 이미 실행 중입니다.")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.label_status.setText("가동중")
            return

        # [안실장 픽스] 매매 시작 시 검증 탭(Verification)의 코드가 실제 매매 설정으로 유입되지 않도록 격리합니다.
        # 매매 로직은 오직 [설정] 탭에서 선택된 전략 파일을 기준으로 구동됩니다.
        # (기존의 active_strategy_code 업데이트 로직 삭제)
        
        self._is_starting = True
        self.btn_start.setEnabled(False)
        self.append_log("자동매매 시작 요청...")
        try:
            # Use provided token (Auto-Start) or None (Manual Start -> Force New Token)
            token = initial_token

            if await self.chat_cmd.start(token=token):
                self.label_status.setText("가동중")
                self.label_status.setStyleSheet("color: #00ff00; font-weight: bold;")
                self.btn_stop.setEnabled(True)
                self.append_log("✅ 자동매매 시작됨")
                
                # Immediate Account Info Update
                if hasattr(self.chat_cmd, 'engine') and self.chat_cmd.engine.token:
                    self.broker.set_token(self.chat_cmd.engine.token)
                    self.update_account_info()
            else:
                self.btn_start.setEnabled(True)
        except Exception as e:
            self.append_log(f"Err: {e}")
            self.btn_start.setEnabled(True)
        finally:
            self._is_starting = False

    @qasync.asyncSlot()
    async def stop_trading(self):
        self.btn_stop.setEnabled(False)
        try:
            if await self.chat_cmd.stop(set_auto_start_false=True):
                self.label_status.setText("중지됨")
                self.label_status.setStyleSheet("color: #ff0000; font-weight: bold;")
                self.btn_start.setEnabled(True)
                self.append_log("🛑 자동매매 중지됨")
            else:
                self.btn_stop.setEnabled(True)
        except Exception as e:
            self.append_log(f"Err: {e}")
            # [안실장 버그픽스] 예외 발생 시에도 UI 버튼 상태 복원 (중지완료 처리)
            self.btn_start.setEnabled(True)
            self.label_status.setText("중지됨(오류)")
            self.label_status.setStyleSheet("color: #ff8800; font-weight: bold;")

    def periodic_update(self):
        """1초 주기 UI 및 시스템 체크"""
        # 1. 시계 업데이트 (글로벌 datetime 클래스 사용)
        try:
            now = datetime.now()
        except TypeError:
            # datetime이 모듈로 취급되는 경우 대비
            import datetime as dt_mod
            now = dt_mod.datetime.now()
        
        # 2. 시장 신호 체크 (30초 주기)
        import time as time_module
        curr_time = time_module.time()
        if curr_time - getattr(self, 'last_signal_check', 0) >= 30:
            self.last_signal_check = curr_time
            self.check_market_signal()
            
        # [안실장 픽스] AttributeError/TypeError 방지를 위한 안전한 UI 갱신 헬퍼
        def safe_set_style(label, text, style):
            try:
                if label and hasattr(label, 'setText') and hasattr(label, 'setStyleSheet'):
                    label.setText(text)
                    label.setStyleSheet(style)
            except: pass

        # 3. 브로커 상태 체크 및 기타 주기가 필요한 작업들
        # Update Market Status (MarketHour 클래스 사용)
        is_open = MarketHour.is_market_open_time()
        if is_open:
            safe_set_style(self.label_market_status, "장중", "color: #00ff00; font-weight: bold;")
        else:
            status_text, _ = MarketHour.get_market_status_text()
            safe_set_style(self.label_market_status, status_text, "color: #ffaa00;")
        
        # Check WS (엔진이 실행 중일 때만 체크)
        engine_running = (hasattr(self.chat_cmd, 'engine') 
                         and self.chat_cmd.engine 
                         and getattr(self.chat_cmd.engine, 'is_running', False))
        
        connected = False
        if engine_running:
            if hasattr(self.chat_cmd.engine, 'rt_search') and self.chat_cmd.engine.rt_search:
                connected = getattr(self.chat_cmd.engine.rt_search, 'connected', False)
        
        if not engine_running:
            # 엔진 미시작 상태 → 경고 불필요
            safe_set_style(self.label_ws_status, "대기", "color: #888;")
            self.disconnect_count = 0
        elif connected:
            safe_set_style(self.label_ws_status, "연결됨", "color: #00ff00;")
            self.disconnect_count = 0
        else:
            safe_set_style(self.label_ws_status, "미연결", "color: #ff0000;")
            
            # 장중일 때만 경고 발송 (장 마감 후 불필요한 알림 방지)
            if MarketHour.is_market_open_time():
                self.disconnect_count += 1
                if self.disconnect_count == 5 or (self.disconnect_count > 0 and self.disconnect_count % 30 == 0):
                    tel_send(f"⚠️ [연결 경고] 웹소켓 연결이 {self.disconnect_count}회 연속 확인되지 않습니다.\n키움 API 재로그인이 필요할 수 있습니다.", threaded=True)
            else:
                self.disconnect_count = 0

        # 4. 종목 마스터 데이터 주기적 재로드 (5분 주기 - [안실장 픽스])
        if curr_time - getattr(self, 'last_master_reload', 0) >= 300:
            self.last_master_reload = curr_time
            from shared.stock_master import load_master_cache
            self.stock_name_map = load_master_cache() or {}
            
        # [기존] Auto Schedule
        self.check_schedule()

    def check_schedule(self):
        # ... logic from original ...
        try:
            auto = get_setting('auto_start', False)
            today = datetime.now().date()
            if self.last_check_date != today:
                self.today_started = False
                self.today_stopped = False
                self.last_check_date = today
            
            if MarketHour.is_market_start_time() and auto and not self.today_started:
                # [안실장] 중복 실행 방지를 위해 플래그를 먼저 설정
                self.today_started = True
                # Schedule start_trading task
                asyncio.create_task(self.start_trading())
            
            elif MarketHour.is_market_end_time() and not self.today_stopped:
                self.stop_trading()
                asyncio.create_task(self.chat_cmd.report())
                self.today_stopped = True
        except Exception as e:
            pass

    def closeEvent(self, event):
        self.chat_cmd.stop_polling()
        
        # Cancel pending account update task
        if self.account_update_task and not self.account_update_task.done():
            self.account_update_task.cancel()
            
        if hasattr(self.chat_cmd, 'engine'):
             self.chat_cmd.engine.shutdown()
        event.accept()

    # update_account_info, _update_account_info_impl, toggle_auto_refresh,

    # send_telegram_test, open_telegram_help, panic_sell_all

    # → Moved to ui/account_mixin.py (AccountMixin)



    def start_polling(self):
        """Start Telegram Polling Task"""
        if not self.polling_task:
            self.polling_task = asyncio.create_task(self.chat_cmd.run_polling())



    def show_confirmation_dialog(self, trade_type, data):
        title = "매수 확인" if trade_type == 'buy' else "매도 확인"
        msg = f"{title}\n{data.get('name')} ({data.get('code')})\n진행하시겠습니까?"
        reply = QMessageBox.question(self, title, msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            asyncio.create_task(self.execute_trade(trade_type, data))

    async def execute_trade(self, trade_type, data):
        """수동 주문 실행 및 진단형 체결 확인"""
        try:
            # 1. 시스템 토큰 및 브로커 확보
            token = self.trading_engine.token or await asyncio.get_event_loop().run_in_executor(None, get_token)
            if not token:
                self.append_log("❌ [오류] 토큰을 발급받지 못해 주문을 보낼 수 없습니다.")
                return

            broker = self.trading_engine.broker
            broker.token = token # 동기화
            
            stk_cd = data['code']
            stk_nm = data['name']
            qty = data['qty']
            price = data.get('price', 0)
            reason = data.get('reason', '수동 주문')
            
            self.append_log(f"📡 [수동주문] {stk_nm}({stk_cd}) {qty}주 {trade_type} 주문을 시도합니다. (사유: {reason})")
            
            loop = asyncio.get_event_loop()
            res_code = '999'
            res_msg = '연결 오류'
            
            # 2. 주문 실행
            if trade_type == 'buy':
                res_code, res_msg = await loop.run_in_executor(None, broker.buy, stk_cd, qty, 0, '3') # 시장가(3)
            else:
                res_code, res_msg = await loop.run_in_executor(None, broker.sell, stk_cd, qty, 0, '3') # 시장가(3)
            
            if str(res_code).strip() in ['0', '00']:
                self.append_log(f"✅ {stk_nm} 주문 요청이 서버에 접수되었습니다. 체결을 기다리는 중...")
                
                # 3. 체결 확인 루프 (Diagnostic)
                confirmed = False
                real_price = price
                actual_qty = qty
                
                for attempt in range(5):
                    await asyncio.sleep(1.5)
                    try:
                        holdings = await loop.run_in_executor(None, broker.get_holdings)
                        target = next((h for h in holdings if h['stk_cd'].replace('A', '') == stk_cd), None)
                        
                        if trade_type == 'buy':
                            if target: # 잔고에 나타남
                                val = target.get('pchs_avg_pric') or target.get('buy_avg_pric') or target.get('avg_prc') or 0
                                q_val = target.get('rmnd_qty') or target.get('qty') or target.get('hold_qty') or 0
                                real_price = int(str(val).replace(',', '')) if val else price
                                actual_qty = int(str(q_val).replace(',', '')) if q_val else qty
                                if actual_qty > 0:
                                    confirmed = True
                                    break
                        else: # sell
                            if not target: # 잔고에서 사라짐 (전량 매도)
                                confirmed = True
                                break
                            else:
                                # 부분 매도 확인 (수량 감소)
                                new_qty = int(str(target.get('rmnd_qty', '0')).replace(',', ''))
                                if new_qty < qty + 1: # 단순 판단 로직 (엄밀하게는 이전 수량 대비 체크 필요)
                                    confirmed = True
                                    break
                                    
                    except Exception as e:
                        self.logger.error(f"Manual confirm check fail: {e}")

                if confirmed:
                    msg_txt = f"🎊 {stk_nm} {trade_type.replace('buy','매수').replace('sell','매도')}체결 완료!"
                    self.append_log(f"✅ {msg_txt}")
                    tel_send(f"✅ [수동체결] {stk_nm} {trade_type} 완료")
                    
                    # 기록
                    from history_manager import record_trade
                    record_trade(stk_cd, trade_type, f"수동({reason})", stk_nm, str(real_price), actual_qty)

                    # UI 즉시 갱신
                    self.engine_callback("trade", {
                        "type": trade_type.replace('buy','매수').replace('sell','매도'), 
                        "time": datetime.now().strftime("%m/%d %H:%M:%S"),
                        "name": stk_nm, "price": str(real_price), "qty": actual_qty, "msg": f"수동({reason})"
                    })
                else:
                    self.append_log(f"⚠️ {stk_nm} 주문은 접수되었으나 체결이 확인되지 않습니다. (잔고 미반영)")
            else:
                self.append_log(f"❌ {stk_nm} 주문 거절: {res_msg} (코드:{res_code})")
                
        except Exception as e:
            self.append_log(f"주문 프로세스 오류: {e}")

def main():
    # [안실장 유지보수 가이드] 명령줄 인자 파싱 (윈도우 위치 제어)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--offset-x', type=int, default=-1)
    parser.add_argument('--offset-y', type=int, default=-1)
    args, unknown = parser.parse_known_args()

    app = QApplication(sys.argv)
    font = QFont("Malgun Gothic", 12)
    app.setFont(font)
    
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = TradingMainWindow()
    
    # [안실장 유지보수 가이드] 전달받은 오프셋이 있으면 윈도우 이동
    if args.offset_x != -1 and args.offset_y != -1:
        window.move(args.offset_x, args.offset_y)
        
    window.show()
    
    # [관제 센터 신호] 초기화 성공 알림 (내부 리다이렉션 우회)
    sys.__stdout__.write("[CENTER] INITIALIZED\n")
    sys.__stdout__.flush()
    
    with loop:
        loop.run_forever()

if __name__ == '__main__':
    main()
