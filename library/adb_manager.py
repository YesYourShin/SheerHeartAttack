from ppadb.client import Client as AdbClient
import os
import re
import subprocess
import win32gui
import sys
import time

adbdevice = None
hwnd = None

# psのNAME列から除外するプロセス名（パッケージではない）
_EXCLUDED_PROCESS_NAMES = frozenset({
    "system_server", "zygote", "zygote64", "surfaceflinger", "audioserver",
    "cameraserver", "mediaserver", "logd", "lmkd", "servicemanager", "vold",
    "netd", "installd", "keystore", "drmserver", "statsd", "incidentd",
})

# 典型的なパッケージ名っぽい行のみ通す
_PKG_LINE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$")
_ACTIVITY_COMPONENT_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)/")


def list_running_packages(device):
    """
    ps -A のプロセス名からパッケージ候補を抽出し、ソート済みリストで返す。
    device が None または失敗時は空リスト。
    """
    if device is None:
        return []
    try:
        raw = device.shell("ps -A -o NAME=")
    except Exception as e:
        print(f"list_running_packages shell 失敗: {e}")
        return []
    if not raw:
        return []
    seen = set()
    out = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        name = line.strip()
        if not name or name.upper() == "NAME":
            continue
        if name in _EXCLUDED_PROCESS_NAMES:
            continue
        if not _PKG_LINE_RE.match(name):
            continue
        if name not in seen:
            seen.add(name)
            out.append(name)
    out.sort()
    return out


def _extract_package_from_line(line):
    match = _ACTIVITY_COMPONENT_RE.search(line or "")
    if not match:
        return None
    pkg = match.group(1)
    if _PKG_LINE_RE.match(pkg):
        return pkg
    return None


def _extract_package_from_dumpsys(raw, markers):
    if not raw:
        return None
    for line in raw.replace("\r\n", "\n").split("\n"):
        if not any(marker in line for marker in markers):
            continue
        pkg = _extract_package_from_line(line)
        if pkg:
            return pkg
    return None


def get_current_foreground_package(device):
    """
    現在フォーカス中またはResume中のActivityからパッケージ名を取得する。
    """
    if device is None:
        return None

    checks = (
        (
            "dumpsys window",
            ("mCurrentFocus", "mFocusedApp"),
        ),
        (
            "dumpsys activity activities",
            ("ResumedActivity", "topResumedActivity", "mResumedActivity"),
        ),
    )

    for command, markers in checks:
        try:
            raw = device.shell(command)
        except Exception as e:
            print(f"get_current_foreground_package shell 失敗 ({command}): {e}")
            continue
        pkg = _extract_package_from_dumpsys(raw, markers)
        if pkg:
            return pkg
    return None


def safe_package_token(pkg):
    """
    shell に渡すパッケージ文字列を検証。危険文字があれば None。
    """
    if not pkg or not isinstance(pkg, str):
        return None
    s = pkg.strip()
    if not s:
        return None
    if any(c in s for c in ';|&\n\r`$()<>'):
        return None
    return s


def get_port():
    """
    파일에서 bluestack의 port번호를 가져와서 반환한다.
    """
    file_path = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
    
    if not os.path.exists(file_path):
        print(f"The specified file {file_path} does not exist.")
        # sys.exit() # 라이브러리에서 exit는 위험하므로 제거하거나 예외 발생
        return None

    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith("bst.instance.Pie64.status.adb_port"):
                # print('현재 포트 번호: ', line.split("=")[1].strip())
                value = line.split("=")[1].strip()
                return re.search(r'\d+', value).group()
    except Exception as e:
        print(f"포트 찾기 실패: {e}")
        return None
        
def run_adb_command():
    # command = f"adb kill-server"
    command = f"adb server start"
    subprocess.run(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def resize_window(hwnd, x, y, width, height):
    """프로그램 창 크기 조절 함수"""
    if hwnd:
        win32gui.MoveWindow(hwnd, x, y, width, height, True)
        print("사이즈 조절 완료")

def adb_connect(program_name, x, y, width, height):
    global hwnd 
    hwnd = win32gui.FindWindow(None, program_name)
    # resize_window(hwnd, x, y, width, height)
    device_port = get_port()
    if not device_port:
        print("BlueStacks 포트를 찾을 수 없습니다.")
        return False

    run_adb_command()
    
    try:
        client = AdbClient(host="127.0.0.1", port=5037)
        client.remote_connect("localhost", int(device_port))
        global adbdevice
        adbdevice = client.device("localhost:"+str(device_port))

        if adbdevice is not None:
            print(f"Adb detected: {device_port}")
            return True
        else:
            print("Adb not detected")
            return False
    except Exception as e:
        print(f"ADB 연결 실패: {e}")
        return False
        
class ADBManager:
    """
    AutomationRunner 등에서 사용할 정적 메서드 래퍼 클래스
    """
    @staticmethod
    def connect(program_name="BlueStacks App Player", x=0, y=0, w=1280, h=720):
        return adb_connect(program_name, x, y, w, h)

    @staticmethod
    def get_device():
        global adbdevice
        return adbdevice

    @staticmethod
    def start_app(package_name):
        global adbdevice
        if adbdevice:
            # monkey를 이용한 실행 (Launcher Activity 자동 실행)
            cmd = f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
            print(f"Start App: {package_name}")
            adbdevice.shell(cmd)
        else:
            print("ADB not connected")

    @staticmethod
    def stop_app(package_name):
        global adbdevice
        if adbdevice:
            cmd = f"am force-stop {package_name}"
            print(f"Stop App: {package_name}")
            adbdevice.shell(cmd)
        else:
            print("ADB not connected")

    @staticmethod
    def is_app_running(package_name):
        global adbdevice
        if not adbdevice:
            return False
        
        # pidof로 프로세스 확인
        pid = adbdevice.shell(f"pidof {package_name}").strip()
        return bool(pid)

    @staticmethod
    def get_current_foreground_package():
        global adbdevice
        return get_current_foreground_package(adbdevice)