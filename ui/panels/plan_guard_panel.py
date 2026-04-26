import json
from PySide6 import QtWidgets, QtCore
from ui.panels.base_panel import BasePropertyPanel
from ui.properties_panel import StartNodeOrderList

class PlanGuardNodePanel(BasePropertyPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        # Plan専用: 接続したGuardの優先順位
        self.plan_guard_group = QtWidgets.QGroupBox("🛡 Plan 연결 Guard 순서")
        pg_layout = QtWidgets.QVBoxLayout(self.plan_guard_group)
        self.plan_guard_order_list = StartNodeOrderList()
        self.plan_guard_order_list.order_changed.connect(self._on_change)
        pg_layout.addWidget(self.plan_guard_order_list)
        layout.addWidget(self.plan_guard_group)
        self.plan_guard_group.setVisible(False)
        
        # 개별 초기화 시간 에디터 (PlanNode 전용)
        self.reset_time_group = QtWidgets.QGroupBox("⏰ 개별 초기화 시간")
        rt_layout = QtWidgets.QVBoxLayout(self.reset_time_group)
        self.use_custom_reset_cb = QtWidgets.QCheckBox("Game 노드 설정 무시하고 개별 시간 사용")
        self.use_custom_reset_cb.stateChanged.connect(self._on_change)
        self.use_custom_reset_cb.stateChanged.connect(self._toggle_reset_time)
        rt_layout.addWidget(self.use_custom_reset_cb)
        
        time_layout = QtWidgets.QHBoxLayout()
        time_layout.addWidget(QtWidgets.QLabel("초기화 시간:"))
        self.reset_time_edit = QtWidgets.QTimeEdit()
        self.reset_time_edit.setDisplayFormat("HH:mm:ss")
        self.reset_time_edit.timeChanged.connect(self._on_change)
        time_layout.addWidget(self.reset_time_edit)
        time_layout.addStretch()
        rt_layout.addLayout(time_layout)
        
        layout.addWidget(self.reset_time_group)
        self.reset_time_group.setVisible(False)

        self.plan_counter_group = QtWidgets.QGroupBox("완료 카운트 기록")
        pc_layout = QtWidgets.QHBoxLayout(self.plan_counter_group)
        pc_layout.addWidget(QtWidgets.QLabel("완료 변수명(선택):"))
        self.completion_counter_input = QtWidgets.QLineEdit()
        self.completion_counter_input.setPlaceholderText("자동 생성 사용 시 비워두세요")
        self.completion_counter_input.textChanged.connect(self._on_change)
        pc_layout.addWidget(self.completion_counter_input)
        layout.addWidget(self.plan_counter_group)
        self.plan_counter_group.setVisible(False)
        
        # Guard専用: 処理完了後の遷移
        self.guard_after_group = QtWidgets.QGroupBox("🛡 가드 처리 완료 후")
        ga_layout = QtWidgets.QVBoxLayout(self.guard_after_group)
        self.after_guard_combo = QtWidgets.QComboBox()
        self.after_guard_combo.addItem("직전 Rule에서 이어서", "resume")
        self.after_guard_combo.addItem("매크로 처음부터 전체 재시작", "restart_from_start")
        self.after_guard_combo.addItem("특정 Plan에서 다시 시작", "goto_plan")
        self.after_guard_combo.currentIndexChanged.connect(self._on_after_guard_mode_changed)
        self.after_guard_combo.currentTextChanged.connect(self._on_after_guard_mode_changed)
        self.after_guard_combo.activated.connect(self._on_after_guard_mode_changed)
        ga_layout.addWidget(self.after_guard_combo)
        goto_row = QtWidgets.QHBoxLayout()
        self.goto_plan_label = QtWidgets.QLabel("대상 Plan:")
        goto_row.addWidget(self.goto_plan_label)
        self.goto_plan_combo = QtWidgets.QComboBox()
        self.goto_plan_combo.setToolTip("같은 Game out에 연결된 모든 Plan이 표시됩니다.")
        self.goto_plan_combo.currentIndexChanged.connect(self._on_goto_plan_changed)
        self.goto_plan_combo.currentTextChanged.connect(self._on_goto_plan_changed)
        self.goto_plan_combo.activated.connect(self._on_goto_plan_changed)
        self.goto_plan_label.setVisible(False)
        self.goto_plan_combo.setVisible(False)
        goto_row.addWidget(self.goto_plan_combo, 1)
        ga_layout.addLayout(goto_row)
        layout.addWidget(self.guard_after_group)
        self.guard_after_group.setVisible(False)
        
        layout.addStretch()

    def detach_from_host(self):
        """Rule/Game/Start 等へ遷移したとき Plan/Guard 専用 UI の self.node 残留を解消"""
        self._skip_snapshot = True
        self.node = None
        self.plan_guard_group.setVisible(False)
        self.reset_time_group.setVisible(False)
        self.plan_counter_group.setVisible(False)
        self.guard_after_group.setVisible(False)
        if hasattr(self, "plan_guard_order_list"):
            self.plan_guard_order_list.clear()
        self._skip_snapshot = False

    def _on_after_guard_mode_ui(self):
        # goto_plan選択時のみPlan一覧を表示
        m = self.after_guard_combo.currentData()
        visible = m == 'goto_plan'
        self.goto_plan_label.setVisible(visible)
        self.goto_plan_combo.setVisible(visible)

    def _on_after_guard_mode_changed(self, *_args):
        self._on_after_guard_mode_ui()
        if not self._skip_snapshot:
            self.changed.emit()

    def _on_goto_plan_changed(self, *_args):
        if not self._skip_snapshot:
            self.changed.emit()

    def _find_upstream_game_node(self, node):
        """Guard/Plan から入力を遡り Game ノードを返す"""
        seen = set()
        cur = node
        while cur and cur.id not in seen:
            seen.add(cur.id)
            if getattr(cur, 'type_', None) == 'macro.nodes.GameNode':
                return cur
            try:
                inputs = cur.connected_input_nodes()
            except Exception:
                inputs = None
            if not inputs:
                break
            next_node = None
            if isinstance(inputs, dict):
                for linked_nodes in inputs.values():
                    if linked_nodes:
                        next_node = linked_nodes[0]
                        break
            elif isinstance(inputs, (list, tuple)):
                if inputs:
                    next_node = inputs[0]
            if not next_node:
                break
            cur = next_node
        return None

    def _plan_ids_for_game(self, gnode, graph):
        """Game の out に繋がった Plan を、plan_nodes_order 優先で安定順に列挙する（game_panel と同じルール）"""
        if not gnode or getattr(gnode, 'type_', None) != 'macro.nodes.GameNode' or not graph:
            return []
        try:
            out_port = gnode.outputs()['out']
            connected_out = gnode.connected_output_nodes().get(out_port, [])
        except Exception:
            connected_out = []
        current_plans = {}
        for n in connected_out:
            if getattr(n, 'type_', None) == 'macro.nodes.PlanNode':
                current_plans[n.id] = n
        order_raw = gnode.get_property('plan_nodes_order') if gnode.has_property('plan_nodes_order') else '[]'
        saved_ids = self._load_json(order_raw or '[]')
        ordered = []
        for pid in saved_ids:
            if pid in current_plans:
                ordered.append(pid)
                del current_plans[pid]
        for pid in sorted(current_plans.keys()):
            ordered.append(pid)
        return ordered

    def _refresh_goto_plan_targets(self, state=None):
        """上位 Game の out 上の全 Plan と plan_nodes_order をマージして一覧を構築する"""
        self.goto_plan_combo.blockSignals(True)
        self.goto_plan_combo.clear()
        self.goto_plan_combo.addItem("(선택)", "")
        if not self.node or getattr(self.node, 'type_', '') != 'macro.nodes.GuardNode':
            self.goto_plan_combo.blockSignals(False)
            return
        graph = getattr(self.node, 'graph', None)
        if not graph:
            self.goto_plan_combo.blockSignals(False)
            return
        gnode = self._find_upstream_game_node(self.node)
        if not gnode:
            self.goto_plan_combo.blockSignals(False)
            return
        plan_ids = self._plan_ids_for_game(gnode, graph)
        for pid in plan_ids:
            try:
                pn = graph.get_node_by_id(pid)
            except Exception:
                pn = None
            if pn and getattr(pn, 'type_', None) == 'macro.nodes.PlanNode':
                # userData は JSON/比較で常に str に揃える
                self.goto_plan_combo.addItem(pn.name(), str(pid))
        self.goto_plan_combo.blockSignals(False)

    def _toggle_reset_time(self):
        self.reset_time_edit.setEnabled(self.use_custom_reset_cb.isChecked())

    def _load_json(self, val):
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _dump_json_list(self, val):
        try:
            data = json.loads(val) if isinstance(val, str) else val
        except (json.JSONDecodeError, TypeError):
            data = []
        if not isinstance(data, list):
            data = []
        return json.dumps(data, ensure_ascii=False)

    def _coerce_guard_mode(self, mode):
        """QComboBoxの currentData が None/想定外のときに揃える。"""
        if mode is None:
            return 'resume'
        if isinstance(mode, str) and not mode.strip():
            return 'resume'
        s = str(mode).strip()
        if s not in ('resume', 'restart_from_start', 'goto_plan'):
            return 'resume'
        return s

    def _coerce_plan_target_id(self, tid):
        if tid is None:
            return ''
        return str(tid).strip()

    def _guard_mode_and_target_from_ui(self):
        """Guard 用: 比較・保存で同じ論理値になるよう取得。"""
        mode = self._coerce_guard_mode(self.after_guard_combo.currentData())
        if mode == 'goto_plan':
            idx = self.goto_plan_combo.currentIndex()
            raw = self.goto_plan_combo.itemData(idx) if idx >= 0 else None
            tid = self._coerce_plan_target_id(raw)
        else:
            tid = ''
        return mode, tid

    def normalize_state(self, state):
        """比較用にGuard/Planの状態を同じ形へ揃える。"""
        normalized = dict(state or {})

        if self.node and getattr(self.node, 'type_', '') == 'macro.nodes.PlanNode':
            use_custom = normalized.get('use_custom_reset_time', 'False')
            normalized['use_custom_reset_time'] = 'True' if use_custom == 'True' else 'False'
            normalized['reset_time'] = normalized.get('reset_time') or '05:00:00'
            normalized['guard_nodes_order'] = self._dump_json_list(normalized.get('guard_nodes_order', '[]'))
            normalized['completion_counter_var'] = str(normalized.get('completion_counter_var') or '').strip()

        if self.node and getattr(self.node, 'type_', '') == 'macro.nodes.GuardNode':
            mode = self._coerce_guard_mode(normalized.get('after_guard_complete'))
            normalized['after_guard_complete'] = mode
            if mode == 'goto_plan':
                normalized['after_guard_target_plan_id'] = self._coerce_plan_target_id(
                    normalized.get('after_guard_target_plan_id')
                )
            else:
                normalized['after_guard_target_plan_id'] = ''

        return normalized

    def _refresh_plan_guards(self, state=None):
        # Planの出力に繋がったGuardのみ順序管理
        if not self.node or self.node.type_ != 'macro.nodes.PlanNode':
            return
        connected_out_nodes = self.node.connected_output_nodes().get(self.node.outputs()['out'], [])
        current_guards = {}
        for n in connected_out_nodes:
            if n.type_ == 'macro.nodes.GuardNode':
                current_guards[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}
        if state:
            saved_guard_ids = self._load_json(state.get('guard_nodes_order', '[]'))
        else:
            saved_guard_ids = self._load_json(self.node.get_property('guard_nodes_order') or '[]')
        new_guard_info = []
        for sid in saved_guard_ids:
            if sid in current_guards:
                new_guard_info.append(current_guards[sid])
                del current_guards[sid]
        # 残りの Guard は id でソートして順序を安定化（dict の列挙順に依存させない）
        for gid in sorted(current_guards.keys()):
            new_guard_info.append(current_guards[gid])
        self.plan_guard_order_list.set_items(new_guard_info, 'Guard')
        if not self._skip_snapshot:
            self.changed.emit()

    def _load_from_state(self, state):
        if not self.node: return
        
        ntype = getattr(self.node, 'type_', '')
        is_plan = ntype == 'macro.nodes.PlanNode'
        is_guard = ntype == 'macro.nodes.GuardNode'
        
        self.plan_guard_group.setVisible(is_plan)
        self.guard_after_group.setVisible(is_guard)
        self.plan_counter_group.setVisible(is_plan)
        
        if is_plan:
            self._refresh_plan_guards(state)
        
        if is_plan:
            self.reset_time_group.setVisible(True)
            self.completion_counter_input.blockSignals(True)
            if state:
                use_custom = state.get('use_custom_reset_time', 'False') == 'True'
                reset_time_str = state.get('reset_time', '05:00:00')
                completion_var = str(state.get('completion_counter_var', '') or '')
            else:
                use_custom = self.node.get_property('use_custom_reset_time') == 'True' if self.node.has_property('use_custom_reset_time') else False
                reset_time_str = self.node.get_property('reset_time') if self.node.has_property('reset_time') else '05:00:00'
                completion_var = self.node.get_property('completion_counter_var') if self.node.has_property('completion_counter_var') else ''
            
            # ロード中はシグナルで dirty にならないよう遮断
            self.use_custom_reset_cb.blockSignals(True)
            self.reset_time_edit.blockSignals(True)
            try:
                self.use_custom_reset_cb.setChecked(use_custom)
                qt_time = QtCore.QTime.fromString(reset_time_str, "HH:mm:ss")
                if qt_time.isValid():
                    self.reset_time_edit.setTime(qt_time)
                self.completion_counter_input.setText(str(completion_var or ''))
            finally:
                self.use_custom_reset_cb.blockSignals(False)
                self.reset_time_edit.blockSignals(False)
                self.completion_counter_input.blockSignals(False)
            self._toggle_reset_time()
        else:
            self.reset_time_group.setVisible(False)
            self.plan_counter_group.setVisible(False)
            
        if is_guard:
            if state:
                mode = state.get('after_guard_complete', 'resume')
            else:
                mode = self.node.get_property('after_guard_complete') if self.node.has_property('after_guard_complete') else 'resume'
            mode = self._coerce_guard_mode(mode)
            idx = self.after_guard_combo.findData(mode)
            if idx < 0:
                idx = 0
            self.after_guard_combo.blockSignals(True)
            try:
                self.after_guard_combo.setCurrentIndex(idx)
            finally:
                self.after_guard_combo.blockSignals(False)
            self._refresh_goto_plan_targets(state)
            if state:
                tid = state.get('after_guard_target_plan_id') or ''
            else:
                tid = self.node.get_property('after_guard_target_plan_id') if self.node.has_property('after_guard_target_plan_id') else ''
            tid = self._coerce_plan_target_id(tid)
            # tid が空のときは (선택) に合わせる
            tidx = self.goto_plan_combo.findData(tid) if tid else self.goto_plan_combo.findData("")
            if tidx < 0:
                tidx = 0
            self.goto_plan_combo.blockSignals(True)
            try:
                self.goto_plan_combo.setCurrentIndex(tidx)
            finally:
                self.goto_plan_combo.blockSignals(False)
            self._on_after_guard_mode_ui()
            
    def get_state(self):
        state = {}
        if self.node and getattr(self.node, 'type_', '') == 'macro.nodes.PlanNode':
            state['use_custom_reset_time'] = 'True' if self.use_custom_reset_cb.isChecked() else 'False'
            state['reset_time'] = self.reset_time_edit.time().toString("HH:mm:ss")
            state['guard_nodes_order'] = self._dump_json_list(self.plan_guard_order_list.get_order_data())
            state['completion_counter_var'] = self.completion_counter_input.text().strip()
        if self.node and getattr(self.node, 'type_', '') == 'macro.nodes.GuardNode':
            mode, tid = self._guard_mode_and_target_from_ui()
            state['after_guard_complete'] = mode
            state['after_guard_target_plan_id'] = tid
        return self.normalize_state(state)

    def save_to_node(self, push_undo=False):
        if not self.node: return
        if getattr(self.node, 'type_', '') == 'macro.nodes.PlanNode':
            if self.node.has_property('use_custom_reset_time'):
                self._set_node_property(
                    'use_custom_reset_time',
                    'True' if self.use_custom_reset_cb.isChecked() else 'False',
                    push_undo=push_undo
                )
            if self.node.has_property('reset_time'):
                self._set_node_property(
                    'reset_time',
                    self.reset_time_edit.time().toString("HH:mm:ss"),
                    push_undo=push_undo
                )
            if self.node.has_property('guard_nodes_order'):
                self._set_node_property(
                    'guard_nodes_order',
                    json.dumps(self.plan_guard_order_list.get_order_data(), ensure_ascii=False),
                    push_undo=push_undo
                )
            if self.node.has_property('completion_counter_var'):
                self._set_node_property(
                    'completion_counter_var',
                    self.completion_counter_input.text().strip(),
                    push_undo=push_undo
                )
                
        if getattr(self.node, 'type_', '') == 'macro.nodes.GuardNode':
            mode, tid = self._guard_mode_and_target_from_ui()
            # has_property に依存しない（旧セッションでキー未作成のノードでも保存できるようにする）
            self._set_node_property('after_guard_complete', mode, push_undo=push_undo)
            self._set_node_property('after_guard_target_plan_id', tid, push_undo=push_undo)

    def _plan_guard_order_ids_from_node(self, node):
        if not node or node.type_ != 'macro.nodes.PlanNode':
            return []
        connected = node.connected_output_nodes().get(node.outputs()['out'], [])
        current = {}
        for n in connected:
            if n.type_ == 'macro.nodes.GuardNode':
                current[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}
        saved = self._load_json(node.get_property('guard_nodes_order') or '[]')
        order = []
        for sid in saved:
            if sid in current:
                order.append(sid)
                del current[sid]
        for gid in sorted(current.keys()):
            order.append(gid)
        return order

    def get_state_from_node(self, node):
        if not node or getattr(node, 'type_', '') not in ('macro.nodes.PlanNode', 'macro.nodes.GuardNode'):
            return {}
        ntype = getattr(node, 'type_', '') or ''
        is_plan = ntype == 'macro.nodes.PlanNode'
        is_guard = ntype == 'macro.nodes.GuardNode'
        prev = self.node
        self.node = node
        try:
            state = {}
            if is_plan:
                gids = self._plan_guard_order_ids_from_node(node)
                use_custom = (
                    node.get_property('use_custom_reset_time') == 'True'
                    if node.has_property('use_custom_reset_time') else False
                )
                reset_time_str = (
                    node.get_property('reset_time') if node.has_property('reset_time') else '05:00:00'
                )
                state['use_custom_reset_time'] = 'True' if use_custom else 'False'
                state['reset_time'] = reset_time_str
                state['guard_nodes_order'] = self._dump_json_list(gids)
                state['completion_counter_var'] = str(
                    node.get_property('completion_counter_var') if node.has_property('completion_counter_var') else ''
                ).strip()
            if is_guard:
                mode = self._coerce_guard_mode(
                    node.get_property('after_guard_complete')
                    if node.has_property('after_guard_complete') else 'resume'
                )
                if mode == 'goto_plan':
                    tid = self._coerce_plan_target_id(
                        node.get_property('after_guard_target_plan_id')
                        if node.has_property('after_guard_target_plan_id') else ''
                    )
                else:
                    tid = ''
                state['after_guard_complete'] = mode
                state['after_guard_target_plan_id'] = tid
            return self.normalize_state(state)
        finally:
            self.node = prev
