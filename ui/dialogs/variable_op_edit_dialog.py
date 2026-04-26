from PySide6 import QtWidgets
from ui.styles import DARK_STYLE

class VariableOpEditDialog(QtWidgets.QDialog):
    """
    변수 변경 편집 다이얼로그 (Rule 노드 전용 탭).
    """
    def __init__(self, data=None, capture_path="", available_vars=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("변수 변경 편집")
        self.setMinimumWidth(350)
        self.setStyleSheet(DARK_STYLE)
        self.available_vars = available_vars or []
        self.data = data or {"name": "", "operation": "=", "value": 0}

        layout = QtWidgets.QVBoxLayout(self)

        vg = QtWidgets.QFormLayout()
        
        self.var_name = QtWidgets.QComboBox()
        if self.available_vars:
            for v in self.available_vars:
                label_text = v.get('label', '')
                if label_text:
                    self.var_name.addItem(label_text, label_text)
            
            val_key = self.data.get("name", "")
            idx = self.var_name.findData(val_key)
            if idx >= 0:
                self.var_name.setCurrentIndex(idx)
        else:
            self.var_name.addItem("(Start 노드에 기록 변수를 셋업하세요)", "")
            self.var_name.setEnabled(False)
            
        vg.addRow("변수명:", self.var_name)
        
        self.var_op = QtWidgets.QComboBox()
        self.var_op.addItems(["=", "+", "-"])
        self.var_op.setCurrentText(self.data.get("operation", "="))
        vg.addRow("연산:", self.var_op)
        
        self.var_val = QtWidgets.QSpinBox()
        self.var_val.setRange(-999999999, 999999999)
        self.var_val.setValue(int(self.data.get("value", 0)))
        vg.addRow("값:", self.var_val)
        
        layout.addLayout(vg)

        bl = QtWidgets.QHBoxLayout(); bl.addStretch()
        cb = QtWidgets.QPushButton("Cancel"); cb.setObjectName("cancelBtn"); cb.clicked.connect(self.reject); bl.addWidget(cb)
        ok = QtWidgets.QPushButton("OK"); ok.clicked.connect(self.accept); ok.setDefault(True); bl.addWidget(ok)
        layout.addLayout(bl)

    def get_data(self):
        vname = self.var_name.currentData() or ""
        return {
            "name": vname,
            "operation": self.var_op.currentText(),
            "value": self.var_val.value()
        }
