from PyQt6.QtWidgets import QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QStatusBar, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor, QFont
from datetime import datetime

class StandardLogWindow(QTextEdit):
    """
    공용 로그 창 (프로젝트 전체에서 동일한 스타일 유지)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1b;
                color: #e0e0e0;
                border: 1px solid #3e3e3e;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # [안실장 픽스] 우클릭 복사 메뉴 및 텍스트 상호작용 강화
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        self.is_paused = False
        self.log_buffer = []

    def show_context_menu(self, pos):
        """로그창 우클릭 메뉴 (복사 기능 등)"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu(self)
        copy_action = QAction("선택 부분 복사", self)
        copy_action.triggered.connect(self.copy)
        
        copy_all_action = QAction("로그 전체 복사", self)
        copy_all_action.triggered.connect(self.copy_all_logs)
        
        clear_action = QAction("로그 지우기", self)
        clear_action.triggered.connect(self.clear)
        
        menu.addAction(copy_action)
        menu.addAction(copy_all_action)
        menu.addSeparator()
        menu.addAction(clear_action)
        menu.exec(self.mapToGlobal(pos))

    def copy_all_logs(self):
        """전체 로그 클립보드 복사"""
        self.selectAll()
        self.copy()
        # 선택 해제 (커서 끝으로)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)


    def set_paused(self, paused: bool):
        """로그 일시 정지 (정지 시 버퍼링, 재개 시 일괄 출력)"""
        self.is_paused = paused
        if not self.is_paused and self.log_buffer:
            # 쌓여있던 로그 한꺼번에 출력
            for msg in self.log_buffer:
                self.append(msg)
            self.log_buffer.clear()
            self.moveCursor(QTextCursor.MoveOperation.End)

    def append_log(self, message: str, color: str = None):
        """시간 표시와 함께 로그 추가 (키워드 자동 채색 지원)"""
        import html
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 기본 색상 로직 (안실장 표준)
        if not color:
            color = "#e0e0e0" # Default
            msg_str = str(message)
            if any(k in msg_str for k in ["오류", "실패", "Err", "⚠️", "❌", "⛔"]):
                color = "#ff3333" # Red
            elif "매도" in msg_str:
                color = "#ff6666" # Soft Red
            elif "매수" in msg_str:
                color = "#66aaff" # Soft Blue
            elif "포착" in msg_str or "시그널" in msg_str:
                color = "#ffff66" # Yellow
            elif "성공" in msg_str or "✅" in msg_str:
                color = "#00ff7f" # Spring Green
        
        safe_text = html.escape(str(message))
        fmt_msg = f'<span style="color:#aaaaaa;">[{timestamp}]</span> <span style="color:{color};">{safe_text}</span>'
            
        if self.is_paused:
            # 정지 모드일 때는 버퍼에 저장만 함
            self.log_buffer.append(fmt_msg)
            # 버퍼가 너무 커지는 것 방지 (최근 500개)
            if len(self.log_buffer) > 500:
                self.log_buffer.pop(0)
        else:
            # [안실장 픽스] 사용자가 텍스트 선택 중일 때는 자동 스크롤 금지 (복사 편의성)
            cursor = self.textCursor()
            has_selection = cursor.hasSelection()
            
            self.append(fmt_msg)
            
            if not has_selection:
                self.moveCursor(QTextCursor.MoveOperation.End)

class StandardStockTable(QTableWidget):
    """
    금융 데이터 전용 테이블 위젯
    - 정렬, 숫자 포맷팅, 등락 색상(빨강/파랑) 자동 처리 지원
    """
    def __init__(self, columns=None, parent=None):
        super().__init__(parent)
        if columns:
            self.setColumnCount(len(columns))
            self.setHorizontalHeaderLabels(columns)
        
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1b;
                alternate-background-color: #252627;
                color: #e0e0e0;
                gridline-color: #3e3e3e;
                border: none;
            }
            QHeaderView::section {
                background-color: #2c2d30;
                color: #aaaaaa;
                padding: 4px;
                border: 1px solid #3e3e3e;
                font-weight: bold;
            }
            QTableWidget::item:selected {
                background-color: #3d3e40;
                color: #00aaff;
            }
            QScrollBar:vertical {
                border: none;
                background: #2d2d30;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #3e3e42;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #505050;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #2d2d30;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #3e3e42;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #505050;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    def enable_hts_interlock(self, code_column=0):
        """
        HTS 차트 연동 기능을 활성화합니다.
        더블 클릭 시 해당 행의 종목코드를 HTS로 전송합니다.
        """
        self.hts_code_column = code_column
        self.cellDoubleClicked.connect(self._on_cell_double_clicked_for_hts)

    def _on_cell_double_clicked_for_hts(self, row, col):
        try:
            code = None
            
            # 1. 설정된 코드 전용 열(hts_code_column)에서 아이템 추출
            target_item = self.item(row, self.hts_code_column)
            if target_item:
                code = target_item.data(Qt.ItemDataRole.UserRole)
                if not code:
                    import re
                    code_raw = target_item.text().strip()
                    match = re.search(r'[A]?[0-9]{6}', code_raw)
                    if match:
                        code = match.group().replace('A', '')
                        
            # 2. 지정된 열에 없었다면 전체 열 스캔 (Fallback)
            if not code:
                for c in range(self.columnCount()):
                    it = self.item(row, c)
                    if it and it.data(Qt.ItemDataRole.UserRole):
                        code = it.data(Qt.ItemDataRole.UserRole)
                        break
                        
            if code:
                # [안실장 픽스] HTS 연동 모듈 호출
                try:
                    from shared.hts_connector import send_to_hts
                    send_to_hts(str(code))
                except ImportError:
                    try:
                        from AT_Sig.hts_connector import send_to_hts
                        send_to_hts(str(code))
                    except: pass
        except Exception as e:
            print(f"HTS 연동 오류: {e}")

    def set_item(self, row, col, text, align=Qt.AlignmentFlag.AlignCenter, color=None, is_numeric=False, code=None):
        """테이블 아이템 설정을 위한 헬퍼 (code 전달 시 UserRole에 저장)"""
        display_text = str(text)
        item = QTableWidgetItem(display_text)
        item.setTextAlignment(align)
        
        if color:
            item.setForeground(QColor(color))
            
        if code:
            item.setData(Qt.ItemDataRole.UserRole, str(code))
            
        self.setItem(row, col, item)

    def set_numeric_item(self, row, col, val, is_percent=False, include_plus=False):
        """숫자/수익률을 위한 전용 아이템 생성기 (빨강/파랑 자동 적용)"""
        try:
            num_val = float(str(val).replace('%', '').replace(',', ''))
            
            if is_percent:
                text = f"{num_val:+.2f}" if include_plus else f"{num_val:.2f}"
            else:
                text = f"{int(num_val):,}" if num_val == int(num_val) else f"{num_val:,.2f}"
            
            color = "#ff3333" if num_val > 0 else "#00aaff" if num_val < 0 else "#ffffff"
            self.set_item(row, col, text, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, color=color)
        except (ValueError, TypeError):
            self.set_item(row, col, str(val))
class StandardStatusBar(QStatusBar):
    """
    공용 하단 상태바 (프로그램 상태 통일)
    - 연결 상태, 시장 상태, 시스템 메시지 등을 일관되게 표시
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QStatusBar {
                background-color: #1e1e1e;
                color: #aaaaaa;
                border-top: 1px solid #333333;
                min-height: 25px;
            }
            QLabel {
                font-family: 'Malgun Gothic', 'Apple SD Gothic Neo';
                font-size: 11px;
                padding-left: 5px;
                padding-right: 5px;
            }
        """)
        
        # 1. 시스템 메시지 (좌측)
        self.lbl_msg = QLabel("준비 완료")
        self.addWidget(self.lbl_msg, 1)

        # 2. 시장 시간/상태 (중앙)
        self.lbl_market = QLabel("시장 대기")
        self.lbl_market.setStyleSheet("color: #FFD700; font-weight: bold;")
        self.addPermanentWidget(self.lbl_market)
        
        # 3. 서버/계좌 모드 (우측)
        self.lbl_mode = QLabel("-")
        self.lbl_mode.setStyleSheet("color: #00E5FF; font-weight: bold;")
        self.addPermanentWidget(self.lbl_mode)
        
        # 4. API 연결 상태 (최우측)
        self.lbl_status = QLabel("● DISCONNECTED")
        self.lbl_status.setStyleSheet("color: #777777;")
        self.addPermanentWidget(self.lbl_status)

    def set_message(self, msg, color=None):
        self.lbl_msg.setText(msg)
        if color:
             self.lbl_msg.setStyleSheet(f"color: {color};")

    def update_market_status(self, text, is_open=True):
        self.lbl_market.setText(text)
        color = "#00FF7F" if is_open else "#FFD700"
        self.lbl_market.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_server_mode(self, is_real=False):
        mode_text = "REAL SERVER" if is_real else "MOCK SERVER"
        mode_color = "#FF5252" if is_real else "#00E5FF"
        self.lbl_mode.setText(mode_text)
        self.lbl_mode.setStyleSheet(f"color: {mode_color}; font-weight: bold;")

    def set_connection_status(self, connected=True):
        if connected:
            self.lbl_status.setText("● CONNECTED")
            self.lbl_status.setStyleSheet("color: #00FF7F; font-weight: bold;")
        else:
            self.lbl_status.setText("● DISCONNECTED")
            self.lbl_status.setStyleSheet("color: #777777;")
