
DARK_THEME_QSS = """
QMainWindow {
    background-color: #1e1e1e;
    color: #ffffff;
}
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
}

/* GroupBox */
QGroupBox {
    border: 1px solid #3e3e3e;
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 15px;
    font-weight: bold;
    color: #c0c0c0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    left: 10px; 
    color: #ff9900;
}

/* Buttons */
QPushButton {
    background-color: #2d2d2d;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 6px 12px;
    color: #e0e0e0;
}
QPushButton:hover {
    background-color: #3e3e3e;
    border-color: #505050;
}
QPushButton:pressed {
    background-color: #ff9900;
    color: #000000;
}
QPushButton:disabled {
    background-color: #666666; 
    color: #ffffff;
    border-color: #888888;
}
QPushButton#btn_run {
    background-color: #ffaa00;
    color: #ffff00;  /* Yellow text for better contrast */
    font-weight: bold;
    font-size: 16px;
    border: none;
}
QPushButton#btn_run:disabled {
    background-color: #404040; /* Slightly lighter gray */
    color: #cccccc; /* Much brighter gray text */
    border: 1px solid #666666; /* Visible border */
}
QPushButton#btn_run:hover {
    background-color: #ffa620;
}
QPushButton#btn_stop {
    background-color: #cc3333;
    color: #ffffff;
    font-weight: bold;
    border: none;
}
QPushButton#btn_stop:hover {
    background-color: #e04444;
}
QPushButton#btn_opt {
    background-color: #0088cc;
    color: #ffffff;
    border: none;
}

/* Input Fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {
    background-color: #252526;
    border: 1px solid #3e3e3e;
    border-radius: 3px;
    padding: 4px;
    color: #e0e0e0;
    selection-background-color: #ff9900;
    selection-color: #000000;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: none; /* Custom arrow if needed */
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #808080;
    margin-right: 5px;
}

/* Table Widget */
QTableWidget {
    background-color: #1e1e1e;
    gridline-color: #333333;
    border: 1px solid #3e3e3e;
}
QTableWidget::item {
    border-bottom: 1px solid #2a2a2a;
    padding: 5px;
}
QTableWidget::item:selected {
    background-color: #2a2d3e;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #252526;
    color: #a0a0a0;
    padding: 5px;
    border: 1px solid #333333;
    font-weight: bold;
}

/* Status Bar */
QStatusBar {
    background-color: #007acc;
    color: #ffffff;
}

/* ScrollBar */
QScrollBar:vertical {
    border: none;
    background: #1e1e1e;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #424242;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
}

/* Tab Widget */
QTabWidget::pane { 
    border: 1px solid #3e3e3e; 
    border-top: 2px solid #ff9900;
}
QTabBar::tab {
    background: #252526;
    border: 1px solid #3e3e3e;
    border-bottom: none;
    padding: 8px 20px;
    margin-left: 2px;
    color: #a0a0a0;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    border-color: #ff9900;
    border-bottom-color: #1e1e1e; 
    color: #ffffff;
    font-weight: bold;
}

/* Labels */
QLabel {
    color: #cccccc;
}
QLabel#header_title {
    font-family: 'Verdana';
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
}

/* Progress Bar */
QProgressBar {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    background-color: #252526;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #ff9900, stop:1 #ffaa00);
    border-radius: 3px;
}

"""
