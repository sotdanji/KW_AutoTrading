"""
Parameter Optimization Dialog (Genetic Algorithm)

Allows users to configure and run GA optimization for strategy parameters.
"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QGroupBox, QFormLayout, QSpinBox,
                             QDoubleSpinBox, QProgressBar, QTextEdit, QMessageBox)
from PyQt6.QtCore import Qt
from core.ga_optimizer import GAOptimizer

class OptimizationDialog(QDialog):
    """Dialog for parameter optimization setup and execution using Genetic Algorithm"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("전략 최적화 (유전 알고리즘)")
        self.setMinimumWidth(500)
        self.setMinimumHeight(600)
        self.worker = None
        self.parent_ref = parent # Store parent reference for engine/token access
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("유전 알고리즘 파라미터 최적화")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # 1. Parameter Ranges
        param_group = QGroupBox("탐색 범위 설정 (최소 ~ 최대)")
        param_layout = QFormLayout()
        
        # Stop Loss Range
        sl_box = QHBoxLayout()
        self.spin_sl_min = QDoubleSpinBox()
        self.spin_sl_min.setRange(0.1, 50.0)
        self.spin_sl_min.setValue(1.0)
        self.spin_sl_min.setSuffix("%")
        
        self.spin_sl_max = QDoubleSpinBox()
        self.spin_sl_max.setRange(0.1, 50.0)
        self.spin_sl_max.setValue(10.0)
        self.spin_sl_max.setSuffix("%")
        
        sl_box.addWidget(self.spin_sl_min)
        sl_box.addWidget(QLabel("~"))
        sl_box.addWidget(self.spin_sl_max)
        param_layout.addRow("손절 (SL):", sl_box)
        
        # Take Profit Range
        tp_box = QHBoxLayout()
        self.spin_tp_min = QDoubleSpinBox()
        self.spin_tp_min.setRange(0.1, 100.0)
        self.spin_tp_min.setValue(5.0)
        self.spin_tp_min.setSuffix("%")
        
        self.spin_tp_max = QDoubleSpinBox()
        self.spin_tp_max.setRange(0.1, 100.0)
        self.spin_tp_max.setValue(30.0)
        self.spin_tp_max.setSuffix("%")
        
        tp_box.addWidget(self.spin_tp_min)
        tp_box.addWidget(QLabel("~"))
        tp_box.addWidget(self.spin_tp_max)
        param_layout.addRow("익절 (TP):", tp_box)
        
        # Ratio Range
        ratio_box = QHBoxLayout()
        self.spin_ratio_min = QSpinBox()
        self.spin_ratio_min.setRange(1, 100)
        self.spin_ratio_min.setValue(10)
        self.spin_ratio_min.setSuffix("%")
        
        self.spin_ratio_max = QSpinBox()
        self.spin_ratio_max.setRange(1, 100)
        self.spin_ratio_max.setValue(50)
        self.spin_ratio_max.setSuffix("%")
        
        ratio_box.addWidget(self.spin_ratio_min)
        ratio_box.addWidget(QLabel("~"))
        ratio_box.addWidget(self.spin_ratio_max)
        param_layout.addRow("비중 (Ratio):", ratio_box)
        
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # 2. GA Settings
        ga_group = QGroupBox("GA 엔진 설정")
        ga_layout = QFormLayout()
        
        self.spin_pop = QSpinBox()
        self.spin_pop.setRange(4, 100)
        self.spin_pop.setValue(10)
        ga_layout.addRow("개체 수 (Population):", self.spin_pop)
        
        self.spin_gen = QSpinBox()
        self.spin_gen.setRange(1, 100)
        self.spin_gen.setValue(5)
        ga_layout.addRow("세대 수 (Generations):", self.spin_gen)
        
        ga_group.setLayout(ga_layout)
        layout.addWidget(ga_group)
        
        # 3. Progress
        progress_group = QGroupBox("진행 상황")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("대기 중...")
        progress_layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        progress_layout.addWidget(self.log_text)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("시작")
        self.btn_start.clicked.connect(self.on_start)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet("background-color: #0088cc; font-weight: bold;")
        
        self.btn_stop = QPushButton("중단")
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setStyleSheet("background-color: #cc3333;")
        
        self.btn_apply = QPushButton("결과 적용")
        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setStyleSheet("background-color: #00cc66;")

        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)
        
        self.best_result_params = None
    
    def on_start(self):
        """Start optimization"""
        # Collect parameters
        param_ranges = {
            'sl': (self.spin_sl_min.value(), self.spin_sl_max.value()),
            'tp': (self.spin_tp_min.value(), self.spin_tp_max.value()),
            'ratio': (self.spin_ratio_min.value(), self.spin_ratio_max.value()),
        }
        
        pop_size = self.spin_pop.value()
        generations = self.spin_gen.value()
        
        # Validate stock selection from parent
        # We need to grab target stocks from main window state if possible
        # Or prompt user. For simplicity, assume parent has `engine` with loaded `token`.
        # And we need stock list. 
        # Let's assume we run on the 'current target stocks' in main window?
        # But optimization dialog doesn't know them. 
        # Strategy: Ask MainWindow or pass in init. 
        # Since we modified this, let's look at `grid_optimizer` usage.
        # It used self.stock_list.
        
        # Hack: Access parent's logic to get universe?
        # We will require MainWindow to be passed as parent.
        if not self.parent_ref or not hasattr(self.parent_ref, 'token'):
            self.log("오류: 메인 윈도우 참조를 찾을 수 없습니다.")
            return

        # Prepare dummy config basics (deprecated for GA but needed structure)
        base_config = {
             'strategy_code': self.parent_ref.text_formula_preview.toPlainText()
        }
        
        if not base_config['strategy_code']:
            QMessageBox.warning(self, "오류", "전략 코드가 없습니다.")
            return

        # Get Target Stocks (Same logic as MainWindow run)
        # Reuse cache if available
        stock_list = []
        if hasattr(self.parent_ref, 'universe_cache') and self.parent_ref.universe_cache:
            stock_list = self.parent_ref.universe_cache[:50] # Limit for speed
        else:
            # Fallback or empty
            self.log("경고: 유니버스가 로드되지 않았습니다. 메인 화면에서 백테스트를 한 번 실행하세요 (종목 로드용).")
            return

        start_date = self.parent_ref.date_start.date()
        end_date = self.parent_ref.date_end.date()

        self.log(f"최적화 시작: {len(stock_list)}개 종목 대상, {generations}세대 x {pop_size}개체")
        
        self.worker = GAOptimizer(
            self.parent_ref, # passing parent as engine provider (it has token)
            stock_list,
            start_date,
            end_date,
            base_config,
            param_ranges,
            pop_size,
            generations
        )
        
        self.worker.progress_updated.connect(self.on_progress)
        self.worker.generation_finished.connect(self.on_generation_finished)
        self.worker.optimization_finished.connect(self.on_finished)
        
        self.worker.start()
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_apply.setEnabled(False)
        self.progress_bar.setValue(0)
    
    def on_stop(self):
        if self.worker:
            self.worker.stop()
            self.log("사용자에 의해 중단됨.")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
    
    def on_progress(self, current, total, msg):
        pct = int((current / total) * 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"진행률 {pct}% - {msg}")
        
    def on_generation_finished(self, gen_idx, best_fitness, best_params):
        self.log(f"[세대 {gen_idx} 완료] 최고 수익률: {best_fitness:.2f}%")
        self.log(f" - 파라미터: {best_params}")
        
    def on_finished(self, best_params, best_fitness):
        self.log("=== 최적화 완료 ===")
        self.log(f"최종 최고 수익률: {best_fitness:.2f}%")
        self.log(f"최종 파라미터: {best_params}")
        
        self.best_result_params = best_params
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_apply.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("완료")
        
        QMessageBox.information(self, "완료", f"최적화가 완료되었습니다.\n최고 수익률: {best_fitness:.2f}%")

    def on_apply(self):
        """Apply best parameters to Main Window"""
        if self.parent_ref and self.best_result_params:
            p = self.best_result_params
            self.parent_ref.spin_loss.setValue(p['sl'])
            self.parent_ref.spin_trigger.setValue(p['tp'])
            self.parent_ref.spin_ratio.setValue(p['ratio'])
            self.log("메인 화면에 파라미터를 적용했습니다.")
            self.accept()

    def log(self, message):
        self.log_text.append(message)
