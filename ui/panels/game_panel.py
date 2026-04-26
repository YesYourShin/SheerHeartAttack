import json
from PySide6 import QtWidgets, QtCore
import library.adb_manager as adb_manager
from ui.panels.base_panel import BasePropertyPanel
from ui.properties_panel import StartNodeOrderList
from ui.widgets.list_editor import ListEditor
from ui.edit_dialogs import _describe_variable_def
from ui.dialogs.variable_def_edit_dialog import VariableDefEditDialog


class GameNodePanel(BasePropertyPanel):
    """Game ノード: Plan/Guard 順・日次変数・リセット時刻"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("📱 실행할 앱 (패키지):"))
        pkg_row = QtWidgets.QGridLayout()
        pkg_row.setHorizontalSpacing(6)
        pkg_row.setVerticalSpacing(6)
        self.package_combo = QtWidgets.QComboBox()
        self.package_combo.setEditable(True)
        self.package_combo.setMinimumWidth(120)
        self.package_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.package_combo.currentTextChanged.connect(self._on_package_text_changed)
        pkg_row.addWidget(self.package_combo, 0, 0, 1, 2)
        self.pkg_current_btn = QtWidgets.QPushButton("현재 앱")
        self.pkg_current_btn.setToolTip("ADB에서 현재 화면에 떠 있는 앱 패키지를 가져옵니다.")
        self.pkg_current_btn.clicked.connect(self._fill_current_app_package)
        pkg_row.addWidget(self.pkg_current_btn, 1, 0)
        self.pkg_refresh_btn = QtWidgets.QPushButton("🔄 목록")
        self.pkg_refresh_btn.setToolTip("ADB 연결 시 실행 중 패키지 목록을 불러옵니다.")
        self.pkg_refresh_btn.clicked.connect(self._refresh_package_list)
        pkg_row.addWidget(self.pkg_refresh_btn, 1, 1)
        pkg_row.setColumnStretch(0, 1)
        pkg_row.setColumnStretch(1, 1)
        layout.addLayout(pkg_row)
        wait_row = QtWidgets.QHBoxLayout()
        wait_row.addWidget(QtWidgets.QLabel("앱 실행 후 대기(초):"))
        self.post_launch_wait_spin = QtWidgets.QDoubleSpinBox()
        self.post_launch_wait_spin.setRange(0, 600)
        self.post_launch_wait_spin.setDecimals(1)
        self.post_launch_wait_spin.setSingleStep(0.5)
        self.post_launch_wait_spin.valueChanged.connect(self._on_change)
        wait_row.addWidget(self.post_launch_wait_spin)
        wait_row.addStretch()
        layout.addLayout(wait_row)

        layout.addSpacing(10)

        layout.addWidget(QtWidgets.QLabel("🛡 Guard 최우선 감시 우선순위:"))
        self.guard_order_list = StartNodeOrderList()
        self.guard_order_list.order_changed.connect(self._on_change)
        layout.addWidget(self.guard_order_list)

        layout.addSpacing(10)

        layout.addWidget(QtWidgets.QLabel("📝 Plan 순차 실행 순서:"))
        self.plan_order_list = StartNodeOrderList()
        self.plan_order_list.order_changed.connect(self._on_change)
        layout.addWidget(self.plan_order_list)

        layout.addSpacing(10)

        layout.addWidget(QtWidgets.QLabel("📊 기록할 변수:"))
        self.daily_vars_editor = ListEditor([], _describe_variable_def, VariableDefEditDialog, on_change=self._on_change)
        layout.addWidget(self.daily_vars_editor)

        layout.addSpacing(10)

        time_layout = QtWidgets.QHBoxLayout()
        time_layout.addWidget(QtWidgets.QLabel("⏰ 일일 초기화 시간:"))
        self.reset_time_edit = QtWidgets.QTimeEdit()
        self.reset_time_edit.setDisplayFormat("HH:mm:ss")
        self.reset_time_edit.timeChanged.connect(self._on_change)
        time_layout.addWidget(self.reset_time_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

    def _load_from_state(self, state):
        self._refresh_game_nodes(state)

        if state:
            var_list = self._load_json(state.get('daily_variables', '[]'))
            reset_time_str = state.get('reset_time', '05:00:00')
        else:
            var_list = self._load_json(self.node.get_property('daily_variables') if self.node and self.node.has_property('daily_variables') else '[]')
            reset_time_str = self.node.get_property('reset_time') if self.node and self.node.has_property('reset_time') else '05:00:00'

        self._skip_snapshot = True
        self.daily_vars_editor.items = list(var_list)
        self.daily_vars_editor._refresh_list()

        qt_time = QtCore.QTime.fromString(reset_time_str, "HH:mm:ss")
        if qt_time.isValid():
            self.reset_time_edit.setTime(qt_time)

        if state:
            pkg = state.get('launch_package', '') or ''
            try:
                wait_v = float(state.get('post_launch_wait_seconds', '0') or 0)
            except (TypeError, ValueError):
                wait_v = 0.0
        else:
            pkg = self.node.get_property('launch_package') if self.node and self.node.has_property('launch_package') else ''
            try:
                wait_v = float(self.node.get_property('post_launch_wait_seconds') or '0')
            except (TypeError, ValueError):
                wait_v = 0.0
        self.package_combo.setEditText(pkg or '')
        self._update_package_tooltip()
        self._update_package_dropdown_width([pkg or ''])
        self.post_launch_wait_spin.setValue(wait_v)

        self._skip_snapshot = False

    def get_state(self):
        state = {}
        state['plan_nodes_order'] = json.dumps(self.plan_order_list.get_order_data())
        state['guard_nodes_order'] = json.dumps(self.guard_order_list.get_order_data())

        var_list = self.daily_vars_editor.get_items()
        state['daily_variables'] = json.dumps(var_list, ensure_ascii=False)
        state['reset_time'] = self.reset_time_edit.time().toString("HH:mm:ss")
        state['launch_package'] = self.package_combo.currentText().strip()
        state['post_launch_wait_seconds'] = str(self.post_launch_wait_spin.value())

        return state

    def save_to_node(self, push_undo=False):
        if not self.node:
            return
        plan_data = self.plan_order_list.get_order_data()
        guard_data = self.guard_order_list.get_order_data()
        self._set_node_property('plan_nodes_order', json.dumps(plan_data), push_undo=push_undo)
        self._set_node_property('guard_nodes_order', json.dumps(guard_data), push_undo=push_undo)

        if self.node.has_property('daily_variables'):
            var_list = self.daily_vars_editor.get_items()
            self._set_node_property(
                'daily_variables',
                json.dumps(var_list, ensure_ascii=False),
                push_undo=push_undo
            )

        if self.node.has_property('reset_time'):
            self._set_node_property(
                'reset_time',
                self.reset_time_edit.time().toString("HH:mm:ss"),
                push_undo=push_undo
            )

        if self.node.has_property('launch_package'):
            self._set_node_property(
                'launch_package',
                self.package_combo.currentText().strip(),
                push_undo=push_undo
            )
        if self.node.has_property('post_launch_wait_seconds'):
            self._set_node_property(
                'post_launch_wait_seconds',
                str(self.post_launch_wait_spin.value()),
                push_undo=push_undo
            )

    def _refresh_package_list(self):
        saved = self.package_combo.currentText().strip()
        pkgs = adb_manager.list_running_packages(adb_manager.adbdevice)
        self.package_combo.blockSignals(True)
        self.package_combo.clear()
        for p in pkgs:
            self.package_combo.addItem(p)
        self.package_combo.setEditText(saved)
        idx = self.package_combo.findText(saved, QtCore.Qt.MatchExactly)
        if idx >= 0:
            self.package_combo.setCurrentIndex(idx)
        self.package_combo.blockSignals(False)
        self._update_package_tooltip()
        self._update_package_dropdown_width([saved] + pkgs)
        if not self._skip_snapshot:
            self.changed.emit()

    def _fill_current_app_package(self):
        pkg = adb_manager.get_current_foreground_package(adb_manager.adbdevice)
        if not pkg:
            QtWidgets.QMessageBox.information(
                self,
                "현재 앱",
                "현재 화면의 앱 패키지를 찾지 못했습니다.\nADB 연결 상태와 앱 포커스를 확인해 주세요.",
            )
            return
        self.package_combo.setEditText(pkg)
        self._update_package_tooltip(pkg)
        self._update_package_dropdown_width([pkg])

    def _on_package_text_changed(self, text):
        self._update_package_tooltip(text)
        self._update_package_dropdown_width([text])
        self._on_change()

    def _update_package_tooltip(self, text=None):
        pkg = (self.package_combo.currentText() if text is None else text).strip()
        tooltip = f"패키지: {pkg}" if pkg else "실행할 앱 패키지를 입력하거나 선택합니다."
        self.package_combo.setToolTip(tooltip)
        if self.package_combo.lineEdit():
            self.package_combo.lineEdit().setToolTip(tooltip)

    def _update_package_dropdown_width(self, candidates=None):
        values = list(candidates or [])
        values.extend(self.package_combo.itemText(i) for i in range(self.package_combo.count()))
        values.append(self.package_combo.currentText())
        longest = max((v for v in values if v), key=len, default="")
        metrics = self.package_combo.fontMetrics()
        width = metrics.horizontalAdvance(longest) + 80
        width = max(320, min(width, 900))
        self.package_combo.view().setMinimumWidth(width)

    def _load_json(self, val):
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _refresh_game_nodes(self, state=None):
        if not self.node or self.node.type_ != 'macro.nodes.GameNode':
            return

        connected_out_nodes = self.node.connected_output_nodes().get(self.node.outputs()['out'], [])

        current_guards = {}
        current_plans = {}

        for n in connected_out_nodes:
            info = {'id': n.id, 'label': n.name(), 'type': n.type_}
            if n.type_ == 'macro.nodes.GuardNode':
                current_guards[n.id] = info
            elif n.type_ == 'macro.nodes.PlanNode':
                current_plans[n.id] = info

        if state:
            saved_plan_ids = self._load_json(state.get('plan_nodes_order', '[]'))
            saved_guard_ids = self._load_json(state.get('guard_nodes_order', '[]'))
        else:
            saved_plan_ids = self._load_json(self.node.get_property('plan_nodes_order') or '[]')
            saved_guard_ids = self._load_json(self.node.get_property('guard_nodes_order') or '[]')

        new_guard_info = []
        for sid in saved_guard_ids:
            if sid in current_guards:
                new_guard_info.append(current_guards[sid])
                del current_guards[sid]
        for info in current_guards.values():
            new_guard_info.append(info)

        new_plan_info = []
        for sid in saved_plan_ids:
            if sid in current_plans:
                new_plan_info.append(current_plans[sid])
                del current_plans[sid]
        for info in current_plans.values():
            new_plan_info.append(info)

        self.guard_order_list.set_items(new_guard_info, 'Guard')
        self.plan_order_list.set_items(new_plan_info, 'Plan')

        if not self._skip_snapshot:
            self.changed.emit()

    def get_state_from_node(self, node):
        if not node or node.type_ != 'macro.nodes.GameNode':
            return {}
        connected = node.connected_output_nodes().get(node.outputs()['out'], [])
        current_guards = {}
        current_plans = {}
        for n in connected:
            info = {'id': n.id, 'label': n.name(), 'type': n.type_}
            if n.type_ == 'macro.nodes.GuardNode':
                current_guards[n.id] = info
            elif n.type_ == 'macro.nodes.PlanNode':
                current_plans[n.id] = info
        saved_plan_ids = self._load_json(node.get_property('plan_nodes_order') or '[]')
        saved_guard_ids = self._load_json(node.get_property('guard_nodes_order') or '[]')
        new_guard_info = []
        for sid in saved_guard_ids:
            if sid in current_guards:
                new_guard_info.append(current_guards[sid])
                del current_guards[sid]
        for info in current_guards.values():
            new_guard_info.append(info)
        new_plan_info = []
        for sid in saved_plan_ids:
            if sid in current_plans:
                new_plan_info.append(current_plans[sid])
                del current_plans[sid]
        for info in current_plans.values():
            new_plan_info.append(info)
        plan_ids = [x['id'] for x in new_plan_info]
        guard_ids = [x['id'] for x in new_guard_info]
        var_list = self._load_json(node.get_property('daily_variables') if node.has_property('daily_variables') else '[]')
        reset_time_str = node.get_property('reset_time') if node.has_property('reset_time') else '05:00:00'
        pkg = node.get_property('launch_package') if node.has_property('launch_package') else ''
        try:
            wait_v = float(node.get_property('post_launch_wait_seconds') or '0')
        except (TypeError, ValueError):
            wait_v = 0.0
        return {
            'plan_nodes_order': json.dumps(plan_ids),
            'guard_nodes_order': json.dumps(guard_ids),
            'daily_variables': json.dumps(var_list, ensure_ascii=False),
            'reset_time': reset_time_str,
            'launch_package': (pkg or '').strip(),
            'post_launch_wait_seconds': str(wait_v),
        }
