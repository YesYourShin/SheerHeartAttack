import win32gui
import win32ui
import win32con
from PIL import Image
import random
import library.adb_manager as adb_manager
import pyautogui
import cv2
import numpy as np
import sys
import time

class MacroManager:
    """
    매크로 동작을 관리하는 클래스입니다.
    AutomationRunner에서 사용하기 위해 클래스 형태로 래핑되었습니다.
    """
    def __init__(self):
        pass

    def screenshot(self):
        """
        ADB를 통해 스크린샷을 찍고 RGB PIL 이미지를 반환합니다.
        템플릿 매칭을 위해 일관된 색상 모드를 보장합니다.
        """
        if adb_manager.adbdevice is None:
            print("오류: ADB 장치가 연결되지 않았습니다.")
            return None

        try:
            result = adb_manager.adbdevice.screencap()
            if not result:
                print("오류: screencap 반환값이 비어 있습니다.")
                return None
                
            byte_data = bytearray(result)
            image_array = np.frombuffer(byte_data, dtype=np.uint8)
            
            # 디코딩: ADB는 일반적으로 PNG 바이너리를 반환합니다. 
            # cv2.imdecode가 이를 처리하며 기본적으로 BGR로 로드합니다.
            image_bgr = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
            
            # PIL/PyAutoGUI 처리를 위해 BGR을 RGB로 변환
            image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            
            return Image.fromarray(image_rgb)
        except Exception as e:
            print(f"스크린샷 실패: {e}")
            return None

    def capture(self):
        """
        screenshot 메서드의 별칭입니다. AutomationRunner와의 호환성을 위해 제공됩니다.
        """
        return self.screenshot()

    def get_pos(self, src_img, scr_img=None, confidence=0.8):
        """
        scr_img 이미지 안에서 src_img를 찾습니다 (없으면 새 스크린샷 촬영).
        (left, top, width, height) 튜플을 반환하거나 찾지 못하면 None을 반환합니다.
        """
        if scr_img is None:
            scr_img = self.screenshot()
        
        if scr_img is None:
            return None

        try:
            # pyautogui.locate는 haystack으로 PIL 이미지를 받습니다.
            # src_img는 경로 문자열이거나 PIL 이미지일 수 있습니다.
            return pyautogui.locate(src_img, scr_img, confidence=confidence)
        except pyautogui.ImageNotFoundException:
            return None
        except Exception as e:
            print(f"디버그: {src_img} 찾기 실패: {type(e).__name__} - {e}")
            return None

    def scan(self, target_list, scr_img=None, confidence=0.8):
        """
        한 번의 스크린샷으로 여러 타겟을 스캔합니다.
        첫 번째로 발견된 타겟을 반환합니다: (target_name_or_img, pos)
        """
        if scr_img is None:
            scr_img = self.screenshot()
            
        if scr_img is None:
            return None, None

        for target in target_list:
            pos = self.get_pos(target, scr_img, confidence)
            if pos:
                return target, pos
                
        return None, None

    def click(self, pos):
        """
        pos 박스 내부의 랜덤한 좌표를 클릭합니다.
        """
        if not pos:
            return False
        
        # [수정] 2개(x, y)만 들어오면 w=1, h=1로 처리
        if len(pos) == 2:
            left, top = int(pos[0]), int(pos[1])
            width, height = 1, 1
        elif len(pos) == 4:
            left, top, width, height = int(pos[0]), int(pos[1]), int(pos[2]), int(pos[3])
        else:
            print(f"클릭 오류: 좌표 형식이 잘못되었습니다. {pos}")
            return False
        
        # 안전장치: 최소 1px 범위 보장
        if width <= 1: width = 2
        if height <= 1: height = 2

        # 수정: 랜덤 범위가 경계 내의 중심쪽 50% 안에 있도록 보정
        # 버튼의 외곽 선을 누르게 될 경우 다른 버튼 패딩을 침범할 수 있으므로 중앙 부근 타겟팅
        margin_x = width // 4
        margin_y = height // 4
        
        # 안전장치: 마진때문에 width/height가 역전되지 않도록 보장
        inner_width = max(1, width - (margin_x * 2))
        inner_height = max(1, height - (margin_y * 2))

        x = random.randint(left + margin_x, left + margin_x + inner_width - 1)
        y = random.randint(top + margin_y, top + margin_y + inner_height - 1)
        
        # 거리 0인 스와이프는 탭으로 동작, 지속 시간은 랜덤 (ms)
        duration = random.randint(50, 120)
        cmd = f"input swipe {x} {y} {x} {y} {duration}"
        
        try:
            adb_manager.adbdevice.shell(cmd)
            return True
        except Exception as e:
            print(f"클릭 실패: {e}")
            return False

    def click_img(self, src_img, scr_img=None, confidence=0.8):
        """
        이미지를 찾아서 클릭합니다.
        """
        pos = self.get_pos(src_img, scr_img, confidence)
        if pos:
            print(f'클릭: {src_img}')
            return self.click(pos)
        return False

    # -------------------------------------------------------
    # 디버그 / 헬퍼 도구
    # -------------------------------------------------------

    def draw_img_pos(self, src_img):
        """
        디버그: 찾은 이미지 주위에 빨간 테두리를 그리고 창을 띄워 보여줍니다.
        """
        scr_img = self.screenshot()
        click_pos = self.get_pos(src_img, scr_img)
        
        if click_pos:
            x, y, width, height = click_pos
            image_np = np.array(scr_img) # RGB
            # cv2.imshow를 위해 다시 BGR로 변환
            image_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)
            
            cv2.rectangle(image_bgr, (x, y), (x + width, y + height), (0, 0, 255), 2)
            
            cv2.imshow('Debug: Image Found', image_bgr)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            print("디버그 드로잉을 위한 이미지를 찾지 못했습니다.")
        # return sys.exit() # 디버그 계속 진행을 위해 exit 제거