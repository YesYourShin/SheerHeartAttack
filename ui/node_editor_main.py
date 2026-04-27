import sys
import os
import math
import tempfile
import json

# 현재 파일(ui/node_editor_main.py)의 상위 폴더(new_macro/)를 시스템 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtWidgets, QtCore, QtGui
from NodeGraphQt import NodeGraph, BaseNode

from ui.custom_nodes import StartNode, GameNode, RuleNode, GuardNode, PlanNode
from ui.properties_panel import RulePropertiesPanel
from ui.workers import LogStream, MacroWorker
from ui.custom_graph import SafeNodeGraph
from ui.adb_toolbar import AdbToolbar
from ui.menu_manager import MenuManager
from ui.settings_dialog import NodeDefaultsDialog, NODE_DEFAULT_SCHEMA
from ui.app_info import (
    APP_AUTHOR,
    APP_CREATED_DATE,
    APP_DESCRIPTION,
    APP_GITHUB_URL,
    APP_ICON_FILE,
    APP_NAME_KO,
    APP_VERSION,
)
import ui.edit_dialogs as edit_dialogs
from framework.flow_runner import FlowRunner
from library.macro_manager import MacroManager
import library.adb_manager as adb_manager


def resource_path(relative_path):
    """PyInstaller配布環境と通常実行の両方でリソースパスを解決する。"""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


class NodeEditorWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME_KO)
        self.setWindowIcon(QtGui.QIcon(resource_path(APP_ICON_FILE)))
        self.resize(1200, 800)
        self.macro_thread = None
        self._overlay_settings_ready = False
        self._log_overlay_height = 180
        self._log_resize_active = False
        self._log_resize_start_global_y = 0
        self._log_resize_start_height = self._log_overlay_height

        # ─── 노드 그래프 ───
        self.graph = SafeNodeGraph()
        self.graph.disable_auto_zoom_on_resize()
        self.graph.disable_middle_drag_zoom()
        self._disable_graph_cursor_hint()
        self.graph.register_node(StartNode)
        self.graph.register_node(GameNode)
        self.graph.register_node(PlanNode)
        self.graph.register_node(RuleNode)
        self.graph.register_node(GuardNode)

        # ─── 중앙 위젯 ───
        self.graph_container = QtWidgets.QWidget()
        self.graph_container.installEventFilter(self)
        graph_layout = QtWidgets.QVBoxLayout(self.graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(0)
        graph_layout.addWidget(self.graph.widget)
        self.setCentralWidget(self.graph_container)

        # ─── 우측: 속성 패널 (커스텀) ───
        self.properties_panel = RulePropertiesPanel()
        self.properties_panel.capture_requested.connect(self._capture_for_node)
        self.properties_overlay = self._create_overlay_panel("Properties", self.properties_panel)
        self.properties_overlay.setMinimumWidth(300)
        self.properties_overlay.hide()

        # 노드 선택/더블클릭 시 패널에 노드 로드
        self.graph.node_selected.connect(self._on_node_selected)
        self.graph.node_double_clicked.connect(self._on_node_selected)
        
        # 포트 연결 시그널을 연결하여 제약 조건 검사
        self.graph.port_connected.connect(self._on_port_connected)
        if hasattr(self.graph, 'port_disconnected'):
            self.graph.port_disconnected.connect(self._on_port_disconnected)

        # ─── 하단: 로그 패널 ───
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dcdcdc; "
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; }"
        )
        self.clear_log_btn = QtWidgets.QPushButton("로그 클리어")
        self.clear_log_btn.setToolTip("현재 표시된 로그 내용을 모두 지웁니다.")
        self.clear_log_btn.clicked.connect(self._clear_log)

        self.log_overlay = self._create_overlay_panel("Log", self.log_text, self.clear_log_btn)
        self.log_overlay.show()
        self.log_resize_handle = QtWidgets.QFrame(self.log_overlay)
        self.log_resize_handle.setFixedHeight(4)
        self.log_resize_handle.setCursor(QtCore.Qt.SizeVerCursor)
        self.log_resize_handle.setStyleSheet(
            "QFrame { background-color: rgba(255, 255, 255, 0.08); border: none; }"
        )
        self.log_resize_handle.installEventFilter(self)

        # stdout 리다이렉트
        self.log_stream = LogStream()
        self.log_stream.message.connect(self._append_log)
        sys.stdout = self.log_stream
        
        # 하이라이트 상태 추적
        self._current_highlight_node = None
        self._current_highlight_orig_color = None

        # ─── ADB 도구 바 ───
        self.adb_toolbar = AdbToolbar(self)
        self.addToolBar(QtCore.Qt.TopToolBarArea, self.adb_toolbar)
        self.adb_toolbar.start_requested.connect(self._start_macro)
        self.adb_toolbar.stop_requested.connect(self._stop_macro)
        self.adb_toolbar.connection_changed.connect(self._on_adb_connection_changed)
        self.adb_toolbar.undo_requested.connect(self._undo_graph_action)
        self.adb_toolbar.redo_requested.connect(self._redo_graph_action)
        self.adb_toolbar.apply_requested.connect(self._apply_graph_changes)

        # ─── 상태바 ───
        self.status_text_label = QtWidgets.QLabel("")
        self.statusBar().addWidget(self.status_text_label, 1)
        self.zoom_status_label = QtWidgets.QLabel("배율: 100%")
        self.statusBar().addPermanentWidget(self.zoom_status_label)
        self._update_status_bar()

        # ─── 메뉴바 ───
        self.menu_manager = MenuManager(self, self.properties_overlay, self.log_overlay)
        self.menu_manager.new_session_requested.connect(self._new_session)
        self.menu_manager.save_session_requested.connect(self._save_session)
        self.menu_manager.load_session_requested.connect(self._load_session)
        self.menu_manager.start_macro_requested.connect(self._start_macro)
        self.menu_manager.stop_macro_requested.connect(self._stop_macro)
        self.menu_manager.fit_to_selection_requested.connect(self._fit_all_nodes)
        self.menu_manager.show_shortcuts_requested.connect(self._show_shortcuts)
        self.menu_manager.show_usage_basics_requested.connect(self._show_usage_basics)
        self.menu_manager.show_usage_nodes_requested.connect(self._show_usage_nodes)
        self.menu_manager.show_usage_advanced_requested.connect(self._show_usage_advanced)
        self.menu_manager.show_node_defaults_requested.connect(self._show_node_defaults_dialog)
        self.menu_manager.show_about_requested.connect(self._show_about)
        self._load_overlay_visibility_settings()

        self.node_default_settings_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "node_defaults.json"
        )
        self.node_default_settings = self._load_node_default_settings()

        # ─── 우클릭 컨텍스트 메뉴 ───
        self._setup_context_menu()
        
        # ─── Delete 키 가로채기 (삭제 확인창) ───
        self.delete_shortcut = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Delete), self.graph.viewer())
        self.delete_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self._on_delete_shortcut)

        self.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.undo_shortcut.activated.connect(self._undo_graph_action)
        self.redo_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.redo_shortcut.activated.connect(self._redo_graph_action)
        self.apply_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        self.apply_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.apply_shortcut.activated.connect(self._apply_graph_changes)
        self.start_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
        self.start_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.start_shortcut.activated.connect(self._start_macro)

        self._setup_history_tracking()

        # 우클릭 방화벽 필터 (마우스 드래그/리클릭 오프라인 가드)
        self._adb_locked = False
        self._editing_locked = False
        self._graph_context_scene_pos = None
        self._middle_descendant_drag_active = False
        self._middle_descendant_undo_macro_open = False
        self._middle_pan_active = False
        self._middle_pan_prev_pos = QtCore.QPoint()
        self.graph.viewer().installEventFilter(self)
        self.graph.viewer().viewport().installEventFilter(self)
        self._setup_inactive_visuals()

        # 초기 실행 시 ADB 미연결 락다운 가동
        QtCore.QTimer.singleShot(0, self._update_overlay_geometry)
        QtCore.QTimer.singleShot(100, lambda: self._on_adb_connection_changed(False))
        QtCore.QTimer.singleShot(0, self._update_zoom_status)

    def _disable_graph_cursor_hint(self):
        """NodeGraphQtがCtrl/Shift時に出すカーソル横の英語ヒントを非表示にする。"""
        viewer = self.graph.viewer()
        cursor_text = getattr(viewer, "_cursor_text", None)
        if cursor_text is not None and cursor_text.scene() is not None:
            cursor_text.scene().removeItem(cursor_text)

    def _create_overlay_panel(self, title, content_widget, header_widget=None):
        """グラフ領域を押し出さない浮動パネルを作成する。"""
        frame = QtWidgets.QFrame(self.graph_container)
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        frame.setAutoFillBackground(True)
        frame.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        title_label = QtWidgets.QLabel(title)
        title_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        header_layout.addWidget(title_label)
        if header_widget is not None:
            header_layout.addWidget(header_widget)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        layout.addWidget(content_widget)
        return frame

    def _update_overlay_geometry(self):
        """リサイズ時もノードマップ本体の geometry は変更せず、浮動パネルだけ再配置する。"""
        if not hasattr(self, 'graph_container'):
            return

        width = self.graph_container.width()
        height = self.graph_container.height()
        if width <= 0 or height <= 0:
            return

        margin = 12
        properties_width = min(360, max(300, width // 3))
        default_log_height = min(180, max(120, height // 4))
        self._log_overlay_height = max(120, min(height - (margin * 2), self._log_overlay_height or default_log_height))
        log_height = self._log_overlay_height

        if hasattr(self, 'properties_overlay'):
            properties_height = max(180, height - (margin * 2))
            self.properties_overlay.setGeometry(
                max(margin, width - properties_width - margin),
                margin,
                properties_width,
                properties_height
            )
            if self.properties_overlay.isVisible():
                self.properties_overlay.raise_()

        if hasattr(self, 'log_overlay'):
            log_width = width - (margin * 2)
            if hasattr(self, 'properties_overlay') and self.properties_overlay.isVisible():
                log_width -= properties_width + margin
            self.log_overlay.setGeometry(
                margin,
                max(margin, height - log_height - margin),
                max(200, log_width),
                log_height
            )
            if hasattr(self, 'log_resize_handle'):
                self.log_resize_handle.setGeometry(0, 0, self.log_overlay.width(), 4)
            if self.log_overlay.isVisible():
                self.log_overlay.raise_()

    @staticmethod
    def _status_zoom_percent_from_viewer(viewer):
        # 日本語: get_zoom()は view.transform().m11() のみで、描画の scene→viewport とずれる。viewportTransform() の2×2列ノルムで実効倍率にする。mapFromSceneの整数QPoint誤差は使わない。
        t = viewer.viewportTransform()
        sx = math.hypot(t.m11(), t.m21())
        sy = math.hypot(t.m12(), t.m22())
        return int(round(0.5 * (sx + sy) * 100))

    def _update_zoom_status(self):
        viewer = self.graph.viewer()
        zoom_percent = self._status_zoom_percent_from_viewer(viewer)
        self.zoom_status_label.setText(f"배율: {zoom_percent}%")

    def _middle_pan_grab(self, viewer):
        # 日本語: 中ドラッグ中はビューア既定の mouseMove へ届かないようグラブする（二重 pan / 変換のぶれ防止）。
        vp = viewer.viewport()
        if vp is not None:
            try:
                vp.grabMouse()
            except Exception:
                pass

    def _middle_pan_ungrab(self, viewer):
        vp = viewer.viewport()
        if vp is not None:
            try:
                vp.releaseMouse()
            except Exception:
                pass

    def _begin_middle_pan(self, viewer, pos):
        viewer.MMB_state = False
        self._middle_pan_active = True
        self._middle_pan_prev_pos = QtCore.QPoint(pos)
        self._middle_pan_grab(viewer)

    def _finish_middle_pan(self, viewer):
        viewer.MMB_state = False
        self._middle_pan_ungrab(viewer)
        self._middle_pan_active = False
        QtCore.QTimer.singleShot(0, self._update_zoom_status)

    def _move_middle_pan(self, viewer, pos):
        # 日本語: 中クリック移動は倍率を変えず、表示中心だけを移動する。fitInView / translate は倍率ドリフトや移動停止の原因になる。
        prev_scene = viewer.mapToScene(self._middle_pan_prev_pos)
        curr_scene = viewer.mapToScene(pos)
        delta = prev_scene - curr_scene
        center_pos = viewer.viewport().rect().center()
        current_center = viewer.mapToScene(center_pos)
        next_center = current_center + delta

        visible_range = viewer.mapToScene(viewer.viewport().rect()).boundingRect()
        if visible_range.isValid() and visible_range.width() > 0 and visible_range.height() > 0:
            next_range = QtCore.QRectF(visible_range)
            next_range.translate(delta)
            margin_x = visible_range.width() * 2.0
            margin_y = visible_range.height() * 2.0
            scene_range = visible_range.united(next_range).adjusted(
                -margin_x, -margin_y, margin_x, margin_y
            )
            viewer.setSceneRect(scene_range)
            viewer._scene_range = QtCore.QRectF(next_range)
        viewer.centerOn(next_center)
        self._middle_pan_prev_pos = QtCore.QPoint(pos)
        self._update_zoom_status()

    def _fit_all_nodes(self):
        self.graph.fit_to_selection()
        self._update_zoom_status()

    def set_properties_overlay_visible(self, visible):
        """View メニューやノード選択から Properties 表示を同期する。"""
        self.properties_overlay.setVisible(visible)
        self._update_overlay_geometry()
        if visible:
            self.properties_overlay.raise_()
        if hasattr(self, 'menu_manager'):
            self.menu_manager.set_overlay_action_checked('properties', visible)
        if self._overlay_settings_ready:
            self._save_overlay_visibility_settings()

    def set_log_overlay_visible(self, visible):
        """View メニューから Log 表示を同期する。"""
        self.log_overlay.setVisible(visible)
        self._update_overlay_geometry()
        if visible:
            self.log_overlay.raise_()
        if hasattr(self, 'menu_manager'):
            self.menu_manager.set_overlay_action_checked('log', visible)
        if self._overlay_settings_ready:
            self._save_overlay_visibility_settings()

    def _view_settings(self):
        return QtCore.QSettings("MacroNodeEditor", "MainWindow")

    def _load_overlay_visibility_settings(self):
        settings = self._view_settings()
        log_visible = settings.value("view/log_visible", True, type=bool)
        properties_visible = settings.value("view/properties_visible", False, type=bool)
        self.set_log_overlay_visible(log_visible)
        self.set_properties_overlay_visible(properties_visible)
        self._overlay_settings_ready = True

    def _save_overlay_visibility_settings(self):
        settings = self._view_settings()
        settings.setValue("view/log_visible", self.log_overlay.isVisible())
        settings.setValue("view/properties_visible", self.properties_overlay.isVisible())

    def _on_adb_connection_changed(self, is_connected):
        if hasattr(self, 'properties_panel'):
            self.properties_panel.set_adb_connected(is_connected)
        self._sync_start_controls()
            
        # 전면 락다운(Locked) 토글
        self._set_adb_lock(not is_connected)

    def _setup_inactive_visuals(self):
        self._inactive_opacity_effects = {}
        self._node_dim_base_colors = {}

    def _graph_undo_stack(self):
        try:
            stack = getattr(self.graph, "_undo_stack", None)
            if stack is not None:
                stack.canUndo()
                return stack
            getter = getattr(self.graph, "undo_stack", None)
            if callable(getter):
                stack = getter()
                if stack is not None:
                    stack.canUndo()
                return stack
        except RuntimeError:
            return None
        return None

    def _setup_history_tracking(self):
        stack = self._graph_undo_stack()
        if not stack:
            return
        try:
            stack.canUndoChanged.connect(lambda _=None: self._sync_history_ui())
            stack.canRedoChanged.connect(lambda _=None: self._sync_history_ui())
            stack.cleanChanged.connect(lambda _=None: self._sync_history_ui())
            stack.setClean()
        except RuntimeError:
            return
        self._sync_history_ui()

    def _sync_history_ui(self):
        stack = self._graph_undo_stack()
        if not stack:
            self._sync_start_controls()
            return
        try:
            can_undo = stack.canUndo()
            can_redo = stack.canRedo()
            is_dirty = not stack.isClean()
        except RuntimeError:
            self._sync_start_controls()
            return
        if hasattr(self, "adb_toolbar"):
            self.adb_toolbar.set_history_state(can_undo, can_redo)
            self.adb_toolbar.set_apply_enabled(is_dirty)
        self._sync_start_controls()

    def _is_graph_dirty(self):
        stack = self._graph_undo_stack()
        if not stack:
            return False
        return not stack.isClean()

    def _can_start_macro(self):
        is_connected = adb_manager.adbdevice is not None
        is_running = bool(self.macro_thread and self.macro_thread.isRunning())
        return is_connected and (not is_running) and (not self._is_graph_dirty())

    def _sync_start_controls(self):
        can_start = self._can_start_macro()
        if hasattr(self, "adb_toolbar") and hasattr(self.adb_toolbar, "run_btn"):
            self.adb_toolbar.run_btn.setEnabled(can_start)
        if hasattr(self, "menu_manager") and hasattr(self.menu_manager, "start_action"):
            self.menu_manager.start_action.setEnabled(can_start)

    def _notify_shortcut_blocked(self, message, timeout_ms=2500):
        self._append_log(f"ℹ {message}")

    def _undo_graph_action(self):
        stack = self._graph_undo_stack()
        if not stack:
            self._notify_shortcut_blocked("되돌리기 스택을 찾을 수 없습니다.")
            return
        if not stack.canUndo():
            self._notify_shortcut_blocked("되돌릴 항목이 없습니다.")
            return
        stack.undo()
        self._refresh_properties_from_current_node()
        self._sync_history_ui()

    def _redo_graph_action(self):
        stack = self._graph_undo_stack()
        if not stack:
            self._notify_shortcut_blocked("다시하기 스택을 찾을 수 없습니다.")
            return
        if not stack.canRedo():
            self._notify_shortcut_blocked("다시할 항목이 없습니다.")
            return
        stack.redo()
        self._refresh_properties_from_current_node()
        self._sync_history_ui()

    def _refresh_properties_from_current_node(self):
        node = getattr(self.properties_panel, "node", None)
        if not node:
            return
        try:
            current = self.graph.get_node_by_id(node.id)
        except Exception:
            current = None
        if current is None:
            self.properties_panel.clear_node()
            return
        self.properties_panel.load_node(current)

    def _apply_graph_changes(self):
        stack = self._graph_undo_stack()
        if not stack:
            self._notify_shortcut_blocked("적용 스택을 찾을 수 없습니다.")
            return
        if self.properties_panel and self.properties_panel.node:
            self.properties_panel.force_save(push_undo=True)
        if stack.isClean():
            self._notify_shortcut_blocked("적용할 변경사항이 없습니다.", 2000)
            self._sync_history_ui()
            return
        stack.setClean()
        self._notify_shortcut_blocked("변경사항을 적용했습니다.", 2000)
        self._sync_history_ui()


    # ╔══════════════════════════════════════════╗
    # ║           우클릭 컨텍스트 메뉴           ║
    # ╚══════════════════════════════════════════╝
    def _setup_context_menu(self):
        """NodeGraphQt의 graph 컨텍스트 메뉴를 정리하고 'Add Node' 서브메뉴만 추가"""
        ctx_menu = self.graph.get_context_menu('graph')
        if ctx_menu:
            # 기존 자동 생성된 메뉴 항목을 모두 제거
            ctx_menu.qmenu.clear()
            ctx_menu._items.clear()
            ctx_menu._menus.clear()
            ctx_menu._commands.clear()

            node_types = [
                ('▶ Start',   StartNode),
                ('🎮 Game',   GameNode),
                ('📝 Plan',    PlanNode),
                ('📋 Rule',    RuleNode),
                ('🛡 Guard',   GuardNode),
            ]

            node_menu = ctx_menu.add_menu('Add Node')
            for label, node_cls in node_types:
                node_menu.add_command(
                    label,
                    func=self._make_add_node_func(node_cls),
                    shortcut=None
                )

        # ─ 특정 노드 우클릭 시의 메뉴 설정 ─
        node_ctx_menu = self.graph.get_context_menu('nodes')
        if node_ctx_menu:
            node_ctx_menu.qmenu.clear()
            node_ctx_menu._items.clear()
            node_ctx_menu._menus.clear()
            node_ctx_menu._commands.clear()
            
            for label, node_cls in node_types:
                try:
                    node_ctx_menu.add_command(
                        '▶ 여기서부터 실행',
                        func=self._run_from_selected_node,
                        node_class=node_cls
                    )
                    node_ctx_menu.add_command(
                        '이 노드를 삭제',
                        func=self._delete_context_node,
                        node_class=node_cls
                    )
                    node_ctx_menu.add_command(
                        '이 노드 하위도 같이 삭제',
                        func=self._delete_context_node_with_children,
                        node_class=node_cls
                    )
                except Exception as e:
                    print(f"Failed to add context menu for {node_cls}: {e}")
            
            node_ctx_menu.qmenu.aboutToShow.connect(self._update_node_ctx_menu_state)

    def _run_from_selected_node(self, graph, node):
        if not node:
            return
        self._start_macro(run_from_node_id=node.id)

    def _delete_context_node(self, graph, node):
        """右クリック対象のノードだけを削除する。"""
        if not self._can_delete_nodes() or not node:
            return

        reply = QtWidgets.QMessageBox.question(
            self, "삭제 확인",
            f"'{node.name()}' 노드를 삭제하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        graph.delete_nodes([node])
        self._after_nodes_deleted()

    def _delete_context_node_with_children(self, graph, node):
        """右クリック対象から出力方向へ辿れる下位ノードもまとめて削除する。"""
        if not self._can_delete_nodes() or not node:
            return

        nodes = self._collect_output_descendants(node)
        reply = QtWidgets.QMessageBox.question(
            self, "삭제 확인",
            f"'{node.name()}' 노드와 하위 {len(nodes) - 1}개 노드를 같이 삭제하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        graph.delete_nodes(nodes)
        self._after_nodes_deleted()

    def _can_delete_nodes(self):
        """実行中はノード削除を禁止する。"""
        return not (self.macro_thread and self.macro_thread.isRunning())

    def _collect_output_descendants(self, root_node):
        """出力ポートの接続を辿って削除対象ノードを集める。"""
        nodes_by_id = {root_node.id: root_node}
        stack = [root_node]

        while stack:
            current = stack.pop()
            try:
                output_map = current.connected_output_nodes()
                output_ports = current.outputs().values()
            except Exception:
                continue

            for port in output_ports:
                for child in output_map.get(port, []):
                    if child.id in nodes_by_id:
                        continue
                    nodes_by_id[child.id] = child
                    stack.append(child)

        return list(nodes_by_id.values())

    def _after_nodes_deleted(self):
        """削除後にプロパティ表示とステータスを最新状態へ戻す。"""
        if hasattr(self, 'properties_panel'):
            self.properties_panel.clear_node()
        self._update_status_bar()

    def _node_at_scene_pos(self, scene_pos):
        """指定位置にあるノードを返す。"""
        for node in self.graph.all_nodes():
            if hasattr(node, 'view') and node.view.sceneBoundingRect().contains(scene_pos):
                return node
        return None

    def _update_node_ctx_menu_state(self):
        """우클릭 컨택스트 메뉴가 열리기 전 ADB 연결 상태에 따라 활성화 분기"""
        import library.adb_manager as adb_manager
        is_connected = adb_manager.adbdevice is not None
        can_delete = self._can_delete_nodes()
        
        node_ctx_menu = self.graph.get_context_menu('nodes')
        if node_ctx_menu:
            for act in node_ctx_menu.qmenu.actions():
                if '여기서부터 실행' in act.text():
                    act.setEnabled(is_connected)
                elif '삭제' in act.text():
                    act.setEnabled(can_delete)

    def _set_adb_lock(self, locked: bool):
        """ADB 연결 대기(오프라인) 상태일 때 노드 편집 및 모든 조작 일괄 동결 (락다운)"""
        stack = self._graph_undo_stack()
        was_clean = False
        if stack:
            try:
                was_clean = stack.isClean()
            except RuntimeError:
                stack = None

        self._adb_locked = locked
        
        # 1. 그래프 뷰어 드래그 및 선택 차단 (휠 스크롤 줌 및 미들 드래그 팬은 유지)
        self.graph.viewer().setInteractive(not locked)
        
        # 2. 우클릭 자체를 완전 비활성화 (오른쪽 클릭 무반응 효과)
        ctx_graph = self.graph.get_context_menu('graph')
        ctx_nodes = self.graph.get_context_menu('nodes')
        if ctx_graph:
            ctx_graph.qmenu.setDisabled(locked)
        if ctx_nodes:
            ctx_nodes.qmenu.setDisabled(locked)

        # 3. Properties オーバーレイを無効化（グレー表示）
        if hasattr(self, 'properties_overlay'):
            self.properties_overlay.setDisabled(locked)

        self._apply_inactive_visual_state()
        if stack and was_clean:
            try:
                stack.setClean()
            except RuntimeError:
                pass
        self._sync_history_ui()

    def _apply_inactive_visual_state(self):
        inactive = bool(self._adb_locked or self._editing_locked)

        for widget, effect in getattr(self, "_inactive_opacity_effects", {}).items():
            if widget is None or effect is None:
                continue
            effect.setOpacity(0.62 if inactive else 1.0)

        current_highlight_id = getattr(getattr(self, "_current_highlight_node", None), "id", None)
        if inactive:
            for node in self.graph.all_nodes():
                nid = getattr(node, "id", None)
                if not nid:
                    continue
                if nid == current_highlight_id:
                    self._set_node_color_runtime(node, 255, 200, 50)
                    continue
                base_rgb = self._node_dim_base_colors.get(nid)
                if base_rgb is None:
                    c = node.color()
                    base_rgb = (int(c[0]), int(c[1]), int(c[2]))
                    self._node_dim_base_colors[nid] = base_rgb
                dim_rgb = tuple(max(0, min(255, int(v * 0.55))) for v in base_rgb)
                self._set_node_color_runtime(node, *dim_rgb)
        else:
            for node in self.graph.all_nodes():
                nid = getattr(node, "id", None)
                if not nid:
                    continue
                base_rgb = self._node_dim_base_colors.get(nid)
                if base_rgb is not None:
                    self._set_node_color_runtime(node, *base_rgb)
            self._node_dim_base_colors.clear()

        self.graph.viewer().update()

    def _set_node_color_runtime(self, node, r, g, b, *rest):
        try:
            node.set_property('color', (r, g, b, 255), push_undo=False)
        except Exception:
            try:
                node.set_color(r, g, b)
            except Exception:
                pass

    def _send_as_left_mouse_event(self, obj, event, event_type, button, buttons):
        """中クリックのノードドラッグを通常の左ドラッグとしてビューアへ渡す。"""
        local_pos = event.position().toPoint()
        translated = QtGui.QMouseEvent(
            event_type,
            QtCore.QPointF(local_pos),
            button,
            buttons,
            QtCore.Qt.NoModifier
        )
        return QtWidgets.QApplication.sendEvent(obj, translated)

    def eventFilter(self, obj, event):
        """ADB 미연결 상태일 때 우클릭 드래그 및 조작 완전 격리"""
        if hasattr(self, 'graph') and obj is self.graph.viewer():
            if event.type() in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                if event.key() == QtCore.Qt.Key_Tab:
                    return True

        if hasattr(self, 'graph_container') and obj is self.graph_container:
            if event.type() == QtCore.QEvent.Resize:
                QtCore.QTimer.singleShot(0, self._update_overlay_geometry)

        if hasattr(self, 'graph') and obj is self.graph.viewer().viewport():
            if event.type() == QtCore.QEvent.Wheel:
                # 日本語: 中ドラッグ中にトラックパッド等で Wheel が混ざるとズームだけ変わり、表示と get_zoom 系が食い違う。パン中はホイール倍率を無効化。
                if self._middle_pan_active:
                    return True
                QtCore.QTimer.singleShot(0, self._update_zoom_status)
            is_locked = getattr(self, '_adb_locked', False)
            viewer = self.graph.viewer()

            if self._middle_pan_active:
                if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.MiddleButton:
                    self._finish_middle_pan(viewer)
                    return True
                if event.type() == QtCore.QEvent.MouseMove:
                    if not (event.buttons() & QtCore.Qt.MiddleButton):
                        self._finish_middle_pan(viewer)
                        return True
                    self._move_middle_pan(viewer, event.position().toPoint())
                    return True

            if is_locked:
                if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.MiddleButton:
                    self._begin_middle_pan(viewer, event.position().toPoint())
                    return True
                if event.type() in [QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove]:
                    if event.button() in [QtCore.Qt.LeftButton, QtCore.Qt.RightButton] or \
                       (event.buttons() & (QtCore.Qt.LeftButton | QtCore.Qt.RightButton)):
                        event.ignore()
                        return True
            else:
                if self._middle_descendant_drag_active:
                    if event.type() == QtCore.QEvent.MouseMove and event.buttons() & QtCore.Qt.MiddleButton:
                        self._send_as_left_mouse_event(
                            obj, event, QtCore.QEvent.MouseMove,
                            QtCore.Qt.NoButton, QtCore.Qt.LeftButton
                        )
                        return True
                    if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.MiddleButton:
                        self._send_as_left_mouse_event(
                            obj, event, QtCore.QEvent.MouseButtonRelease,
                            QtCore.Qt.LeftButton, QtCore.Qt.NoButton
                        )
                        stack = self._graph_undo_stack()
                        if stack and self._middle_descendant_undo_macro_open:
                            stack.endMacro()
                            self._middle_descendant_undo_macro_open = False
                        self._middle_descendant_drag_active = False
                        return True

                if (
                    event.type() == QtCore.QEvent.MouseButtonPress and
                    event.button() == QtCore.Qt.MiddleButton and
                    self._can_delete_nodes()
                ):
                    scene_pos = self.graph.viewer().mapToScene(event.position().toPoint())
                    node = self._node_at_scene_pos(scene_pos)
                    if node:
                        stack = self._graph_undo_stack()
                        if stack and not self._middle_descendant_undo_macro_open:
                            stack.beginMacro("Move descendant nodes")
                            self._middle_descendant_undo_macro_open = True
                        for n in self.graph.all_nodes():
                            n.set_selected(False)
                        for n in self._collect_output_descendants(node):
                            n.set_selected(True)
                        self._middle_descendant_drag_active = True
                        self._send_as_left_mouse_event(
                            obj, event, QtCore.QEvent.MouseButtonPress,
                            QtCore.Qt.LeftButton, QtCore.Qt.LeftButton
                        )
                        return True
                    self._begin_middle_pan(viewer, event.position().toPoint())
                    return True

                # 💡 정상 연결 상태: 우클릭 마우스 누름 시 해당 위치 노드 자동 선택
                if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.RightButton:
                    scene_pos = self.graph.viewer().mapToScene(event.position().toPoint())
                    # ノード追加時にメニュー上のカーソル位置ではなく、最初の右クリック位置を使う。
                    self._graph_context_scene_pos = QtCore.QPointF(scene_pos)
                    node = self._node_at_scene_pos(scene_pos)
                    if node:
                        # 모든 선택 해제 후 타겟만 선택
                        for n in self.graph.all_nodes():
                            n.set_selected(False)
                        node.set_selected(True)
        if hasattr(self, 'log_resize_handle') and obj is self.log_resize_handle:
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self._log_resize_active = True
                self._log_resize_start_global_y = event.globalPosition().toPoint().y()
                self._log_resize_start_height = self._log_overlay_height
                self.log_resize_handle.setCursor(QtCore.Qt.SizeVerCursor)
                return True
            if event.type() == QtCore.QEvent.MouseMove:
                if self._log_resize_active:
                    delta = event.globalPosition().toPoint().y() - self._log_resize_start_global_y
                    self._log_overlay_height = max(120, self._log_resize_start_height - delta)
                    self._update_overlay_geometry()
                    self.log_resize_handle.setCursor(QtCore.Qt.SizeVerCursor)
                    return True
            if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                if self._log_resize_active:
                    self._log_resize_active = False
                    self.log_resize_handle.setCursor(QtCore.Qt.SizeVerCursor)
                    return True
        return super().eventFilter(obj, event)

    def _make_add_node_func(self, node_cls):
        """노드 생성 함수를 클로저로 반환 (컨텍스트 메뉴용)"""
        def _add_node(graph):
            if node_cls.type_ == 'macro.nodes.StartNode':
                has_start = any(n.type_ == 'macro.nodes.StartNode' for n in self.graph.all_nodes())
                if has_start:
                    self._append_log("ℹ Start 노드는 하나만 생성할 수 있습니다.")
                    return

            viewer = graph.viewer()
            scene_pos = self._graph_context_scene_pos
            if scene_pos is None:
                # キーボード等で開いた場合だけ現在カーソル位置へフォールバックする。
                cursor_pos = viewer.mapFromGlobal(QtGui.QCursor.pos())
                scene_pos = viewer.mapToScene(cursor_pos)
            pos = [scene_pos.x(), scene_pos.y()]

            node = graph.create_node(
                node_cls.type_,
                pos=pos,
                push_undo=True
            )
            if node:
                self._apply_node_defaults(node)
                # クリック位置がノードの横・縦中央に来るよう、生成直後の未更新サイズにも対応する。
                scene_rect = node.view.sceneBoundingRect()
                local_rect = node.view.boundingRect()
                node_w = max(scene_rect.width(), local_rect.width(), 160)
                node_h = max(scene_rect.height(), local_rect.height(), 60)
                node.set_pos(scene_pos.x() - node_w / 2, scene_pos.y() - node_h / 2)
                # 겹침 방지: 다른 노드와 겹치면 아래로 밀기
                self._resolve_overlap(node)
                self._update_status_bar()
        return _add_node

    def _load_node_default_settings(self):
        normalized = NodeDefaultsDialog.normalize_defaults({})
        if not os.path.exists(self.node_default_settings_path):
            return normalized
        try:
            with open(self.node_default_settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return NodeDefaultsDialog.normalize_defaults(loaded)
        except Exception as e:
            print(f"⚠ 기본값 설정 파일을 읽지 못해 기본 설정으로 시작합니다: {e}")
            return normalized

    def _save_node_default_settings(self):
        try:
            os.makedirs(os.path.dirname(self.node_default_settings_path), exist_ok=True)
            with open(self.node_default_settings_path, "w", encoding="utf-8") as f:
                json.dump(self.node_default_settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "설정 저장 실패",
                f"기본값 설정 저장 중 오류가 발생했습니다.\n{e}"
            )

    def _apply_node_defaults(self, node):
        node_type = getattr(node, "type_", "")
        settings = self.node_default_settings.get(node_type, {})
        schema = NODE_DEFAULT_SCHEMA.get(node_type, {})
        for key, fallback in schema.items():
            value = settings.get(key, fallback)
            if key == "name":
                name_value = str(value).strip()
                if name_value:
                    node.set_property("name", name_value)
                continue
            node.set_property(key, str(value))

    def _show_node_defaults_dialog(self):
        dialog = NodeDefaultsDialog(self.node_default_settings, self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        self.node_default_settings = NodeDefaultsDialog.normalize_defaults(dialog.get_values())
        self._save_node_default_settings()
        self._append_log("ℹ 노드 기본값 설정이 저장되었습니다.")

    def _resolve_overlap(self, new_node):
        """새 노드가 기존 노드와 겹치면 아래로 밀어서 빈 자리를 찾는다."""
        all_nodes = self.graph.all_nodes()
        new_x, new_y = new_node.pos()
        node_w, node_h = 160, 60  # 노드 대략적 크기

        max_attempts = 50
        for _ in range(max_attempts):
            overlapping = False
            for other in all_nodes:
                if other.id == new_node.id:
                    continue
                ox, oy = other.pos()
                if (abs(new_x - ox) < node_w and abs(new_y - oy) < node_h):
                    overlapping = True
                    new_y = oy + node_h + 20  # 아래로 밀기
                    break
            if not overlapping:
                break
        new_node.set_pos(new_x, new_y)

    # ╔══════════════════════════════════════════╗
    # ║        편집 잠금 (실행 중 비활성화)      ║
    # ╚══════════════════════════════════════════╝
    def _set_editing_enabled(self, enabled: bool):
        """매크로 실행 중 모든 편집 UI를 비활성화 / 실행 종료 시 복구"""
        self._editing_locked = not enabled

        # ─ 노드 그래프 편집 (선택 및 이동 비활성화, 휠 패닝은 허용) ─
        self.graph.viewer().setInteractive(enabled)

        # ─ 속성 패널 ─
        if hasattr(self, 'properties_panel'):
            self.properties_panel.setEnabled(enabled)

        # ─ ADB 툴바 버튼 및 File 메뉴 ─
        if hasattr(self, 'adb_toolbar'):
            self.adb_toolbar.set_editing_enabled(enabled)
            
        if hasattr(self, 'menu_manager'):
            self.menu_manager.set_editing_enabled(enabled)

        # 로그 패널 리사이즈는 실행 중에도 항상 허용한다.
        if hasattr(self, 'log_overlay'):
            self.log_overlay.setEnabled(True)
        if hasattr(self, 'log_resize_handle'):
            self.log_resize_handle.setEnabled(True)
        self._apply_inactive_visual_state()

    # ╔══════════════════════════════════════════╗
    # ║             이벤트 핸들러                ║
    # ╚══════════════════════════════════════════╝
    def _on_delete_shortcut(self):
        """Delete 키 입력 시 매크로 실행 상태 확인 및 삭제 의사 확인"""
        if self.macro_thread and self.macro_thread.isRunning():
            return # 실행 중이면 삭제 불가
            
        selected = self.graph.selected_nodes()
        if not selected:
            return
            
        reply = QtWidgets.QMessageBox.question(
            self, "삭제 확인",
            f"선택한 {len(selected)}개의 노드를 정말 삭제하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.graph.delete_nodes(selected)
            self._after_nodes_deleted()

    def _on_node_selected(self, node):
        """노드 클릭/더블클릭 시 우측 패널에 해당 노드 속성 표시."""
        if not self.properties_overlay.isVisible():
            self.set_properties_overlay_visible(True)
        self.properties_panel.load_node(node)

    def _on_port_connected(self, port_in, port_out):
        """
        포트가 연결될 때 유효성을 검사합니다.
        Start → Game 만, Game → Plan/Guard, Plan 입력은 Game 만.
        """
        node_out = port_out.node()
        node_in = port_in.node()

        if node_out and node_out.type_ == 'macro.nodes.StartNode':
            if node_in and node_in.type_ != 'macro.nodes.GameNode':
                QtCore.QTimer.singleShot(0, lambda: port_out.disconnect_from(port_in))
                self._append_log("❌ Start 노드에는 Game 노드만 연결할 수 있습니다.")
                orig_color = node_in.color()
                self._set_node_color_runtime(node_in, 255, 50, 50)
                QtCore.QTimer.singleShot(500, lambda: self._set_node_color_runtime(node_in, *orig_color))
                return

        if node_out and node_out.type_ == 'macro.nodes.GameNode':
            if node_in and node_in.type_ not in ['macro.nodes.PlanNode', 'macro.nodes.GuardNode']:
                QtCore.QTimer.singleShot(0, lambda: port_out.disconnect_from(port_in))
                self._append_log("❌ Game 노드에는 Plan 또는 Guard만 연결할 수 있습니다.")
                orig_color = node_in.color()
                self._set_node_color_runtime(node_in, 255, 50, 50)
                QtCore.QTimer.singleShot(500, lambda: self._set_node_color_runtime(node_in, *orig_color))
                return

        if node_in and node_in.type_ == 'macro.nodes.PlanNode':
            if node_out and node_out.type_ != 'macro.nodes.GameNode':
                QtCore.QTimer.singleShot(0, lambda: port_out.disconnect_from(port_in))
                self._append_log("❌ Plan 입력은 Game 노드에서만 연결할 수 있습니다.")
                orig_color = node_out.color()
                self._set_node_color_runtime(node_out, 255, 50, 50)
                QtCore.QTimer.singleShot(500, lambda: self._set_node_color_runtime(node_out, *orig_color))
                return

        # Planの出力はRuleまたはGuardのみ
        if node_out and node_out.type_ == 'macro.nodes.PlanNode':
            if node_in and node_in.type_ not in ['macro.nodes.RuleNode', 'macro.nodes.GuardNode']:
                QtCore.QTimer.singleShot(0, lambda: port_out.disconnect_from(port_in))
                self._append_log("❌ Plan 노드에는 Rule 노드 또는 Guard 노드만 연결할 수 있습니다.")
                orig_color = node_in.color()
                self._set_node_color_runtime(node_in, 255, 50, 50)
                QtCore.QTimer.singleShot(500, lambda: self._set_node_color_runtime(node_in, *orig_color))
                return

        # 日本語: Rule から Guard への直接接続は禁止（Guard は Game/Plan 配下のみ有効）。
        if node_out and node_out.type_ == 'macro.nodes.RuleNode':
            if node_in and node_in.type_ == 'macro.nodes.GuardNode':
                QtCore.QTimer.singleShot(0, lambda: port_out.disconnect_from(port_in))
                self._append_log("❌ Rule 노드에서 Guard 노드로는 연결할 수 없습니다.")
                orig_color = node_in.color()
                self._set_node_color_runtime(node_in, 255, 50, 50)
                QtCore.QTimer.singleShot(500, lambda: self._set_node_color_runtime(node_in, *orig_color))
                return

        self._refresh_current_panel_connections(node_out, node_in)

    def _on_port_disconnected(self, port_in, port_out):
        """接続解除後、開いている Plan の Guard 順序リストを更新する。"""
        self._refresh_current_panel_connections(port_out.node(), port_in.node())

    def _refresh_current_panel_connections(self, node_out=None, node_in=None):
        if not hasattr(self, 'properties_panel'):
            return
        current = self.properties_panel.node
        if not current:
            return
        if current not in (node_out, node_in):
            return
        current_type = getattr(current, 'type_', None)
        if current_type == 'macro.nodes.PlanNode':
            QtCore.QTimer.singleShot(0, self.properties_panel.refresh_plan_guard_connections)
        elif current_type == 'macro.nodes.GameNode':
            QtCore.QTimer.singleShot(0, self.properties_panel.refresh_game_connections)

    def _capture_for_node(self):
        """현재 선택된 노드용 ADB 캡처"""
        macro_mgr = self.adb_toolbar.get_macro_manager()
        if not macro_mgr:
            print("❌ ADB가 연결되어 있지 않습니다. 먼저 연결해주세요.")
            return
        node = self.properties_panel.node
        if not node:
            return

        img = macro_mgr.screenshot()
        if not img:
            print("❌ 스크린샷 캡처에 실패했습니다.")
            return

        import io
        import base64
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{img_str}"
        
        print(f"📸 노드용 캡처 완료 (Base64 인코딩됨)")

        self.properties_panel.set_capture_image(data_uri)

    def _append_log(self, text):
        """로그 패널에 메시지 추가"""
        self.log_text.append(text)
        # 자동 스크롤
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_log(self):
        """表示中のログを空にする。"""
        self.log_text.clear()

    def _update_status_bar(self):
        """상태바에 현재 그래프 정보 표시"""
        nodes = self.graph.all_nodes()
        node_count = len(nodes)
        self.status_text_label.setText(
            f"노드: {node_count}개  |  우클릭: Add Node  |  F5: 실행  |  F6: 정지"
        )
        
    def _highlight_node(self, node_id):
        """실행 중인 노드를 시각적으로 돋보이게 처리"""
        node = self.graph.get_node_by_id(node_id)
        if not node:
            return
            
        # 이전 노드 복구
        if self._current_highlight_node and self._current_highlight_orig_color:
            try:
                self._set_node_color_runtime(self._current_highlight_node, *self._current_highlight_orig_color)
            except Exception:
                pass
                
        # 새 노드 하이라이트
        self._current_highlight_node = node
        self._current_highlight_orig_color = node.color()
        # 노드를 눈에 띄게 (예: 핑크/보라 계열 또는 밝은 테두리 강조, 여기서는 강렬한 노란색으로 처리)
        self._set_node_color_runtime(node, 255, 200, 50)
        self._keep_runtime_visual_changes_clean()

    def _keep_runtime_visual_changes_clean(self, force=False):
        if (not force) and (not (self.macro_thread and self.macro_thread.isRunning())):
            return
        stack = self._graph_undo_stack()
        if not stack:
            return
        try:
            stack.setClean()
        except RuntimeError:
            return
        self._sync_history_ui()

    # ╔══════════════════════════════════════════╗
    # ║           File 메뉴 핸들러              ║
    # ╚══════════════════════════════════════════╝
    def _new_session(self):
        reply = QtWidgets.QMessageBox.question(
            self, "New Macro",
            "현재 매크로를 모두 지우고 새로 시작하시겠습니까?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.graph.clear_session()
            stack = self._graph_undo_stack()
            if stack:
                stack.clear()
                stack.setClean()
            if hasattr(self, 'menu_manager'):
                self.menu_manager.set_current_session_path(None)
            
            if hasattr(self, 'properties_panel'):
                self.properties_panel.load_node(None)
            if hasattr(self, 'log_text'):
                self.log_text.clear()

            self._update_status_bar()
            self._sync_history_ui()

    def _save_session(self, file_path):
        if file_path:
            self.graph.save_session(file_path)
            self._strip_color_from_session_file(file_path)
            if hasattr(self, 'menu_manager'):
                self.menu_manager.set_current_session_path(file_path)
            stack = self._graph_undo_stack()
            if stack:
                stack.setClean()
                self._sync_history_ui()
            self._update_status_bar()
            print(f"매크로 저장 완료: {file_path}")

    def _load_session(self, file_path):
        if file_path:
            try:
                # 기존 파일에 남아있는 미사용 속성(label)을 임시 제거 후 로드
                import json as _json
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = _json.load(f)
                
                # nodes 딕셔너리를 순회하면서 조건부 처리
                nodes_data = data.get('graph', {}).get('nodes', {})
                for node_id, node_data in nodes_data.items():
                    custom = node_data.get('custom', {})
                    if 'label' in custom:
                        del custom['label']
                
                # 임시 파일로 저장 후 로드 (기본 로더가 cp949로 읽을 때 깨지지 않도록 ensure_ascii=True 사용)
                clean_path = file_path + '.tmp'
                with open(clean_path, 'w', encoding='utf-8') as f:
                    _json.dump(data, f, ensure_ascii=True)
                
                self.graph.load_session(clean_path)
                stack = self._graph_undo_stack()
                if stack:
                    stack.setClean()
                
                import os
                if os.path.exists(clean_path):
                    os.remove(clean_path)
                    
                self._update_status_bar()
                
                if hasattr(self, 'properties_panel'):
                    self.properties_panel.load_node(None)
                if hasattr(self, 'log_text'):
                    self.log_text.clear()

                print(f"매크로 로드 완료: {file_path}")
                if hasattr(self, 'menu_manager'):
                    self.menu_manager.set_current_session_path(file_path)
                # 로드 과정에서 타입 기본색이 재적용되므로, 현재 잠금 상태 시각효과를 다시 덮어쓴다.
                self._apply_inactive_visual_state()
                self._sync_history_ui()
                self._update_zoom_status()
            except Exception as e:
                import traceback
                error_msg = traceback.format_exc()
                print(f"Load Error: {error_msg}")
                QtWidgets.QMessageBox.warning(
                    self, "Load Error",
                    f"파일을 불러오는 중 오류가 발생했습니다:\n{e}"
                )

    def _strip_color_from_session_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        nodes_data = data.get("graph", {}).get("nodes", {})
        changed = False
        for _node_id, node_data in nodes_data.items():
            if "color" in node_data:
                del node_data["color"]
                changed = True

        if not changed:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ╔══════════════════════════════════════════╗
    # ║           Run 메뉴 핸들러               ║
    # ╚══════════════════════════════════════════╝
    def _start_macro(self, run_from_node_id=None):
        if isinstance(run_from_node_id, bool):
            run_from_node_id = None
        if self.macro_thread and self.macro_thread.isRunning():
            return
        if adb_manager.adbdevice is None:
            self._notify_shortcut_blocked("ADB 연결 후 실행할 수 있습니다.", 2500)
            return
        if self._is_graph_dirty():
            self._notify_shortcut_blocked("변경사항을 먼저 적용(Ctrl+S)한 뒤 실행하세요.", 3000)
            return

        temp_dir = tempfile.gettempdir()
        temp_json = os.path.join(temp_dir, "current_macro_run.json")
        self.graph.save_session(temp_json)
        self._strip_color_from_session_file(temp_json)

        self.macro_thread = MacroWorker(temp_json, log_stream=self.log_stream, run_from_node_id=run_from_node_id)
        self.macro_thread.finished_signal.connect(self._on_macro_finished)
        self.macro_thread.node_running_signal.connect(self._highlight_node)

        if hasattr(self, 'adb_toolbar'):
            self.adb_toolbar.set_execution_state(True)
        if hasattr(self, 'menu_manager'):
            self.menu_manager.set_execution_state(True)
        self._sync_start_controls()
            
        self._set_editing_enabled(False)
        self._append_log("▶ 매크로 실행 중...")
        print("═══ 매크로 실행 시작 ═══")
        self.macro_thread.start()

    def _stop_macro(self):
        if self.macro_thread and self.macro_thread.isRunning():
            self.macro_thread.stop()
            self.macro_thread.wait()
            # 큐에 남아 있는 실행 로그를 먼저 비운 뒤, 중지 완료를 마지막에 표시한다.
            QtWidgets.QApplication.processEvents()
            self._on_macro_finished()
            self._append_log("═══ 매크로 중지 완료 ═══")

    def _on_macro_finished(self):
        if hasattr(self, 'adb_toolbar'):
            self.adb_toolbar.set_execution_state(False)
        if hasattr(self, 'menu_manager'):
            self.menu_manager.set_execution_state(False)
        self._sync_start_controls()
            
        self._set_editing_enabled(True)
        self._update_status_bar()
        
        self._current_highlight_node = None
        self._current_highlight_orig_color = None
        self._keep_runtime_visual_changes_clean(force=True)
        self.macro_thread = None

    # ╔══════════════════════════════════════════╗
    # ║           Help 메뉴 핸들러              ║
    # ╚══════════════════════════════════════════╝
    def _show_shortcuts(self):
        shortcuts = (
            "<h3>단축키 안내</h3>"
            "<table cellpadding='4'>"
            "<tr><td><b>Ctrl+N</b></td><td>새 그래프</td></tr>"
            "<tr><td><b>Ctrl+S</b></td><td>변경사항 적용</td></tr>"
            "<tr><td><b>Ctrl+Alt+S</b></td><td>매크로 저장</td></tr>"
            "<tr><td><b>Ctrl+Shift+S</b></td><td>다른 이름으로 매크로 저장</td></tr>"
            "<tr><td><b>Ctrl+O</b></td><td>매크로 불러오기</td></tr>"
            "<tr><td><b>Ctrl+Z / Ctrl+Y</b></td><td>뒤로가기 / 앞으로가기</td></tr>"
            "<tr><td><b>F</b></td><td>Fit to All Nodes</td></tr>"
            "<tr><td><b>F5</b></td><td>매크로 실행</td></tr>"
            "<tr><td><b>F6</b></td><td>매크로 정지</td></tr>"
            "<tr><td><b>Delete</b></td><td>선택한 노드 삭제</td></tr>"
            "<tr><td><b>Ctrl+C / Ctrl+V</b></td><td>리스트 편집기 항목 복사/붙여넣기</td></tr>"
            "</table>"
            "<p><b>참고:</b> Ctrl+C/Ctrl+V는 Rule/Plan 등의 리스트 편집 영역에서 동작합니다.</p>"
        )
        QtWidgets.QMessageBox.information(self, "Shortcuts", shortcuts)

    def _show_usage_basics(self):
        usage = (
            "<h3>Usage - 시작하기</h3>"
            "<ol>"
            "<li><b>ADB 연결</b>: 상단 툴바에서 기기 연결 상태를 먼저 확인합니다.</li>"
            "<li><b>새 매크로 만들기</b>: File &gt; New Macro 또는 Ctrl+N으로 시작합니다.</li>"
            "<li><b>노드 추가</b>: 그래프 빈 공간 우클릭 후 Add Node에서 필요한 노드를 추가합니다.</li>"
            "<li><b>변경 적용</b>: Ctrl+S로 현재 변경을 적용할 수 있습니다.</li>"
            "<li><b>매크로 저장</b>: Ctrl+Alt+S로 저장하고 Ctrl+Shift+S로 다른 이름 저장할 수 있습니다.</li>"
            "<li><b>매크로 불러오기</b>: Ctrl+O로 저장한 매크로를 불러옵니다.</li>"
            "<li><b>실행/정지</b>: F5로 실행, F6으로 정지합니다.</li>"
            "</ol>"
            "<p><b>저장 위치:</b> 기본 저장 경로는 <code>macros/</code> 폴더입니다.</p>"
        )
        QtWidgets.QMessageBox.information(self, "Usage - 시작하기", usage)

    def _show_usage_nodes(self):
        usage = (
            "<h3>Usage - 노드와 편집</h3>"
            "<ul>"
            "<li><b>Start</b>: 매크로 시작점입니다. 전체 흐름의 기준이 됩니다.</li>"
            "<li><b>Game</b>: 게임/작업 단위를 나누는 상위 그룹 노드입니다.</li>"
            "<li><b>Plan</b>: 실제 작업 흐름을 묶는 노드입니다.</li>"
            "<li><b>Rule</b>: 조건 검사 후 동작을 수행하는 핵심 노드입니다.</li>"
            "<li><b>Guard</b>: 팝업/예외 상황 등 돌발 흐름 처리용 노드입니다.</li>"
            "<li><b>노드 우클릭 메뉴</b>: 여기서부터 실행, 노드 삭제, 하위 포함 삭제를 사용할 수 있습니다.</li>"
            "<li><b>연결 검사</b>: 잘못된 연결은 자동 취소되며 상태바에 이유가 표시됩니다.</li>"
            "</ul>"
        )
        QtWidgets.QMessageBox.information(self, "Usage - 노드와 편집", usage)

    def _show_usage_advanced(self):
        usage = (
            "<h3>Usage - 변수와 실행</h3>"
            "<ul>"
            "<li><b>Daily Variables</b>: Start 노드에서 일일 변수를 선언해 실행 중 값 변화를 추적할 수 있습니다.</li>"
            "<li><b>실행 제한 조건</b>: Plan/Guard/Rule에서 조건을 걸어 특정 상황에서 실행을 중단하거나 우회할 수 있습니다.</li>"
            "<li><b>로그 확인</b>: View &gt; Log 패널에서 실행 과정과 판단 흐름을 확인할 수 있습니다.</li>"
            "<li><b>노드 기본값</b>: Setting &gt; Node Defaults에서 새로 추가되는 노드의 기본 입력값을 지정할 수 있습니다.</li>"
            "<li><b>기록 파일</b>: 일일 기록은 <code>daily_records/</code>에 저장됩니다.</li>"
            "</ul>"
        )
        QtWidgets.QMessageBox.information(self, "Usage - 변수와 실행", usage)

    def _show_about(self):
        about = (
            f"<h3>{APP_NAME_KO}</h3>"
            f"<p>{APP_DESCRIPTION}</p>"
            "<table cellpadding='4'>"
            f"<tr><td><b>버전:</b></td><td>{APP_VERSION}</td></tr>"
            f"<tr><td><b>제작일:</b></td><td>{APP_CREATED_DATE}</td></tr>"
            f"<tr><td><b>제작자:</b></td><td>{APP_AUTHOR}</td></tr>"
            f"<tr><td><b>프로젝트 깃허브:</b></td><td><a href='{APP_GITHUB_URL}'>{APP_GITHUB_URL}</a></td></tr>"
            "</table>"
        )
        QtWidgets.QMessageBox.about(self, f"About {APP_NAME_KO}", about)

    # ╔══════════════════════════════════════════╗
    # ║             윈도우 종료 처리             ║
    # ╚══════════════════════════════════════════╝
    def closeEvent(self, event):
        stack = self._graph_undo_stack()
        if stack and self._middle_descendant_undo_macro_open:
            stack.endMacro()
            self._middle_descendant_undo_macro_open = False
        # 매크로 실행 중이면 정지 후 종료
        if self.macro_thread and self.macro_thread.isRunning():
            self.macro_thread.stop()
            self.macro_thread.wait()
        # stdout 복구
        sys.stdout = sys.__stdout__
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(resource_path(APP_ICON_FILE)))
    window = NodeEditorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
