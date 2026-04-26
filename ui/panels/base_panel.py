import json
from PySide6 import QtWidgets, QtCore

class BasePropertyPanel(QtWidgets.QWidget):
    """
    모든 속성 패널의 기본 클래스. 
    공통된 상태 관리(undo/redo 기반) 및 이벤트 전파 로직을 가짐.
    """
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self._skip_snapshot = False

    def load_node(self, node, state=None):
        """노드 데이터를 UI에 적재"""
        self.node = node
        self._skip_snapshot = True
        self._load_from_state(state)
        self._skip_snapshot = False

    def get_state(self):
        """현재 UI의 상태를 딕셔너리로 반환"""
        return {}

    def _load_from_state(self, state):
        """state 딕셔너리를 읽어 UI를 업데이트하는 내부 구현용"""
        pass

    def save_to_node(self, push_undo=False):
        """UI의 현재 상태를 실제 노드의 프로퍼티로 반영"""
        pass

    def _set_node_property(self, key, value, push_undo=False):
        if not self.node:
            return
        try:
            self.node.set_property(key, value, push_undo=push_undo)
        except TypeError:
            self.node.set_property(key, value)

    def get_state_from_node(self, node):
        """노드 프로퍼티만으로 get_state()와 동일 키/형식(미저장 비교用 원본)"""
        return {}

    def _on_change(self, *args):
        if not self._skip_snapshot:
            self.changed.emit()

    def _get_action_dialog_kwargs(self):
        """모든 패널에서 공통으로 사용하는 대화상자 인자 생성 (daily_variables 추출)"""
        available_vars = []
        if self.node and hasattr(self.node, 'graph') and self.node.graph:
            try:
                game_nodes = self.node.graph.get_nodes_by_type('macro.nodes.GameNode')
            except Exception:
                game_nodes = []
            for gnode in game_nodes:
                if not gnode.has_property('daily_variables'):
                    continue
                daily_vars_str = gnode.get_property('daily_variables')
                if not daily_vars_str:
                    continue
                try:
                    parsed = json.loads(daily_vars_str)
                    if isinstance(parsed, list):
                        for v in parsed:
                            if isinstance(v, str):
                                available_vars.append({"label": v, "key": v, "value": 0})
                            elif isinstance(v, dict):
                                available_vars.append(v)
                except Exception:
                    pass
        return {"available_vars": available_vars}
