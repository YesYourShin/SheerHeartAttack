"""
조건/동작 설명 텍스트 생성 함수.
- _describe_condition / _describe_action / _describe_variable_op / _describe_variable_def / _describe_variable_cond: 설명 텍스트 생성 함수
"""
import os

def _describe_variable_def(v):
    return f"🏷️ [{v.get('label', '')}] (초기값: {v.get('value', 0)})"

def _describe_variable_op(v):
    return f"🧮 {v.get('name','?')} {v.get('operation','=')} {v.get('value',0)}"

def _describe_variable_cond(v):
    return f"🛑 {v.get('name','?')} {v.get('operator','==')} {v.get('value',0)}"

def _describe_condition(c):
    t = c.get("type", "?")
    if t == "image_region":
        x, y = c.get('x', 0), c.get('y', 0)
        return f"🔍 이미지 영역: ({x}, {y}) ~ ({x + c.get('w', 0)}, {y + c.get('h', 0)})"
    elif t == "color":
        return f"🎨 색상: ({c.get('x',0)},{c.get('y',0)}) RGB({c.get('r',0)},{c.get('g',0)},{c.get('b',0)})"
    elif t == "image":
        return f"🔍 이미지: {os.path.basename(c.get('image','?'))}"
    elif t == "var_cond":
        return f"🧮 변수 비교: {c.get('name','?')} {c.get('operator','==')} {c.get('value',0)}"
    return f"? {t}"

def _describe_action(a):
    t = a.get("type", "?")
    if t == "click_region":
        x, y = a.get('x', 0), a.get('y', 0)
        return f"🖱️ 영역 클릭: ({x}, {y}) ~ ({x + a.get('w', 0)}, {y + a.get('h', 0)})"
    elif t == "click_pos":
        return f"🖱️ 좌표 클릭: ({a.get('x',0)}, {a.get('y',0)})"
    elif t == "click_found":
        return "🖱️ 찾은 이미지 위치 클릭"
    elif t == "click_image":
        return f"🖱️ 이미지 클릭: {os.path.basename(a.get('image','?'))}"
    elif t == "wait":
        if a.get("use_random", False):
            return f"⏱️ 랜덤 대기 {a.get('min_seconds', 1.0)}~{a.get('max_seconds', 2.0)}초"
        return f"⏱️ 대기 {a.get('seconds', 1.0)}초"
    elif t == "var_op":
        return f"🧮 변수 변경: {a.get('name','?')} {a.get('operation','=')} {a.get('value',0)}"
    elif t == "app_package":
        pkg = a.get("package", "") or "?"
        if a.get("mode") == "force_stop":
            return f"📱 앱 종료: {pkg}"
        return f"📱 앱 실행: {pkg}"
    return f"? {t}"
