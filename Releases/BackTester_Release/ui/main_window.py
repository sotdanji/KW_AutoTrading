from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QStatusBar, QComboBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
                             QFormLayout, QDateEdit, QSpinBox, QDoubleSpinBox, QTabWidget,
                             QSplitter, QFrame, QListWidget, QLineEdit, QProgressBar)
from PyQt6.QtCore import Qt, QDate, QThread
from PyQt6.QtGui import QIcon, QFont
import datetime
import sys
import os
import json

# Matplotlib imports
import logging
import matplotlib

matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# Configure Korean font for matplotlib
import platform
if platform.system() == 'Windows':
    plt.rcParams['font.family'] = 'Malgun Gothic'
else:
    plt.rcParams['font.family'] = 'NanumGothic'
plt.rcParams['axes.unicode_minus'] = False  # Fix minus sign display

# Add project root to sys.path to allow imports from core
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Core modules
from core.login import get_access_token
from core.condition_loader import get_condition_list_sync
from core.backtest_engine import BacktestEngine
from ui.styles import DARK_THEME_QSS

SETTINGS_FILE = os.path.join(project_root, "settings.json")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sotdanji Backtesting Lab")
        self.setGeometry(100, 100, 1400, 900)
        
        # Apply Dark Theme
        self.setStyleSheet(DARK_THEME_QSS)
        
        self.token = None 
        self.init_ui()
        
    def init_ui(self):
        # Central Widget acts as the main container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Left Sidebar (Control Panel)
        sidebar = QFrame()
        sidebar.setFixedWidth(320)
        sidebar.setStyleSheet("background-color: #1a1a1a; border-right: 1px solid #333;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(15)
        
        # Title
        lbl_title = QLabel("Sotdanji Backtesting Lab")
        lbl_title.setObjectName("header_title")
        sidebar_layout.addWidget(lbl_title)
        
        # [Login & Control]
        # Auto Login triggered at startup


        # [Strategy Selection] moved to separate tab for more space
        
        # Guidance Label
        lbl_guidance = QLabel("💡 먼저 [전략수립]탭에 전략을 입력하세요.")
        lbl_guidance.setStyleSheet("""
            color: #ffaa00; 
            padding: 8px; 
            background-color: #2a2520; 
            border-radius: 5px;
            border-left: 3px solid #ffaa00;
            font-size: 11px;
        """)
        lbl_guidance.setWordWrap(True)
        sidebar_layout.addWidget(lbl_guidance)
        
        # Add vertical spacing
        sidebar_layout.addSpacing(15)

        # [Stock Selection] (Manual Input for Verification)
        grp_stock = QGroupBox("종목 선택 (선택시에만 단일종목 검증)")
        vbox_stock = QVBoxLayout()
        
        # Input Area only
        self.input_stock = QLineEdit()
        self.input_stock.setPlaceholderText("종목코드 입력 (예: 005930)")
        vbox_stock.addWidget(self.input_stock)
        
        grp_stock.setLayout(vbox_stock)
        sidebar_layout.addWidget(grp_stock)
        
        # [Action Buttons]
        self.btn_run = QPushButton("Run Backtest")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setMinimumHeight(45)
        self.btn_run.setEnabled(False)
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setMinimumHeight(35)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_opt = QPushButton("유전 알고리즘 최적화")
        self.btn_opt.setObjectName("btn_opt")
        self.btn_opt.setMinimumHeight(35)
        self.btn_opt.setCursor(Qt.CursorShape.PointingHandCursor)
        
        sidebar_layout.addWidget(self.btn_run)
        sidebar_layout.addWidget(self.btn_stop)
        sidebar_layout.addWidget(self.btn_opt)
        
        # [Progress Bar]
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("대기 중...")
        self.progress_bar.setMinimumHeight(25)
        sidebar_layout.addWidget(self.progress_bar)
        
        # [Settings - Date]
        grp_period = QGroupBox("백테스트 기간")
        form_period = QFormLayout()
        self.date_start = QDateEdit(QDate.currentDate().addMonths(-3))
        self.date_start.setCalendarPopup(True)
        self.date_end = QDateEdit(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        form_period.addRow("시작일자", self.date_start)
        form_period.addRow("종료일자", self.date_end)
        grp_period.setLayout(form_period)
        sidebar_layout.addWidget(grp_period)
        
        # [Settings - Filter]
        grp_filter = QGroupBox("종목 필터")
        form_filter = QFormLayout()
        self.spin_min_price = QSpinBox()
        self.spin_min_price.setRange(0, 10000000)
        self.spin_min_price.setValue(1000)
        self.spin_min_price.setSuffix(" 원")
        
        self.spin_min_vol = QSpinBox()
        self.spin_min_vol.setRange(0, 100000000)
        self.spin_min_vol.setValue(50000)
        self.spin_min_vol.setSuffix(" 주")
        
        form_filter.addRow("최소 가격", self.spin_min_price)
        form_filter.addRow("최소 거래량", self.spin_min_vol)
        grp_filter.setLayout(form_filter)
        sidebar_layout.addWidget(grp_filter)
        
        # [Settings - Capital]
        grp_capital = QGroupBox("실매매 자본 설정")
        form_capital = QFormLayout()
        self.spin_deposit = QDoubleSpinBox()
        self.spin_deposit.setRange(0, 10000000000)
        self.spin_deposit.setValue(10000000) # 1000만
        self.spin_deposit.setSuffix(" 원")
        
        self.spin_ratio = QDoubleSpinBox()
        self.spin_ratio.setRange(1, 100)
        self.spin_ratio.setValue(10)
        self.spin_ratio.setSuffix(" %")
        
        form_capital.addRow("초기 예수금", self.spin_deposit)
        form_capital.addRow("포지션 비중", self.spin_ratio)
        grp_capital.setLayout(form_capital)
        sidebar_layout.addWidget(grp_capital)

        # [Settings - Risk]
        grp_risk = QGroupBox("손절 · 익절 (%)")
        layout_risk = QHBoxLayout()
        
        box_loss = QVBoxLayout()
        box_loss.addWidget(QLabel("손절"))
        self.spin_loss = QDoubleSpinBox()
        self.spin_loss.setValue(3.0)
        box_loss.addWidget(self.spin_loss)
        
        box_profit = QVBoxLayout()
        box_profit.addWidget(QLabel("익절"))
        self.spin_trigger = QDoubleSpinBox()
        self.spin_trigger.setValue(5.0)
        box_profit.addWidget(self.spin_trigger)
        
        layout_risk.addLayout(box_loss)
        layout_risk.addLayout(box_profit)
        grp_risk.setLayout(layout_risk)
        sidebar_layout.addWidget(grp_risk)
        
        sidebar_layout.addStretch()
        
        # [Exit Button]
        self.btn_exit = QPushButton("종료")
        self.btn_exit.setObjectName("btn_exit")
        self.btn_exit.setMinimumHeight(40)
        self.btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #552222;
                border: 1px solid #772222;
                color: #ffcccc;
            }
            QPushButton:hover {
                background-color: #773333;
            }
            QPushButton:pressed {
                background-color: #994444;
            }
        """)
        sidebar_layout.addWidget(self.btn_exit)

        # 2. Main Content (Center) & Log (Right) Splitter
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Center Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        # Tab 0: Strategy Setup (전략수립)
        self.tab_strategy = QWidget()
        self.setup_strategy_tab()
        self.tabs.addTab(self.tab_strategy, "📋 전략수립")
        
        # Tab 1: Trade History
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["종목", "매수일", "매도일", "매수가", "매도가", "수익률(%)", "상태"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.tabs.addTab(self.table, "💼 거래 내역")
        
        # Tab 2: Performance Summary
        self.tab_summary = QWidget()
        self.setup_summary_tab()
        self.tabs.addTab(self.tab_summary, "📊 성과 요약")
        
        content_splitter.addWidget(self.tabs)
        
        # 3. Right Log Panel
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_log = QLabel("실행 로그")
        lbl_log.setStyleSheet("padding: 5px; font-weight: bold; background: #252526;")
        log_layout.addWidget(lbl_log)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("border: none;")
        log_layout.addWidget(self.log_console)
        
        content_splitter.addWidget(log_widget)
        content_splitter.setStretchFactor(0, 7) # Main Content
        content_splitter.setStretchFactor(1, 3) # Log
        
        # Add Sidebar and Splitter to Main Layout
        main_layout.addWidget(sidebar)
        main_layout.addWidget(content_splitter)
        
        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Ready")
        self.setStatusBar(self.status_bar)

        # Connect Signals
        # Connect Signals


        self.btn_run.clicked.connect(self.on_run_strategy)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_opt.clicked.connect(self.on_optimize)
        self.btn_exit.clicked.connect(self.close)


        self.log("UI Initialized.")
        
        # Formula Editor Signal
        self.btn_convert.clicked.connect(self.on_convert_formula)
        
        # Load Settings
        self.load_ui_settings()
        
        # Initialize Engine
        self.engine = None
        
        # Auto Login
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self.on_login)

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_console.append(f"[{timestamp}] {message}")
        logging.info(message)
    
    def setup_strategy_tab(self):
        """Setup the strategy formula editor tab with larger workspace"""
        layout = QVBoxLayout(self.tab_strategy)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # === Title Section ===
        title_layout = QHBoxLayout()
        title = QLabel("전략 수식 편집기 & 관리")
        title.setObjectName("strategy_title")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # Help button
        btn_help = QPushButton("❓ 도움말")
        btn_help.setMaximumWidth(100)
        btn_help.clicked.connect(self.show_formula_help)
        title_layout.addWidget(btn_help)
        
        layout.addLayout(title_layout)
        
        # === Split View: Formula Input (Top) and Python Output (Bottom) ===
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # --- Top Section: Formula Input ---
        input_group = QGroupBox("📝 키움 수식 입력")
        input_layout = QVBoxLayout()
        input_layout.setContentsMargins(15, 20, 15, 15)
        input_layout.setSpacing(10)
        
        # Strategy name input (separate field)
        name_layout = QHBoxLayout()
        name_label = QLabel("전략 이름:")
        name_label.setMinimumWidth(80)
        name_layout.addWidget(name_label)
        
        self.input_strategy_name = QLineEdit()
        self.input_strategy_name.setPlaceholderText("예: 골든 크로스")
        self.input_strategy_name.setMaximumHeight(35)
        name_layout.addWidget(self.input_strategy_name)
        input_layout.addLayout(name_layout)
        
        # Formula input text editor
        self.text_formula_input = QTextEdit()
        self.text_formula_input.setPlaceholderText(
            "키움 수식을 입력하세요.\n\n"
            "예시:\n"
            "BBU = BBandsUp(20, 2);\n"
            "CCU = eavg(C, 20) + ATR(20) * 2;\n"
            "CrossUp(C, BBU)"
        )
        self.text_formula_input.setMinimumHeight(180)
        font = QFont("Consolas", 10)
        self.text_formula_input.setFont(font)
        input_layout.addWidget(self.text_formula_input)
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        self.btn_convert = QPushButton("🔄 파이썬 코드로 변환")
        self.btn_convert.setObjectName("btn_convert")
        self.btn_convert.setMinimumHeight(40)
        self.btn_convert.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_layout.addWidget(self.btn_convert)
        
        btn_clear = QPushButton("🗑️ 초기화")
        btn_clear.setMaximumWidth(100)
        btn_clear.setMinimumHeight(40)
        btn_clear.clicked.connect(self.clear_formula)
        btn_layout.addWidget(btn_clear)
        
        btn_save_strategy = QPushButton("💾 저장")
        btn_save_strategy.setMaximumWidth(100)
        btn_save_strategy.setMinimumHeight(40)
        btn_save_strategy.clicked.connect(self.save_strategy)
        btn_layout.addWidget(btn_save_strategy)
        
        btn_load_strategy = QPushButton("📂 불러오기")
        btn_load_strategy.setMaximumWidth(120)
        btn_load_strategy.setMinimumHeight(40)
        btn_load_strategy.clicked.connect(self.load_strategy_popup)
        btn_layout.addWidget(btn_load_strategy)
        
        btn_delete_strategy = QPushButton("🗑️ 삭제")
        btn_delete_strategy.setMaximumWidth(100)
        btn_delete_strategy.setMinimumHeight(40)
        btn_delete_strategy.clicked.connect(self.delete_strategy_popup)
        btn_layout.addWidget(btn_delete_strategy)
        
        input_layout.addLayout(btn_layout)
        input_group.setLayout(input_layout)
        splitter.addWidget(input_group)
        
        # --- Bottom Section: Python Code Output ---
        output_group = QGroupBox("🐍 변환된 파이썬 코드")
        output_layout = QVBoxLayout()
        output_layout.setContentsMargins(15, 20, 15, 15)
        output_layout.setSpacing(10)
        
        # Python code preview
        self.text_formula_preview = QTextEdit()
        self.text_formula_preview.setPlaceholderText(
            "변환된 파이썬 코드가 여기에 표시됩니다.\n\n"
            "변환 후 코드를 수동으로 편집할 수도 있습니다."
        )
        self.text_formula_preview.setReadOnly(False)  # Allow manual edits
        self.text_formula_preview.setMinimumHeight(200)
        self.text_formula_preview.setFont(font)
        output_layout.addWidget(self.text_formula_preview)
        
        # Validation button
        validate_layout = QHBoxLayout()
        
        btn_validate = QPushButton("✅ 코드 검증 (샘플 데이터)")
        btn_validate.setObjectName("btn_validate")
        btn_validate.setMinimumHeight(40)
        btn_validate.clicked.connect(self.validate_converted_code)
        validate_layout.addWidget(btn_validate)
        
        output_layout.addLayout(validate_layout)
        output_group.setLayout(output_layout)
        splitter.addWidget(output_group)
        
        # Set initial splitter sizes (1:2 ratio - formula:python code)
        splitter.setSizes([200, 400])
        layout.addWidget(splitter)
        
        # === Status/Info Section ===
        info_label = QLabel(
            "💡 <b>팁</b>: 수식 변환 후 백테스트를 실행하려면 사이드바의 'Run Backtest' 버튼을 클릭하세요."
        )
        info_label.setStyleSheet("color: #a0a0a0; padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
    
    def setup_summary_tab(self):
        """Setup the performance summary tab UI"""
        layout = QVBoxLayout(self.tab_summary)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("백테스트 성과 요약")
        title.setObjectName("summary_title")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # === Top Cards: Key Metrics ===
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)
        
        # Card 1: Total Return
        self.card_return = self.create_metric_card("총 수익률", "0.0%", "#ff9900")
        cards_layout.addWidget(self.card_return)
        
        # Card 2: Win Rate
        self.card_winrate = self.create_metric_card("승률", "0.0%", "#00aaff")
        cards_layout.addWidget(self.card_winrate)
        
        # Card 3: Total Trades
        self.card_trades = self.create_metric_card("총 거래", "0회", "#00cc66")
        cards_layout.addWidget(self.card_trades)
        
        layout.addLayout(cards_layout)
        
        # === Detailed Statistics ===
        detail_group = QGroupBox("상세 통계")
        detail_layout = QFormLayout()
        detail_layout.setSpacing(10)
        detail_layout.setContentsMargins(15, 20, 15, 15)
        
        # Create labels for statistics
        self.lbl_initial = QLabel("0원")
        self.lbl_final = QLabel("0원")
        self.lbl_profit = QLabel("0원")
        self.lbl_win_count = QLabel("0회")
        self.lbl_loss_count = QLabel("0회")
        self.lbl_avg_profit = QLabel("0.0%")
        self.lbl_avg_loss = QLabel("0.0%")
        self.lbl_avg_return = QLabel("0.0%")
        self.lbl_max_consec = QLabel("0회")
        
        # Add to form
        detail_layout.addRow("초기 자본:", self.lbl_initial)
        detail_layout.addRow("최종 잔고:", self.lbl_final)
        detail_layout.addRow("총 손익:", self.lbl_profit)
        detail_layout.addRow("승리 거래:", self.lbl_win_count)
        detail_layout.addRow("손실 거래:", self.lbl_loss_count)
        detail_layout.addRow("평균 수익 (승):", self.lbl_avg_profit)
        detail_layout.addRow("평균 손실 (패):", self.lbl_avg_loss)
        detail_layout.addRow("평균 수익률:", self.lbl_avg_return)
        detail_layout.addRow("최대 연속 손실:", self.lbl_max_consec)
        
        detail_group.setLayout(detail_layout)
        layout.addWidget(detail_group)
        
        # === Charts Section ===
        charts_group = QGroupBox("차트 분석")
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(10)
        
        # Chart 1: Cumulative Returns
        self.fig_cumulative = Figure(figsize=(6, 3), facecolor='#1e1e1e')
        self.canvas_cumulative = FigureCanvas(self.fig_cumulative)
        self.canvas_cumulative.setMinimumHeight(250)
        self.ax_cumulative = self.fig_cumulative.add_subplot(111)
        self.setup_chart_style(self.ax_cumulative)
        self.ax_cumulative.set_title('누적 수익률', color='#ffffff', fontsize=12, pad=10)
        self.ax_cumulative.set_xlabel('거래 번호', color='#a0a0a0', fontsize=10)
        self.ax_cumulative.set_ylabel('수익률 (%)', color='#a0a0a0', fontsize=10)
        self.ax_cumulative.grid(True, alpha=0.2, color='#3e3e3e')
        self.fig_cumulative.tight_layout()
        charts_layout.addWidget(self.canvas_cumulative)
        
        # Chart 2: Win/Loss Pie Chart
        self.fig_pie = Figure(figsize=(4, 3), facecolor='#1e1e1e')
        self.canvas_pie = FigureCanvas(self.fig_pie)
        self.canvas_pie.setMinimumHeight(250)
        self.ax_pie = self.fig_pie.add_subplot(111)
        self.ax_pie.set_facecolor('#1e1e1e')
        self.ax_pie.set_title('승/패 비율', color='#ffffff', fontsize=12, pad=10)
        self.fig_pie.tight_layout()
        charts_layout.addWidget(self.canvas_pie)
        
        charts_group.setLayout(charts_layout)
        layout.addWidget(charts_group)
        
        # Add stretch to push content to top
        layout.addStretch()
    
    def setup_chart_style(self, ax):
        """Setup dark theme style for matplotlib chart"""
        ax.set_facecolor('#1e1e1e')
        ax.tick_params(colors='#a0a0a0', labelsize=9)
        for spine in ax.spines.values():
            spine.set_color('#3e3e3e')
    
    def create_metric_card(self, title, value, color):
        """Create a metric card widget"""
        card = QFrame()
        card.setObjectName("metric_card")
        card.setStyleSheet(f"""
            QFrame#metric_card {{
                background-color: #252526;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(5)
        
        # Title label
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #a0a0a0; font-size: 13px;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Value label
        value_lbl = QLabel(value)
        value_lbl.setObjectName("card_value")
        value_lbl.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        card_layout.addWidget(title_lbl)
        card_layout.addWidget(value_lbl)
        
        # Store value label for later updates
        card.value_label = value_lbl
        card.title_label = title_lbl
        card.color = color
        
        return card

    def on_login(self):
        self.log("API 로그인 시도 중...")
        try:
            # Threading needed for real app
            self.token = get_access_token()
            if self.token:
                self.log("로그인 성공! 토큰 발급 완료.")
                self.status_bar.showMessage("Logged In")
                self.btn_run.setEnabled(True)
            else:
                self.log("로그인 실패.")
                self.status_bar.showMessage("Login Failed")
        except Exception as e:
            self.log(f"로그인 에러: {e}")

    def on_run_strategy(self):
        # try:  <-- I will not add try-except blindly if I can't indent the rest easily.
        # Just removing logs for now.
        
        if not self.token: 
            self.log("❌ 로그인이 필요합니다. 잠시 후 다시 시도하세요.")
            return
        
        # === 입력 검증 ===
        
        # 1. 날짜 범위 검증
        start_date = self.date_start.date()
        end_date = self.date_end.date()
        
        if start_date > end_date:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "날짜 오류",
                "시작일이 종료일보다 늦을 수 없습니다.\n날짜 범위를 확인하세요."
            )
            self.log("❌ 입력 오류: 시작일이 종료일보다 늦습니다.")
            return
        
        # 2. 전략 코드 검증
        strategy_code = self.text_formula_preview.toPlainText().strip()
        if not strategy_code:
            QMessageBox.warning(
                self,
                "전략 오류",
                "변환된 파이썬 코드가 없습니다.\n\n"
                "1. '전략 (수식 편집)'에 키움 수식을 입력하세요\n"
                "2. '파이썬 코드로 변환' 버튼을 클릭하세요\n"
                "3. 변환 결과를 확인한 후 백테스트를 실행하세요"
            )
            self.log("❌ 전략 코드가 없습니다. 수식을 입력하고 변환하세요.")
            return
        
        # 3. 종목 코드 형식 검증 (입력된 경우만)
        manual_code = self.input_stock.text().strip()
        if manual_code:
            # 종목코드는 6자리 숫자여야 함
            if not manual_code.isdigit() or len(manual_code) != 6:
                QMessageBox.warning(
                    self,
                    "종목 코드 오류",
                    f"종목 코드는 6자리 숫자여야 합니다.\n입력값: '{manual_code}'\n\n"
                    f"예시: 005930 (삼성전자)"
                )
                self.log(f"❌ 잘못된 종목 코드 형식: {manual_code}")
                return
        
        # === 입력 검증 완료 ===
        
        # 1. Get Target Stocks
        target_codes = []
        
        # Manual Input or Universe Mode
        manual_code = self.input_stock.text().strip()
        if manual_code:
            # Single stock mode
            target_codes.append(manual_code)
            self.log(f"단일 종목 검증: {manual_code}")
        else:
            # Multi-stock universe mode
            if hasattr(self, 'universe_cache') and self.universe_cache:
                self.log("유니버스 모드: 캐시된 종목 리스트 사용")
                full_universe = self.universe_cache
            else:
                self.log("유니버스 모드: 전종목 리스트 가져오는 중...")
                from core.stock_universe import get_full_stock_universe
                # Get full universe (no pre-filtering)
                full_universe = get_full_stock_universe(self.token)
                self.universe_cache = full_universe
                
            # Limit to first 200 stocks to avoid API rate limit issues
            target_codes = full_universe[:200]
        
            self.log(f"전체 유니버스: {len(full_universe)}개 종목")
            self.log(f"백테스트 대상: 처음 {len(target_codes)}개 종목 (샘플)")
        
        if len(target_codes) == 0:
            self.log("경고: 종목 리스트를 가져올 수 없습니다.")
            return

        self.log(f"백테스트 시작. 대상 종목: {len(target_codes)}개")





        
        # 2. Config
        start_date = self.date_start.date()
        end_date = self.date_end.date()
        
        config = {
            'deposit': self.spin_deposit.value(),
            'ratio': self.spin_ratio.value(),
            'sl': self.spin_loss.value(),
            'tp': self.spin_trigger.value(),
            'strategy_code': self.text_formula_preview.toPlainText() # Pass Custom Code
        }
        
        if not config['strategy_code']:
            self.log("경고: 변환된 파이썬 코드가 없습니다. '파이썬 변환' 버튼을 눌러주세요.")
            return # Don't run legacy strategy implicitly anymore
        
        # 3. Setup Engine (Main Thread Execution with processEvents)
        self.engine = BacktestEngine(self.token)
        self.engine.log_message.connect(self.log)
        self.engine.trade_executed.connect(self.on_trade_executed)
        self.engine.progress_updated.connect(self.on_progress_updated)
        self.engine.finished.connect(self.on_backtest_finished)
        self.engine.finished.connect(lambda: self.btn_run.setEnabled(True))
        
        self.btn_run.setEnabled(False)
        self.table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("진행 중... 0%")
        
        # Run directly on main thread (using QTimer to allow UI update first)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self.engine.run(target_codes, start_date, end_date, config))
    
    def on_optimize(self):
        """Show optimization dialog"""
        from ui.optimization_dialog import OptimizationDialog
        dialog = OptimizationDialog(self)
        dialog.exec()

    def on_trade_executed(self, trade):
        # Add to table
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(trade['code']))
        self.table.setItem(row, 1, QTableWidgetItem(str(trade['buy_date'])))
        self.table.setItem(row, 2, QTableWidgetItem(str(trade['sell_date'])))
        self.table.setItem(row, 3, QTableWidgetItem(str(trade['buy_price'])))
        self.table.setItem(row, 4, QTableWidgetItem(str(trade['sell_price'])))
        
        item_profit = QTableWidgetItem(f"{trade['profit_pct']:.2f}")
        if trade['profit_pct'] > 0:
            item_profit.setForeground(Qt.GlobalColor.red)
        else:
            item_profit.setForeground(Qt.GlobalColor.blue)
        self.table.setItem(row, 5, item_profit)
        self.table.setItem(row, 6, QTableWidgetItem(trade['status']))

    def on_progress_updated(self, current, total):
        """Update progress bar as backtest progresses"""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
            self.progress_bar.setFormat(f"진행 중... {percentage}%")
    
    def on_backtest_finished(self, summary):
        """Handle backtest completion and update summary tab"""
        self.log(f"백테스트 완료. 최종 잔고: {summary['final_cash']:,.0f}")
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("완료!")
        
        # Update performance summary tab
        self.update_summary_tab(summary)
    
    def update_summary_tab(self, summary):
        """Update the performance summary tab with backtest results"""
        # Update top cards
        return_pct = summary['return_pct']
        
        # Color based on profit/loss
        return_color = "#00cc66" if return_pct > 0 else "#cc3333"
        self.card_return.value_label.setText(f"{return_pct:+.2f}%")
        self.card_return.value_label.setStyleSheet(f"color: {return_color}; font-size: 24px; font-weight: bold;")
        self.card_return.setStyleSheet(f"""
            QFrame#metric_card {{
                background-color: #252526;
                border: 2px solid {return_color};
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        
        self.card_winrate.value_label.setText(f"{summary['win_rate']:.1f}%")
        self.card_trades.value_label.setText(f"{summary['total_trades']}회")
        
        # Update detailed statistics
        self.lbl_initial.setText(f"{summary['initial_deposit']:,.0f}원")
        
        final_color = "#00cc66" if summary['total_profit'] > 0 else "#cc3333"
        self.lbl_final.setText(f"{summary['final_cash']:,.0f}원")
        self.lbl_final.setStyleSheet(f"color: {final_color}; font-weight: bold;")
        
        profit_text = f"{summary['total_profit']:+,.0f}원 ({return_pct:+.2f}%)"
        self.lbl_profit.setText(profit_text)
        self.lbl_profit.setStyleSheet(f"color: {return_color}; font-weight: bold;")
        
        self.lbl_win_count.setText(f"{summary['win_count']}회")
        self.lbl_loss_count.setText(f"{summary['loss_count']}회")
        
        # Average profit/loss with colors
        avg_profit_color = "#00cc66"
        self.lbl_avg_profit.setText(f"+{summary['avg_profit']:.2f}%")
        self.lbl_avg_profit.setStyleSheet(f"color: {avg_profit_color}; font-weight: bold;")
        
        avg_loss_color = "#cc3333"
        self.lbl_avg_loss.setText(f"{summary['avg_loss']:.2f}%")
        self.lbl_avg_loss.setStyleSheet(f"color: {avg_loss_color}; font-weight: bold;")
        
        avg_return_color = "#00cc66" if summary['avg_return'] > 0 else "#cc3333"
        self.lbl_avg_return.setText(f"{summary['avg_return']:+.2f}%")
        self.lbl_avg_return.setStyleSheet(f"color: {avg_return_color}; font-weight: bold;")
        
        self.lbl_max_consec.setText(f"{summary['max_consecutive_loss']}회")
        
        # === Update Charts ===
        self.update_charts(summary)
    
    def update_charts(self, summary):
        """Update matplotlib charts with backtest results"""
        trades = summary.get('trades', [])
        
        if not trades:
            return
        
        # === Chart 1: Cumulative Returns ===
        self.ax_cumulative.clear()
        self.setup_chart_style(self.ax_cumulative)
        
        # Calculate cumulative returns
        cumulative_returns = []
        cumulative = 0
        for trade in trades:
            cumulative += trade['profit_pct']
            cumulative_returns.append(cumulative)
        
        # Plot line
        x = range(1, len(cumulative_returns) + 1)
        color = '#00cc66' if cumulative_returns[-1] > 0 else '#cc3333'
        self.ax_cumulative.plot(x, cumulative_returns, color=color, linewidth=2, marker='o', markersize=3)
        self.ax_cumulative.axhline(y=0, color='#666666', linestyle='--', linewidth=1, alpha=0.5)
        
        self.ax_cumulative.set_title('누적 수익률', color='#ffffff', fontsize=12, pad=10)
        self.ax_cumulative.set_xlabel('거래 번호', color='#a0a0a0', fontsize=10)
        self.ax_cumulative.set_ylabel('수익률 (%)', color='#a0a0a0', fontsize=10)
        self.ax_cumulative.grid(True, alpha=0.2, color='#3e3e3e')
        
        self.fig_cumulative.tight_layout()
        self.canvas_cumulative.draw()
        
        # === Chart 2: Win/Loss Pie Chart ===
        self.ax_pie.clear()
        
        win_count = summary['win_count']
        loss_count = summary['loss_count']
        
        if win_count > 0 or loss_count > 0:
            sizes = [win_count, loss_count]
            labels = [f'승리\n{win_count}회', f'손실\n{loss_count}회']
            colors = ['#00cc66', '#cc3333']
            explode = (0.05, 0)
            
            self.ax_pie.pie(sizes, explode=explode, labels=labels, colors=colors, 
                           autopct='%1.1f%%', startangle=90, textprops={'color': '#ffffff', 'fontsize': 10})
            self.ax_pie.set_facecolor('#1e1e1e')
            self.ax_pie.set_title('승/패 비율', color='#ffffff', fontsize=12, pad=10)
        
        self.fig_pie.tight_layout()
        self.canvas_pie.draw()

    def load_ui_settings(self):
        try:
            if not os.path.exists(SETTINGS_FILE):
                return
                
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Filter
            if 'min_price' in data: self.spin_min_price.setValue(int(float(data['min_price'])))
            if 'min_vol' in data: self.spin_min_vol.setValue(int(float(data['min_vol'])))
            
            # Capital
            if 'initial_deposit' in data: self.spin_deposit.setValue(float(data['initial_deposit']))
            if 'position_ratio' in data: self.spin_ratio.setValue(float(data['position_ratio']))
            
            # Risk
            if 'stop_loss' in data: self.spin_loss.setValue(float(data['stop_loss']))
            if 'trigger_profit' in data: self.spin_trigger.setValue(float(data['trigger_profit']))
            
            self.log("설정 로드 완료.")
        except Exception as e:
            self.log(f"설정 로드 실패: {e}")

    def save_ui_settings(self):
        try:
            # Read existing if possible to preserve other keys
            data = {}
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except:
                    pass
            
            # Update UI values
            data['min_price'] = self.spin_min_price.value()
            data['min_vol'] = self.spin_min_vol.value()
            data['initial_deposit'] = self.spin_deposit.value()
            data['position_ratio'] = self.spin_ratio.value()
            data['stop_loss'] = self.spin_loss.value()
            data['trigger_profit'] = self.spin_trigger.value()
            
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            self.log("설정 저장 완료.")
        except Exception as e:
            self.log(f"설정 저장 실패: {e}")

    def closeEvent(self, event):
        # Check if backtest is running
        if hasattr(self, 'engine') and self.engine and self.engine.running:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                '백테스트 실행 중',
                '백테스트가 실행 중입니다.\n정말 종료하시겠습니까?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            else:
                # Stop the backtest before closing
                if self.engine:
                    self.engine.stop()
        
        # Save settings before exit
        self.save_ui_settings()
        event.accept()
        
    def on_stop(self):
        print("[DEBUG] on_stop called!")  # Debug
        self.log("작업 중지 요청됨.")
        if self.engine:
            self.engine.stop()
        else:
            self.log("경고: 백테스트 엔진이 없습니다.")

    def on_stop(self):
        self.log("작업 중지 요청됨.")
        if self.engine:
            self.engine.stop()
        else:
            self.log("경고: 백테스트 엔진이 없습니다.")

    def on_convert_formula(self):
        """Convert Kiwoom Formula to Python"""
        formula = self.text_formula_input.toPlainText()
        if not formula.strip():
            self.log("수식을 입력하세요.")
            return
            
        try:
            # Lazy import to avoid circular dependency
            from core.formula_parser import FormulaParser
            from core.hangul_converter import HangulVariableConverter
            
            # 1. Convert Hangul Variables
            h_converter = HangulVariableConverter()
            safe_formula = h_converter.convert(formula)
            if h_converter.get_mapping():
                self.log(f"📝 한글 변수 변환: {h_converter.get_mapping()}")

            # 2. Parse Formula
            parser = FormulaParser()
            py_code = parser.parse(safe_formula)
            self.text_formula_preview.setPlainText(py_code)
            self.log("✅ 수식 변환 성공!")
            
            # Visual feedback - green border
            self.text_formula_preview.setStyleSheet("border: 2px solid #00cc66;")
        except Exception as e:
            self.log(f"❌ 변환 오류: {e}")
            # Visual feedback - red border
            self.text_formula_preview.setStyleSheet("border: 2px solid #cc3333;")
    
    def show_formula_help(self):
        """Show formula syntax help dialog"""
        from PyQt6.QtWidgets import QMessageBox
        help_text = """
<h3>지원하는 수식 문법</h3>

<b>1. 기본 변수</b>
- C, O, H, L, V (종가, 시가, 고가, 저가, 거래량)

<b>2. 과거 데이터 참조</b>
- C(1): 1일 전 종가
- O(2): 2일 전 시가

<b>3. 기술 지표</b>
- avg(C, 20): 20일 이동평균
- eavg(C, 20): 20일 지수이동평균
- BBandsUp(20, 2): 볼린저 밴드 상단
- BBandsDown(20, 2): 볼린저 밴드 하단
- ATR(20): Average True Range

<b>4. 교차 함수</b>
- CrossUp(C, avg(C, 20)): 상향 돌파
- CrossDown(C, avg(C, 20)): 하향 돌파

<b>5. 논리 연산자</b>
- && : AND
- || : OR
- > , < , >= , <= : 비교 연산자

<b>6. 예제</b>
BBU = BBandsUp(20, 2);
CrossUp(C, BBU)
        """
        QMessageBox.information(self, "수식 문법 도움말", help_text)
    
    def clear_formula(self):
        """Clear formula input and output"""
        self.input_strategy_name.clear()
        self.text_formula_input.clear()
        self.text_formula_preview.clear()
        self.text_formula_preview.setStyleSheet("")  # Reset border
        self.log("수식 편집기 초기화 완료")
    
    def get_strategies_dir(self):
        """Get or create strategies directory"""
        strategies_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategies")
        if not os.path.exists(strategies_dir):
            os.makedirs(strategies_dir)
        return strategies_dir
    
    def save_strategy(self):
        """Save current strategy to file"""
        formula = self.text_formula_input.toPlainText()
        py_code = self.text_formula_preview.toPlainText()
        strategy_name = self.input_strategy_name.text().strip()
        
        if not formula.strip():
            self.log("❌ 저장할 수식이 없습니다.")
            return
        
        if not strategy_name:
            self.log("❌ 전략 이름을 입력하세요.")
            return
        
        # Remove invalid characters from filename
        import re
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', strategy_name)
        
        strategies_dir = self.get_strategies_dir()
        filepath = os.path.join(strategies_dir, f"{safe_filename}.json")
        
        strategy_data = {
            'name': strategy_name,
            'formula': formula,
            'python_code': py_code,
            'saved_at': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(strategy_data, f, indent=4, ensure_ascii=False)
            
            self.log(f"✅ 전략 저장 완료: {strategy_name}")
        except Exception as e:
            self.log(f"❌ 저장 실패: {e}")

    
    def load_strategy_popup(self):
        """Show popup dialog to select and load strategy"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton
        
        strategies_dir = self.get_strategies_dir()
        
        # Get list of strategies
        strategy_files = []
        if os.path.exists(strategies_dir):
            for filename in os.listdir(strategies_dir):
                if filename.endswith('.json'):
                    strategy_files.append(filename[:-5])  # Remove .json extension
        
        if not strategy_files:
            self.log("⚠️ 저장된 전략이 없습니다.")
            return
        
        # Create popup dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("전략 불러오기")
        dialog.setMinimumWidth(400)
        dialog.setMinimumHeight(300)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("📂 불러올 전략을 선택하세요:")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # List widget
        list_widget = QListWidget()
        for strategy_name in strategy_files:
            list_widget.addItem(strategy_name)
        list_widget.itemDoubleClicked.connect(dialog.accept)
        layout.addWidget(list_widget)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_ok = QPushButton("✅ 불러오기")
        btn_ok.clicked.connect(dialog.accept)
        btn_ok.setMinimumWidth(100)
        btn_layout.addWidget(btn_ok)
        
        btn_cancel = QPushButton("❌ 취소")
        btn_cancel.clicked.connect(dialog.reject)
        btn_cancel.setMinimumWidth(100)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            current_item = list_widget.currentItem()
            if current_item:
                strategy_name = current_item.text()
                filepath = os.path.join(strategies_dir, f"{strategy_name}.json")
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        strategy_data = json.load(f)
                    
                    # Load strategy data into appropriate fields
                    strategy_name_text = strategy_data.get('name', strategy_name)
                    formula_content = strategy_data.get('formula', '')
                    
                    # Set strategy name in the dedicated field
                    self.input_strategy_name.setText(strategy_name_text)
                    # Set formula content (without name prefix)
                    self.text_formula_input.setPlainText(formula_content)
                    self.text_formula_preview.setPlainText(strategy_data.get('python_code', ''))
                    
                    saved_at = strategy_data.get('saved_at', '알 수 없음')
                    self.log(f"✅ 전략 불러오기 완료: {strategy_name_text} (저장: {saved_at})")
                    self.text_formula_preview.setStyleSheet("")  # Reset border
                except Exception as e:
                    self.log(f"❌ 불러오기 실패: {e}")
    
    def delete_strategy_popup(self):
        """Show popup dialog to select and delete strategy"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QListWidget, QPushButton
        
        strategies_dir = self.get_strategies_dir()
        
        # Get list of strategies
        strategy_files = []
        if os.path.exists(strategies_dir):
            for filename in os.listdir(strategies_dir):
                if filename.endswith('.json'):
                    strategy_files.append(filename[:-5])  # Remove .json extension
        
        if not strategy_files:
            self.log("⚠️ 저장된 전략이 없습니다.")
            return
        
        # Create popup dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("전략 삭제")
        dialog.setMinimumWidth(400)
        dialog.setMinimumHeight(300)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title = QLabel("🗑️ 삭제할 전략을 선택하세요:")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px; color: #ff6666;")
        layout.addWidget(title)
        
        # List widget
        list_widget = QListWidget()
        for strategy_name in strategy_files:
            list_widget.addItem(strategy_name)
        layout.addWidget(list_widget)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_delete = QPushButton("🗑️ 삭제")
        btn_delete.clicked.connect(dialog.accept)
        btn_delete.setMinimumWidth(100)
        btn_delete.setStyleSheet("background-color: #cc3333;")
        btn_layout.addWidget(btn_delete)
        
        btn_cancel = QPushButton("❌ 취소")
        btn_cancel.clicked.connect(dialog.reject)
        btn_cancel.setMinimumWidth(100)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            current_item = list_widget.currentItem()
            if current_item:
                strategy_name = current_item.text()
                
                # Confirmation
                reply = QMessageBox.question(
                    self,
                    '전략 삭제 확인',
                    f'정말로 "{strategy_name}" 전략을 삭제하시겠습니까?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    filepath = os.path.join(strategies_dir, f"{strategy_name}.json")
                    
                    try:
                        os.remove(filepath)
                        self.log(f"✅ 전략 삭제 완료: {strategy_name}")
                        self.refresh_strategies_list() # Added this line to refresh the list after deletion
                    except Exception as e:
                        self.log(f"❌ 삭제 실패: {e}")
    
    def validate_converted_code(self):
        """Validate converted Python code with sample data"""
        py_code = self.text_formula_preview.toPlainText()
        
        if not py_code.strip():
            self.log("❌ 변환된 코드가 없습니다. 먼저 수식을 변환하세요.")
            return
        
        self.log("코드 검증 시작...")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        
        try:
            logging.debug("Generating sample data...")
            import pandas as pd
            import numpy as np
            from core.indicators import TechnicalIndicators as TI
            
            # Generate sample data
            np.random.seed(42)
            dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
            returns = np.random.normal(0.001, 0.02, 100)
            price = 10000 * (1 + returns).cumprod()
            
            df = pd.DataFrame({
                'date': dates,
                'open': price * (1 + np.random.uniform(-0.01, 0.01, 100)),
                'high': price * (1 + np.random.uniform(0, 0.02, 100)),
                'low': price * (1 + np.random.uniform(-0.02, 0, 100)),
                'close': price,
                'volume': np.random.randint(100000, 1000000, 100)
            })
            
            # Ensure price constraints
            df['high'] = df[['high', 'close']].max(axis=1)
            df['low'] = df[['low', 'close']].min(axis=1)
            
            # Ensure price constraints
            df['high'] = df[['high', 'close']].max(axis=1)
            df['low'] = df[['low', 'close']].min(axis=1)
            
            print("[DEBUG] Environment Setup...")
            # --- Setup Environment (Match BacktestEngine) ---
            from core.execution_context import get_execution_context
            exec_globals = get_execution_context(df)
            
            # Execute code
            local_vars = {}
            logging.debug(f"Executing code:\n{py_code}")
            QApplication.processEvents()
            
            exec(py_code, exec_globals, local_vars)
            
            print("[DEBUG] Execution finished.")
            
            if 'cond' in local_vars:
                cond = local_vars['cond']
                true_count = cond.sum() if hasattr(cond, 'sum') else 0
                
                self.log(f"✅ 코드 검증 성공!")
                self.log(f"  - 결과 타입: {type(cond).__name__}")
                self.log(f"  - 데이터 길이: {len(cond)}")
                self.log(f"  - 신호 발생: {true_count}회")
                
                # Visual feedback
                self.text_formula_preview.setStyleSheet("border: 2px solid #00cc66;")
                print("[DEBUG] Validation Success")
            else:
                self.log("⚠️ 'cond' 변수가 생성되지 않았습니다.")
                self.text_formula_preview.setStyleSheet("border: 2px solid #ff9900;")
                print("[DEBUG] 'cond' variable missing")
                
        except Exception as e:
            self.log(f"❌ 코드 검증 실패: {e}")
            self.text_formula_preview.setStyleSheet("border: 2px solid #cc3333;")
            import traceback
            self.log(f"상세 오류:\n{traceback.format_exc()}")
            print(f"[DEBUG] Error: {e}")
            print(traceback.format_exc())
