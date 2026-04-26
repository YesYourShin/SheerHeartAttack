import copy
import json
from PySide6 import QtWidgets, QtCore


NODE_DEFAULT_SCHEMA = {
    "macro.nodes.GameNode": {
        "reset_time": "05:00:00",
        "post_launch_wait_seconds": "0",
    },
    "macro.nodes.RuleNode": {
        "next_rule_search_timeout_seconds": "5",
        "default_condition_threshold": "0.8",
    },
}


NODE_TITLES = {
    "macro.nodes.GameNode": "Plan",
    "macro.nodes.RuleNode": "Rule",
}

FIELD_LABELS = {
    "post_launch_wait_seconds": "앱 실행 후 대기(초)",
    "reset_time": "일일 초기화 시간",
    "next_rule_search_timeout_seconds": "다음 Rule 탐색 제한(초)",
    "default_condition_threshold": "조건 이미지 유사도 기본값",
}


class NodeDefaultsDialog(QtWidgets.QDialog):
    def __init__(self, defaults_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Node Default Settings")
        self.resize(680, 560)
        self._editors = {}
        self._defaults_data = copy.deepcopy(defaults_data or {})

        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        self._build_tabs()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_tabs(self):
        for node_type, schema in NODE_DEFAULT_SCHEMA.items():
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            form.setContentsMargins(12, 12, 12, 12)
            form.setSpacing(8)
            self._editors[node_type] = {}

            saved_values = self._defaults_data.get(node_type, {})
            for key, default_value in schema.items():
                value = saved_values.get(key, default_value)
                editor = self._create_editor(key, value)
                self._editors[node_type][key] = editor
                form.addRow(f"{FIELD_LABELS.get(key, key)}:", editor)

            form.addItem(QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))
            self.tabs.addTab(page, NODE_TITLES.get(node_type, node_type))

    def get_values(self):
        result = {}
        for node_type, schema in NODE_DEFAULT_SCHEMA.items():
            node_values = {}
            for key in schema.keys():
                widget = self._editors[node_type][key]
                if key == "reset_time":
                    node_values[key] = widget.time().toString("HH:mm:ss")
                elif key in {"post_launch_wait_seconds", "next_rule_search_timeout_seconds", "default_condition_threshold"}:
                    node_values[key] = str(widget.value())
                else:
                    node_values[key] = str(schema[key])
            result[node_type] = node_values
        return result

    @staticmethod
    def normalize_defaults(defaults_data):
        normalized = {}
        source = defaults_data or {}
        for node_type, schema in NODE_DEFAULT_SCHEMA.items():
            src_values = source.get(node_type, {})
            normalized[node_type] = {}
            for key, default_value in schema.items():
                value = src_values.get(key, default_value)
                if key == "reset_time":
                    normalized[node_type][key] = NodeDefaultsDialog._normalize_time(value, default_value)
                elif key == "post_launch_wait_seconds":
                    normalized[node_type][key] = NodeDefaultsDialog._normalize_float(value, 0.0, 600.0, 0.1, default_value)
                elif key == "next_rule_search_timeout_seconds":
                    normalized[node_type][key] = NodeDefaultsDialog._normalize_float(value, 0.5, 3600.0, 0.1, default_value)
                elif key == "default_condition_threshold":
                    normalized[node_type][key] = NodeDefaultsDialog._normalize_float(value, 0.0, 1.0, 0.01, default_value)
                elif isinstance(value, (dict, list)):
                    normalized[node_type][key] = json.dumps(value, ensure_ascii=False)
                else:
                    normalized[node_type][key] = str(value)
        return normalized

    @staticmethod
    def _normalize_time(value, fallback):
        s = str(value).strip()
        t = QtCore.QTime.fromString(s, "HH:mm:ss")
        if not t.isValid():
            t = QtCore.QTime.fromString(str(fallback), "HH:mm:ss")
        if not t.isValid():
            t = QtCore.QTime(5, 0, 0)
        return t.toString("HH:mm:ss")

    @staticmethod
    def _normalize_float(value, min_v, max_v, step, fallback):
        try:
            v = float(value)
        except (TypeError, ValueError):
            try:
                v = float(fallback)
            except (TypeError, ValueError):
                v = min_v
        v = max(min_v, min(max_v, v))
        v = round(v / step) * step
        return f"{v:.1f}"

    def _create_editor(self, key, value):
        if key == "reset_time":
            editor = QtWidgets.QTimeEdit()
            editor.setDisplayFormat("HH:mm:ss")
            t = QtCore.QTime.fromString(str(value), "HH:mm:ss")
            if not t.isValid():
                t = QtCore.QTime.fromString("05:00:00", "HH:mm:ss")
            editor.setTime(t if t.isValid() else QtCore.QTime(5, 0, 0))
            return editor

        if key == "post_launch_wait_seconds":
            editor = QtWidgets.QDoubleSpinBox()
            editor.setRange(0.0, 600.0)
            editor.setDecimals(1)
            editor.setSingleStep(0.5)
            try:
                editor.setValue(max(0.0, min(600.0, float(value))))
            except (TypeError, ValueError):
                editor.setValue(0.0)
            return editor

        if key == "next_rule_search_timeout_seconds":
            editor = QtWidgets.QDoubleSpinBox()
            editor.setRange(0.5, 3600.0)
            editor.setDecimals(1)
            editor.setSingleStep(0.5)
            try:
                editor.setValue(max(0.5, min(3600.0, float(value))))
            except (TypeError, ValueError):
                editor.setValue(5.0)
            return editor

        if key == "default_condition_threshold":
            editor = QtWidgets.QDoubleSpinBox()
            editor.setRange(0.0, 1.0)
            editor.setDecimals(2)
            editor.setSingleStep(0.01)
            try:
                editor.setValue(max(0.0, min(1.0, float(value))))
            except (TypeError, ValueError):
                editor.setValue(0.8)
            return editor

        return QtWidgets.QLineEdit(str(value))
