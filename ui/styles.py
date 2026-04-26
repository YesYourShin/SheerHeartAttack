"""
공통 다크 테마 스타일시트.
모든 UI 다이얼로그/위젯에서 공유.
"""

DARK_STYLE = """
QDialog { background-color: #2b2b2b; color: #dcdcdc; }
QLabel { color: #dcdcdc; font-size: 13px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #3c3f41; color: #dcdcdc; border: 1px solid #555;
    border-radius: 4px; padding: 4px 8px; font-size: 13px; min-height: 22px;
}
QComboBox QAbstractItemView { background-color: #3c3f41; color: #dcdcdc; }
QGroupBox {
    color: #87ceeb; border: 1px solid #555; border-radius: 6px;
    margin-top: 12px; padding-top: 16px; font-weight: bold; font-size: 13px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QListWidget {
    background-color: #3c3f41; color: #dcdcdc; border: 1px solid #555;
    border-radius: 4px; font-size: 12px;
}
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background-color: #365880; }
QPushButton {
    background-color: #365880; color: white; border: none;
    border-radius: 4px; padding: 5px 14px; font-size: 12px;
}
QPushButton:hover { background-color: #4a6fa5; }
QPushButton:disabled { background-color: #3a3a3a; color: #666; }
QPushButton#dangerBtn { background-color: #8b3a3a; }
QPushButton#dangerBtn:hover { background-color: #a04545; }
QPushButton#cancelBtn { background-color: #555; }
QPushButton#cancelBtn:hover { background-color: #666; }
QTabWidget::pane { border: 1px solid #555; background-color: #2b2b2b; }
QTabBar::tab {
    background-color: #3c3f41; color: #777; padding: 8px 18px;
    border: 1px solid #555; border-bottom: none; border-radius: 4px 4px 0 0;
    font-size: 13px; margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #2b2b2b; color: #ffffff; font-weight: bold;
    border-bottom: 2px solid #4a9eff;
}
QTabBar::tab:hover:!selected { background-color: #454545; color: #bbb; }
"""
