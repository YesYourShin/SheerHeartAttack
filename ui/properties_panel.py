"""
RuleNode/GuardNode용 우측 Properties 패널.
캡처+조건/동작 편집+Undo/Redo+미저장 확인.
"""
import json
import os
from PySide6 import QtWidgets, QtCore

from ui.styles import DARK_STYLE

class StartNodeOrderList(QtWidgets.QListWidget):
    """연결 노드 실행 순서를 지정하는 공용 리스트"""
    order_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.order_changed.emit()

    def set_items(self, info_list, label_prefix=""):
        self.clear()
        for info in info_list:
            node_id = info['id']
            node_label = info.get('label', 'Unnamed')
            text = f"[{label_prefix}] {node_label}" if label_prefix else node_label
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, node_id)
            self.addItem(item)

    def get_order_data(self):
        order = []
        for i in range(self.count()):
            item = self.item(i)
            order.append(item.data(QtCore.Qt.UserRole))
        return order

from ui.panels.game_panel import GameNodePanel
from ui.panels.entry_start_panel import EntryStartPanel
from ui.panels.rule_panel import RuleNodePanel
from ui.panels.plan_guard_panel import PlanGuardNodePanel


class ConditionalWheelScrollArea(QtWidgets.QScrollArea):
    def wheelEvent(self, event):
        if self.verticalScrollBar().maximum() <= 0:
            event.ignore()
            return
        super().wheelEvent(event)


class CurrentOnlyStackedWidget(QtWidgets.QStackedWidget):
    def sizeHint(self):
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return super().minimumSizeHint()


# 지원하는 노드 타입
_EDITABLE_TYPES = {
    'macro.nodes.RuleNode', 'macro.nodes.GuardNode', 'macro.nodes.PlanNode',
    'macro.nodes.StartNode', 'macro.nodes.GameNode',
}

_JSON_LIST_FIELDS = {
    'conditions', 'actions', 'variable_ops',
    'daily_variables', 'out_nodes_order', 'game_nodes_order',
    'plan_nodes_order', 'guard_nodes_order',
}

_BOOL_FIELDS = {'use_custom_reset_time'}
_FLOAT_FIELDS = {'post_launch_wait_seconds', 'next_rule_search_timeout_seconds'}

_COMPARE_DEFAULTS = {
    'macro.nodes.RuleNode': {
        'name': '',
        'capture_image': '',
        'conditions': [],
        'actions': [],
        'variable_ops': [],
        'out_nodes_order': [],
        'next_rule_search_timeout_seconds': 5.0,
    },
    'macro.nodes.StartNode': {
        'name': '',
        'game_nodes_order': [],
    },
    'macro.nodes.GameNode': {
        'name': '',
        'plan_nodes_order': [],
        'guard_nodes_order': [],
        'daily_variables': [],
        'reset_time': '05:00:00',
        'launch_package': '',
        'post_launch_wait_seconds': 0.0,
    },
    'macro.nodes.PlanNode': {
        'name': '',
        'use_custom_reset_time': False,
        'reset_time': '05:00:00',
        'guard_nodes_order': [],
        'completion_counter_var': '',
    },
    'macro.nodes.GuardNode': {
        'name': '',
        'after_guard_complete': 'resume',
        'after_guard_target_plan_id': '',
    },
}


def _canonical_nested(value):
    """比較用: dict のキー順だけ無視し、list の順序は維持する。"""
    if isinstance(value, dict):
        return {
            str(k): _canonical_nested(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_canonical_nested(v) for v in value]
    return value


def _canonical_json_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else []
        except (json.JSONDecodeError, TypeError, ValueError):
            value = []
    if value is None:
        value = []
    if not isinstance(value, list):
        value = []
    return _canonical_nested(value)


def _canonical_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'yes', 'y', 'on')


def _canonical_float(value):
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _canonical_scalar(value):
    if value is None:
        return ''
    return str(value).strip()


def _canonical_for_compare(state, node_type):
    raw = dict(state or {})
    out = {}
    for key, value in raw.items():
        if key in _JSON_LIST_FIELDS:
            out[key] = _canonical_json_list(value)
        elif key in _BOOL_FIELDS:
            out[key] = _canonical_bool(value)
        elif key in _FLOAT_FIELDS:
            out[key] = _canonical_float(value)
        else:
            out[key] = _canonical_scalar(value)

    for key, default in _COMPARE_DEFAULTS.get(node_type, {}).items():
        if key not in out:
            out[key] = default

    if node_type == 'macro.nodes.GuardNode':
        mode = out.get('after_guard_complete') or 'resume'
        if mode not in ('resume', 'restart_from_start', 'goto_plan'):
            mode = 'resume'
        out['after_guard_complete'] = mode
        if mode != 'goto_plan':
            out['after_guard_target_plan_id'] = ''

    if node_type == 'macro.nodes.PlanNode':
        out['use_custom_reset_time'] = _canonical_bool(out.get('use_custom_reset_time'))
        out['reset_time'] = out.get('reset_time') or '05:00:00'

    return out

# 開発中のみ True: 미저장 diff の最初のキーを 1 行表示
# 環境変数 MACRO_PROPS_DEBUG=1 でも有効(ファイルを編集しなくてよい)
_PROPS_UNSAVE_DEBUG = False


def _unsave_debug_enabled():
    if _PROPS_UNSAVE_DEBUG:
        return True
    v = (os.environ.get("MACRO_PROPS_DEBUG") or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")

class RulePropertiesPanel(QtWidgets.QWidget):
    capture_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self.saved_state = None
        self._skip_snapshot = False
        self._loading_node = False
        self._discarding = False
        self._is_adb_connected = False
        self._baseline_expected_id = None
        # baseline 用: 前回の QTimer を止めてから再スケジュール(ノード切替の競合防止)
        self._baseline_timer0 = QtCore.QTimer(self)
        self._baseline_timer0.setSingleShot(True)
        self._baseline_timer0.timeout.connect(self._on_baseline_timer0)
        self._baseline_timer50 = QtCore.QTimer(self)
        self._baseline_timer50.setSingleShot(True)
        self._baseline_timer50.timeout.connect(self._on_baseline_timer50)
        # Guard: UI 安定まで dirty 比較を一時的に避ける(compare_dirty_unblocked)
        self._compare_dirty_unblocked = True

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 6, 6, 6)

        # 미선택 스크린
        self.empty_label = QtWidgets.QLabel("노드를 클릭하면\n여기에 속성이 표시됩니다")
        self.empty_label.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; font-size: 13px;")
        self.main_layout.addWidget(self.empty_label)

        # 편집 영역
        self.edit_scroll = ConditionalWheelScrollArea()
        self.edit_scroll.setWidgetResizable(True)
        self.edit_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.edit_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.edit_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.edit_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.edit_area = QtWidgets.QWidget()
        self.edit_area.setStyleSheet("background: transparent;")
        edit_layout = QtWidgets.QVBoxLayout(self.edit_area)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        # 라벨 (공통)
        lbl_row = QtWidgets.QHBoxLayout()
        lbl_row.addWidget(QtWidgets.QLabel("노드 이름:"))
        self.label_input = QtWidgets.QLineEdit()
        self.label_input.textChanged.connect(self._on_change)
        lbl_row.addWidget(self.label_input)
        edit_layout.addLayout(lbl_row)

        # QStackedWidget을 통한 노드별 컨텐츠 교체
        self.stacked_widget = CurrentOnlyStackedWidget()
        
        self.rule_widget = RuleNodePanel()
        self.rule_widget.capture_requested.connect(self.capture_requested.emit)
        self.rule_widget.changed.connect(self._on_change)
        self.stacked_widget.addWidget(self.rule_widget)
        
        self.entry_start_widget = EntryStartPanel()
        self.entry_start_widget.changed.connect(self._on_change)
        self.stacked_widget.addWidget(self.entry_start_widget)

        self.game_widget = GameNodePanel()
        self.game_widget.changed.connect(self._on_change)
        self.stacked_widget.addWidget(self.game_widget)
        
        self.plan_guard_widget = PlanGuardNodePanel()
        self.plan_guard_widget.changed.connect(self._on_change)
        self.stacked_widget.addWidget(self.plan_guard_widget)

        edit_layout.addWidget(self.stacked_widget)

        self.edit_scroll.setWidget(self.edit_area)
        self.main_layout.addWidget(self.edit_scroll)
        self.edit_scroll.setVisible(False)

    def get_active_panel(self):
        if not self.node:
            return None
        if self.node.type_ == 'macro.nodes.StartNode':
            return self.entry_start_widget
        if self.node.type_ == 'macro.nodes.GameNode':
            return self.game_widget
        if self.node.type_ in ['macro.nodes.PlanNode', 'macro.nodes.GuardNode']:
            return self.plan_guard_widget
        return self.rule_widget

    def set_adb_connected(self, is_connected):
        self._is_adb_connected = is_connected
        self.rule_widget.set_adb_connected(is_connected)

    def set_capture_image(self, path):
        self.rule_widget.set_capture_image(path)

    def refresh_plan_guard_connections(self):
        if not self.node or self.node.type_ != 'macro.nodes.PlanNode':
            return
        self.plan_guard_widget._refresh_plan_guards()

    def refresh_game_connections(self):
        if not self.node or self.node.type_ != 'macro.nodes.GameNode':
            return
        self.game_widget._refresh_game_nodes()

    @staticmethod
    def _label_text_from_node(node):
        if not node:
            return ""
        return node.name() or ""

    def _committed_from_node(self):
        if not self.node or self.node.type_ not in _EDITABLE_TYPES:
            return None
        p = self.get_active_panel()
        d = {}
        if p:
            d.update(p.get_state_from_node(self.node))
        d["name"] = self._label_text_from_node(self.node)
        return d

    def _reload_ui_from_node(self):
        if not self.node:
            return
        self._skip_snapshot = True
        self._set_label_text_silent(self._label_text_from_node(self.node))
        p = self.get_active_panel()
        if p:
            p.load_node(self.node, None)
        self._skip_snapshot = False

    def _set_compare_gating_for_node(self, node):
        self._compare_dirty_unblocked = not (
            node and getattr(node, "type_", None) == "macro.nodes.GuardNode"
        )

    def _get_state(self):
        state = {'name': self.label_input.text()}
        active_panel = self.get_active_panel()
        if active_panel:
            state.update(active_panel.get_state())
        return state

    def _state_for_compare(self, state):
        node_type = getattr(self.node, 'type_', None)
        return _canonical_for_compare(state, node_type)

    def _set_label_text_silent(self, text):
        """setText 時の textChanged で dirty にならないよう遮断"""
        self.label_input.blockSignals(True)
        try:
            self.label_input.setText(text or "")
        finally:
            self.label_input.blockSignals(False)

    def _set_state(self, state):
        self._skip_snapshot = True
        self._set_label_text_silent(state.get('name', ''))
        
        active_panel = self.get_active_panel()
        if active_panel:
            active_panel.load_node(self.node, state)
        self._refresh_edit_area_minimum_height()

        self._skip_snapshot = False

    def _refresh_edit_area_minimum_height(self):
        size_hint = self.edit_area.sizeHint()
        min_height = max(0, size_hint.height())
        if self.edit_area.minimumHeight() != min_height:
            self.edit_area.setMinimumHeight(min_height)

    def _on_change(self, *args):
        if self._skip_snapshot or self._loading_node or self._discarding:
            return
        self._save_to_node(push_undo=True)

    def _log_unsaved_diff(self, cur, ref):
        node_type = getattr(self.node, 'type_', '')
        node_name = self._label_text_from_node(self.node)
        print(f"[properties] dirty node type={node_type!r} name={node_name!r}")
        diff_keys = [k for k in sorted(set(cur) | set(ref)) if cur.get(k) != ref.get(k)]
        for k in diff_keys[:5]:
            print(f"[properties] diff key={k!r} cur={cur.get(k)!r} ref={ref.get(k)!r}")
        if len(diff_keys) > 5:
            print(f"[properties] diff more={len(diff_keys) - 5}")

    def has_unsaved_changes(self):
        return False

    def _apply_baseline(self):
        """노드 원본과 동일한 정규화 ref を saved_state に(표시=원본이면 dirty 아님)."""
        if not self.node or self.node.type_ not in _EDITABLE_TYPES:
            return
        raw = self._committed_from_node()
        if raw is None:
            return
        self.saved_state = self._state_for_compare(raw)

    def _apply_baseline_if_node_id(self, expected_id):
        if not self.node or getattr(self.node, "id", None) != expected_id:
            return
        self._apply_baseline()

    def _cancel_baseline_timers(self):
        self._baseline_timer0.stop()
        self._baseline_timer50.stop()

    def _on_baseline_timer0(self):
        self._apply_baseline_if_node_id(self._baseline_expected_id)

    def _on_baseline_timer50(self):
        self._compare_dirty_unblocked = True
        self._apply_baseline_if_node_id(self._baseline_expected_id)

    def _schedule_baseline_for_node(self, node):
        """Guard ノードは QComboBox などが1フレーム遅れて揃うため baseline を複数回当てる。"""
        if not node or node.type_ not in _EDITABLE_TYPES:
            return
        self._cancel_baseline_timers()
        self._baseline_expected_id = getattr(node, "id", None)
        is_guard = node.type_ == "macro.nodes.GuardNode"
        self._apply_baseline()
        self._baseline_timer0.start(0)
        if is_guard:
            self._baseline_timer50.start(50)

    def load_node(self, node):
        self._cancel_baseline_timers()
        self._loading_node = True
        self.node = node

        try:
            if not node or node.type_ not in _EDITABLE_TYPES:
                self.empty_label.setVisible(True)
                self.edit_scroll.setVisible(False)
                self.saved_state = None
                self.plan_guard_widget.detach_from_host()
                return

            self.empty_label.setVisible(False)
            self.edit_scroll.setVisible(True)

            self._skip_snapshot = True
            self._set_label_text_silent(node.name())

            active_panel = self.get_active_panel()
            if active_panel:
                self.stacked_widget.setCurrentWidget(active_panel)
                active_panel.load_node(node)
            self._refresh_edit_area_minimum_height()

            if node.type_ not in ['macro.nodes.PlanNode', 'macro.nodes.GuardNode']:
                self.plan_guard_widget.detach_from_host()

            self._skip_snapshot = False
            self._set_compare_gating_for_node(node)
            self._schedule_baseline_for_node(node)
        finally:
            self._skip_snapshot = False
            self._loading_node = False

    def _save_to_node(self, push_undo=False):
        if not self.node or self.node.type_ not in _EDITABLE_TYPES:
            return
        self._cancel_baseline_timers()
        new_name = self.label_input.text().strip()
        if new_name and new_name != self.node.name():
            try:
                self.node.set_property('name', new_name, push_undo=push_undo)
            except TypeError:
                self.node.set_property('name', new_name)
            
        active_panel = self.get_active_panel()
        if active_panel:
            active_panel.save_to_node(push_undo=push_undo)

        self._set_compare_gating_for_node(self.node)
        self._schedule_baseline_for_node(self.node)

    def force_save(self, push_undo=False):
        self._save_to_node(push_undo=push_undo)

    def discard_changes(self):
        if not self.node:
            return
        self._cancel_baseline_timers()
        self._discarding = True
        try:
            self._reload_ui_from_node()
        finally:
            self._discarding = False
        self._schedule_baseline_for_node(self.node)
        self._refresh_edit_area_minimum_height()

    def clear_node(self):
        self._cancel_baseline_timers()
        self.node = None
        self.saved_state = None
        self._loading_node = False
        self._discarding = False
        self._compare_dirty_unblocked = True
        self.plan_guard_widget.detach_from_host()
        self.empty_label.setVisible(True)
        self.edit_scroll.setVisible(False)
