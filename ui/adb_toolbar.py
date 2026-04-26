from PySide6 import QtWidgets, QtCore
import library.adb_manager as adb_manager
from library.macro_manager import MacroManager

class AdbToolbar(QtWidgets.QToolBar):
    start_requested = QtCore.Signal()
    stop_requested = QtCore.Signal()
    connection_changed = QtCore.Signal(bool)
    undo_requested = QtCore.Signal()
    redo_requested = QtCore.Signal()
    apply_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__("ADB", parent)
        self.setMovable(False)
        self.setStyleSheet(
            "QToolBar { background: #2b2b2b; border-bottom: 1px solid #555; padding: 4px; spacing: 6px; }"
            "QLabel { color: #dcdcdc; font-size: 12px; }"
            "QLineEdit { background: #3c3f41; color: #dcdcdc; border: 1px solid #555; "
            "border-radius: 3px; padding: 3px 6px; min-width: 70px; font-size: 12px; }"
            "QPushButton { font-size: 12px; padding: 4px 12px; }"
            "QPushButton:disabled { background-color: #3a3a3a; color: #666; }"
        )

        self.macro_mgr = None

        self._setup_ui()

    def _setup_ui(self):
        self.addWidget(QtWidgets.QLabel("  ADB 포트:"))
        self.port_input = QtWidgets.QLineEdit()
        self.port_input.setPlaceholderText("자동감지")
        self.port_input.setFixedWidth(90)
        auto_port = adb_manager.get_port()
        if auto_port:
            self.port_input.setText(str(auto_port))
        self.addWidget(self.port_input)

        self.connect_btn = QtWidgets.QPushButton("🔌 연결")
        self.connect_btn.setStyleSheet("QPushButton { background: #2d6a4f; color: white; border-radius: 3px; }"
                                        "QPushButton:hover { background: #40916c; }"
                                        "QPushButton:disabled { background: #3a3a3a; color: #666; }")
        self.connect_btn.clicked.connect(self._connect_adb)
        self.addWidget(self.connect_btn)

        self.disconnect_btn = QtWidgets.QPushButton("⛔ 해제")
        self.disconnect_btn.setStyleSheet("QPushButton { background: #8b3a3a; color: white; border-radius: 3px; }"
                                           "QPushButton:hover { background: #a04545; }"
                                           "QPushButton:disabled { background: #3a3a3a; color: #666; }")
        self.disconnect_btn.clicked.connect(self._disconnect_adb)
        self.disconnect_btn.setEnabled(False)
        self.addWidget(self.disconnect_btn)

        self.addSeparator()

        self.status_label = QtWidgets.QLabel("  ⚪ 미연결")
        self.status_label.setStyleSheet("color: #999; font-weight: bold;")
        self.addWidget(self.status_label)

        self.addSeparator()



        self.run_btn = QtWidgets.QPushButton("▶ 실행")
        self.run_btn.setStyleSheet("QPushButton { background: #2d6a4f; color: white; border-radius: 3px; font-weight: bold; }"
                                    "QPushButton:hover { background: #40916c; }"
                                    "QPushButton:disabled { background: #3a3a3a; color: #666; }")
        self.run_btn.clicked.connect(self.start_requested.emit)
        self.run_btn.setEnabled(False)
        self.addWidget(self.run_btn)

        self.stop_btn = QtWidgets.QPushButton("⏹ 정지")
        self.stop_btn.setStyleSheet("QPushButton { background: #8b3a3a; color: white; border-radius: 3px; font-weight: bold; }"
                                     "QPushButton:hover { background: #a04545; }"
                                     "QPushButton:disabled { background: #3a3a3a; color: #666; }")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.setEnabled(False)
        self.addWidget(self.stop_btn)
        self.addSeparator()

        self.undo_btn = QtWidgets.QPushButton("↩ 뒤로")
        self.undo_btn.setToolTip("Ctrl+Z")
        self.undo_btn.clicked.connect(self.undo_requested.emit)
        self.undo_btn.setEnabled(False)
        self.addWidget(self.undo_btn)

        self.redo_btn = QtWidgets.QPushButton("↪ 앞으로")
        self.redo_btn.setToolTip("Ctrl+Y")
        self.redo_btn.clicked.connect(self.redo_requested.emit)
        self.redo_btn.setEnabled(False)
        self.addWidget(self.redo_btn)

        self.apply_btn = QtWidgets.QPushButton("💾 적용")
        self.apply_btn.setToolTip("Ctrl+S")
        self.apply_btn.clicked.connect(self.apply_requested.emit)
        self.apply_btn.setEnabled(False)
        self.addWidget(self.apply_btn)

    def _connect_adb(self):
        port_text = self.port_input.text().strip()
        if not port_text:
            port_text = adb_manager.get_port()
            if port_text:
                self.port_input.setText(str(port_text))
            else:
                print("포트를 감지할 수 없습니다. 수동으로 입력해주세요.")
                return

        print(f"ADB 연결 시도: 포트 {port_text}")
        adb_manager.run_adb_command()

        try:
            from ppadb.client import Client as AdbClient
            client = AdbClient(host="127.0.0.1", port=5037)
            client.remote_connect("localhost", int(port_text))
            adb_manager.adbdevice = client.device("localhost:" + str(port_text))

            if adb_manager.adbdevice:
                print(f"✅ ADB 연결 성공 (포트: {port_text})")
                self.macro_mgr = MacroManager()
                self.status_label.setText("  🟢 연결됨")
                self.status_label.setStyleSheet("color: #40c057; font-weight: bold;")
                
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                self.run_btn.setEnabled(True)
                self.port_input.setEnabled(False)
                
                self.connection_changed.emit(True)
            else:
                print("❌ ADB 디바이스를 찾을 수 없습니다.")
        except Exception as e:
            print(f"❌ ADB 연결 실패: {e}")

    def _disconnect_adb(self):
        adb_manager.adbdevice = None
        self.macro_mgr = None
        self.status_label.setText("  ⚪ 미연결")
        self.status_label.setStyleSheet("color: #999; font-weight: bold;")
        
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.port_input.setEnabled(True)
        
        self.connection_changed.emit(False)
        print("ADB 연결이 해제되었습니다.")

    def get_macro_manager(self):
        return self.macro_mgr

    def set_editing_enabled(self, enabled: bool):
        is_connected = adb_manager.adbdevice is not None
        if enabled:
            self.connect_btn.setEnabled(not is_connected)
            self.disconnect_btn.setEnabled(is_connected)
            self.port_input.setEnabled(not is_connected)
        else:
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)
            self.port_input.setEnabled(False)
            
    def set_execution_state(self, is_running: bool):
        is_connected = adb_manager.adbdevice is not None
        self.run_btn.setEnabled(not is_running and is_connected)
        self.stop_btn.setEnabled(is_running)

    def set_history_state(self, can_undo: bool, can_redo: bool):
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)

    def set_apply_enabled(self, enabled: bool):
        self.apply_btn.setEnabled(enabled)
