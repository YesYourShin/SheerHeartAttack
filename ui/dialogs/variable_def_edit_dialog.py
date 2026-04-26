from PySide6 import QtWidgets
from ui.styles import DARK_STYLE

class VariableDefEditDialog(QtWidgets.QDialog):
    """
    기록 변수 선언 편집 다이얼로그 (GameNode 전용).
    """
    def __init__(self, data=None, capture_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("기록 변수 편집")
        self.setMinimumWidth(350)
        self.setStyleSheet(DARK_STYLE)
        self.data = data or {"label": "", "value": 0}

        layout = QtWidgets.QVBoxLayout(self)

        vg = QtWidgets.QFormLayout()
        
        self.v_label = QtWidgets.QLineEdit()
        self.v_label.setPlaceholderText("화면에 표시될 이름 (예: 골드)")
        self.v_label.setText(self.data.get("label", ""))
        vg.addRow("LABEL (표시명):", self.v_label)
        
        self.v_val = QtWidgets.QSpinBox()
        self.v_val.setRange(-999999999, 999999999)
        self.v_val.setValue(int(self.data.get("value", 0)))
        vg.addRow("초기 VALUE:", self.v_val)
        
        layout.addLayout(vg)

        bl = QtWidgets.QHBoxLayout(); bl.addStretch()
        cb = QtWidgets.QPushButton("Cancel"); cb.setObjectName("cancelBtn"); cb.clicked.connect(self.reject); bl.addWidget(cb)
        ok = QtWidgets.QPushButton("OK"); ok.clicked.connect(self.accept); ok.setDefault(True); bl.addWidget(ok)
        layout.addLayout(bl)

    def accept(self):
        if not self.v_label.text().strip():
            QtWidgets.QMessageBox.warning(self, "오류", "LABEL(표시명)을 입력해주세요.")
            return
        super().accept()

    def get_data(self):
        return {
            "label": self.v_label.text().strip(),
            "value": self.v_val.value()
        }
