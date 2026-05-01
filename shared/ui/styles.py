
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
    border: 1px solid #ff9900;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #ff9900;
    color: #000000;
}

/* Input Fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox {
    background-color: #252526;
    border: 1px solid #3e3e3e;
    border-radius: 3px;
    padding: 4px;
    color: #e0e0e0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid #ff9900;
}

/* ComboBox */
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #ff9900;
    width: 0;
    height: 0;
}

/* SpinBox - Original Vertical Layout */
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #3e3e3e;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 4px solid #ff9900;
    width: 0;
    height: 0;
}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #3e3e3e;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid #ff9900;
    width: 0;
    height: 0;
}

/* Table Widget */
QTableWidget {
    background-color: #1e1e1e;
    gridline-color: #333333;
    border: 1px solid #3e3e3e;
}
QHeaderView::section {
    background-color: #252526;
    color: #a0a0a0;
    padding: 5px;
    border: 1px solid #333333;
}

/* Tab Widget */
QTabWidget::pane { 
    border: 1px solid #3e3e3e; 
}
QTabBar::tab {
    background: #252526;
    border: 1px solid #3e3e3e;
    padding: 8px 16px;
    color: #a0a0a0;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    border-color: #ff9900;
    color: #ffffff;
}

/* Labels */
QLabel {
    color: #cccccc;
}

/* ToolTip */
QToolTip {
    color: #ffffff;
    background-color: #333333;
    border: 1px solid #777777;
    border-radius: 4px;
    padding: 5px;
}
"""
