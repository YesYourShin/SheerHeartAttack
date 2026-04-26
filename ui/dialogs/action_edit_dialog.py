import os
import copy
from PySide6 import QtWidgets, QtCore

from ui.styles import DARK_STYLE
from ui.image_widgets import ImageRegionSelector
import library.adb_manager as adb_manager

class ActionEditDialog(QtWidgets.QDialog):
    """
    동작 편집 다이얼로그.
    클릭 영역, 절대 좌표 클릭, 대기, 변수 변경 등의 동작을 셋업합니다.
    """
    def __init__(self, data=None, capture_path="", available_vars=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("동작 편집")
        self.setMinimumWidth(420)
        self.setStyleSheet(DARK_STYLE)
        self.capture_path = capture_path
        self.available_vars = available_vars or []
        self.data = data or {"type": "click_region", "x": 0, "y": 0, "w": 0, "h": 0}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)

        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("동작 타입:"))
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems([
            "영역 이미지 찾아 클릭 (캡처에서 선택)",
            "절대 좌표 클릭 (캡처에서 선택)",
            "대기",
            "🧮 변수 변경",
            "📱 앱 패키지 (실행/종료)",
        ])
        type_map = {"click_region": 0, "click_pos": 1, "wait": 2, "var_op": 3, "app_package": 4}
        self.type_combo.setCurrentIndex(type_map.get(self.data.get("type", "click_region"), 0))
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)

        # ── 영역 클릭 ──
        self.region_group = QtWidgets.QGroupBox("클릭할 이미지 영역")
        rg = QtWidgets.QVBoxLayout(self.region_group)
        self.region_label = QtWidgets.QLabel(self._format_region())
        rg.addWidget(self.region_label)
        sel_btn = QtWidgets.QPushButton("📐 캡처에서 영역 선택")
        sel_btn.clicked.connect(self._select_region)
        rg.addWidget(sel_btn)
        layout.addWidget(self.region_group)

        # ── 좌표 클릭 ──
        self.pos_group = QtWidgets.QGroupBox("클릭 좌표")
        pg = QtWidgets.QVBoxLayout(self.pos_group)
        self.pos_label = QtWidgets.QLabel(self._format_pos())
        pg.addWidget(self.pos_label)
        ppick_btn = QtWidgets.QPushButton("🎯 캡처에서 좌표 선택")
        ppick_btn.clicked.connect(self._pick_pos)
        pg.addWidget(ppick_btn)
        layout.addWidget(self.pos_group)

        # ── 대기 ──
        self.wait_group = QtWidgets.QGroupBox("대기 시간")
        wg = QtWidgets.QVBoxLayout(self.wait_group)
        
        self.use_random_wait = QtWidgets.QCheckBox("랜덤 범위 사용")
        self.use_random_wait.setChecked(self.data.get("use_random", False))
        self.use_random_wait.toggled.connect(self._toggle_random_wait)
        wg.addWidget(self.use_random_wait)
        
        # 고정 대기 레이아웃 
        self.fixed_sec_widget = QtWidgets.QWidget()
        fixed_layout = QtWidgets.QHBoxLayout(self.fixed_sec_widget)
        fixed_layout.setContentsMargins(0,0,0,0)
        fixed_layout.addWidget(QtWidgets.QLabel("대기:"))
        self.wait_sec = QtWidgets.QDoubleSpinBox()
        self.wait_sec.setRange(0.0, 9999.0); self.wait_sec.setSingleStep(0.5)
        self.wait_sec.setDecimals(1); self.wait_sec.setSuffix(" 초")
        self.wait_sec.setValue(float(self.data.get("seconds", 1.0)))
        fixed_layout.addWidget(self.wait_sec)
        wg.addWidget(self.fixed_sec_widget)
        
        # 랜덤 대기 레이아웃
        self.random_sec_widget = QtWidgets.QWidget()
        rand_layout = QtWidgets.QHBoxLayout(self.random_sec_widget)
        rand_layout.setContentsMargins(0,0,0,0)
        rand_layout.addWidget(QtWidgets.QLabel("최소:"))
        self.wait_min_sec = QtWidgets.QDoubleSpinBox()
        self.wait_min_sec.setRange(0.0, 9999.0); self.wait_min_sec.setDecimals(1); self.wait_min_sec.setSuffix(" 초")
        self.wait_min_sec.setValue(float(self.data.get("min_seconds", 1.0)))
        rand_layout.addWidget(self.wait_min_sec)
        
        rand_layout.addWidget(QtWidgets.QLabel(" ~ 최대:"))
        self.wait_max_sec = QtWidgets.QDoubleSpinBox()
        self.wait_max_sec.setRange(0.0, 9999.0); self.wait_max_sec.setDecimals(1); self.wait_max_sec.setSuffix(" 초")
        self.wait_max_sec.setValue(float(self.data.get("max_seconds", 2.0)))
        rand_layout.addWidget(self.wait_max_sec)
        wg.addWidget(self.random_sec_widget)
        
        layout.addWidget(self.wait_group)
        self._toggle_random_wait(self.use_random_wait.isChecked())

        # ── 변수 변경 ──
        self.varop_group = QtWidgets.QGroupBox("변수 변경")
        vop_layout = QtWidgets.QFormLayout(self.varop_group)
        
        self.var_name_box = QtWidgets.QComboBox()
        if self.available_vars:
            for v in self.available_vars:
                label_text = v.get('label', '')
                if label_text:
                    self.var_name_box.addItem(label_text, label_text)
            
            if self.data.get("type") == "var_op":
                val_key = self.data.get("name", "")
                idx = self.var_name_box.findData(val_key)
                if idx >= 0:
                    self.var_name_box.setCurrentIndex(idx)
        else:
            self.var_name_box.addItem("(Start 노드에 기록 변수를 셋업하세요)", "")
            self.var_name_box.setEnabled(False)
        vop_layout.addRow("변수명:", self.var_name_box)
        
        self.var_op_box = QtWidgets.QComboBox()
        self.var_op_box.addItems(["=", "+", "-"])
        if self.data.get("type") == "var_op":
            self.var_op_box.setCurrentText(self.data.get("operation", "="))
        vop_layout.addRow("연산:", self.var_op_box)
        
        self.var_val_spin = QtWidgets.QSpinBox()
        self.var_val_spin.setRange(-999999999, 999999999)
        if self.data.get("type") == "var_op":
            self.var_val_spin.setValue(int(self.data.get("value", 0)))
        vop_layout.addRow("값:", self.var_val_spin)
        
        layout.addWidget(self.varop_group)

        # ── アプリパッケージ（起動/終了）──
        self.app_pkg_group = QtWidgets.QGroupBox("앱 패키지")
        apg = QtWidgets.QVBoxLayout(self.app_pkg_group)
        self.app_mode_combo = QtWidgets.QComboBox()
        self.app_mode_combo.addItem("실행", "launch")
        self.app_mode_combo.addItem("종료", "force_stop")
        if self.data.get("type") == "app_package":
            m = self.data.get("mode", "launch")
            self.app_mode_combo.setCurrentIndex(1 if m == "force_stop" else 0)
        apg.addWidget(self.app_mode_combo)

        pkg_row = QtWidgets.QHBoxLayout()
        self.package_combo = QtWidgets.QComboBox()
        self.package_combo.setEditable(True)
        self.package_combo.setMinimumWidth(280)
        if self.data.get("type") == "app_package":
            self.package_combo.setEditText(self.data.get("package", ""))
        pkg_row.addWidget(self.package_combo, 1)
        self.pkg_refresh_btn = QtWidgets.QPushButton("목록 새로고침")
        self.pkg_refresh_btn.setToolTip("ADB로 실행 중인 프로세스명(패키지 후보)을 불러옵니다")
        self.pkg_refresh_btn.clicked.connect(self._refresh_package_list)
        pkg_row.addWidget(self.pkg_refresh_btn)
        apg.addLayout(pkg_row)
        hint = QtWidgets.QLabel("목록에서 선택하거나 패키지명을 직접 입력하세요.")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        apg.addWidget(hint)
        layout.addWidget(self.app_pkg_group)
        self._update_pkg_refresh_enabled()

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
        self.pos_group.setVisible(idx == 1)
        self.wait_group.setVisible(idx == 2)
        self.varop_group.setVisible(idx == 3)
        self.app_pkg_group.setVisible(idx == 4)

        type_map_rev = {0: "click_region", 1: "click_pos", 2: "wait", 3: "var_op", 4: "app_package"}
        if hasattr(self, 'data'):
            new_type = type_map_rev.get(idx, "click_region")
            if not getattr(self, '_is_loading', False):
                prev_type = self.data.get("type", "")
                if prev_type != new_type:
                    self.data = {"type": new_type}
                    if new_type == "app_package":
                        self.app_mode_combo.setCurrentIndex(0)
                        self.package_combo.clear()
                        self.package_combo.setEditText("")
            self.data["type"] = new_type
            if idx == 0:
                self.region_label.setText(self._format_region())
            elif idx == 1:
                self.pos_label.setText(self._format_pos())
        self._update_pkg_refresh_enabled()

    def _update_pkg_refresh_enabled(self):
        if not hasattr(self, "pkg_refresh_btn"):
            return
        ok = adb_manager.adbdevice is not None
        self.pkg_refresh_btn.setEnabled(ok and self.type_combo.currentIndex() == 4)
        if not ok:
            self.pkg_refresh_btn.setToolTip("ADB 연결 후 사용할 수 있습니다")
        else:
            self.pkg_refresh_btn.setToolTip("ADB로 실행 중인 프로세스명(패키지 후보)을 불러옵니다")

    def _refresh_package_list(self):
        if adb_manager.adbdevice is None:
            QtWidgets.QMessageBox.information(self, "알림", "ADB에 연결되어 있지 않습니다.")
            return
        saved = self.package_combo.currentText().strip()
        pkgs = adb_manager.list_running_packages(adb_manager.adbdevice)
        self.package_combo.clear()
        for p in pkgs:
            self.package_combo.addItem(p)
        if saved:
            self.package_combo.setEditText(saved)
            idx = self.package_combo.findText(saved, QtCore.Qt.MatchExactly)
            if idx >= 0:
                self.package_combo.setCurrentIndex(idx)

    def _toggle_random_wait(self, checked):
        """대기 그룹박스 내부 고정/랜덤 위젯 토글 토글"""
        self.fixed_sec_widget.setVisible(not checked)
        self.random_sec_widget.setVisible(checked)

    def _format_region(self):
        d = self.data
        if d.get("w", 0) > 0:
            x, y = d.get('x', 0), d.get('y', 0)
            return f"영역: ({x}, {y}) ~ ({x + d.get('w', 0)}, {y + d.get('h', 0)})"
        return "영역: 미지정"

    def _format_pos(self):
        d = self.data
        if d.get("type") == "click_pos":
            return f"좌표: ({d.get('x',0)}, {d.get('y',0)})"
        return "좌표: 미지정"

    def _select_region(self):
        is_valid = self.capture_path and (self.capture_path.startswith("data:image/png;base64,") or os.path.exists(self.capture_path))
        if not is_valid:
            QtWidgets.QMessageBox.warning(self, "오류", "캡처 이미지가 없습니다.")
            return
        existing = (self.data.get("x", 0), self.data.get("y", 0), self.data.get("w", 0), self.data.get("h", 0)) if self.data.get("w", 0) > 0 else None
        dlg = ImageRegionSelector(self.capture_path, mode="region", existing_rect=existing, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            r = dlg.get_result()
            if r:
                self.data["x"], self.data["y"], self.data["w"], self.data["h"] = r
                self.region_label.setText(self._format_region())

    def _pick_pos(self):
        is_valid = self.capture_path and (self.capture_path.startswith("data:image/png;base64,") or os.path.exists(self.capture_path))
        if not is_valid:
            QtWidgets.QMessageBox.warning(self, "오류", "캡처 이미지가 없습니다.")
            return
        existing_pt = (self.data.get("x", 0), self.data.get("y", 0)) if self.data.get("type") == "click_pos" else None
        dlg = ImageRegionSelector(self.capture_path, mode="point", existing_point=existing_pt, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            pt = dlg.get_result()
            if pt:
                self.data["x"], self.data["y"] = pt
                self.pos_label.setText(f"좌표: ({pt[0]}, {pt[1]})")

    def accept(self):
        idx = self.type_combo.currentIndex()
        if idx == 3: # 변수 변경
            if not self.var_name_box.currentData():
                QtWidgets.QMessageBox.warning(self, "오류", "변경할 변수를 선택해주세요.")
                return
        if idx == 4:
            if not self.package_combo.currentText().strip():
                QtWidgets.QMessageBox.warning(self, "오류", "패키지명을 입력하거나 선택해주세요.")
                return
        super().accept()

    def get_data(self):
        idx = self.type_combo.currentIndex()
        if idx == 0:
            return {"type": "click_region", "x": self.data.get("x", 0), "y": self.data.get("y", 0),
                    "w": self.data.get("w", 0), "h": self.data.get("h", 0)}
        elif idx == 1:
            return {"type": "click_pos", "x": self.data.get("x", 0), "y": self.data.get("y", 0)}
        elif idx == 2:
            return {
                "type": "wait",
                "use_random": self.use_random_wait.isChecked(),
                "seconds": self.wait_sec.value(),
                "min_seconds": self.wait_min_sec.value(),
                "max_seconds": self.wait_max_sec.value()
            }
        elif idx == 3:
            return {
                "type": "var_op",
                "name": self.var_name_box.currentData() or "",
                "operation": self.var_op_box.currentText(),
                "value": self.var_val_spin.value()
            }
        elif idx == 4:
            return {
                "type": "app_package",
                "mode": self.app_mode_combo.currentData() or "launch",
                "package": self.package_combo.currentText().strip(),
            }
        else:
            return {"type": "wait", "seconds": 1.0}
