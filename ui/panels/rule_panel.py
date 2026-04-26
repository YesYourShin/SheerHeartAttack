import json
import os
from PySide6 import QtWidgets, QtCore

from ui.panels.base_panel import BasePropertyPanel
from ui.image_widgets import CapturePreview, FullImageViewer
from ui.widgets.list_editor import ListEditor
from ui.dialogs.condition_edit_dialog import ConditionEditDialog
from ui.dialogs.action_edit_dialog import ActionEditDialog
from ui.dialogs.variable_op_edit_dialog import VariableOpEditDialog
from ui.edit_dialogs import (
    _describe_condition, _describe_action, _describe_variable_op
)
from ui.properties_panel import StartNodeOrderList

class RuleNodePanel(BasePropertyPanel):
    capture_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self._pending_capture_path = ""
        self._is_adb_connected = False
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        # 狭いPropertiesでもボタン同士が押し合わないようグリッド配置にする。
        cap_row = QtWidgets.QGridLayout()
        cap_row.setHorizontalSpacing(6)
        self.capture_btn = QtWidgets.QPushButton("📸 캡처")
        self.capture_btn.setToolTip("ADB로 스크린샷을 찍어 이 노드에 등록")
        self.capture_btn.clicked.connect(self._on_capture_clicked)
        self.capture_btn.setEnabled(False)
        cap_row.addWidget(self.capture_btn, 0, 0)
        
        self.view_original_btn = QtWidgets.QPushButton("🔎 원본 보기")
        self.view_original_btn.setToolTip("캡처 이미지를 원본 크기로 봅니다")
        self.view_original_btn.clicked.connect(self._view_original_image)
        self.view_original_btn.setEnabled(False)
        cap_row.addWidget(self.view_original_btn, 0, 1)
        cap_row.setColumnStretch(0, 1)
        cap_row.setColumnStretch(1, 1)
        layout.addLayout(cap_row)

        self.preview = CapturePreview()
        layout.addWidget(self.preview)

        timeout_row = QtWidgets.QHBoxLayout()
        timeout_row.addWidget(QtWidgets.QLabel("다음 Rule 탐색 제한(초):"))
        self.next_rule_timeout_spin = QtWidgets.QDoubleSpinBox()
        self.next_rule_timeout_spin.setDecimals(1)
        self.next_rule_timeout_spin.setRange(0.5, 3600.0)
        self.next_rule_timeout_spin.setSingleStep(0.5)
        self.next_rule_timeout_spin.setValue(5.0)
        self.next_rule_timeout_spin.valueChanged.connect(self._on_change)
        timeout_row.addWidget(self.next_rule_timeout_spin)
        timeout_row.addStretch()
        layout.addLayout(timeout_row)

        # 탭 (조건/동작/분기)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("ruleTabs")
        
        self.cond_editor = ListEditor([], _describe_condition, ConditionEditDialog,
                                       on_change=self._on_change,
                                       capture_path_fn=self._get_capture_path,
                                      dialog_kwargs_fn=self._rule_dialog_common_kwargs)
        self.tabs.addTab(self.cond_editor, "🔍 조건")
        
        self.act_editor = ListEditor([], _describe_action, ActionEditDialog,
                                      on_change=self._on_change,
                                      capture_path_fn=self._get_capture_path,
                                      dialog_kwargs_fn=self._get_action_dialog_kwargs)
        self.tabs.addTab(self.act_editor, "🖱️ 동작")
        

        
        # Rule 분기 관리
        self.rule_out_widget = QtWidgets.QWidget()
        rule_out_layout = QtWidgets.QVBoxLayout(self.rule_out_widget)
        rule_out_layout.addWidget(QtWidgets.QLabel("🔄 Rule 다중 갈래 연결 우선순위:"))
        self.rule_order_list = StartNodeOrderList()
        self.rule_order_list.order_changed.connect(self._on_change)
        rule_out_layout.addWidget(self.rule_order_list)
        
        self.rule_refresh_btn = QtWidgets.QPushButton("🔄 연결된 다음 노드 새로고침")
        self.rule_refresh_btn.setToolTip("out 포트에 여러 개의 노드가 연결되었을 경우 검사 순서를 정합니다.")
        self.rule_refresh_btn.clicked.connect(self._refresh_rule_out_nodes)
        rule_out_layout.addWidget(self.rule_refresh_btn)
        self.tabs.addTab(self.rule_out_widget, "🔀 분기 순서")
        
        layout.addWidget(self.tabs)

    def _rule_dialog_common_kwargs(self):
        kwargs = self._get_action_dialog_kwargs()
        defaults = {}
        win = self.window()
        if win and hasattr(win, "node_default_settings"):
            defaults = win.node_default_settings.get("macro.nodes.RuleNode", {})
        kwargs["condition_default_threshold"] = defaults.get("default_condition_threshold", "0.8")
        return kwargs

    def _get_capture_path(self):
        if self._pending_capture_path:
            if self._pending_capture_path.startswith("data:image/png;base64,") or os.path.exists(self._pending_capture_path):
                return self._pending_capture_path
        if self.node:
            p = self.node.get_property('capture_image') or ''
            if p:
                if p.startswith("data:image/png;base64,") or os.path.exists(p):
                    return p
        return ""

    def _on_capture_clicked(self):
        self.capture_requested.emit()

    def set_adb_connected(self, is_connected):
        self._is_adb_connected = is_connected
        if self.node and self.node.type_ not in ['macro.nodes.StartNode', 'macro.nodes.GameNode', 'macro.nodes.PlanNode', 'macro.nodes.GuardNode']:
            self.capture_btn.setEnabled(is_connected)
        else:
            self.capture_btn.setEnabled(False)

    def _view_original_image(self):
        path = self._get_capture_path()
        if path and (path.startswith("data:image/png;base64,") or os.path.exists(path)):
            conditions = self.cond_editor.get_items()
            actions = self.act_editor.get_items()
            dlg = FullImageViewer(path, conditions=conditions, actions=actions, parent=self)
            dlg.exec()
        else:
            QtWidgets.QMessageBox.information(self, "알림", "표시할 캡처 이미지가 없습니다.")

    def set_capture_image(self, path):
        self._pending_capture_path = path
        self.preview.set_image(path)
        is_valid = bool(path and (path.startswith("data:image/png;base64,") or os.path.exists(path)))
        self.view_original_btn.setEnabled(is_valid)
        self._on_change()

    def _load_json(self, val):
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _load_from_state(self, state):
        if not self.node: return
        
        if state:
            cond_data = self._load_json(state.get('conditions', '[]'))
            act_data = self._load_json(state.get('actions', '[]'))
            varop_data = self._load_json(state.get('variable_ops', '[]'))
            cap = state.get('capture_image', '')
            timeout_sec = state.get('next_rule_search_timeout_seconds', '5')
        else:
            cond_data = self._load_json(self.node.get_property('conditions'))
            act_data = self._load_json(self.node.get_property('actions'))
            varop_data = self._load_json(self.node.get_property('variable_ops')) if self.node.has_property('variable_ops') else []
            cap = self.node.get_property('capture_image') if self.node.has_property('capture_image') else ''
            timeout_sec = self.node.get_property('next_rule_search_timeout_seconds') if self.node.has_property('next_rule_search_timeout_seconds') else '5'
            
        # 마이그레이션: 기존 variable_ops를 actions 내 var_op 타입으로 전환
        if varop_data:
            for op in varop_data:
                is_dup = False
                for existing_act in act_data:
                    if existing_act.get('type') == 'var_op' and existing_act.get('name') == op.get('name'):
                        is_dup = True
                        break
                if not is_dup:
                    act_data.append({
                        "type": "var_op",
                        "name": op.get('name', ''),
                        "operation": op.get('operation', '='),
                        "value": op.get('value', 0)
                    })

        self.cond_editor.items = list(cond_data)
        self.cond_editor._refresh_list()
        
        self.act_editor.items = list(act_data)
        self.act_editor._refresh_list()
        
        self.capture_btn.setEnabled(self._is_adb_connected)
        self._pending_capture_path = cap
        self.preview.set_image(cap)
        self.view_original_btn.setEnabled(bool(cap and (cap.startswith("data:image/png;base64,") or os.path.exists(cap))))
        self.next_rule_timeout_spin.blockSignals(True)
        try:
            try:
                sec = float(timeout_sec)
            except (TypeError, ValueError):
                sec = 5.0
            if sec < 0.5:
                sec = 0.5
            self.next_rule_timeout_spin.setValue(sec)
        finally:
            self.next_rule_timeout_spin.blockSignals(False)
        
        if self.node.type_ == 'macro.nodes.RuleNode':
            self.rule_out_widget.setVisible(True)
            self._refresh_rule_out_nodes(state)
        else:
            self.rule_out_widget.setVisible(False)
            
        # UI overlays
        self.preview.set_overlays(self.cond_editor.get_items(), self.act_editor.get_items())

    def get_state(self):
        state = {
            'capture_image': self._pending_capture_path or (self.node.get_property('capture_image') if self.node and self.node.has_property('capture_image') else ''),
            'conditions': json.dumps(self.cond_editor.get_items(), ensure_ascii=False),
            'actions': json.dumps(self.act_editor.get_items(), ensure_ascii=False),
            'variable_ops': '[]',
            'next_rule_search_timeout_seconds': str(self.next_rule_timeout_spin.value())
        }
        if self.node and self.node.type_ == 'macro.nodes.RuleNode':
            state['out_nodes_order'] = json.dumps(self.rule_order_list.get_order_data())
        return state

    def save_to_node(self, push_undo=False):
        if not self.node: return
        
        if self.node.has_property('conditions'):
            self._set_node_property(
                'conditions',
                json.dumps(self.cond_editor.get_items(), ensure_ascii=False),
                push_undo=push_undo
            )
        if self.node.has_property('actions'):
            self._set_node_property(
                'actions',
                json.dumps(self.act_editor.get_items(), ensure_ascii=False),
                push_undo=push_undo
            )
        if self.node.has_property('variable_ops'):
            self._set_node_property('variable_ops', '[]', push_undo=push_undo)
            
        if self.node.type_ == 'macro.nodes.RuleNode':
            order_data = self.rule_order_list.get_order_data()
            self._set_node_property('out_nodes_order', json.dumps(order_data), push_undo=push_undo)
            if self.node.has_property('next_rule_search_timeout_seconds'):
                self._set_node_property(
                    'next_rule_search_timeout_seconds',
                    str(self.next_rule_timeout_spin.value()),
                    push_undo=push_undo
                )
        
        cap_path = self._pending_capture_path or (self.node.get_property('capture_image') if self.node.has_property('capture_image') else '')
        if self.node.has_property('capture_image'):
            self._set_node_property('capture_image', cap_path, push_undo=push_undo)
            
    def _refresh_rule_out_nodes(self, state=None):
        if not self.node or self.node.type_ != 'macro.nodes.RuleNode':
            return
            
        connected_out_nodes = self.node.connected_output_nodes().get(self.node.outputs()['out'], [])
        current_out_nodes = {}
        for n in connected_out_nodes:
            current_out_nodes[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}
                
        # 기존 저장된 순서
        if state:
            saved_out_ids = self._load_json(state.get('out_nodes_order', '[]'))
        else:
            saved_out_ids = self._load_json(self.node.get_property('out_nodes_order') or '[]')
        
        new_out_info = []
        for sid in saved_out_ids:
            if sid in current_out_nodes:
                new_out_info.append(current_out_nodes[sid])
                del current_out_nodes[sid]
        
        for info in current_out_nodes.values():
            new_out_info.append(info)
            
        self.rule_order_list.set_items(new_out_info, 'Next Rule/Plan')
        
        if not self._skip_snapshot:
            self.changed.emit()

    @staticmethod
    def _var_ops_migrate_into_actions(varop_data, act_data):
        if not varop_data:
            return act_data
        out = list(act_data) if act_data else []
        for op in varop_data:
            is_dup = False
            for existing_act in out:
                if existing_act.get('type') == 'var_op' and existing_act.get('name') == op.get('name'):
                    is_dup = True
                    break
            if not is_dup:
                out.append({
                    "type": "var_op",
                    "name": op.get('name', ''),
                    "operation": op.get('operation', '='),
                    "value": op.get('value', 0)
                })
        return out

    def _rule_out_ids_from_node(self, node):
        if not node or node.type_ != 'macro.nodes.RuleNode':
            return []
        connected = node.connected_output_nodes().get(node.outputs()['out'], [])
        current = {}
        for n in connected:
            current[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}
        saved_ids = self._load_json(node.get_property('out_nodes_order') or '[]')
        order = []
        for sid in saved_ids:
            if sid in current:
                order.append(sid)
                del current[sid]
        for info in current.values():
            order.append(info['id'])
        return order

    def get_state_from_node(self, node):
        if not node or node.type_ != 'macro.nodes.RuleNode':
            return {}
        cond_data = self._load_json(node.get_property('conditions') if node.has_property('conditions') else '[]')
        act_data = self._load_json(node.get_property('actions') if node.has_property('actions') else '[]')
        varop_data = self._load_json(
            node.get_property('variable_ops') if node.has_property('variable_ops') else '[]'
        )
        act_data = self._var_ops_migrate_into_actions(varop_data, act_data)
        cap = node.get_property('capture_image') if node.has_property('capture_image') else ''
        state = {
            'capture_image': cap,
            'conditions': json.dumps(cond_data, ensure_ascii=False),
            'actions': json.dumps(act_data, ensure_ascii=False),
            'variable_ops': '[]',
            'next_rule_search_timeout_seconds': str(
                node.get_property('next_rule_search_timeout_seconds')
                if node.has_property('next_rule_search_timeout_seconds') else '5'
            ),
        }
        if node.type_ == 'macro.nodes.RuleNode':
            state['out_nodes_order'] = json.dumps(
                self._rule_out_ids_from_node(node), ensure_ascii=False
            )
        return state
