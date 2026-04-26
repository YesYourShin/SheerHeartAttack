import json
from PySide6 import QtWidgets
from ui.panels.base_panel import BasePropertyPanel
from ui.properties_panel import StartNodeOrderList


class EntryStartPanel(BasePropertyPanel):
    """진입 Start: Game 실행 순서만 편집"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QtWidgets.QLabel("🎮 Game 순차 실행 순서:"))
        self.game_order_list = StartNodeOrderList()
        self.game_order_list.order_changed.connect(self._on_change)
        layout.addWidget(self.game_order_list)

        self.refresh_btn = QtWidgets.QPushButton("🔄 연결된 Game 새로고침")
        self.refresh_btn.setToolTip("에디터에서 Start에 연결한 Game 목록을 다시 읽습니다.")
        self.refresh_btn.clicked.connect(self._refresh_games)
        layout.addWidget(self.refresh_btn)
        layout.addStretch()

    def _load_from_state(self, state):
        self._refresh_games(state)

    def get_state(self):
        return {'game_nodes_order': json.dumps(self.game_order_list.get_order_data())}

    def get_state_from_node(self, node):
        if not node or node.type_ != 'macro.nodes.StartNode':
            return {}
        connected = node.connected_output_nodes().get(node.outputs()['out'], [])
        current = {}
        for n in connected:
            if n.type_ == 'macro.nodes.GameNode':
                current[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}
        saved_ids = self._load_json(node.get_property('game_nodes_order') or '[]')
        new_info = []
        for sid in saved_ids:
            if sid in current:
                new_info.append(current[sid])
                del current[sid]
        for info in current.values():
            new_info.append(info)
        order = [x['id'] for x in new_info]
        return {'game_nodes_order': json.dumps(order)}

    def save_to_node(self, push_undo=False):
        if not self.node:
            return
        self._set_node_property(
            'game_nodes_order',
            json.dumps(self.game_order_list.get_order_data()),
            push_undo=push_undo
        )

    def _load_json(self, val):
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _refresh_games(self, state=None):
        if not self.node or self.node.type_ != 'macro.nodes.StartNode':
            return

        connected_out_nodes = self.node.connected_output_nodes().get(self.node.outputs()['out'], [])
        current = {}
        for n in connected_out_nodes:
            if n.type_ == 'macro.nodes.GameNode':
                current[n.id] = {'id': n.id, 'label': n.name(), 'type': n.type_}

        if state:
            saved_ids = self._load_json(state.get('game_nodes_order', '[]'))
        else:
            saved_ids = self._load_json(self.node.get_property('game_nodes_order') or '[]')

        new_info = []
        for sid in saved_ids:
            if sid in current:
                new_info.append(current[sid])
                del current[sid]
        for info in current.values():
            new_info.append(info)

        self.game_order_list.set_items(new_info, 'Game')

        if not self._skip_snapshot:
            self.changed.emit()
