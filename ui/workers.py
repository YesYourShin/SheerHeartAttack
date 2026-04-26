import sys
from PySide6 import QtCore
from framework.flow_runner import FlowRunner

# ──────────────────────────────────────────────
# 로그 리다이렉터: print() 출력을 QTextEdit로 전달
# ──────────────────────────────────────────────
class LogStream(QtCore.QObject):
    """stdout/stderr 를 Qt 시그널로 리다이렉트"""
    message = QtCore.Signal(str)

    def write(self, text):
        if text.strip():
            self.message.emit(str(text))

    def flush(self):
        pass


# ──────────────────────────────────────────────
# 매크로 백그라운드 실행 스레드
# ──────────────────────────────────────────────
class MacroWorker(QtCore.QThread):
    finished_signal = QtCore.Signal()
    log_signal = QtCore.Signal(str)
    node_running_signal = QtCore.Signal(str)

    def __init__(self, json_path, log_stream=None, run_from_node_id=None):
        super().__init__()
        self.json_path = json_path
        self.runner = None
        self._log_stream = log_stream
        self.run_from_node_id = run_from_node_id

    def run(self):
        # 스레드 내에서도 print가 UI 로그에 표시되도록 stdout 리다이렉트
        if self._log_stream:
            sys.stdout = self._log_stream
        self.runner = FlowRunner(self.json_path, progress_callback=lambda nid: self.node_running_signal.emit(nid))
        self.runner.run(run_from_node_id=self.run_from_node_id)
        self.finished_signal.emit()

    def stop(self):
        if self.runner:
            self.runner.stop()
