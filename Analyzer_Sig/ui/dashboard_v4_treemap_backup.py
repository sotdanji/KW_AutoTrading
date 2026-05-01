import sys
import os
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.font_manager as fm
import matplotlib.patches as patches
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

import time
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QPushButton, QFrame, QComboBox, QTabWidget, QMessageBox, QApplication, QProgressBar, QTextEdit
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QCursor, QColor, QTextCursor

from core.market_engine import MarketEngine as MarketAnalyzer
from core.integrator import AT_SigIntegrator
from config import ACCOUNT_MODE
from core.settings import get_kw_setting, update_kw_setting
from core.db_manager import DBManager
from ui.history_widget import HistoryWidget
from ui.signal_history_dialog import SignalHistoryDialog


from core.logger import get_logger

# 로거 초기화
logger = get_logger(__name__)
from PyQt6.QtWidgets import (QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QComboBox, QMessageBox, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)

# Set Hangul Font for Matplotlib (Windows)
try:
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if os.path.exists(font_path):
        font_prop = fm.FontProperties(fname=font_path)
        matplotlib.rc('font', family=font_prop.get_name())
        matplotlib.rcParams['axes.unicode_minus'] = False # Fix minus sign issue
except:
    pass

import logging

class LogSignal(QObject):
    msg = pyqtSignal(str)

class QThandler(logging.Handler):
    def __init__(self, slot):
        super().__init__()
        self.log_signal = LogSignal()
        self.log_signal.msg.connect(slot)
        self.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', '%H:%M:%S'))

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.msg.emit(msg)

class StartupThread(QThread):
    """
    Application Startup Task (Heavy Lifting)
    Runs PreMarketLoader to fetch/load historical data.
    """
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer

    def run(self):
        try:
            self.status_signal.emit("V4 Top-Down 엔진 초기화 중...")
            self.analyzer.initialize_loader()
            
            self.status_signal.emit("V4 엔진 준비 완료.")
            self.finished_signal.emit(True)
        except Exception as e:
            logger.error(f"Startup Thread Failed: {e}")
            self.status_signal.emit(f"초기화 오류: {e}")
            self.finished_signal.emit(False)


class DataThread(QThread):
    data_ready = pyqtSignal(dict)
    status_signal = pyqtSignal(str)

    def __init__(self, analyzer, sector_state, theme_state):
        super().__init__()
        self.analyzer = analyzer
        self.sector_state = sector_state # {"view": "Overview", "selected": None}
        self.theme_state = theme_state   # {"view": "Overview", "selected": None}
        self._stop_flag = False


    def run(self):
        
        try:
            # 상위 10개 테마 캐싱 조회 (트리맵/Top 2용)
            themes_raw = self.analyzer.get_themes_cached()
            
            # Extract System Alerts if present
            system_alerts = []
            themes = []
            for t in themes_raw:
                if t.get('is_system_alert'):
                    system_alerts.extend(t.get('messages', []))
                else:
                    themes.append(t)
            
            # [DataFetcher] 이미 Smart Ranking(2-Stage)으로 정렬된 상태
            # 별도의 정렬을 수행하지 않고 그대로 사용함
            # themes = sorted(themes, key=lambda x: x['change'], reverse=True)
            
            # 통계용 전체 테마 조회 (V3: Radar 스냅샷에서 추출)
            all_themes = self.analyzer.get_all_themes_for_stats()
            
            # 트리맵에는 상위 8개 테마만 표시
            top8_themes = themes[:8]
            
            # Top 3 테마 실시간 감시 (우측 패널) - V4: 점수 기준 상위 3개 (하락장에서도 노출)
            top3_themes = themes[:3]
            top3_data = []
            
            for i, theme in enumerate(top3_themes):
                t_name = theme['name']
                t_stocks = self.analyzer.get_theme_stocks_direct(t_name)
                
                # 등락률 순 정렬
                if t_stocks:
                    t_stocks.sort(key=lambda x: x.get('change', 0), reverse=True)
                
                top3_data.append({
                    "rank": i + 1,
                    "name": t_name,
                    "change": theme['change'],
                    "stocks": t_stocks
                })
            # Selected Theme Drilldown Logic
            drilldown_data = []
            target_theme = None
            
            if self.theme_state and self.theme_state.get("selected"):
                target_theme = self.theme_state["selected"]
                drilldown_data = self.analyzer.get_theme_stocks_direct(target_theme)
            
            # [NEW] 10분 등락률 추적 데이터 가져오기 (30종목)
            momentum_10min = self.analyzer.get_10min_momentum_data(limit=30)
            
            # 결과 구성 (섹터 제거)
            result = {
                "themes": top8_themes,
                "themes_all": all_themes,  # 통계용 전체 테마
                "theme_drilldown": drilldown_data,
                "target_theme": target_theme,
                "top3_themes_data": top3_data,
                "momentum_10min": momentum_10min,
                "system_alerts": system_alerts,
                "indices": self.analyzer.fetcher.get_market_indices()
            }
                
            self.data_ready.emit(result)
            
            # 성공 시 실패 카운트 리셋 (여기서는 지역 변수라 의미 없지만, 클래스 멤버로 관리한다면 필요)
            # self.failure_count = 0 
            
        except Exception as e:
            print(f"DataThread Error: {e}")
            self.status_signal.emit(f"FETCH_ERROR:{e}")
            




class MarketDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.debug("Dashboard __init__ start")
        # Load mode from local settings or config
        mode = get_kw_setting('data_mode', ACCOUNT_MODE)
        logger.debug(f"Dashboard init mode: {mode}")
        self.analyzer = MarketAnalyzer(mode=mode)
        self.integrator = AT_SigIntegrator()
        self.db_manager = DBManager()
        
        self.consecutive_failures = 0 # Track connection failures
        
        # 독립적인 뷰 상태 관리
        self.sector_state = {"view": "Overview", "selected": None}
        self.theme_state = {"view": "Overview", "selected": None}
        
        self.rect_map = [] 
        self.current_data = {
            "sectors": [], "themes": [], 
            "sector_drilldown": [], "theme_drilldown": [],
            "size_indices": [] # 대형/중형/소형 데이터 저장소 추가
        } 
        self.data_thread = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.request_data_update)
        self.update_interval = 10000  # 타이머 interval 고정 (10초)
        
        # [NEW] Signal History Dialog
        self.signal_history_dlg = SignalHistoryDialog(self)
        
        self.init_ui()
        
        # Setup Logger
        self.log_handler = QThandler(self.append_log)
        logging.getLogger().addHandler(self.log_handler)
        
        # [NEW] Startup Sequence
        # 2. Run Startup Thread
        self.startup_thread = StartupThread(self.analyzer)
        self.startup_thread.status_signal.connect(self.update_status_message)
        self.startup_thread.finished_signal.connect(self.on_startup_finished)
        self.startup_thread.start()
        
    def update_status_message(self, msg):
        self.status_label.setText(msg)
        
    def on_startup_finished(self, success):
        if success:
            logger.info("Startup sequence completed successfully.")
            # Start regular data updates
            logger.debug("Requesting initial data update")
            self.request_data_update()
        else:
            QMessageBox.critical(self, "오류", "시스템 초기화 중 문제가 발생했습니다.\n로그를 확인해주세요.")



    def closeEvent(self, event):
        # 창이 닫힐 때 자원 정리
        if hasattr(self, 'log_handler'):
            logging.getLogger().removeHandler(self.log_handler)
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
        if hasattr(self, 'data_thread') and self.data_thread and self.data_thread.isRunning():
            # 즉시 종료 (대기 없음)
            logger.debug("Requesting data thread to stop")
            self.data_thread._stop_flag = True
            self.data_thread.quit()  # 이벤트 루프 종료 요청
            # 100ms만 대기 (거의 즉시)
            if not self.data_thread.wait(100):
                logger.warning("Data thread did not finish quickly, terminating")
                self.data_thread.terminate()
        event.accept()

    def append_log(self, text):
        if hasattr(self, 'log_viewer'):
            # HTML Coloring for System Alerts
            if "🔥 초기폭발 감지" in text:
                text = f'<span style="color: #FF5252; font-weight: bold;">{text}</span>'
            elif "💧 낙수효과 포착" in text:
                text = f'<span style="color: #00E5FF; font-weight: bold;">{text}</span>'
            elif "ERROR" in text or "Exception" in text:
                text = f'<span style="color: #FF7043;">{text}</span>'
            else:
                text = f'<span style="color: #A0A0A0;">{text}</span>'
                
            self.log_viewer.append(text)
            doc = self.log_viewer.document()
            if doc.blockCount() > 500:
                cursor = self.log_viewer.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()

    def init_ui(self):
        self.setWindowTitle("Lead_Sig: 주도주 발굴 시스템 (Market Analyzer)")
        self.resize(1280, 800) # 가로를 조금 더 넓게
        self.setStyleSheet("background-color: #121212; color: white;")

        # Main Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main Layout (Horizontal: Sidebar | Content)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 1. Left Sidebar ===
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background-color: #1E1E1E; border-right: 1px solid #333;")
        
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(15)

        # [Title Section]
        # 1. Brand (Sotdanji Lab)
        brand_label = QLabel("Sotdanji Lab")
        brand_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_label.setStyleSheet("font-size: 14px; color: #888; font-weight: bold; margin-bottom: 2px;")
        sidebar_layout.addWidget(brand_label)

        # 2. Product Name (Lead_Sig)
        prod_label = QLabel("Lead_Sig")
        prod_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prod_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00E5FF; margin-bottom: 10px;")
        sidebar_layout.addWidget(prod_label)
        
        # 3. Description (Wrapped)
        desc_label = QLabel("주도주 발굴 시스템\n(Market Analyzer)")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True) # 줄바꿈 허용
        desc_label.setStyleSheet("color: #DDD; font-size: 14px; font-weight: bold; padding: 5px;")
        sidebar_layout.addWidget(desc_label)
        
        # [Control: Update Interval] (Horizontal)
        interval_layout = QHBoxLayout()
        lbl_interval = QLabel("갱신 주기")
        lbl_interval.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
        interval_layout.addWidget(lbl_interval)
        
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["5초", "10초", "15초", "30초", "1분"])
        self.interval_combo.currentIndexChanged.connect(self.change_interval)
        self.interval_combo.setCurrentIndex(1)
        self.interval_combo.setStyleSheet("""
            QComboBox {
                background-color: #333; color: #FFD700; padding: 5px; border-radius: 3px; font-weight: bold; border: 1px solid #444;
            }
            QComboBox::drop-down { border: 0px; }
        """)
        interval_layout.addWidget(self.interval_combo, 1) # Stretch
        sidebar_layout.addLayout(interval_layout)

        # [Control: Data Mode] (Horizontal)
        mode_layout = QHBoxLayout()
        lbl_mode = QLabel("데이터 모드")
        lbl_mode.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
        mode_layout.addWidget(lbl_mode)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["시뮬레이션", "실시간"])
        # Fix: Use the actual initialized mode from analyzer, not the global default constant
        current_mode = self.analyzer.fetcher.mode
        self.mode_combo.setCurrentIndex(0 if current_mode == "PAPER" else 1)
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #333; color: #00E5FF; padding: 5px; border-radius: 3px; font-weight: bold; border: 1px solid #444;
            }
            QComboBox::drop-down { border: 0px; }
        """)
        self.mode_combo.currentIndexChanged.connect(self.change_mode)
        mode_layout.addWidget(self.mode_combo, 1) # Stretch
        sidebar_layout.addLayout(mode_layout)

        # [Separator]
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setFrameShadow(QFrame.Shadow.Sunken)
        line1.setStyleSheet("background-color: #333; margin: 10px 0;")
        sidebar_layout.addWidget(line1)

        # [Market Indices Panel] (Moved from center)
        # 지수 라벨 초기화 및 배치
        self.index_labels = {}
        index_names = ["KOSPI", "KOSPI 200", "KOSDAQ", "KOSDAQ 150", "Futures"]
        
        for name in index_names:
            box = QFrame()
            box.setStyleSheet("background-color: #383838; border: 1px solid #555555; border-radius: 4px;")
            blayout = QVBoxLayout(box)
            blayout.setContentsMargins(8, 6, 8, 6)
            blayout.setSpacing(2)
            
            # Name
            idx_title = QLabel(name)
            idx_title.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold;")
            blayout.addWidget(idx_title)
            
            # Row for Price and Change
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            
            price = QLabel("-")
            price.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
            row.addWidget(price)
            
            row.addStretch()
            
            change = QLabel("-")
            change.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            change.setStyleSheet("color: #AAAAAA; font-size: 11px;")
            row.addWidget(change)
            
            blayout.addLayout(row)
            
            sidebar_layout.addWidget(box)
            self.index_labels[name] = {"price": price, "change": change}

        # [Separator]
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setStyleSheet("background-color: #333; margin: 10px 0;")
        sidebar_layout.addWidget(line2)

        # [NEW: Signal History Button]
        self.btn_signal = QPushButton("🚨 시그널 히스토리")
        self.btn_signal.setFixedHeight(35)
        self.btn_signal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_signal.setStyleSheet("""
            QPushButton { 
                background-color: #4A148C; 
                color: #FFF; 
                border: 1px solid #7B1FA2; 
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { 
                background-color: #6A1B9A; 
            }
        """)
        self.btn_signal.clicked.connect(self.signal_history_dlg.show)
        sidebar_layout.addWidget(self.btn_signal)

        # [Bottom: Status & Exit]
        self.status_label = QLabel("시스템 대기 중")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold; margin-top: 5px;")
        sidebar_layout.addWidget(self.status_label)

        # [Bottom Buttons Container]
        bottom_btn_layout = QHBoxLayout()
        bottom_btn_layout.setSpacing(5)

        # Exit Button (Resized)
        self.exit_btn = QPushButton(" 종료")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setFixedHeight(40) # 높이 조금 줄임
        self.exit_btn.setStyleSheet("""
            QPushButton { 
                background-color: #d32f2f; 
                color: white; 
                border: 1px solid #c62828; 
                border-radius: 4px;
                font-weight: bold; 
                font-size: 14px; 
            }
            QPushButton:hover { 
                background-color: #ff5252; 
                border: 1px solid #ff867c;
            }
            QPushButton:pressed { 
                background-color: #b71c1c; 
            }
        """)
        self.exit_btn.clicked.connect(QApplication.instance().quit)
        
        # Pin Button (Moved here)
        self.top_btn = QPushButton("📌")
        self.top_btn.setCheckable(True)
        self.top_btn.setToolTip("항상 위에 표시 (Pin Window)")
        self.top_btn.setFixedSize(40, 40) # 종료 버튼 높이와 맞춤
        self.top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top_btn.setStyleSheet("""
            QPushButton { 
                background-color: #2D2D2D; border: 1px solid #444; border-radius: 4px; font-size: 16px;
            }
            QPushButton:checked { background-color: #00E5FF; color: black; border-color: #00E5FF; }
            QPushButton:hover { background-color: #3D3D3D; }
        """)
        self.top_btn.clicked.connect(self.toggle_always_on_top)

        # Add buttons to layout (Exit takes more space)
        bottom_btn_layout.addWidget(self.exit_btn, 1) # Stretch factor 1
        bottom_btn_layout.addWidget(self.top_btn, 0)  # Fixed size
        
        sidebar_layout.addLayout(bottom_btn_layout)

        # Add Sidebar to Main Layout
        main_layout.addWidget(sidebar)

        # === 2. Right Content Area (Tabs) ===
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(0)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; background-color: #121212; }
            QTabBar::tab {
                background: #1E1E1E; color: #888; padding: 10px 20px;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
                font-weight: bold; font-size: 13px;
            }
            QTabBar::tab:selected {
                background: #2D2D2D; color: #00E5FF; border-bottom: 2px solid #00E5FF;
            }
            QTabBar::tab:hover {
                background: #252525; color: #DDD;
            }
        """)
        content_layout.addWidget(self.tabs)
        main_layout.addWidget(content_area)

        # === Master-Detail Layout Setup ===
        
        # --- Tab 1: 전광판 (Market Watch) ---
        self.tab_watch = QWidget()
        self.tabs.addTab(self.tab_watch, "📊 전광판 (Market Watch)")
        
        # === Master Layout (Split H) ===
        main_watch_layout = QHBoxLayout(self.tab_watch)
        main_watch_layout.setContentsMargins(5, 5, 5, 5)
        main_watch_layout.setSpacing(10)
        
        # === 1. Left Area (Interactive Map + Detail) ===
        left_area = QWidget()
        left_layout = QVBoxLayout(left_area)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        
        # 1-1. Theme Map (Top)
        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header
        theme_header = QHBoxLayout()
        theme_header.addStretch(1)
        self.header_theme_label = QLabel("주요 테마 (Themes)")
        self.header_theme_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #FFD700;")
        theme_header.addWidget(self.header_theme_label)
        theme_header.addSpacing(15)
        self.breadth_theme_label = QLabel("-")
        self.breadth_theme_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        theme_header.addWidget(self.breadth_theme_label)
        theme_header.addStretch(1)
        map_layout.addLayout(theme_header)
        
        # Canvas
        self.canvas_right = FigureCanvas(Figure(figsize=(10, 6), facecolor='#121212'))
        self.ax_right = self.canvas_right.figure.add_subplot(111)
        self.ax_right.set_axis_off()
        self.canvas_right.figure.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
        self.canvas_right.mpl_connect('button_press_event', self.on_click)
        self.canvas_right.mpl_connect('motion_notify_event', self.on_hover)
        map_layout.addWidget(self.canvas_right)
        
        left_layout.addWidget(map_container, 6) # Map takes 55% height of left
        
        # 1-2. Theme Detail (Middle)
        self.panel_theme = self.create_detail_sub_panel("선택 테마 상세 (Detail)", "theme")
        left_layout.addWidget(self.panel_theme, 3) # Detail takes 27% height of left

        # 1-3. Log viewer (Bottom)
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(2)
        
        log_tool_layout = QHBoxLayout()
        log_tool_layout.setContentsMargins(2, 2, 2, 2)
        
        log_header = QLabel("📝 실행 로그")
        log_header.setStyleSheet("color: #AAA; font-weight: bold; font-size: 13px;")
        log_tool_layout.addWidget(log_header)
        
        log_tool_layout.addStretch()

        btn_style = """
            QPushButton {
                background-color: #333333; 
                color: #ffffff; 
                border: 1px solid #555555; 
                border-radius: 4px; 
                font-weight: bold; 
                font-size: 11px;
                padding: 1px 4px;
            }
            QPushButton:hover {
                background-color: #444444;
                border: 1px solid #777777;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
        """

        btn_clear_log = QPushButton("지우기")
        btn_clear_log.setFixedSize(50, 20)
        btn_clear_log.clicked.connect(lambda: self.log_viewer.clear())
        btn_clear_log.setStyleSheet(btn_style)
        btn_clear_log.setCursor(Qt.CursorShape.PointingHandCursor)
        log_tool_layout.addWidget(btn_clear_log)
        
        log_layout.addLayout(log_tool_layout)
        
        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setStyleSheet("""
            QTextEdit {
                background-color: #1A1A1A; 
                color: #A0A0A0; 
                font-family: Consolas, monospace; 
                font-size: 13px; 
                border: 1px solid #333;
                padding: 4px;
            }
        """)
        log_layout.addWidget(self.log_viewer)
        
        left_layout.addWidget(log_container, 2) # Log takes 18% height of left

        main_watch_layout.addWidget(left_area, 6) # Left Area takes 60% width

        # === 2. Right Area (Auto Monitor Top 3) ===
        right_area = QWidget()
        right_layout = QVBoxLayout(right_area)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        
        # Header for Right
        r_header = QLabel("🔥 실시간 주도 테마 (Top 3)")
        r_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_header.setStyleSheet("color: #FF5252; font-size: 15px; font-weight: bold; margin-bottom: 5px;")
        right_layout.addWidget(r_header)
        
        # Create 3 Auto Panels (Fixed)
        self.auto_panels = []
        for i in range(3):
            panel = self.create_auto_monitor_panel(i + 1)
            right_layout.addWidget(panel, 1) # Equal heights
            self.auto_panels.append(panel)
            
        main_watch_layout.addWidget(right_area, 4) # Right Area takes 40% width

        # --- Tab 2: 10분 등락률 (10Min Momentum) ---
        self.tab_momentum = QWidget()
        self.tabs.addTab(self.tab_momentum, "⏱️ 10분 등락률 (10Min Momentum)")
        
        momentum_layout = QHBoxLayout(self.tab_momentum)
        momentum_layout.setContentsMargins(10, 10, 10, 10)
        momentum_layout.setSpacing(10)
        
        # Helper: Create momentum table panel
        def create_momentum_table(titleText):
            container = QWidget()
            container.setStyleSheet("background-color: #2D2D2D; border-radius: 6px;")
            l = QVBoxLayout(container)
            l.setContentsMargins(5, 5, 5, 5)
            
            title = QLabel(titleText)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
            l.addWidget(title)
            
            table = QTableWidget()
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels(["No.", "종목명", "현재가", "등락률"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, 35) # Rank
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) # Name
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Price
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Change
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setStyleSheet("""
                QTableWidget { background-color: #1E1E1E; gridline-color: #333; border: 0; }
                QHeaderView::section { background-color: #2D2D2D; color: white; border: 1px solid #333; padding: 2px; font-weight: bold; }
                QTableWidget::item { padding: 2px; font-size: 12px; }
            """)
            l.addWidget(table)
            return container, table

        # 4개의 테이블 생성 (1x4 가로 배치)
        container1, self.table_past_vol = create_momentum_table("10분전 거래량 Top")
        container2, self.table_curr_vol = create_momentum_table("현재 거래량 Top")
        container3, self.table_past_val = create_momentum_table("10분전 거래대금 Top")
        container4, self.table_curr_val = create_momentum_table("현재 거래대금 Top")
        
        momentum_layout.addWidget(container1, 1)
        momentum_layout.addWidget(container2, 1)
        momentum_layout.addWidget(container3, 1)
        momentum_layout.addWidget(container4, 1)

        # --- Tab 3: 추적실 (Tracking Room) ---
        self.history_widget = HistoryWidget(self.db_manager, self.analyzer)
        self.tabs.addTab(self.history_widget, "🕵️ 추적실 (Tracking Room)")
        
        # 탭 변경 이벤트 연결 (추적실 진입 시 데이터 자동 갱신)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        # Tooltip (Floating)
        self.tooltip = QLabel(self)
        self.tooltip.setStyleSheet("background-color: rgba(0, 0, 0, 220); color: white; padding: 6px; border: 1px solid #777; border-radius: 4px; font-size: 12px;")
        self.tooltip.hide()
        
    def create_auto_monitor_panel(self, rank):
        """Create a fixed panel for auto-monitoring Top 1/2/3 themes"""
        frame = QFrame()
        frame.setStyleSheet("background-color: #2D2D2D; border: 1px solid #444; border-radius: 6px;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # Header (Rank + Name + Change)
        header = QHBoxLayout()
        rank_lbl = QLabel(f"{rank}위")
        rank_lbl.setFixedSize(30, 20)
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setStyleSheet("background-color: #FFD700; color: black; border-radius: 3px; font-weight: bold; font-size: 11px;")
        
        name_lbl = QLabel("-")
        name_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 13px; margin-left: 5px;")
        
        change_lbl = QLabel("-")
        change_lbl.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 12px;")
        
        layout.addLayout(header)
        
        # Table (Mini List)
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["신호", "종목명", "현재가", "등락률"])
        
        # 0: Signal (Fixed, Small)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 30) # 신호 아이콘 공간 축소
        
        # 1: Name (Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        # 2,3: Content
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(3, 50) # 등락률 폭 고정
        
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(20) # 행 높이 축소 (10개 노출용)
        table.setStyleSheet("""
            QTableWidget { background-color: #1E1E1E; gridline-color: #2D2D2D; border: 0; outline: none; }
            QHeaderView::section { background-color: #252526; color: #BBB; padding: 1px; border: 0; font-size: 10px; font-weight: bold; }
            QTableWidget::item { padding: 0px 2px; font-size: 11px; }
        """)
        
        # Disable Scrollbars for Clean Look (If 10 rows fit)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        layout.addWidget(table)
        
        # Store references to widgets for updating data later
        frame.widgets = {
            "name": name_lbl,
            "change": change_lbl,
            "table": table
        }
        
        return frame

    def create_detail_sub_panel(self, title, panel_type):
        """Create a detail sub-panel (Theme Detail)""" # Refactored generic panel creator
        container = QWidget()
        container.setStyleSheet("background-color: #2D2D2D; border-radius: 8px;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        
        # 1. Header (Title + Batch Buttons)
        header_layout = QHBoxLayout()
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: bold;")
        header_layout.addWidget(lbl_title)
        header_layout.addStretch()

        # Auto Reset Button (Initially Hidden)
        btn_reset = QPushButton("🔄 자동")
        btn_reset.setFixedSize(60, 24)
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setToolTip("자동 모드로 복귀 (1위 항목 표시)")
        btn_reset.hide()
        btn_reset.setStyleSheet("""
            QPushButton { background-color: #004444; color: #00E5FF; border: 1px solid #00E5FF; border-radius: 4px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background-color: #006666; }
        """)
        btn_reset.clicked.connect(lambda: self.reset_panel_selection(panel_type))
        header_layout.addWidget(btn_reset)

        
        # Batch Buttons
        btn_db = QPushButton("💾 저장(DB)")
        btn_db.setFixedSize(85, 24)
        btn_db.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_db.setStyleSheet("""
            QPushButton { background-color: #333; color: #DDD; border: 1px solid #555; border-radius: 4px; font-size: 11px; }
            QPushButton:hover { background-color: #444; border-color: #DDD; }
        """)
        btn_db.clicked.connect(lambda: self.add_batch_stocks(target="db", source=panel_type))
        header_layout.addWidget(btn_db)

        btn_at = QPushButton("⚡ 감시+저장")
        btn_at.setFixedSize(85, 24)
        btn_at.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_at.setStyleSheet("""
            QPushButton { background-color: #444; color: #00E5FF; border: 1px solid #555; border-radius: 4px; font-size: 11px; font-weight: bold; }
            QPushButton:hover { background-color: #555; border-color: #00E5FF; }
        """)
        btn_at.clicked.connect(lambda: self.add_batch_stocks(target="atsig", source=panel_type))
        header_layout.addWidget(btn_at)
        
        layout.addLayout(header_layout)
        
        # 2. Content (Table + Chart) Split H
        content_split = QHBoxLayout()
        # Table Left
        # ... logic will be set in update_single_panel ...
        # Let's try Horizontal but compacted.
        
        content_layout = QHBoxLayout()
        
        # Table
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["신호", "종목명", "현재가", "등락률"])
        
        # 0: Signal (Fixed, Small)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 35)
        
        # 1: Name (Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        # 2: Price (Fixed, 75)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(2, 75)
        
        # 3: Rate (Fixed, 65)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(3, 65)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch) # Rows fill height
        table.setStyleSheet("""
            QTableWidget { background-color: #1E1E1E; gridline-color: #333; border: none; }
            QHeaderView::section { background-color: #2D2D2D; color: white; border: 1px solid #333; padding: 2px; }
            QTableWidget::item { padding: 2px; }
            QTableWidget::item { padding: 2px; }
            QTableWidget::item:selected { background-color: #0055aa; }
        """)
        
        # Click Behavior Settings
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        
        # Store reference
        if panel_type == "sector":
            self.table_sector = table
            self.lbl_sector_title = lbl_title
            self.btn_sector_db = btn_db
            self.btn_sector_at = btn_at
            self.btn_sector_reset = btn_reset
        else:
            self.table_theme = table
            self.lbl_theme_title = lbl_title
            self.btn_theme_db = btn_db
            self.btn_theme_at = btn_at
            self.btn_theme_reset = btn_reset
            
        table.itemClicked.connect(lambda item, t=table: self.on_mini_table_click(t, item.row(), item.column()))
        
        # Add Table to Split
        content_split.addWidget(table, 6) # Table 60%

        # Chart (Right Side of Split)
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        
        canvas = FigureCanvas(Figure(figsize=(5, 3), facecolor='#2D2D2D'))
        ax = canvas.figure.add_subplot(111)
        ax.set_facecolor('#2D2D2D')
        
        # Hide Spines
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis='x', colors='#888', labelsize=8)
        ax.tick_params(axis='y', colors='#888', labelsize=8)
        
        chart_layout.addWidget(canvas)
        
        content_split.addWidget(chart_container, 4) # Chart 40%
        
        layout.addLayout(content_split)
        
        if panel_type == "sector":
            self.canvas_sector = canvas
            self.ax_sector = ax
        else:
            self.canvas_theme = canvas
            self.ax_theme = ax
            
        return container

    def update_auto_panels(self, top3_data):
        """Update the 3 auto-monitoring panels on the right (Expanded to 10 stocks + Role Icons)"""
        if not hasattr(self, 'auto_panels') or not top3_data:
            return

        for i, panel in enumerate(self.auto_panels):
            # Clear if no data for this rank
            if i >= len(top3_data):
                panel.widgets["name"].setText("-")
                panel.widgets["change"].setText("-")
                panel.widgets["table"].setRowCount(0)
                continue
                
            data = top3_data[i]
            
            # Update Header
            panel.widgets["name"].setText(data['name'])
            
            rate = data['change']
            color = "#FF5252" if rate > 0 else "#448AFF" if rate < 0 else "white"
            sign = "+" if rate > 0 else ""
            panel.widgets["change"].setText(f"{sign}{rate:.2f}%")
            panel.widgets["change"].setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")
            
            # Update Table
            stocks = data.get('stocks', [])
            if stocks is None: stocks = []
            
            
            table = panel.widgets["table"]
            table.setRowCount(0)
            
            # Show top 10 stocks (Catch Followers!)
            limit = 10
            for row_idx, stock in enumerate(stocks[:limit]):
                table.insertRow(row_idx)
                
                # Role Based Signal/Icon
                sig_type = stock.get('signal_type')
                role = stock.get('role', 'sleeper')
                
                lbl_sig = QLabel()
                lbl_sig.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                # Choice Icon
                if sig_type == "king": lbl_sig.setText("👑")
                elif sig_type == "breakout": lbl_sig.setText("🔴") 
                elif sig_type == "close": lbl_sig.setText("🔵")
                else:
                    # Role based icons
                    if role == 'leader_overheat': lbl_sig.setText("🔥")
                    elif role == 'leader': lbl_sig.setText("🚀")
                    elif role == 'target': lbl_sig.setText("🎯")
                    else: lbl_sig.setText("·")
                
                table.setCellWidget(row_idx, 0, lbl_sig)

                # Name (1) + Role Badge (Mini)
                name_widget = QWidget()
                name_layout = QHBoxLayout(name_widget)
                name_layout.setContentsMargins(2, 0, 2, 0)
                name_layout.setSpacing(2)
                
                display_name = stock['name']
                lbl_name = QLabel(display_name)
                lbl_name.setStyleSheet("color: white; font-size: 11px;")
                name_layout.addWidget(lbl_name)
                
                # Role Badge (Smaller than main detail)
                if role != 'sleeper':
                   role_name = stock.get('role_name', '대기')
                   lbl_role = QLabel(role_name[:2]) # 2 letters (대장, 후발 등)
                   r_style = "font-size: 8px; border-radius: 2px; padding: 0px 2px; font-weight: bold; color: white;"
                   if role == 'leader_overheat': r_style += "background-color: #D32F2F;"
                   elif role == 'leader': r_style += "background-color: #E64A19;"
                   elif role == 'target': r_style += "background-color: #2E7D32;"
                   lbl_role.setStyleSheet(r_style)
                   name_layout.addWidget(lbl_role)

                name_layout.addStretch()
                table.setCellWidget(row_idx, 1, name_widget)
                
                # Price (2)
                item_price = QTableWidgetItem(f"{stock['price']:,}")
                item_price.setForeground(QColor("white"))
                item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_idx, 2, item_price)
                
                # Rate (3)
                s_rate = stock['change']
                lbl_rate = QLabel(f"{s_rate:+.2f}%")
                lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl_rate.setFixedWidth(45)
                
                if s_rate > 0:
                    bg_col = "#CC3333" if role != 'target' else "#2E7D32" # Target uses green BG
                elif s_rate < 0:
                    bg_col = "#3333CC"
                else:
                    bg_col = "#1E1E1E"
                    
                lbl_rate.setStyleSheet(f"background-color: {bg_col}; color: white; border-radius: 3px; font-weight: bold; font-size: 10px;")
                table.setCellWidget(row_idx, 3, lbl_rate)

                # [Auto Save] Signal or Target Role
                if sig_type in ["king", "breakout", "close"] or role == 'target':
                    self.db_manager.add_watched_stock(
                        code=stock['code'],
                        name=stock['name'],
                        sector=data['name'], 
                        price=stock['price'],
                        signal_type=sig_type if sig_type else role
                    )


    def request_data_update(self):
        logger.debug("request_data_update called")
        if self.data_thread and self.data_thread.isRunning():
            logger.debug("Data thread already running, skipping")
            return
            
        # [Sync Check] 실시간 시세 데이터 갱신 요청
        self.data_thread = DataThread(self.analyzer, self.sector_state, self.theme_state)
        self.data_thread.data_ready.connect(self.on_data_received)
        self.data_thread.status_signal.connect(self.update_status_message)
        self.data_thread.start()

    def on_data_received(self, data_dict):
        self.current_data.update(data_dict)
        self.draw_treemap()
        self.update_breadth_display() # 종목수 통계 업데이트
        self.update_index_display()   # 시장 지수 업데이트
        self.update_ticker_display()  # 사이즈 지수(전광판) 업데이트 (NEW)
        
        # 첫 데이터 수신 후 타이머 시작 (아직 시작 안 했으면)
        if not self.timer.isActive():
            self.timer.start(self.update_interval)
            logger.debug(f"Timer started after initial data load ({self.update_interval}ms)")
        
        # 하단 상세 패널 업데이트 (자동 선택 또는 사용자 선택)
        # Sector Panel Removed
        
        # [NEW] 10분 등락률 (Momentum) 업데이트
        if 'momentum_10min' in data_dict:
            m_data = data_dict['momentum_10min']
            
            def _fill_table(table, items):
                table.setRowCount(0)
                for i, row_data in enumerate(items):
                    table.insertRow(i)
                    
                    # 1. Rank (No)
                    lbl_rank = QLabel(f"{i+1}")
                    lbl_rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl_rank.setStyleSheet("background-color: #333; color: white; border-radius: 2px;")
                    table.setCellWidget(i, 0, lbl_rank)
                    # 2. Name + Smart Money Badges
                    name_widget = QWidget()
                    name_layout = QHBoxLayout(name_widget)
                    name_layout.setContentsMargins(2, 0, 2, 0)
                    name_layout.setSpacing(2)
                    
                    lbl_name = QLabel(str(row_data.get('name', '')))
                    lbl_name.setStyleSheet("color: white;")
                    name_layout.addWidget(lbl_name)
                    
                    # Smart Money Badges
                    f_net = row_data.get('foreign_net', 0)
                    i_net = row_data.get('inst_net', 0)
                    
                    if f_net > 0:
                        lbl_f = QLabel("외")
                        lbl_f.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
                        name_layout.addWidget(lbl_f)
                    if i_net > 0:
                        lbl_i = QLabel("기")
                        lbl_i.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
                        name_layout.addWidget(lbl_i)
                        
                    name_layout.addStretch()
                    table.setCellWidget(i, 1, name_widget)
                    
                    # 3. Price
                    price_val = row_data.get('price', 0)
                    item_price = QTableWidgetItem(f"{price_val:,}")
                    item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(i, 2, item_price)
                    
                    # 4. Change Rate
                    rate_val = row_data.get('change', 0.0)
                    lbl_rate = QLabel(f"{rate_val:.2f}%")
                    lbl_rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    color = "#FF5252" if rate_val > 0 else "#448AFF" if rate_val < 0 else "white"
                    lbl_rate.setStyleSheet(f"color: {color}; font-weight: bold;")
                    table.setCellWidget(i, 3, lbl_rate)
                    
            if hasattr(self, 'table_past_vol') and m_data:
                _fill_table(self.table_past_vol, m_data.get('past_vol', []))
                _fill_table(self.table_curr_vol, m_data.get('curr_vol', []))
                _fill_table(self.table_past_val, m_data.get('past_val', []))
                _fill_table(self.table_curr_val, m_data.get('curr_val', []))
            
        if "theme_drilldown" in data_dict:
            target = data_dict.get("target_theme", "Unknown")
            self.lbl_theme_title.setText(f"주요 테마: {target}")
            self.update_single_panel(data_dict["theme_drilldown"], "theme")

        # [NEW] Right side Auto Panels Update
        if "top3_themes_data" in data_dict:
            self.update_auto_panels(data_dict["top3_themes_data"])

        # [NEW] System Alerts
        if "system_alerts" in data_dict and data_dict["system_alerts"]:
            current_time = time.strftime('%H:%M:%S')
            for alert_msg in data_dict["system_alerts"]:
                self.append_log(alert_msg)
                
            # Update Option 4 (Signal History Dialog)
            self.signal_history_dlg.add_alerts(data_dict["system_alerts"], current_time)

        self.status_label.setText(f"마지막 업데이트: {time.strftime('%H:%M:%S')}")

    def update_index_display(self):
        """시장 지수 전광판 업데이트"""
        indices = self.current_data.get("indices", {})
        for name, data in indices.items():
            if name in self.index_labels:
                price_val = data.get("price", 0)
                change_val = data.get("change", 0)
                
                # 색상 결정 (상승 빨강 / 하락 파랑 / 보합 흰색)
                # 색상 결정 (상승 빨강 / 하락 파랑 / 보합 흰색) - 배경색 변경
                if change_val > 0:
                    bg_color = "#CC3333" # Red text box background
                    sign = "" # + 기호 생략
                elif change_val < 0:
                    bg_color = "#3333CC" # Blue text box background
                    sign = ""
                else:
                    bg_color = "transparent"
                    sign = ""
                
                self.index_labels[name]["price"].setText(f"{price_val:,.2f}")
                # Price Text Color: Always White
                self.index_labels[name]["price"].setStyleSheet(f"color: white; font-size: 15px; font-weight: bold;")
                
                self.index_labels[name]["change"].setText(f"{sign}{change_val:.2f}%")
                # Rate Text Color: White, Background: Red/Blue
                self.index_labels[name]["change"].setStyleSheet(f"color: white; background-color: {bg_color}; border-radius: 3px; padding: 2px; font-size: 12px; font-weight: bold;")

    def update_ticker_display(self):
        """사이즈 지수(대형/중형/소형) 전광판 업데이트"""
        size_data = self.current_data.get("size_indices", [])
        
        # Mapping: API Name -> Widget Label Key
        # Assuming names are "대형주", "중형주", "소형주"
        
        for item in size_data:
            name = item.get("name", "")
            change = item.get("change", 0)
            
            if name in self.ticker_labels:
                # 색상 결정
                # 색상 결정
                if change > 0:
                    bg_color = "#CC3333"
                elif change < 0:
                    bg_color = "#3333CC"
                else:
                    bg_color = "transparent"
                    
                label = self.ticker_labels[name]
                label.setText(f"{abs(change):.2f}%")
                label.setStyleSheet(f"color: white; background-color: {bg_color}; border-radius: 3px; padding: 2px; font-size: 12px; font-weight: bold;")

    def update_breadth_display(self):
        # 섹션별 통계 계산 로직 (전체 데이터 기반)
        def calculate(data_list, prefix=""):
            if not data_list: return f"{prefix} 상승:- 하락:- 보합:-"
            up = sum(1 for d in data_list if d.get('change', 0) > 0)
            down = sum(1 for d in data_list if d.get('change', 0) < 0)
            even = len(data_list) - up - down
            return f'<span style="color:#EEEEEE; font-size:13px;">{prefix}</span> <span style="color:#FF4444;">▲ {up}</span> <span style="color:#4444FF;">▼ {down}</span> <span style="color:#FFFFFF;">- {even}</span>'

        # 섹터 라벨 업데이트 (전체 섹터 기준) - REMOVED (UI Label deleted)
        # sector_data = self.current_data.get("sectors_all", [])
        # self.breadth_sector_label.setText(calculate(sector_data, "전체 섹터 중"))
        
        # 테마 라벨 업데이트 (전체 테마 기준)
        theme_data = self.current_data.get("themes_all", [])
        self.breadth_theme_label.setText(calculate(theme_data, "전체 테마 중"))

    def update_breadth(self, data_list):
        # breadth_label 제거됨
        pass

    def change_mode(self, index):
        mode = "PAPER" if index == 0 else "REAL"
        self.analyzer.fetcher.mode = mode
        update_kw_setting('data_mode', mode)
        self.status_label.setText(f"모드 변경: {mode}")
        self.request_data_update()

    def change_interval(self, index):
        intervals = [5000, 10000, 15000, 30000, 60000]  # 5초, 10초, 15초, 30초, 1분
        new_interval = intervals[index]
        self.update_interval = new_interval  # update_interval도 변경
        self.timer.setInterval(new_interval)
        
        # [Safety Check] 초기화 중 호출 시 status_label이 없을 수 있음
        if hasattr(self, 'status_label'):
            self.status_label.setText(f"갱신 주기 변경: {new_interval//1000}초")

    def on_tab_changed(self, index):
        if not hasattr(self, 'status_label') or not hasattr(self, 'tabs'):
            return
        self.status_label.setText(f"탭 전환: {self.tabs.tabText(index)}")
        self.request_data_update()

    def reset_panel_selection(self, panel_type):
        """수동 선택을 해제하고 자동 모드(1위 표시)로 복귀"""
        if panel_type == "sector":
            self.sector_state["selected"] = None
        else:
            self.theme_state["selected"] = None
            
        self.request_data_update()

    def reset_view(self, target):
        self.reset_panel_selection(target)

    def show_sectors(self):
        # 전체 초기화 (호환성 유지용)
        self.reset_view("sector")
        self.reset_view("theme")

    def on_click(self, event):
        """트리맵 클릭 이벤트 처리 (상세 정보 하단 패널 표시)"""
        # Fix: Removed ax_left support
        if event.inaxes != self.ax_right:
            return
            
        x, y = event.xdata, event.ydata
        if x is None or y is None: return

        target_name = None
        for patch, name, p_ax in self.rect_map:
            if p_ax != event.inaxes: continue
            if patch.contains(event)[0]:
                target_name = name
                break
        
        if not target_name: return
        
        # Only Theme Click is supported now
        logger.debug(f"Theme clicked: {target_name}")
        target_list = self.analyzer.get_lead_signals_for_theme(target_name)
        logger.debug(f"Received {len(target_list)} stocks for theme {target_name}")
        self.lbl_theme_title.setText(f"주요 테마: {target_name}")
        self.update_single_panel(target_list, "theme")
        self.theme_state["selected"] = target_name # Update State

    def update_single_panel(self, stock_list, panel_type):
        """Updates a specific detail panel (sector or theme) with data (Expanded to 10 stocks)"""
        # 1. Sort & Top 10
        sorted_list = sorted(stock_list, key=lambda x: x.get('rate', 0), reverse=True)
        top_stocks = sorted_list[:10]
        
        # Check Selection State & Toggle Reset Button
        if panel_type == "sector":
            is_manual = self.sector_state["selected"] is not None
            if is_manual: self.btn_sector_reset.show()
            else: self.btn_sector_reset.hide()
        else:
            is_manual = self.theme_state["selected"] is not None
            if is_manual: self.btn_theme_reset.show()
            else: self.btn_theme_reset.hide()
        
        # Save current list for batch add
        if panel_type == "sector":
            self.current_sector_list = top_stocks
            table = self.table_sector
            ax = self.ax_sector
            canvas = self.canvas_sector
        else:
            self.current_theme_list = top_stocks
            table = self.table_theme
            ax = self.ax_theme
            canvas = self.canvas_theme
        
        # 2. Update Table (Fixed 10 Rows)
        table.setRowCount(10)
        
        for i in range(10):
            if i < len(top_stocks):
                stock = top_stocks[i]
                
                # Check Status
                is_leader = stock.get('is_leader', False)
                is_caution = stock.get('is_caution', False)
                reason = stock.get('caution_reason', "")
                role = stock.get('role', 'sleeper')
                role_name = stock.get('role_name', '대기')
                
                # Construct Name with Icon
                display_name = stock.get('name', 'Unknown')
                if is_leader:
                    display_name = f"👑 {display_name}"
                elif is_caution:
                    display_name = f"⚠️ {display_name}"
                
                price = stock.get('price', 0)
                rate = stock.get('rate', 0)
                
                item_name = QTableWidgetItem(display_name)
                # Tooltip for Caution
                if is_caution and reason:
                   item_name.setToolTip(f"주의: {reason}")
                elif is_leader:
                    item_name.setToolTip("주도주 조건 충족 (거래대금/등락률/윗꼬리 양호)")

                item_price = QTableWidgetItem(f"{price:,}")
                item_price.setForeground(QColor("white"))
                
                # --- Rate Column as Styled Widget (Text Box style) ---
                container = QWidget()
                layout = QHBoxLayout(container)
                layout.setContentsMargins(2, 2, 2, 2) 
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                lbl_rate = QLabel(f"{rate:.2f}%")
                lbl_rate.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                if rate > 0:
                    style = "background-color: #CC3333; color: white; border-radius: 4px; font-weight: bold;"
                elif rate < 0:
                    style = "background-color: #3333CC; color: white; border-radius: 4px; font-weight: bold;"
                else:
                    style = "color: white; font-weight: bold;"
                
                lbl_rate.setStyleSheet(style)
                lbl_rate.setFixedHeight(20) 
                lbl_rate.setFixedWidth(55)  
                
                layout.addWidget(lbl_rate)
                
                # Signal (0) - Now includes Role Badge
                lbl_sig = QLabel()
                lbl_sig.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sig_type = stock.get('signal_type')
                
                # Use icon based on role if no specific signal
                if sig_type == "king": lbl_sig.setText("👑")
                elif sig_type == "breakout": lbl_sig.setText("🔴") 
                elif sig_type == "close": lbl_sig.setText("🔵")
                else:
                    # Role based icons
                    if role == 'leader_overheat': lbl_sig.setText("🔥")
                    elif role == 'leader': lbl_sig.setText("🚀")
                    elif role == 'target': lbl_sig.setText("🎯")
                    else: lbl_sig.setText("·")

                table.setCellWidget(i, 0, lbl_sig)
                
                # Name + Role Badge (1)
                name_widget = QWidget()
                name_layout = QHBoxLayout(name_widget)
                name_layout.setContentsMargins(2, 0, 2, 0)
                name_layout.setSpacing(4)
                
                lbl_name = QLabel(display_name)
                lbl_name.setStyleSheet("color: white;")
                name_layout.addWidget(lbl_name)
                
                # Role Badge
                if role != 'sleeper':
                    lbl_role = QLabel(role_name)
                    r_style = "font-size: 8px; border-radius: 2px; padding: 1px 3px; font-weight: bold; color: white;"
                    if role == 'leader_overheat': r_style += "background-color: #D32F2F;"
                    elif role == 'leader': r_style += "background-color: #E64A19;"
                    elif role == 'target': r_style += "background-color: #2E7D32;"
                    lbl_role.setStyleSheet(r_style)
                    name_layout.addWidget(lbl_role)

                # Smart Money Icons (Foreign/Inst)
                f_net = stock.get('foreign_net', 0)
                i_net = stock.get('inst_net', 0)
                if f_net > 0:
                    lbl_f = QLabel("외")
                    lbl_f.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
                    name_layout.addWidget(lbl_f)
                if i_net > 0:
                    lbl_i = QLabel("기")
                    lbl_i.setStyleSheet("background-color: #FF1744; color: white; border-radius: 2px; padding: 1px; font-size: 9px; font-weight: bold;")
                    name_layout.addWidget(lbl_i)
                    
                name_layout.addStretch()
                table.setCellWidget(i, 1, name_widget)
                
                # Price (2)
                table.setItem(i, 2, item_price)
                table.setCellWidget(i, 3, container)
                
            else:
                # Empty Row
                table.removeCellWidget(i, 0)
                table.setItem(i, 1, QTableWidgetItem(""))
                table.setItem(i, 2, QTableWidgetItem(""))
                table.removeCellWidget(i, 3)
            
        # 3. Update Mini Bar Chart (Fixed 10 Slots)
        ax.clear()
        
        # Ensure fixed vertical range for 10 items (0 to 9)
        ax.set_ylim(-0.6, 9.6) 
        
        if top_stocks:
            names = [s['name'] for s in top_stocks]
            rates = [s.get('rate', 0) for s in top_stocks]
            
            # Horizontal Bar
            y_pos = range(len(names))
            colors = []
            for s in top_stocks:
                r = s.get('rate', 0)
                role = s.get('role', '')
                if role == 'target': colors.append('#4CAF50') # Green for targets
                elif r > 0: colors.append('#FF4444')
                else: colors.append('#4444FF')
            
            ax.barh(y_pos, rates, color=colors, alpha=0.7)
            # ax.axis('off') # Hide all axes/ticks (Keep off for clean look)
            ax.axis('off')
            
            # Draw Zero Line (Reference)
            ax.axvline(0, color='#666', linewidth=1, linestyle='-')
            
            # Ensure 0 is centered or visible
            max_val = max([abs(r) for r in rates]) if rates else 0
            if max_val == 0:
                ax.set_xlim(-1, 1) # Force range for 0% case
            else:
                limit = max_val * 1.2
                ax.set_xlim(-limit, limit)

            ax.invert_yaxis() # Top rank at top
        else:
             ax.axis('off')
             ax.invert_yaxis()
        
        canvas.draw()
        
        # 4. Check Intersection Highlight
        self._highlight_intersection()

    def _highlight_intersection(self):
        """Highlight stocks present in BOTH sector and theme panels (Intersection)"""
        # Reset backgrounds first
        def reset_bg(table):
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    item = table.item(r, c)
                    if item: item.setBackground(QColor("#1E1E1E")) # Default BG

        if hasattr(self, 'table_sector'):
            reset_bg(self.table_sector)
        if hasattr(self, 'table_theme'):
            reset_bg(self.table_theme)
        
        # Get Codes
        sector_codes = {s['code'] for s in getattr(self, 'current_sector_list', [])}
        theme_codes = {s['code'] for s in getattr(self, 'current_theme_list', [])}
        
        intersection = sector_codes & theme_codes
        
        if not intersection:
            return
            
        # Apply Gold BG for Intersection
        gold_color = QColor("#554400") # Dark Gold Background
        
        def apply_highlight(table, current_list):
            for r, stock in enumerate(current_list):
                if stock['code'] in intersection:
                    for c in range(table.columnCount()):
                        item = table.item(r, c)
                        if item: item.setBackground(gold_color)

        if hasattr(self, 'table_sector'):
            apply_highlight(self.table_sector, getattr(self, 'current_sector_list', []))
        if hasattr(self, 'table_theme'):
            apply_highlight(self.table_theme, getattr(self, 'current_theme_list', []))

    def on_mini_table_click(self, table, row, col):
        # Debug Click
        # print(f"Table Clicked: Row={row}, Col={col}", file=sys.stderr)
        
        item = table.item(row, 0)
        if item:
            self.show_add_menu(item.text())

    def on_hover(self, event):
        try:
            # Fix: Only check ax_right, ax_left is removed
            if event.inaxes != self.ax_right:
                self.tooltip.hide()
                return

            found = False
            for patch, name, p_ax in self.rect_map:
                if p_ax != event.inaxes: continue
                
                cont, ind = patch.contains(event)
                if cont:
                    patch.set_edgecolor('#00E5FF')
                    patch.set_linewidth(2)
                    
                    # 모든 데이터 소스 검색
                    all_raw = (self.current_data["sectors"] + self.current_data["themes"] + 
                               self.current_data["sector_drilldown"] + self.current_data["theme_drilldown"])
                    item = next((d for d in all_raw if d['name'] == name), None)
                    
                    if item:
                        info = f"<b>{item['name']}</b><br>등락: {item['change']:+.2f}%"
                        self.tooltip.setText(info)
                        if hasattr(self, 'centralWidget') and self.centralWidget():
                            local_pos = self.centralWidget().mapFromGlobal(QCursor.pos())
                            self.tooltip.move(local_pos.x() + 15, local_pos.y() + 15)
                            self.tooltip.show()
                    found = True
                else:
                    patch.set_edgecolor('white')
                    patch.set_linewidth(1)
            
            if not found:
                self.tooltip.hide()
            
            # 갱신 타겟 결정 - Only Right Canvas exists
            self.canvas_right.draw_idle()
        except:
            pass

    def show_add_menu(self, stock_name):
        # Merge all current data lists for searching
        # Must include detail lists because treemap data might be just headlines
        detail_lists = getattr(self, 'current_sector_list', []) + getattr(self, 'current_theme_list', [])
        all_raw = (self.current_data["sectors"] + self.current_data["themes"] + 
                   self.current_data["sector_drilldown"] + self.current_data["theme_drilldown"] +
                   detail_lists)
                   
        stock_info = next((s for s in all_raw if s['name'] == stock_name), None)
        
        # Fallback: If still None, maybe name is different? But for now return.
        if not stock_info: 
            # print(f"Stock not found: {stock_name}", file=sys.stderr)
            return

        # 1. AT_Sig 감시 리스트 추가 질문
        reply = QMessageBox.question(self, '종목 포착', 
                                     f"'{stock_name}' 종목을 [AT_Sig 자동매매 감시 리스트]에 추가하시겠습니까?\n\n(Yes: 자동매매 감시 + DB 저장)\n(No: DB에만 관심종목으로 저장)\n(Cancel: 취소)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        
        if reply == QMessageBox.StandardButton.Yes:
            # AT_Sig 연동 + DB 저장
            result = self.integrator.add_to_watchlist(stock_info)
            self._save_to_db(stock_info) # DB 무조건 저장

            if result is True:
                QMessageBox.information(self, "완료", f"'{stock_name}' 종목이 감시 리스트와 로컬 DB에 추가되었습니다.")
            elif result == 'duplicate':
                QMessageBox.warning(self, "중복", "이미 감시 리스트에 존재하는 종목입니다. (DB 업데이트 완료)")
            elif result == 'missing':
                QMessageBox.information(self, "안내", "AT_Sig 폴더가 없어 로컬 DB에만 저장했습니다.")
            else:
                QMessageBox.critical(self, "오류", "리스트 저장 중 오류가 발생했습니다.")
        elif reply == QMessageBox.StandardButton.No:
            # DB에만 저장 질문
            db_reply = QMessageBox.question(self, '관심 저장', 
                                     f"그럼 '{stock_name}' 종목을 [로컬 관심 DB]에만 저장하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if db_reply == QMessageBox.StandardButton.Yes:
                self._save_to_db(stock_info)
                QMessageBox.information(self, "저장 완료", f"'{stock_name}' 종목이 로컬 관심 DB에 저장되었습니다.")

    def _save_to_db(self, stock_info):
        """DB 저장 헬퍼 함수"""
        if not hasattr(self, 'db_manager'): return
        
        code = stock_info.get('code', 'Unknown')
        name = stock_info.get('name', 'Unknown')
        # price 필드가 있으면 사용, 없으면 0 (이제 DataFetcher에서 price를 줌)
        price = stock_info.get('price', 0)
        signal_type = stock_info.get('signal_type', None)
        
        # 현재 화면 상태에 따라 섹터명 유추
        sector = "Unknown"
        if self.sector_state["selected"]:
            sector = self.sector_state["selected"]
        elif self.theme_state["selected"]:
            sector = self.theme_state["selected"]
            
        self.db_manager.add_watched_stock(code, name, sector, price, signal_type=signal_type)

    def add_batch_stocks(self, target="db", source="sector"):
        """현재 리스트의 모든 종목(Top 5)을 일괄 추가"""
        
        # Determine Source List
        if source == "sector":
            current_list = getattr(self, 'current_sector_list', [])
            title = "산업 섹터"
        else:
            current_list = getattr(self, 'current_theme_list', [])
            title = "주요 테마"
            
        if not current_list:
            QMessageBox.warning(self, "알림", f"{title} 패널에 추가할 종목 리스트가 없습니다.")
            return

        cnt = len(current_list)
        
        if target == "atsig":
            msg = f"[{title}] Top {cnt}개 종목을 모두
[⚡ AT_Sig 자동매매 감시 리스트]에 추가하시겠습니까?
(로컬 DB에도 자동 저장됩니다)

* 순위/등락률에 따라 매수 비중이 자동 조절됩니다."
        else:
            msg = f"[{title}] Top {cnt}개 종목을 모두
[💾 로컬 관심 DB]에만 저장하시겠습니까?"

        reply = QMessageBox.question(self, '일괄 추가', msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            added_cnt = 0
            dup_cnt = 0
            fail_cnt = 0
            
            for i, stock in enumerate(current_list):
                # 1. DB Add (Always)
                self._save_to_db(stock)
                
                # 2. AT_Sig Add (Optional)
                if target == "atsig":
                    # Calculate Smart Weight
                    rank = i + 1
                    rate = stock.get('rate', 0)
                    weight = self._calculate_weight(rank, rate)
                    
                    # Pass weight to integrator
                    stock_with_weight = stock.copy()
                    stock_with_weight['weight'] = weight
                    
                    res = self.integrator.add_to_watchlist(stock_with_weight)
                    
                    if res is True:
                        added_cnt += 1
                    elif res == 'duplicate':
                        dup_cnt += 1
                    else:
                        fail_cnt += 1
                else:
                    # DB Only counting
                    added_cnt += 1 
            
            # 결과 리포트
            if target == "atsig":
                msg = f"[{title}] 자동매매 감시 추가 완료!

- 신규 추가: {added_cnt}건
- 중복(이미 존재): {dup_cnt}건"
            else:
                msg = f"[{title}] 관심 DB 저장 완료!

- {cnt}개 종목이 추적실에 저장되었습니다."
                
            if fail_cnt > 0:
                msg += f"
- 실패: {fail_cnt}건"
                
            QMessageBox.information(self, "결과", msg)
    def draw_treemap(self):
        logger.debug("draw_treemap start")
        # 캔버스 초기화
        # self.ax_left.clear() # Removed
        # self.ax_left.set_axis_off()
        # self.ax_left.set_xlim(-1, 101)
        # self.ax_left.set_ylim(-1, 101)
        
        self.ax_right.clear()
        self.ax_right.set_axis_off()
        # 테두리 잘림 방지를 위해 Limit 확장 (-1 ~ 101)
        self.ax_right.set_xlim(-1, 101)
        self.ax_right.set_ylim(-1, 101)
            
        self.rect_map = [] 
        
        # 왼쪽 캔버스 (섹터) - REMOVED
        # if self.sector_state["view"] == "Overview":
        #    ...
            
        # 오른쪽 캔버스 (테마) - This is now the MAIN Map on the left
            
        # [New] Visual Balancing Algorithm
        # User Request: Max 20%, Min 4% per block for better readability
        # We process the top 8 themes to distribute 'visual area'
        current_themes = self.current_data.get("themes", [])
        if current_themes:
            # [Fix] Sort by momentum_score BEFORE balancing and drawing
            # This ensures that the 1st rank (highest score) always takes the primary/largest slot on the left.
            current_themes.sort(key=lambda x: x.get('momentum_score', 0.0), reverse=True)

            # 1. Calculate Raw Weights (Momentum Score based)
            # Use momentum_score for sizing to ensure Rank 1 is visually the largest.
            raw_values = [t.get('momentum_score', 1.0) for t in current_themes]
            
            total_raw = sum(raw_values)
            if total_raw > 0:
                shares = [v / total_raw for v in raw_values]
            else:
                shares = [1.0 / len(current_themes)] * len(current_themes)
                
            # 2. Iterative Clamping (Redistribute)
            # Max 20% (0.2), Min 4% (0.04)
            # 8 items: 0.04*8=0.32, 0.20*8=1.6. Range is valid.
            for _ in range(5): # 5 iterations usually sufficient
                # Clamp
                shares = [max(0.04, min(0.20, s)) for s in shares]
                # Normalize
                total_share = sum(shares)
                if total_share == 0: total_share = 1
                shares = [s / total_share for s in shares]
                
            # 3. Assign back to data
            for t, s in zip(current_themes, shares):
                t['visual_size'] = s
                
        # 오른쪽 캔버스 (테마)
        if self.theme_state["view"] == "Overview":
            self.header_theme_label.setText("주요 테마 (Themes)")
            self.header_theme_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #FFD700; padding: 5px;")
            logger.debug(f"Drawing themes: {len(self.current_data['themes'])} items")
            self._recursive_split(self.ax_right, self.current_data["themes"], 0, 0, 100, 100, True)
        else:
            self.header_theme_label.setText(f"테마 상세: {self.theme_state['selected']}")
            self.header_theme_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #00FF41; padding: 5px;")
            # Drilldown data usually doesn't have 'visual_size' calculated above, 
            # but _recursive_split will fallback to trade_value/etc. fine.
            self._recursive_split(self.ax_right, self.current_data["theme_drilldown"], 0, 0, 100, 100, True)
            
        self.canvas_right.draw()
        logger.debug("draw_treemap end")

    def _recursive_split(self, ax, data, x, y, w, h, vertical):
        # sys.stderr.write(f"split: len={len(data)}, x={x}, y={y}, w={w}, h={h}\n")
        if not data:
            return
        
        if len(data) == 1:
            item = data[0]
            color = self._get_color(item['change'])
            rect = patches.Rectangle((x, y), w, h, linewidth=1, edgecolor='white', facecolor=color, alpha=0.9)
            ax.add_patch(rect)
            self.rect_map.append((rect, item['name'], ax))
            
            # Text label - dynamic size based on rect size
            fs = min(w, h) / 10 + 6
            fs = max(min(fs, 14), 7)
            ax.text(x + w/2, y + h/2, f"{item['name']}\n{item['change']:.2f}%", 
                    color='white', weight='bold', ha='center', va='center', fontsize=fs)
            return

        # Modified Custom Treemap Logic
        # 1. Size: Use pre-calculated 'visual_size' (if balanced) or 'trade_value'
        # 2. Order: Input data is already sorted by 'Smart Ranking Score'. Keep this order.
        
        def get_size(item):
            # Prioritize Visual Balanced Size (calculated in draw_treemap)
            if item.get('visual_size', 0) > 0:
                return item['visual_size']
            # Fallback 1: Trade Value
            if item.get('trade_value', 0) > 0:
                return item['trade_value']
            # Fallback 2: Change * Volume
            return abs(item.get('change', 0)) * item.get('volume', 1)

        total_size = sum(get_size(d) for d in data)
        
        if total_size <= 0:
            split_idx = 1
            ratio = 1.0 / len(data)
        else:
            # First item size ratio
            first_size = get_size(data[0])
            ratio = first_size / total_size
            split_idx = 1
             
        # Guard against zero ratio (if first item has 0 value)
        if ratio <= 0.001: ratio = 0.001
        
        group1 = data[:split_idx]  # First (largest) item
        group2 = data[split_idx:]  # Rest
        
        if vertical:
            # Vertical split: group1 on LEFT, group2 on RIGHT
            new_w = w * ratio
            self._recursive_split(ax, group1, x, y, new_w, h, not vertical)
            self._recursive_split(ax, group2, x + new_w, y, w - new_w, h, not vertical)
        else:
            # Horizontal split: group1 on TOP, group2 on BOTTOM
            new_h = h * ratio
            # Top-left priority: vertical split -> LEFT is 1st. Horizontal split -> TOP is 1st.
            self._recursive_split(ax, group1, x, y + (h - new_h), w, new_h, not vertical)  # Top
            self._recursive_split(ax, group2, x, y, w, h - new_h, not vertical)  # Bottom

    def _get_color(self, change):
        # Premium Deep Palette
        if change > 0:
            intensity = min(change / 10, 1.0)
            return (0.1 + 0.8 * intensity, 0.05, 0.1) # Deep Crimson
        else:
            intensity = min(abs(change) / 10, 1.0)
            return (0.05, 0.1, 0.1 + 0.8 * intensity) # Deep Indigo

    def toggle_always_on_top(self, checked):
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show() # windowFlags 변경 후 show() 호출 필요

    def on_tab_changed(self, index):
        """탭 변경 시 호출되는 슬롯"""
        # 1번 탭(인덱스 1)이 추적실이라고 가정
        if index == 1 and hasattr(self, 'history_widget'):
            self.history_widget.load_data()

    def show_history_dialog(self):
        # 팝업 대신 탭으로 이동 (혹시 모를 구형 호출 대비)
        self.tabs.setCurrentIndex(1)
