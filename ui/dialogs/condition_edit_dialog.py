import os
from PySide6 import QtWidgets, QtCore, QtGui

from ui.styles import DARK_STYLE
from ui.image_widgets import ImageRegionSelector

class ConditionEditDialog(QtWidgets.QDialog):
    """
    조건 편집 다이얼로그.
    이미지 영역, 색상 매칭, 변수 비교 유형의 조건을 셋업합니다.
    """
    def __init__(self, data=None, capture_path="", available_vars=None, condition_default_threshold=0.8, parent=None):
        super().__init__(parent)
        self.setWindowTitle("조건 편집")
        self.setMinimumWidth(420)
        self.setStyleSheet(DARK_STYLE)
        self.capture_path = capture_path
        self.available_vars = available_vars or []
        try:
            default_threshold = float(condition_default_threshold)
        except (TypeError, ValueError):
            default_threshold = 0.8
        default_threshold = max(0.0, min(1.0, default_threshold))
        self.data = data or {"type": "image_region", "x": 0, "y": 0, "w": 0, "h": 0, "threshold": default_threshold}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)

        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("조건 타입:"))
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(["이미지 영역 (캡처에서 선택)", "색상 매칭 (캡처에서 좌표)", "🧮 변수 비교"])
        
        type_map = {"image_region": 0, "color": 1, "var_cond": 2}
        self.type_combo.setCurrentIndex(type_map.get(self.data.get("type", "image_region"), 0))
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)

        # ── 이미지 영역 그룹 ──
        self.region_group = QtWidgets.QGroupBox("이미지 영역")
        rg = QtWidgets.QVBoxLayout(self.region_group)
        self.region_label = QtWidgets.QLabel(self._format_region())
        rg.addWidget(self.region_label)
        sel_btn = QtWidgets.QPushButton("📐 캡처에서 영역 선택")
        sel_btn.clicked.connect(self._select_region)
        rg.addWidget(sel_btn)
        tr = QtWidgets.QHBoxLayout()
        tr.addWidget(QtWidgets.QLabel("유사도:"))
        self.threshold = QtWidgets.QDoubleSpinBox()
        self.threshold.setRange(0.0, 1.0); self.threshold.setSingleStep(0.05); self.threshold.setDecimals(2)
        self.threshold.setValue(float(self.data.get("threshold", 0.8)))
        tr.addWidget(self.threshold); tr.addStretch()
        rg.addLayout(tr)
        layout.addWidget(self.region_group)

        # ── 색상 그룹 ──
        self.color_group = QtWidgets.QGroupBox("색상 매칭")
        cg = QtWidgets.QVBoxLayout(self.color_group)
        self.color_label = QtWidgets.QLabel(self._format_color())
        cg.addWidget(self.color_label)
        cpick_btn = QtWidgets.QPushButton("🎯 캡처에서 좌표/색상 선택")
        cpick_btn.clicked.connect(self._pick_color)
        cg.addWidget(cpick_btn)
        tol_row = QtWidgets.QHBoxLayout()
        tol_row.addWidget(QtWidgets.QLabel("허용 오차:"))
        self.ctol = QtWidgets.QSpinBox(); self.ctol.setRange(0, 255)
        self.ctol.setValue(int(self.data.get("tolerance", 10)))
        tol_row.addWidget(self.ctol); tol_row.addStretch()
        cg.addLayout(tol_row)
        layout.addWidget(self.color_group)

        # ── 변수 비교 그룹 ──
        self.varcond_group = QtWidgets.QGroupBox("변수 비교")
        vg = QtWidgets.QFormLayout(self.varcond_group)
        
        self.var_name_combo = QtWidgets.QComboBox()
        if self.available_vars:
            for v in self.available_vars:
                label = v.get('label', '')
                if label:
                    self.var_name_combo.addItem(label, label)
            
            if self.data.get("type") == "var_cond":
                val = self.data.get("name", "")
                idx = self.var_name_combo.findData(val)
                if idx >= 0: self.var_name_combo.setCurrentIndex(idx)
        else:
            self.var_name_combo.addItem("(Start 노드에 기록 변수를 셋업하세요)", "")
            self.var_name_combo.setEnabled(False)
        vg.addRow("변수명:", self.var_name_combo)
        
        self.var_op_combo = QtWidgets.QComboBox()
        self.var_op_combo.addItems(["==", ">=", "<=", ">", "<", "!="])
        if self.data.get("type") == "var_cond":
            self.var_op_combo.setCurrentText(self.data.get("operator", "=="))
        vg.addRow("조건:", self.var_op_combo)
        
        self.var_val_spin = QtWidgets.QSpinBox()
        self.var_val_spin.setRange(-999999999, 999999999)
        if self.data.get("type") == "var_cond":
            self.var_val_spin.setValue(int(self.data.get("value", 0)))
        vg.addRow("값:", self.var_val_spin)
        
        layout.addWidget(self.varcond_group)

        self._is_loading = True
        self.type_combo.currentIndexChanged.connect(self._toggle)
        self._toggle()
        self._is_loading = False

        bl = QtWidgets.QHBoxLayout(); bl.addStretch()
        cb = QtWidgets.QPushButton("Cancel"); cb.setObjectName("cancelBtn"); cb.clicked.connect(self.reject); bl.addWidget(cb)
        ok = QtWidgets.QPushButton("OK"); ok.clicked.connect(self.accept); ok.setDefault(True); bl.addWidget(ok)
        layout.addLayout(bl)

    def _toggle(self):
        idx = self.type_combo.currentIndex()
        self.region_group.setVisible(idx == 0)
        self.color_group.setVisible(idx == 1)
        self.varcond_group.setVisible(idx == 2)
        
        type_map_rev = {0: "image_region", 1: "color", 2: "var_cond"}
        if hasattr(self, 'data'):
            new_type = type_map_rev.get(idx, "image_region")
            if not getattr(self, '_is_loading', False):
                prev_type = self.data.get("type", "")
                if prev_type != new_type:
                    self.data = {"type": new_type}
            self.data["type"] = new_type
            if idx == 0:
                self.region_label.setText(self._format_region())
            elif idx == 1:
                self.color_label.setText(self._format_color())

    def _format_region(self):
        d = self.data
        if d.get("w", 0) > 0:
            x, y = d.get('x', 0), d.get('y', 0)
            return f"영역: ({x}, {y}) ~ ({x + d.get('w',0)}, {y + d.get('h',0)})"
        return "영역: 미지정"

    def _format_color(self):
        d = self.data
        if d.get("type") == "color":
            return f"좌표: ({d.get('x',0)}, {d.get('y',0)})  RGB({d.get('r',0)}, {d.get('g',0)}, {d.get('b',0)})"
        return "좌표/색상: 미지정"

    def _select_region(self):
        is_valid = self.capture_path and (self.capture_path.startswith("data:image/png;base64,") or os.path.exists(self.capture_path))
        if not is_valid:
            QtWidgets.QMessageBox.warning(self, "오류", "캡처 이미지가 없습니다. 먼저 캡처해주세요.")
            return
        existing = (self.data.get("x", 0), self.data.get("y", 0), self.data.get("w", 0), self.data.get("h", 0)) if self.data.get("w", 0) > 0 else None
        dlg = ImageRegionSelector(self.capture_path, mode="region", existing_rect=existing, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            r = dlg.get_result()
            if r:
                self.data["x"], self.data["y"], self.data["w"], self.data["h"] = r
                self.region_label.setText(self._format_region())

    def _pick_color(self):
        is_valid = self.capture_path and (self.capture_path.startswith("data:image/png;base64,") or os.path.exists(self.capture_path))
        if not is_valid:
            QtWidgets.QMessageBox.warning(self, "오류", "캡처 이미지가 없습니다. 먼저 캡처해주세요.")
            return
        existing_pt = (self.data.get("x", 0), self.data.get("y", 0)) if self.data.get("type") == "color" else None
        dlg = ImageRegionSelector(self.capture_path, mode="point", existing_point=existing_pt, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            pt = dlg.get_result()
            if pt:
                self.data["x"], self.data["y"] = pt
                # 이미지에서 색상 읽기
                img = QtGui.QImage()
                if self.capture_path.startswith("data:image/png;base64,"):
                    import base64
                    b64_str = self.capture_path.split(",", 1)[1]
                    byte_data = QtCore.QByteArray.fromBase64(b64_str.encode("utf-8"))
                    img.loadFromData(byte_data)
                else:
                    img.load(self.capture_path)
                if 0 <= pt[0] < img.width() and 0 <= pt[1] < img.height():
                    c = img.pixelColor(pt[0], pt[1])
                    self.data["r"], self.data["g"], self.data["b"] = c.red(), c.green(), c.blue()
                self.color_label.setText(self._format_color())

    def accept(self):
        idx = self.type_combo.currentIndex()
        if idx == 2: # 변수 비교
            if not self.var_name_combo.currentData():
                QtWidgets.QMessageBox.warning(self, "오류", "비교할 변수를 선택해주세요.")
                return
        super().accept()

    def get_data(self):
        idx = self.type_combo.currentIndex()
        if idx == 0:
            return {"type": "image_region", "x": self.data.get("x", 0), "y": self.data.get("y", 0),
                    "w": self.data.get("w", 0), "h": self.data.get("h", 0),
                    "threshold": self.threshold.value()}
        elif idx == 1:
            return {"type": "color", "x": self.data.get("x", 0), "y": self.data.get("y", 0),
                    "r": self.data.get("r", 0), "g": self.data.get("g", 0), "b": self.data.get("b", 0),
                    "tolerance": self.ctol.value()}
        elif idx == 2:
            return {
                "type": "var_cond",
                "name": self.var_name_combo.currentData() or "",
                "operator": self.var_op_combo.currentText(),
                "value": self.var_val_spin.value()
            }
        else:
            return {"type": "image_region", "x": 0, "y": 0, "w": 0, "h": 0}
