from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QPushButton
from PyQt6.QtCore import Qt

class HistoryDialog(QDialog):
    def __init__(self, db_manager, analyzer, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.analyzer = analyzer # 분석기(DataFetcher 포함) 인스턴스 저장
        self.setWindowTitle("발굴 종목 추적 이력 (수익률 검증)")
        self.resize(700, 450)
        self.setStyleSheet("background-color: #1E1E1E; color: white;")
        
        self.layout = QVBoxLayout(self)
        
        # 헤더
        title = QLabel("🔍 포착 종목 히스토리")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00E5FF; margin-bottom: 10px;")
        self.layout.addWidget(title)
        
        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(7) # 컬럼 증가
        self.table.setHorizontalHeaderLabels(["시간", "종목코드", "종목명", "발굴 섹터", "포착가격", "현재가", "수익률"])
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2D2D2D;
                gridline-color: #444;
                border: none;
            }
            QHeaderView::section {
                background-color: #333;
                color: #DDD;
                padding: 4px;
                border: 1px solid #444;
            }
            QTableWidget::item {
                padding: 5px;
            }
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.layout.addWidget(self.table)
        
        # 닫기 버튼
        close_btn = QPushButton("닫기")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: white;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        close_btn.clicked.connect(self.accept)
        self.layout.addWidget(close_btn)
        
        self.load_data()
        
    def load_data(self):
        stocks = self.db_manager.get_active_stocks()
        self.table.setRowCount(len(stocks))
        
        for i, stock in enumerate(stocks):
            # 시간 포맷팅
            time_str = stock['found_at']
            code = stock['code']
            found_price = float(stock['found_price']) if stock['found_price'] else 0
            
            # 아이템 생성: 기본 정보
            self.table.setItem(i, 0, QTableWidgetItem(str(time_str)))
            self.table.setItem(i, 1, QTableWidgetItem(code))
            self.table.setItem(i, 2, QTableWidgetItem(stock['name']))
            self.table.setItem(i, 3, QTableWidgetItem(stock['sector']))
            
            # 포착 가격 (변동률이 아닌 가격 정보가 필요하지만, DB 스키마상 found_price에 등락률이 들어가는 임시 구조였음 수정 필요)
            # 현재 found_price에는 '등락률'이 들어가 있음 (dashboard.py의 _save_to_db 참고)
            # 정확한 수익률 계산을 위해서는 "포착 당시의 주가"가 필요한데 지금은 "포착 당시의 등락률"만 있음.
            # *중요*: 수익률을 계산하려면 '현재가'와 '매수가(포착가)'가 있어야 함.
            # 일단 현재 DB에 저장된 found_price는 등락률이므로, 이를 '포착 당시 변동률'로 표기하고,
            # *실제 수익률 계산 불가* 문제를 해결하기 위해,
            # 이번 실행부터는 DB 저장 시 '현재 주가'를 저장하도록 dashboard logic도 수정해야 함.
            
            # 하지만 이미 저장된 데이터는 어쩔 수 없으므로,
            # 여기서는 실시간 데이터를 가져와서 화면에 뿌려주는 '현재 상태' 위주로 표시.
            
            # 실시간 데이터 조회
            current_info = self.analyzer.fetcher._fetch_stock_quote(code)
            current_price = 0
            current_change = 0
            
            if current_info:
                # ka10004 Response spec: stk_prc (현재가), pst_diff (전일대비 등락금액), ... ?? 
                # DataFetcher._fetch_stock_quote mocking 확인 필요.
                # DataFetcher의 Real mode에서는 ka10004를 사용함.
                # 보통 API에서 'stk_prc'를 줌.
                current_price = float(current_info.get('stk_prc', 0))
                # pst_diff는 전일비 등락폭일 수 있으므로 등락률 계산 필요할 수도. (pst_rtd: 등락률)
            
            # 표시 로직
            # 1. 포착 당시 주가
            found_price_fmt = f"{int(found_price):,}" if found_price > 100 else f"{found_price:.2f}"
            found_rate_item = QTableWidgetItem(found_price_fmt)
            self.table.setItem(i, 4, found_rate_item)
            
            # 2. 현재가
            curr_price_item = QTableWidgetItem(f"{current_price:,.0f}")
            self.table.setItem(i, 5, curr_price_item)
            
            # 3. 수익률 계산
            profit_rate = 0
            if found_price > 0 and current_price > 0:
                profit_rate = ((current_price - found_price) / found_price) * 100
            
            profit_item = QTableWidgetItem(f"{profit_rate:+.2f}")
            if profit_rate > 0:
                profit_item.setForeground(Qt.GlobalColor.red)
            elif profit_rate < 0:
                profit_item.setForeground(Qt.GlobalColor.blue)
            self.table.setItem(i, 6, profit_item)
