"""Native Endfield-inspired workbench components and bounded motion."""
from PySide6.QtCore import QEvent, QObject, Property, QPropertyAnimation, QEasingCurve, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QWidget


SIGNAL_YELLOW = QColor("#FFE600")
INK_BLACK = QColor("#000000")
PAPER_WHITE = QColor("#F5F5F2")
GROUND = QColor("#121316")


class IndustrialComboBox(QComboBox):
    """Square combo box with a path-independent industrial disclosure arrow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._popup_open = False
        self.setProperty("industrialDisclosure", True)

    def disclosure_rect(self) -> QRect:
        return QRect(max(0, self.width() - 28), 0, min(28, self.width()), self.height())

    def showPopup(self) -> None:
        self._popup_open = True
        self.update(self.disclosure_rect())
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        self.update(self.disclosure_rect())

    def paintEvent(self, event: QEvent) -> None:
        super().paintEvent(event)
        area = self.disclosure_rect()
        center_x = area.center().x()
        center_y = area.center().y()
        color = QColor("#66666A") if not self.isEnabled() else QColor("#FFE600" if self.hasFocus() or self.underMouse() else "#F5F5F2")
        direction = -1 if self._popup_open else 1
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        if direction > 0:
            points = [QPointF(center_x - 5, center_y - 2), QPointF(center_x + 5, center_y - 2), QPointF(center_x, center_y + 4)]
        else:
            points = [QPointF(center_x - 5, center_y + 2), QPointF(center_x + 5, center_y + 2), QPointF(center_x, center_y - 4)]
        painter.drawPolygon(QPolygonF(points))
SURFACE = QColor("#1A1C20")
HAIRLINE = QColor("#2E323A")


def _draw_cross_grid(painter: QPainter, width: int, height: int, step: int = 16) -> None:
    """Draw a quiet, original calibration grid without using external assets."""
    painter.setPen(QPen(QColor("#292D34"), 1))
    for y in range(8, height, step):
        for x in range(8, width, step):
            painter.drawLine(x - 1, y, x + 1, y)
            painter.drawLine(x, y - 1, x, y + 1)


class StageCanvas(QWidget):
    """Cold-gray application stage with a restrained 16 px cross grid."""

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), GROUND)
        _draw_cross_grid(painter, self.width(), self.height())


class IndustrialPanel(QWidget):
    """Flat technical surface with measured corner brackets.

    The optional oversized section code is disabled for operational panels:
    their header badges already own that information, while action buttons
    need an uncluttered hit area.
    """

    def __init__(
        self,
        section_code: str,
        parent: QWidget | None = None,
        *,
        show_section_watermark: bool = False,
    ) -> None:
        super().__init__(parent)
        self.section_code = section_code
        self.show_section_watermark = show_section_watermark
        self.setAccessibleDescription(f"工作区 {section_code}")

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), SURFACE)
        _draw_cross_grid(painter, self.width(), self.height())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(HAIRLINE, 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QPen(QColor("#6B707A"), 1))
        length = 8
        right = self.width() - 1
        bottom = self.height() - 1
        for x, sx in ((0, 1), (right, -1)):
            painter.drawLine(x, 0, x + sx * length, 0)
            painter.drawLine(x, bottom, x + sx * length, bottom)
        for y, sy in ((0, 1), (bottom, -1)):
            painter.drawLine(0, y, 0, y + sy * length)
            painter.drawLine(right, y, right, y + sy * length)
        if not self.show_section_watermark:
            return
        painter.setPen(QColor("#2B2F36"))
        font = QFont("Impact", 44)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(max(0, self.width() - 150), 2, 132, 54),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self.section_code,
        )


class CutBadge(QWidget):
    """Large tabular identifier painted as an original slanted label."""

    def __init__(self, text: str = "SYS.PROC // 01", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self.setFixedSize(164, 34)
        self.setAccessibleName(f"当前步骤 {text}")

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.setAccessibleName(f"当前步骤 {text}")
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#090A0C"))
        rect = self.rect().adjusted(5, 4, -5, -4)
        cut = 7
        polygon = QPolygonF([
            QPointF(cut, rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right() - cut, rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SIGNAL_YELLOW)
        painter.drawPolygon(polygon)
        painter.setPen(INK_BLACK)
        font = QFont("Consolas", 9)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.7)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class StepSwitch(QPushButton):
    """High-contrast switch whose checked state is visible without OS chrome."""

    def __init__(
        self,
        checked: bool = True,
        on_text: str = "■  ENABLED",
        off_text: str = "□  DISABLED",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_text = on_text
        self.off_text = off_text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(156, 38)
        self.setChecked(checked)
        self.toggled.connect(self._sync_text)
        self._sync_text(checked)

    def sizeHint(self) -> QSize:
        return QSize(156, 38)

    def _sync_text(self, checked: bool) -> None:
        text = self.on_text if checked else self.off_text
        self.setText(text)
        self.setAccessibleName(text)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        polygon = QPolygonF([rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()])
        checked = self.isChecked()
        enabled = self.isEnabled()
        fill = QColor("#0C0D10") if checked else QColor("#202329")
        border = SIGNAL_YELLOW if checked else PAPER_WHITE
        foreground = SIGNAL_YELLOW if checked else QColor("#8B909A")
        if not enabled:
            fill, border, foreground = QColor("#171717"), QColor("#444444"), QColor("#727272")
        elif self.underMouse() and not checked:
            fill = QColor("#242424")
            border = SIGNAL_YELLOW
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawPolygon(polygon)
        painter.setPen(foreground)
        font = QFont("Consolas", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus():
            painter.setPen(QPen(SIGNAL_YELLOW, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)


class IndustrialCheckBox(QCheckBox):
    """Flat checkbox with a dark housing and a compact yellow state pixel."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box_size = 18
        box = QRectF(1, (self.height() - box_size) / 2, box_size, box_size)
        border = SIGNAL_YELLOW if self.underMouse() or self.hasFocus() else QColor("#3A3F4D")
        foreground = QColor("#C5C8D0") if self.isEnabled() else QColor("#686D77")
        painter.setPen(QPen(border, 1))
        painter.setBrush(QColor("#15171B"))
        painter.drawRect(box)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(SIGNAL_YELLOW if self.isEnabled() else QColor("#686D77"))
            painter.drawRect(QRectF(box.left() + 5, box.top() + 5, 8, 8))
        painter.setPen(foreground)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(29, 0, max(0, self.width() - 29), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )


class PixelStatusButton(QPushButton):
    """Compact step state with a real enabled/disabled pixel indicator."""

    def __init__(self, checked: bool = True, parent: QWidget | None = None, *, breakpoint: bool = False) -> None:
        super().__init__(parent)
        self.breakpoint = bool(breakpoint)
        self.runtime_status: str | None = None
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(78, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._sync_text)
        self._sync_text(checked)

    def _sync_text(self, checked: bool) -> None:
        text = "[FAILED]" if self.runtime_status == "failed" else ("[READY]" if checked else "[OFF]")
        self.setText(text)
        if self.runtime_status == "failed":
            accessible = "步骤执行失败"
        elif self.breakpoint and checked:
            accessible = "步骤已启用并设置断点"
        else:
            accessible = "步骤已启用" if checked else "步骤已停用"
        self.setAccessibleName(accessible)
        self.update()

    def set_runtime_status(self, status: str | None) -> None:
        self.runtime_status = status
        self._sync_text(self.isChecked())

    def indicator_color(self) -> QColor:
        if self.runtime_status == "failed" or (self.breakpoint and self.isChecked()):
            return QColor("#FF3B4D")
        return QColor("#00D98B") if self.isChecked() else QColor("#5A606B")

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1D2025"))
        checked = self.isChecked()
        dot = self.indicator_color()
        text = QColor("#FF737F") if self.runtime_status == "failed" else (QColor("#C5C8D0") if checked else QColor("#7C818B"))
        painter.fillRect(7, (self.height() - 4) // 2, 4, 4, dot)
        painter.setPen(text)
        font = QFont("Consolas", 8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(15, 0, self.width() - 17, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.underMouse() or self.hasFocus():
            painter.setPen(QPen(SIGNAL_YELLOW, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class FocusPixelFilter(QObject):
    """Adds the requested 3 px focus locator to native editor widgets."""

    EDITOR_TYPES = (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit)

    def __init__(self, root: QWidget) -> None:
        super().__init__(root)
        self.markers: dict[QWidget, QWidget] = {}
        for editor_type in self.EDITOR_TYPES:
            for editor in root.findChildren(editor_type):
                if editor in self.markers:
                    continue
                marker = QWidget(editor)
                marker.setObjectName("focusPixel")
                marker.setFixedSize(3, 3)
                marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                marker.hide()
                editor.installEventFilter(self)
                self.markers[editor] = marker
                self._place(editor, marker)

    @staticmethod
    def _place(editor: QWidget, marker: QWidget) -> None:
        marker.move(max(0, editor.width() - 4), max(0, editor.height() - 4))
        marker.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        marker = self.markers.get(watched)  # type: ignore[arg-type]
        if marker is not None:
            if event.type() == QEvent.Type.FocusIn:
                self._place(watched, marker)  # type: ignore[arg-type]
                marker.show()
            elif event.type() == QEvent.Type.FocusOut:
                marker.hide()
            elif event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
                self._place(watched, marker)  # type: ignore[arg-type]
        return super().eventFilter(watched, event)


class CutActionButton(QPushButton):
    """Primary action with a directional right-hand wedge."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("cutActionButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(120, 38)
        self.setAccessibleName(text)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        cut = 13.0
        polygon = QPolygonF([
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right() - cut, rect.top()),
            QPointF(rect.right(), rect.center().y()),
            QPointF(rect.right() - cut, rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ])
        enabled = self.isEnabled()
        fill = SIGNAL_YELLOW if enabled else QColor("#202020")
        if enabled and self.underMouse():
            fill = QColor("#FFF04A")
        painter.setPen(QPen(fill if enabled else QColor("#4A4A4A"), 1.5))
        painter.setBrush(fill)
        painter.drawPolygon(polygon)
        painter.setPen(INK_BLACK if enabled else QColor("#777777"))
        font = QFont("Arial Narrow", 11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(8, 0, -cut, 0), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus():
            painter.setPen(QPen(PAPER_WHITE, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(polygon)


class CutOutlineButton(QPushButton):
    """Secondary outlined action with a clipped upper-right corner."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setAccessibleName(text)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        cut = 7.0
        polygon = QPolygonF([
            rect.topLeft(),
            QPointF(rect.right() - cut, rect.top()),
            QPointF(rect.right(), rect.top() + cut),
            rect.bottomRight(),
            rect.bottomLeft(),
        ])
        border = SIGNAL_YELLOW if self.hasFocus() else PAPER_WHITE
        fill = QColor("#1F2228") if self.underMouse() else QColor("#0D0F12")
        if not self.isEnabled():
            border, fill = QColor("#454A54"), QColor("#191B20")
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawPolygon(polygon)
        painter.setPen(PAPER_WHITE if self.isEnabled() else QColor("#686D77"))
        font = QFont("Microsoft YaHei UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(9, 0, -9, 0), Qt.AlignmentFlag.AlignCenter, self.text())


class FieldStrip(QWidget):
    """Actual step position on a calibrated rail, not completion percentage."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.position = 0.0
        self.label = "就绪 · 尚未运行"
        self.reduced_motion = False
        self.animation = QPropertyAnimation(self, b"positionValue", self)
        self.animation.setDuration(220)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setAccessibleName("流程运行状态与步骤位置")

    def get_position(self):
        return self.position

    def set_position(self, value):
        self.position = value
        self.update()

    positionValue = Property(float, get_position, set_position)

    def report(self, text, position=None):
        self.label = text
        self.setAccessibleDescription(text)
        if position is not None:
            self.animation.stop()
            if self.reduced_motion:
                self.set_position(position)
            else:
                self.animation.setStartValue(self.position)
                self.animation.setEndValue(position)
                self.animation.start()
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0B0C0E"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SIGNAL_YELLOW)
        for x in range(-6, self.width(), 16):
            painter.drawPolygon(QPolygonF([
                QPointF(x + 3, 0), QPointF(x + 11, 0),
                QPointF(x + 8, 3), QPointF(x, 3),
            ]))
        painter.setPen(QColor("#3D424B"))
        for x in range(0, self.width(), 24):
            painter.drawLine(x, 23, x, 29)
        painter.setPen(QPen(SIGNAL_YELLOW, 2))
        painter.drawLine(0, 29, int(self.width() * self.position), 29)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SIGNAL_YELLOW)
        painter.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(9, 0), QPointF(0, 9)]))
        painter.setPen(PAPER_WHITE)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(14, 19, self.label)
