import time
import json
import library.adb_manager as adb_manager

class ActionExecutor:
    """
    마우스 클릭, 딜레이 대기, 변수 값 변조 등 액션 수행 로직을 전담합니다.
    """
    def __init__(self, runner):
        self.runner = runner
        self.macro = getattr(runner, 'macro', None)

    def execute_actions(self, actions, found_pos, capture_image=""):
        """동작 리스트를 위에서 아래로 순서대로 실행."""
        if self.macro is None:
            return

        for act in actions:
            # runner의 정지 상태 플래그 확인
            if hasattr(self.runner, 'is_running') and not self.runner.is_running:
                return

            atype = act.get('type', 'click_found')

            if atype == 'click_region':
                x, y = int(act.get('x', 0)), int(act.get('y', 0))
                w, h = int(act.get('w', 0)), int(act.get('h', 0))
                if w <= 0 or h <= 0 or not capture_image:
                    continue
                
                # ConditionEvaluator의 크롭 기능 위임 활용
                crop_path = None
                if hasattr(self.runner, 'condition_evaluator'):
                    crop_path = self.runner.condition_evaluator._crop_region(capture_image, x, y, w, h)
                    
                if crop_path:
                    pos = self.macro.get_pos(crop_path, confidence=0.8)
                    if pos:
                        self.macro.click(pos)

            elif atype == 'click_found' and found_pos:
                self.macro.click(found_pos)

            elif atype == 'click_pos':
                x = int(act.get('x', 0))
                y = int(act.get('y', 0))
                self.macro.click((x, y, 0, 0))

            elif atype == 'click_image':
                img = act.get('image', '')
                if img:
                    pos = self.macro.get_pos(img, confidence=0.8)
                    if pos:
                        self.macro.click(pos)

            elif atype == 'wait':
                if act.get('use_random', False):
                    import random
                    min_sec = float(act.get('min_seconds', 1.0))
                    max_sec = float(act.get('max_seconds', 2.0))
                    sec = random.uniform(min_sec, max_sec)
                else:
                    sec = float(act.get('seconds', 1.0))
                if hasattr(self.runner, '_sleep_interruptible'):
                    self.runner._sleep_interruptible(sec)
                else:
                    time.sleep(sec)

            elif atype == 'var_op':
                vname = act.get('name')
                vop = act.get('operation', '=')
                vval = act.get('value', 0)
                if vname and hasattr(self.runner, 'variable_manager'):
                    self.runner.variable_manager.update_variable(vname, vop, vval)

            elif atype == 'app_package':
                # Rule から保存されたパッケージで ADB shell を実行
                pkg = adb_manager.safe_package_token(act.get('package', ''))
                if not pkg:
                    print("app_package: パッケージ名が無効です")
                    continue
                dev = adb_manager.adbdevice
                if dev is None:
                    print("app_package: ADB 未接続")
                    continue
                mode = act.get('mode', 'launch')
                try:
                    if mode == 'force_stop':
                        dev.shell(f"am force-stop {pkg}")
                    else:
                        dev.shell(
                            f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1"
                        )
                except Exception as e:
                    print(f"app_package 失敗 ({pkg}): {e}")

    def execute_variable_ops(self, ops_json):
        """변수 연산 JSON 문자열을 해석하여 실행"""
        try:
            ops = json.loads(ops_json)
        except Exception:
            ops = []
        for op in ops:
            vname = op.get('name')
            vop = op.get('operation')
            vval = op.get('value')
            if vname and hasattr(self.runner, 'variable_manager'):
                self.runner.variable_manager.update_variable(vname, vop, vval)
