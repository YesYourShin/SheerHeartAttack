import os
import json
import tempfile
from PIL import Image

class ConditionEvaluator:
    """
    이미지 매칭, 색상 비교, 변수 조건 비교 등 화면 판정 로직을 전담합니다.
    """
    def __init__(self, runner):
        self.runner = runner
        self.macro = getattr(runner, 'macro', None)

    def check_conditions(self, conditions, capture_image="", scope_log_prefix="", rule_label=""):
        """
        조건 리스트를 모두 검사. 모두 통과하면 (True, found_pos) 반환.
        """
        found_pos = None

        if self.macro is None:
            return False, None

        scr_img = self.macro.screenshot()
        if scr_img is None:
            return False, None

        scope_prefix = scope_log_prefix or "Node"
        rule_text = (rule_label or "").strip() or "Rule"

        def _log(msg):
            print(f"[{scope_prefix}] {rule_text} {msg}")

        for cond in conditions:
            ctype = cond.get('type', 'image')

            try:
                if ctype == 'image_region':
                    x, y = int(cond.get('x', 0)), int(cond.get('y', 0))
                    w, h = int(cond.get('w', 0)), int(cond.get('h', 0))
                    threshold = float(cond.get('threshold', 0.8))
                    if w <= 0 or h <= 0 or not capture_image:
                        return False, None
                    crop_path = self._crop_region(capture_image, x, y, w, h)
                    if not crop_path:
                        return False, None
                    pos = self.macro.get_pos(crop_path, scr_img=scr_img, confidence=threshold)
                    if not pos:
                        _log(f"이미지 영역 조건 실패 (임계값 {threshold})")
                        return False, None
                    
                    _log(f"이미지 영역 조건 성공 (좌표 {pos}, 임계값 {threshold})")
                    if found_pos is None:
                        found_pos = pos

                elif ctype == 'image':
                    img = cond.get('image', '')
                    threshold = float(cond.get('threshold', 0.8))
                    if not img:
                        return False, None
                    pos = self.macro.get_pos(img, scr_img=scr_img, confidence=threshold)
                    if not pos:
                        _log(f"이미지 조건 실패: {os.path.basename(img)} (임계값 {threshold})")
                        return False, None
                        
                    _log(f"이미지 조건 성공: {os.path.basename(img)} (좌표 {pos}, 임계값 {threshold})")
                    if found_pos is None:
                        found_pos = pos

                elif ctype == 'color':
                    x = int(cond.get('x', 0))
                    y = int(cond.get('y', 0))
                    r = int(cond.get('r', 0))
                    g = int(cond.get('g', 0))
                    b = int(cond.get('b', 0))
                    tol = int(cond.get('tolerance', 10))
                    import numpy as np
                    arr = np.array(scr_img)
                    if y < arr.shape[0] and x < arr.shape[1]:
                        px = arr[y, x]
                        if abs(int(px[0]) - r) <= tol and abs(int(px[1]) - g) <= tol and abs(int(px[2]) - b) <= tol:
                            _log(f"색상 조건 성공: ({x}, {y}) RGB({r},{g},{b}) 허용오차 {tol}")
                        else:
                            _log(f"색상 조건 실패: ({x}, {y}) RGB({r},{g},{b}) 허용오차 {tol}")
                            return False, None
                    else:
                        _log(f"색상 조건 실패: 좌표 범위 초과 ({x}, {y})")
                        return False, None

                elif ctype == 'var_cond':
                    vname = cond.get('name')
                    vop = cond.get('operator', '==')
                    vval = int(cond.get('value', 0))
                    
                    if not vname:
                        return False, None
                    
                    # VariableManager를 통해 변수 조회
                    current_val = self.runner.variable_manager.get_variable(vname)
                    match = False
                    if vop == '==': match = (current_val == vval)
                    elif vop == '>=': match = (current_val >= vval)
                    elif vop == '<=': match = (current_val <= vval)
                    elif vop == '>': match = (current_val > vval)
                    elif vop == '<': match = (current_val < vval)
                    elif vop == '!=': match = (current_val != vval)
                    
                    if not match:
                        _log(f"변수 조건 실패: {vname} ({current_val}) {vop} {vval}")
                        return False, None
                    
                    _log(f"변수 조건 성공: {vname} ({current_val}) {vop} {vval}")
                else:
                    _log(f"조건 실패: 알 수 없는 타입 {ctype}")
                    return False, None
            except Exception as e:
                print(f"⚠ 조건 검사 오류: {e}")
                return False, None

        return True, found_pos

    def _crop_region(self, image_data, x, y, w, h):
        """캡처 이미지에서 지정된 영역을 크롭하여 임시 파일로 저장."""
        try:
            import io
            import base64
            if image_data.startswith("data:image/png;base64,"):
                b64_str = image_data.split(",", 1)[1]
                img = Image.open(io.BytesIO(base64.b64decode(b64_str)))
            else:
                img = Image.open(image_data)
                
            if img.mode != 'RGB':
                img = img.convert('RGB')
            cropped = img.crop((x, y, x + w, y + h))
            tmp = os.path.join(tempfile.gettempdir(), f"macro_crop_{x}_{y}_{w}_{h}.png")
            cropped.save(tmp)
            return tmp
        except Exception as e:
            print(f"[Condition] 이미지 영역 크롭 실패: {e}")
            return None
