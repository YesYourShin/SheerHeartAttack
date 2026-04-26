"""
이미지 관련 위젯 모음.
- ImageRegionSelector: 캡처 이미지에서 영역/좌표 선택
- _ZoomableGraphicsView: 드래그 팬 + 스크롤 줌
- FullImageViewer: 오버레이 포함 원본 이미지 뷰어
- CapturePreview: 속성 패널 내 미리보기 + 오버레이
"""
import os
from PySide6 import QtWidgets, QtCore, QtGui

from ui.styles import DARK_STYLE


# ══════════════════════════════════════════════
# 이미지 영역 선택 위젯
# ══════════════════════════════════════════════
class ImageRegionSelector(QtWidgets.QDialog):
    """캡처 이미지 위에서 드래그로 영역을 선택하거나, 클릭으로 좌표를 지정하는 다이얼로그."""

    def __init__(self, image_path, mode="region", existing_rect=None, existing_point=None, parent=None):
        """
        mode: "region" (드래그 영역 선택) 또는 "point" (클릭 좌표 선택)
        """
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("영역 선택" if mode == "region" else "좌표 선택")
        self.setStyleSheet(DARK_STYLE)

        self.pixmap = QtGui.QPixmap()
        if image_path.startswith("data:image/png;base64,"):
            import base64
            b64_data = image_path.split(",", 1)[1]
            byte_data = QtCore.QByteArray.fromBase64(b64_data.encode("utf-8"))
            self.pixmap.loadFromData(byte_data)
        else:
            self.pixmap.load(image_path)
        if self.pixmap.isNull():
            QtWidgets.QMessageBox.warning(self, "오류", "이미지를 불러올 수 없습니다.")
            self.reject()
            return

        # 화면 크기에 맞게 스케일 (원본 비율 유지)
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        max_w, max_h = int(screen.width() * 0.8), int(screen.height() * 0.8)
        self.scale = min(max_w / self.pixmap.width(), max_h / self.pixmap.height(), 1.0)
        self.display_pixmap = self.pixmap.scaled(
            int(self.pixmap.width() * self.scale),
            int(self.pixmap.height() * self.scale),
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )

        self.selected_rect = existing_rect  # (x, y, w, h) in original image coords
        self.selected_point = existing_point  # (x, y) in original image coords
        self.drag_start = None

        layout = QtWidgets.QVBoxLayout(self)
        hint = "드래그하여 영역을 선택하세요" if mode == "region" else "클릭하여 좌표를 선택하세요"
        layout.addWidget(QtWidgets.QLabel(hint))

        self.scene = QtWidgets.QGraphicsScene(self)
        self.pixmap_item = self.scene.addPixmap(self.display_pixmap)
        
        self.view = _ZoomableGraphicsView()
        self.view.setScene(self.scene)
        self.view.setCursor(QtCore.Qt.CrossCursor)
        # 뷰포트 마우스 이벤트를 가로채기 위해 이벤트 필터 설치
        self.view.viewport().installEventFilter(self)
        
        layout.addWidget(self.view)
        
        # 그리기용 오버레이 아이템 (선택 영역/포인트 표시용)
        self.overlay_item = QtWidgets.QGraphicsPixmapItem()
        self.scene.addItem(self.overlay_item)
        
        # 뷰와 다이얼로그 크기 지정
        self.view.setSceneRect(0, 0, self.display_pixmap.width(), self.display_pixmap.height())
        dlg_w = min(self.display_pixmap.width() + 40, max_w)
        dlg_h = min(self.display_pixmap.height() + 100, max_h)
        self.resize(dlg_w, dlg_h)

        self.coord_label = QtWidgets.QLabel("선택: 없음")
        layout.addWidget(self.coord_label)

        bl = QtWidgets.QHBoxLayout()
        bl.addStretch()
        cb = QtWidgets.QPushButton("Cancel"); cb.setObjectName("cancelBtn"); cb.clicked.connect(self.reject); bl.addWidget(cb)
        self.ok_btn = QtWidgets.QPushButton("OK"); self.ok_btn.clicked.connect(self.accept); self.ok_btn.setEnabled(False); bl.addWidget(self.ok_btn)
        layout.addLayout(bl)

        # 초기 영역 마킹 (오버레이 생성 후 기폭)
        if self.selected_rect and self.mode == "region":
            QtCore.QTimer.singleShot(50, lambda: self._draw_existing_rect(*self.selected_rect))
        elif self.selected_point and self.mode == "point":
            QtCore.QTimer.singleShot(50, lambda: self._draw_existing_point(*self.selected_point))

    def _to_orig(self, pos):
        return int(pos.x() / self.scale), int(pos.y() / self.scale)

    def eventFilter(self, obj, e):
        # 뷰포트의 마우스 이벤트 가로채기
        if obj is self.view.viewport():
            if e.type() == QtCore.QEvent.MouseButtonPress:
                self._mouse_press(e)
            elif e.type() == QtCore.QEvent.MouseMove:
                self._mouse_move(e)
            elif e.type() == QtCore.QEvent.MouseButtonRelease:
                self._mouse_release(e)
        return super().eventFilter(obj, e)

    def _get_scene_pos(self, e):
        # 뷰포트 좌표를 씬 좌표로 변환
        return self.view.mapToScene(e.pos())

    def _mouse_press(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.drag_start = self._get_scene_pos(e)
            # 마우스 클릭 즉시 오버레이 클리어 (사용성 개선)
            pm = QtGui.QPixmap(self.display_pixmap.size())
            pm.fill(QtCore.Qt.transparent)
            self.overlay_item.setPixmap(pm)

    def _mouse_move(self, e):
        if self.drag_start and self.mode == "region":
            self._draw_rect(self._get_scene_pos(e))

    def _mouse_release(self, e):
        if e.button() != QtCore.Qt.LeftButton or not self.drag_start:
            return
            
        end_pos = self._get_scene_pos(e)

        if self.mode == "point":
            ox, oy = self._to_orig(end_pos)
            self.selected_point = (ox, oy)
            # 색상 읽기
            img = self.pixmap.toImage()
            if 0 <= ox < img.width() and 0 <= oy < img.height():
                c = img.pixelColor(ox, oy)
                self.coord_label.setText(f"좌표: ({ox}, {oy})  색상: RGB({c.red()}, {c.green()}, {c.blue()})")
            else:
                self.coord_label.setText(f"좌표: ({ox}, {oy})")
            self._draw_point(end_pos)
            self.ok_btn.setEnabled(True)
        else:
            sx, sy = self._to_orig(self.drag_start)
            ex, ey = self._to_orig(end_pos)
            x = min(sx, ex); y = min(sy, ey)
            w = abs(ex - sx); h = abs(ey - sy)
            if w > 2 and h > 2:
                self.selected_rect = (x, y, w, h)
                self.coord_label.setText(f"영역: ({x}, {y}) ~ ({x+w}, {y+h})")
                self.ok_btn.setEnabled(True)
        self.drag_start = None

    def _draw_rect(self, end):
        pm = QtGui.QPixmap(self.display_pixmap.size())
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 150, 255), 2))
        painter.setBrush(QtGui.QColor(0, 150, 255, 40))
        painter.drawRect(QtCore.QRectF(self.drag_start, end))
        painter.end()
        self.overlay_item.setPixmap(pm)

    def _draw_point(self, pos):
        pm = QtGui.QPixmap(self.display_pixmap.size())
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 50, 50), 2))
        painter.drawLine(QtCore.QPointF(pos.x() - 10, pos.y()), QtCore.QPointF(pos.x() + 10, pos.y()))
        painter.drawLine(QtCore.QPointF(pos.x(), pos.y() - 10), QtCore.QPointF(pos.x(), pos.y() + 10))
        painter.end()
        self.overlay_item.setPixmap(pm)

    def _draw_existing_rect(self, x, y, w, h):
        """기존 영역 마킹"""
        pm = QtGui.QPixmap(self.display_pixmap.size())
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 150, 255), 2))
        painter.setBrush(QtGui.QColor(0, 150, 255, 40))
        sx, sy = x * self.scale, y * self.scale
        sw, sh = w * self.scale, h * self.scale
        painter.drawRect(QtCore.QRectF(sx, sy, sw, sh))
        painter.end()
        self.overlay_item.setPixmap(pm)
        self.ok_btn.setEnabled(True)
        self.coord_label.setText(f"영역: ({x}, {y}) ~ ({x+w}, {y+h})")

    def _draw_existing_point(self, x, y):
        """기존 좌표 마킹"""
        pm = QtGui.QPixmap(self.display_pixmap.size())
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pm)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 50, 50), 2))
        px, py = x * self.scale, y * self.scale
        painter.drawLine(QtCore.QPointF(px - 10, py), QtCore.QPointF(px + 10, py))
        painter.drawLine(QtCore.QPointF(px, py - 10), QtCore.QPointF(px, py + 10))
        painter.end()
        self.overlay_item.setPixmap(pm)
        self.ok_btn.setEnabled(True)
        
        # 색상 로드 헬퍼
        img = self.pixmap.toImage()
        if 0 <= x < img.width() and 0 <= y < img.height():
            c = img.pixelColor(x, y)
            self.coord_label.setText(f"좌표: ({x}, {y})  색상: RGB({c.red()}, {c.green()}, {c.blue()})")
        else:
            self.coord_label.setText(f"좌표: ({x}, {y})")

    def get_result(self):
        if self.mode == "region":
            return self.selected_rect
        return self.selected_point


# ══════════════════════════════════════════════
# 줌/패닝 가능한 QGraphicsView
# ══════════════════════════════════════════════
class _ZoomableGraphicsView(QtWidgets.QGraphicsView):
    """마우스 드래그로 패닝, 스크롤 휠로 확대/축소하는 QGraphicsView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("QGraphicsView { border: none; background: #1a1a1a; }")
        self._zoom = 1.0

    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() > 0:
            self._zoom *= factor
            self.scale(factor, factor)
        else:
            self._zoom /= factor
            self.scale(1 / factor, 1 / factor)

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            # 마우스 프레스 이벤트를 다시 생성하여 드래그 시작하게 함
            press_event = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonPress,
                event.pos(), QtCore.Qt.LeftButton,
                QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
            )
            super().mousePressEvent(press_event)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            release_event = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonRelease,
                event.pos(), QtCore.Qt.LeftButton,
                QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
            )
            super().mouseReleaseEvent(release_event)
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            return
        super().mouseReleaseEvent(event)


# ══════════════════════════════════════════════
# 오버레이 포함 이미지 뷰어 다이얼로그
# ══════════════════════════════════════════════
class FullImageViewer(QtWidgets.QDialog):
    """원본 크기 캡처 이미지에 조건/동작 오버레이를 그려서 볼 수 있는 다이얼로그.
    마우스 드래그로 이동, 스크롤 휠로 확대/축소."""

    def __init__(self, image_path, conditions=None, actions=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("캡처 이미지 상세 보기  (드래그: 이동 / 스크롤: 확대·축소)")
        self.setStyleSheet(DARK_STYLE)

        pixmap = QtGui.QPixmap()
        if image_path.startswith("data:image/png;base64,"):
            import base64
            b64_data = image_path.split(",", 1)[1]
            byte_data = QtCore.QByteArray.fromBase64(b64_data.encode("utf-8"))
            pixmap.loadFromData(byte_data)
        else:
            pixmap.load(image_path)
        if pixmap.isNull():
            QtWidgets.QMessageBox.warning(self, "오류", "이미지를 불러올 수 없습니다.")
            self.reject()
            return

        # 오버레이 그리기 (원본 크기에 직접 그림)
        pm = pixmap.copy()
        painter = QtGui.QPainter(pm)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        font = painter.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)

        # 조건: 파란색 사각형
        for i, c in enumerate(conditions or []):
            if c.get("type") == "image_region" and c.get("w", 0) > 0:
                pen = QtGui.QPen(QtGui.QColor(0, 150, 255), 3)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor(0, 150, 255, 30))
                painter.drawRect(c["x"], c["y"], c["w"], c["h"])
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(c["x"] + 4, c["y"] - 4, f"조건{i+1}")
            elif c.get("type") == "color":
                pen = QtGui.QPen(QtGui.QColor(255, 200, 0), 3)
                painter.setPen(pen)
                cx, cy = c.get("x", 0), c.get("y", 0)
                painter.drawLine(cx - 10, cy, cx + 10, cy)
                painter.drawLine(cx, cy - 10, cx, cy + 10)
                painter.drawEllipse(cx - 12, cy - 12, 24, 24)
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(cx + 14, cy - 4, f"조건{i+1}")

        # 동작: 녹색 사각형
        for i, a in enumerate(actions or []):
            if a.get("type") == "click_region" and a.get("w", 0) > 0:
                pen = QtGui.QPen(QtGui.QColor(50, 200, 50), 3)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor(50, 200, 50, 30))
                painter.drawRect(a["x"], a["y"], a["w"], a["h"])
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(a["x"] + 4, a["y"] - 4, f"동작{i+1}")
            elif a.get("type") == "click_pos":
                pen = QtGui.QPen(QtGui.QColor(255, 80, 80), 3)
                painter.setPen(pen)
                cx, cy = a.get("x", 0), a.get("y", 0)
                painter.drawLine(cx - 10, cy, cx + 10, cy)
                painter.drawLine(cx, cy - 10, cx, cy + 10)
                painter.drawEllipse(cx - 12, cy - 12, 24, 24)
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.drawText(cx + 14, cy - 4, f"동작{i+1}")

        painter.end()

        # 화면 크기의 85%를 최대 크기로
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        max_w, max_h = int(screen.width() * 0.85), int(screen.height() * 0.85)
        dlg_w = min(pm.width() + 40, max_w)
        dlg_h = min(pm.height() + 100, max_h)
        self.resize(dlg_w, dlg_h)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        info_label = QtWidgets.QLabel(
            f"원본 크기: {pixmap.width()} × {pixmap.height()}px  |  "
            f"🔵 조건: {len(conditions or [])}개  🟢 동작: {len(actions or [])}개  |  "
            f"드래그: 이동 / 스크롤: 확대·축소"
        )
        info_label.setStyleSheet("color: #aaa; font-size: 11px; padding: 2px;")
        layout.addWidget(info_label)

        # QGraphicsView 기반 뷰어
        self.view = _ZoomableGraphicsView()
        scene = QtWidgets.QGraphicsScene(self)
        scene.addPixmap(pm)
        self.view.setScene(scene)
        self.view.setSceneRect(0, 0, pm.width(), pm.height())
        layout.addWidget(self.view)

        # 하단 버튼
        btn_row = QtWidgets.QHBoxLayout()
        reset_btn = QtWidgets.QPushButton("🔄 원래 크기")
        reset_btn.setFixedWidth(110)
        reset_btn.clicked.connect(self.view.reset_zoom)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        close_btn = QtWidgets.QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        close_btn.setFixedWidth(100)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ══════════════════════════════════════════════
# 이미지 미리보기 + 오버레이 위젯
# ══════════════════════════════════════════════
class CapturePreview(QtWidgets.QLabel):
    """캡처 이미지를 표시하고, 조건/동작 영역을 오버레이로 그리는 위젯."""

    _PREVIEW_HEIGHT = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFixedHeight(self._PREVIEW_HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setStyleSheet("background: #1e1e1e; border: 1px solid #555; border-radius: 4px;")
        self.setText("캡처 이미지 없음")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("클릭하면 이미지를 크게 볼 수 있습니다")
        self.image_path = ""
        self.conditions = []
        self.actions = []
        self._orig_pixmap = None

    def set_image(self, path):
        self.image_path = path
        if path:
            if path.startswith("data:image/png;base64,"):
                import base64
                b64_data = path.split(",", 1)[1]
                byte_data = QtCore.QByteArray.fromBase64(b64_data.encode("utf-8"))
                self._orig_pixmap = QtGui.QPixmap()
                self._orig_pixmap.loadFromData(byte_data)
                self._redraw()
            elif os.path.exists(path):
                self._orig_pixmap = QtGui.QPixmap(path)
                self._redraw()
            else:
                self._orig_pixmap = None
                self.setText("캡처 이미지 없음")
        else:
            self._orig_pixmap = None
            self.setText("캡처 이미지 없음")

    def set_overlays(self, conditions, actions):
        self.conditions = conditions
        self.actions = actions
        if self._orig_pixmap:
            self._redraw()

    def mousePressEvent(self, event):
        """클릭 시 오버레이 포함 이미지 뷰어 팝업"""
        if event.button() == QtCore.Qt.LeftButton and self.image_path and (self.image_path.startswith("data:image/png;base64,") or os.path.exists(self.image_path)):
            dlg = FullImageViewer(self.image_path, conditions=self.conditions, actions=self.actions, parent=self)
            dlg.exec()
        super().mousePressEvent(event)

    def _redraw(self):
        if not self._orig_pixmap:
            return
        # 枠の大きさは固定し、画像全体が比率維持で収まるよう中央に描画する。
        frame_w = max(self.width() - 4, 1)
        frame_h = max(self.height() - 4, 1)
        scaled = self._orig_pixmap.scaled(
            frame_w,
            frame_h,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        scale = scaled.width() / self._orig_pixmap.width()
        offset_x = (frame_w - scaled.width()) // 2
        offset_y = (frame_h - scaled.height()) // 2

        pm = QtGui.QPixmap(frame_w, frame_h)
        pm.fill(QtGui.QColor("#1e1e1e"))
        painter = QtGui.QPainter(pm)
        painter.drawPixmap(offset_x, offset_y, scaled)

        # 조건: 파란색 사각형
        for c in self.conditions:
            if c.get("type") == "image_region" and c.get("w", 0) > 0:
                pen = QtGui.QPen(QtGui.QColor(0, 150, 255), 2)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor(0, 150, 255, 30))
                painter.drawRect(offset_x + int(c["x"] * scale), offset_y + int(c["y"] * scale),
                                 int(c["w"] * scale), int(c["h"] * scale))
            elif c.get("type") == "color":
                pen = QtGui.QPen(QtGui.QColor(255, 200, 0), 2)
                painter.setPen(pen)
                cx = offset_x + int(c.get("x", 0) * scale)
                cy = offset_y + int(c.get("y", 0) * scale)
                painter.drawLine(cx - 6, cy, cx + 6, cy)
                painter.drawLine(cx, cy - 6, cx, cy + 6)

        # 동작: 녹색 사각형
        for a in self.actions:
            if a.get("type") == "click_region" and a.get("w", 0) > 0:
                pen = QtGui.QPen(QtGui.QColor(50, 200, 50), 2)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor(50, 200, 50, 30))
                painter.drawRect(offset_x + int(a["x"] * scale), offset_y + int(a["y"] * scale),
                                 int(a["w"] * scale), int(a["h"] * scale))
            elif a.get("type") == "click_pos":
                pen = QtGui.QPen(QtGui.QColor(255, 80, 80), 2)
                painter.setPen(pen)
                cx = offset_x + int(a.get("x", 0) * scale)
                cy = offset_y + int(a.get("y", 0) * scale)
                painter.drawLine(cx - 6, cy, cx + 6, cy)
                painter.drawLine(cx, cy - 6, cx, cy + 6)

        painter.end()
        self.setPixmap(pm)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._orig_pixmap:
            self._redraw()
