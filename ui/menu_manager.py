from PySide6 import QtWidgets, QtCore
import os

class MenuManager(QtCore.QObject):
    new_session_requested = QtCore.Signal()
    save_session_requested = QtCore.Signal(str)
    load_session_requested = QtCore.Signal(str)
    start_macro_requested = QtCore.Signal()
    stop_macro_requested = QtCore.Signal()
    fit_to_selection_requested = QtCore.Signal()
    show_shortcuts_requested = QtCore.Signal()
    show_usage_basics_requested = QtCore.Signal()
    show_usage_nodes_requested = QtCore.Signal()
    show_usage_advanced_requested = QtCore.Signal()
    show_node_defaults_requested = QtCore.Signal()
    show_about_requested = QtCore.Signal()

    def __init__(self, main_window, properties_overlay, log_overlay):
        super().__init__(main_window)
        self.main_window = main_window
        self.properties_overlay = properties_overlay
        self.log_overlay = log_overlay
        self.current_session_path = None
        
        # Macros 폴더 경로 기본 설정
        self.macros_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'macros')
        os.makedirs(self.macros_dir, exist_ok=True)
        
        self._setup_menus()
        self.set_current_session_path(None)

    def _setup_menus(self):
        menubar = self.main_window.menuBar()

        # ── File 메뉴 ──
        file_menu = menubar.addMenu("File")

        self.new_action = file_menu.addAction("New Macro")
        self.new_action.setShortcut("Ctrl+N")
        self.new_action.triggered.connect(self.new_session_requested.emit)

        self.save_action = file_menu.addAction("Save Macro")
        self.save_action.setShortcut("Ctrl+Alt+S")
        self.save_action.triggered.connect(self._handle_save)

        self.save_as_action = file_menu.addAction("Save As Macro")
        self.save_as_action.setShortcut("Ctrl+Shift+S")
        self.save_as_action.triggered.connect(self._handle_save_as)

        self.load_action = file_menu.addAction("Load Macro")
        self.load_action.setShortcut("Ctrl+O")
        self.load_action.triggered.connect(self._handle_load)

        # ── View 메뉴 ──
        view_menu = menubar.addMenu("View")

        # オーバーレイ表示を切り替えるチェックアクション
        self.properties_view_action = view_menu.addAction("Properties")
        self.properties_view_action.setCheckable(True)
        self.properties_view_action.setChecked(self.properties_overlay.isVisible())
        self.properties_view_action.triggered.connect(self.main_window.set_properties_overlay_visible)

        self.log_view_action = view_menu.addAction("Log")
        self.log_view_action.setCheckable(True)
        self.log_view_action.setChecked(self.log_overlay.isVisible())
        self.log_view_action.triggered.connect(self.main_window.set_log_overlay_visible)

        view_menu.addSeparator()
        fit_action = view_menu.addAction("Fit to All Nodes")
        fit_action.setShortcut("F")
        fit_action.triggered.connect(self.fit_to_selection_requested.emit)

        # ── Run 메뉴 ──
        run_menu = menubar.addMenu("Run")

        self.start_action = run_menu.addAction("Start Macro")
        self.start_action.triggered.connect(self.start_macro_requested.emit)
        self.start_action.setEnabled(False)

        self.stop_action = run_menu.addAction("Stop Macro")
        self.stop_action.setShortcut("F6")
        self.stop_action.triggered.connect(self.stop_macro_requested.emit)
        self.stop_action.setEnabled(False)

        # ── Setting 메뉴 ──
        setting_menu = menubar.addMenu("Setting")
        defaults_action = setting_menu.addAction("Node Defaults")
        defaults_action.triggered.connect(self.show_node_defaults_requested.emit)

        # ── Help 메뉴 ──
        help_menu = menubar.addMenu("Help")
        shortcuts_action = help_menu.addAction("Shortcuts")
        shortcuts_action.triggered.connect(self.show_shortcuts_requested.emit)
        help_menu.addSeparator()
        usage_basics_action = help_menu.addAction("Usage - 시작하기")
        usage_basics_action.triggered.connect(self.show_usage_basics_requested.emit)
        usage_nodes_action = help_menu.addAction("Usage - 노드와 편집")
        usage_nodes_action.triggered.connect(self.show_usage_nodes_requested.emit)
        usage_advanced_action = help_menu.addAction("Usage - 변수와 실행")
        usage_advanced_action.triggered.connect(self.show_usage_advanced_requested.emit)
        help_menu.addSeparator()
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self.show_about_requested.emit)

    def _handle_save(self):
        if self.current_session_path:
            self.save_session_requested.emit(self.current_session_path)
            return
        self._handle_save_as()

    def _handle_save_as(self):
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.main_window, "Save Macro As", self.macros_dir, "JSON Files (*.json)"
        )
        if file_path:
            self.save_session_requested.emit(file_path)

    def _handle_load(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.main_window, "Load Macro", self.macros_dir, "JSON Files (*.json)"
        )
        if file_path:
            self.load_session_requested.emit(file_path)
            
    def set_editing_enabled(self, enabled: bool):
        self.new_action.setEnabled(enabled)
        can_save = enabled and bool(self.current_session_path)
        self.save_action.setEnabled(can_save)
        self.save_as_action.setEnabled(can_save)
        self.load_action.setEnabled(enabled)

    def set_current_session_path(self, path):
        self.current_session_path = path or None
        has_loaded_session = bool(self.current_session_path)
        self.save_action.setEnabled(has_loaded_session)
        self.save_as_action.setEnabled(has_loaded_session)

    def set_overlay_action_checked(self, overlay_name, checked):
        """外部から表示状態が変わったとき View メニューのチェック状態を合わせる。"""
        action_map = {
            'properties': getattr(self, 'properties_view_action', None),
            'log': getattr(self, 'log_view_action', None),
        }
        action = action_map.get(overlay_name)
        if not action:
            return
        action.blockSignals(True)
        try:
            action.setChecked(checked)
        finally:
            action.blockSignals(False)
        
    def set_execution_state(self, is_running: bool):
        self.start_action.setEnabled(not is_running)
        self.stop_action.setEnabled(is_running)
