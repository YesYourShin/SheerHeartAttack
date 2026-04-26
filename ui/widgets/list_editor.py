import copy
from PySide6 import QtWidgets, QtCore

class ListEditor(QtWidgets.QWidget):
    """
    범용 리스트 편집 위젯.
    아이템 목록을 보여주고, 추가/삭제/더블클릭 편집 및 드래그 앤 드롭 순서 변경을 지원합니다.
    """
    def __init__(self, items, describe_fn, edit_dialog_cls, on_change=None, capture_path_fn=None, dialog_kwargs_fn=None, parent=None):
        super().__init__(parent)
        self.setObjectName("listEditor")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setStyleSheet("#listEditor { background-color: #2b2b2b; border: 0; }")
        self.items = list(items)
        self.describe_fn = describe_fn
        self.edit_dialog_cls = edit_dialog_cls
        self.on_change = on_change
        self.capture_path_fn = capture_path_fn  # 캡처 경로를 동적으로 가져오는 함수
        self.dialog_kwargs_fn = dialog_kwargs_fn # 다이얼로그 생성 시 추가 인자 반환

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setMinimumHeight(100)
        self.list_widget.itemDoubleClicked.connect(self._edit)
        self.list_widget.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.list_widget.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        
        # 💡 다중 선택 모드 활성화 (Ctrl+클릭, Shift+클릭 지원)
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        
        from PySide6 import QtGui
        # Ctrl+C / Ctrl+V 단축키 바인딩
        self._copy_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+C"), self.list_widget)
        self._copy_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self._copy_shortcut.activated.connect(self._copy_selected)
        
        self._paste_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+V"), self.list_widget)
        self._paste_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self._paste_shortcut.activated.connect(self._paste)
        
        self._refresh_list()
        layout.addWidget(self.list_widget)

        btn_bar = QtWidgets.QWidget()
        btn_bar.setObjectName("listEditorButtonBar")
        btn_bar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        btn_bar.setStyleSheet("#listEditorButtonBar { background-color: #2b2b2b; border: 0; }")
        btn_row = QtWidgets.QGridLayout(btn_bar)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setHorizontalSpacing(6)
        add_btn = QtWidgets.QPushButton("＋ 추가")
        add_btn.clicked.connect(self._add)
        btn_row.addWidget(add_btn, 0, 0)
        self.del_btn = QtWidgets.QPushButton("🗑 삭제")
        self.del_btn.setObjectName("dangerBtn")
        self.del_btn.clicked.connect(self._delete)
        self.del_btn.setEnabled(False)
        btn_row.addWidget(self.del_btn, 0, 1)
        btn_row.setColumnStretch(0, 1)
        btn_row.setColumnStretch(1, 1)
        layout.addWidget(btn_bar)
        self.list_widget.itemSelectionChanged.connect(self._update_delete_button)

    def _refresh_list(self):
        self.list_widget.clear()
        for i, item in enumerate(self.items):
            self.list_widget.addItem(f"{i+1}. {self.describe_fn(item)}")
        self._update_delete_button()

    def _update_delete_button(self):
        if hasattr(self, "del_btn"):
            self.del_btn.setEnabled(bool(self.list_widget.selectedItems()))

    def _get_capture_path(self):
        return self.capture_path_fn() if self.capture_path_fn else ""

    def _add(self):
        kwargs = self.dialog_kwargs_fn() if self.dialog_kwargs_fn else {}
        dlg = self.edit_dialog_cls(capture_path=self._get_capture_path(), parent=self, **kwargs)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.items.append(dlg.get_data())
            self._refresh_list()
            if self.on_change: self.on_change()

    def _edit(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        kwargs = self.dialog_kwargs_fn() if self.dialog_kwargs_fn else {}
        dlg = self.edit_dialog_cls(data=copy.deepcopy(self.items[row]), capture_path=self._get_capture_path(), parent=self, **kwargs)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.items[row] = dlg.get_data()
            self._refresh_list()
            if self.on_change: self.on_change()

    def _delete(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
            
        rows = []
        for item in selected_items:
            try:
                rows.append(int(item.text().split('.')[0]) - 1)
            except (ValueError, IndexError):
                pass
                
        # 💡 역순으로 안전 제거 (인덱스 꼬임 방지)
        for r in sorted(list(set(rows)), reverse=True):
            if 0 <= r < len(self.items):
                self.items.pop(r)
                
        self._refresh_list()
        if self.on_change: self.on_change()

    def _copy_selected(self):
        """선택된 아이템 원본 데이터를 JSON 클립보드화"""
        import json
        selected_items = self.list_widget.selectedItems()
        copied_data = []
        for item in selected_items:
            try:
                idx = int(item.text().split('.')[0]) - 1
                if 0 <= idx < len(self.items):
                    copied_data.append(self.items[idx])
            except (ValueError, IndexError):
                pass
        if copied_data:
            QtWidgets.QApplication.clipboard().setText(json.dumps(copied_data, ensure_ascii=False))

    def _paste(self):
        """클립보드 JSON 데이터를 리스트에 덧붊"""
        import json
        text = QtWidgets.QApplication.clipboard().text()
        if not text: return
        try:
            data = json.loads(text)
            if not isinstance(data, list): data = [data]
            valid_items = [d for d in data if isinstance(d, dict)]
            if valid_items:
                self.items.extend(valid_items)
                self._refresh_list()
                if self.on_change: self.on_change()
        except (json.JSONDecodeError, TypeError):
            pass

    def _on_rows_moved(self, *args):
        new_order = []
        for i in range(self.list_widget.count()):
            text = self.list_widget.item(i).text()
            try:
                orig_idx = int(text.split('.')[0]) - 1
                new_order.append(self.items[orig_idx])
            except (ValueError, IndexError):
                pass
        if len(new_order) == len(self.items):
            self.items = new_order
        self._refresh_list()
        if self.on_change: self.on_change()

    def get_items(self):
        return self.items
