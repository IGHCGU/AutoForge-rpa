from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal, QPropertyAnimation
from PySide6.QtGui import QAction, QColor, QCloseEvent, QCursor, QDesktopServices, QIcon, QKeySequence, QPixmap, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QTabWidget,
    QGraphicsOpacityEffect,
    QSizePolicy,
)

from . import __version__
from .engine import (
    AutomationRunner,
    BLOCK_END_TYPES,
    BLOCK_PAIRS,
    Match,
    RunPlan,
    StopRequested,
    VisionEngine,
    build_block_map,
    normalize_run_span,
    parse_region,
    parse_scales,
    preflight_workflow,
)
from .history import RunHistoryStore, RunRecord
from .theme import studio_style
from .workbench import (
    CutActionButton,
    CutBadge,
    FieldStrip,
    FocusPixelFilter,
    IndustrialCheckBox,
    IndustrialComboBox,
    IndustrialPanel,
    PixelStatusButton,
    StageCanvas,
    StepSwitch,
)
from .models import DEFAULT_PARAMS, STEP_LABELS, Step, Workflow
from .recorder import GlobalStopHotkey, InputRecorder, RecordedAction, compact_recorded_actions, recorded_actions_to_steps
from .storage import WorkflowDocument, load_document, save_document
from .window_target import TargetTransform, WindowService, WindowTargetError, resolve_target


STATUS_COLORS = {
    "running": (QColor("#FFE600"), QColor("#000000")),
    "paused": (QColor("#F5F5F2"), QColor("#000000")),
    "done": (QColor("#075F3B"), QColor("#FFFFFF")),
    "failed": (QColor("#711F26"), QColor("#FFFFFF")),
    "skipped": (QColor("#242428"), QColor("#B8B8BC")),
}

STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 20
HISTORY_RECORD_ROLE = int(Qt.ItemDataRole.UserRole) + 21

KEY_INPUT_HELP = """输入格式
组合键请用 + 连接，例如：ctrl+s、ctrl+shift+esc、alt+f4、win+r。
单个按键直接填写按键名称，例如：enter。输入时不需要引号。

可用按键名称
字母键：a, b, c, ..., z
数字键：0, 1, 2, ..., 9
功能键：f1, f2, ..., f12
箭头键：left, right, up, down
控制键：ctrl, alt, shift, win
其他键：enter, space, backspace, tab, esc, delete, home, end, pageup, pagedown

空格键请输入：space
macOS 的 Command 键名称为 command；本工具当前主要面向 Windows，请使用 win 表示 Windows 键。"""


def automation_cursor_position(fallback: tuple[int, int]) -> tuple[int, int]:
    """Return coordinates in the same coordinate system used for playback."""
    try:
        import pyautogui

        cursor = pyautogui.position()
        return int(cursor.x), int(cursor.y)
    except Exception:
        return fallback


def step_summary(step: Step) -> str:
    p = step.params
    if step.type == "run_subflow":
        return Path(str(p.get("subflow", ""))).name or "请导入 .kmflow 子流程"
    if step.type in {"click_image", "wait_image", "wait_image_gone"}:
        return Path(str(p.get("image", ""))).name or "未选择图片"
    if step.type == "drag_image":
        return f"{Path(str(p.get('image', ''))).name} → {Path(str(p.get('target_image', ''))).name}"
    if step.type == "drag_image_to_position":
        return f"{Path(str(p.get('image', ''))).name or '未选择图片'} → ({p.get('x2', 0)}, {p.get('y2', 0)})"
    if step.type == "drag_position_to_image":
        return f"({p.get('x', 0)}, {p.get('y', 0)}) → {Path(str(p.get('target_image', ''))).name or '未选择图片'}"
    if step.type in {"click_text", "wait_text", "wait_text_gone", "type_text"}:
        text = str(p.get("text", "")).replace("\n", " ")
        return text[:45] or "未填写文字"
    if step.type == "click_position":
        return f"({p.get('x', 0)}, {p.get('y', 0)})"
    if step.type == "drag_position":
        return f"({p.get('x', 0)}, {p.get('y', 0)}) → ({p.get('x2', 0)}, {p.get('y2', 0)})"
    if step.type in {"hotkey", "press_key"}:
        return str(p.get("keys", ""))
    if step.type == "scroll":
        return str(p.get("amount", ""))
    if step.type == "wait":
        return f"{p.get('seconds', 1)} 秒"
    if step.type == "set_variable":
        operations = {"set": "设为", "add": "增加", "subtract": "减少"}
        return f"{p.get('variable', '')} {operations.get(str(p.get('variable_operation')), '设为')} {p.get('value', '')}"
    if step.type == "if_variable":
        operators = {
            "equals": "等于",
            "not_equals": "不等于",
            "contains": "包含",
            "not_contains": "不包含",
            "greater": ">",
            "greater_equal": "≥",
            "less": "<",
            "less_equal": "≤",
            "not_empty": "不为空",
            "is_empty": "为空",
        }
        return f"{p.get('variable', '')} {operators.get(str(p.get('operator')), '')} {p.get('value', '')}".strip()
    if step.type == "if_image":
        state = "存在" if p.get("condition_state", "present") == "present" else "不存在"
        return f"{Path(str(p.get('image', ''))).name or '未选择图片'} {state}"
    if step.type == "if_text":
        state = "存在" if p.get("condition_state", "present") == "present" else "不存在"
        text = str(p.get("text", "")).replace("\n", " ")[:36]
        return f"“{text or '未填写文字'}” {state}"
    if step.type == "if_else":
        return "条件不成立时执行下面的步骤"
    if step.type == "loop_start":
        index_text = f"，序号写入 {p.get('index_variable')}" if p.get("index_variable") else ""
        return f"{p.get('loop_count', 1)} 次{index_text}"
    if step.type in {"if_end", "loop_end"}:
        return "结束当前块"
    return ""


def workflow_step_depths(steps: list[Step]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for step in steps:
        if step.type in {"if_end", "loop_end"}:
            depth = max(0, depth - 1)
        elif step.type == "if_else":
            depth = max(0, depth - 1)
        depths.append(depth)
        if step.type in {"if_variable", "if_image", "if_text", "loop_start", "if_else"}:
            depth += 1
    return depths


def workflow_tree_prefixes(steps: list[Step]) -> list[str]:
    """Return compact XMind-like branch connectors for the workflow table."""
    depths = workflow_step_depths(steps)
    starts = {"if_variable", "if_image", "if_text", "loop_start"}
    ends = {"if_end", "loop_end"}
    prefixes: list[str] = []
    for step, depth in zip(steps, depths):
        if step.type in starts:
            connector = "│   " * max(0, depth - 1) + ("├─" if depth else "")
            prefixes.append(f"{connector}◆ ")
        elif step.type == "if_else":
            prefixes.append(f"{'│   ' * depth}├─◇ ")
        elif step.type in ends:
            prefixes.append(f"{'│   ' * depth}└─ ")
        elif depth:
            prefixes.append(f"{'│   ' * max(0, depth - 1)}├─ ")
        else:
            prefixes.append("")
    return prefixes


def new_steps_for_type(step_type: str) -> list[Step]:
    if step_type == "loop_start":
        return [Step("loop_start"), Step("loop_end")]
    if step_type in {"if_variable", "if_image", "if_text"}:
        start = Step(step_type)
        if step_type in {"if_image", "if_text"}:
            start.timeout = 1.0
        return [start, Step("if_end")]
    return [Step(step_type)]


def control_block_span(steps: list[Step], row: int) -> tuple[int, int]:
    if not 0 <= row < len(steps):
        return row, row
    try:
        start_to_end, end_to_start, _start_to_else, else_to_start = build_block_map(steps)
    except Exception:
        return row, row
    if row in start_to_end:
        return row, start_to_end[row]
    if row in end_to_start:
        start = end_to_start[row]
        return start, row
    if row in else_to_start:
        start = else_to_start[row]
        return start, start_to_end[start]
    return row, row


def containing_block_start(steps: list[Step], row: int) -> int | None:
    try:
        start_to_end, _end_to_start, _start_to_else, _else_to_start = build_block_map(steps)
    except Exception:
        return None
    candidates = [start for start, end in start_to_end.items() if start <= row <= end]
    return max(candidates) if candidates else None


class RunnerThread(QThread):
    log_message = Signal(str, str)
    step_status = Signal(int, str)
    debug_paused = Signal(int)
    run_ended = Signal(str)

    def __init__(self, document: WorkflowDocument, failure_dir: Path, plan: RunPlan | None = None) -> None:
        super().__init__()
        self.workflow_steps = document.workflow.steps
        self.failure_dir = failure_dir
        self.failure_screenshot: Path | None = None
        self.failure_step = -1
        self.last_error = ""
        self.plan = plan or RunPlan()
        self.runner = AutomationRunner(
            document.workflow,
            document.asset_dir,
            lambda level, message: self.log_message.emit(level, message),
            lambda index, status: self.step_status.emit(index, status),
            lambda index: self.debug_paused.emit(index),
            self._capture_failure,
            plan=self.plan,
        )

    def _capture_failure(self, index: int, _step: Step, error: Exception) -> None:
        self.failure_step = index
        self.last_error = str(error)
        if self.failure_screenshot is not None:
            return
        frame = self.runner.vision.capture()
        cv2, _np = self.runner.vision._imports()
        self.failure_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target = self.failure_dir / f"failure_step_{index + 1}_{stamp}.png"
        success, encoded = cv2.imencode(".png", frame)
        if not success:
            raise RuntimeError("无法编码失败截图")
        encoded.tofile(target)
        self.failure_screenshot = target
        self.log_message.emit("warning", f"已保存失败现场：{target}")

    def run(self) -> None:
        try:
            self.runner.run()
        except StopRequested:
            self.run_ended.emit("stopped")
        except Exception as exc:
            self.last_error = str(exc)
            index = self.runner.current_index
            if self.failure_screenshot is None and 0 <= index < len(self.workflow_steps):
                try:
                    self._capture_failure(index, self.workflow_steps[index], exc)
                except Exception as capture_error:
                    self.log_message.emit("warning", f"无法保存失败现场：{capture_error}")
            self.log_message.emit("error", str(exc))
            self.log_message.emit("debug", traceback.format_exc())
            self.run_ended.emit("failed")
        else:
            self.run_ended.emit("done")

    def request_stop(self) -> None:
        self.runner.stop()

    def request_pause(self) -> None:
        self.runner.request_pause()

    def resume_workflow(self) -> None:
        self.runner.resume()

    def step_once(self) -> None:
        self.runner.step_once()


class StepTable(QTableWidget):
    rows_moved = Signal(int, int)

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        # Selection remains readable over execution colors and gains a strong,
        # non-color-only edge marker for multi-row selections.
        painter = QPainter(self.viewport())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFE600"))
        for index in self.selectionModel().selectedRows():
            rect = self.visualRect(self.model().index(index.row(), 0))
            if rect.isValid():
                painter.drawRect(0, rect.top(), 3, rect.height())
                painter.drawPolygon(QPolygon([
                    QPoint(self.viewport().width() - 9, rect.top()),
                    QPoint(self.viewport().width(), rect.top()),
                    QPoint(self.viewport().width(), rect.top() + 9),
                ]))
        # Qt's stylesheet selection/alternating-row painting can mask item
        # background roles. Draw failed execution state last so it remains
        # unmistakable after the editor returns to the foreground.
        for row in range(self.rowCount()):
            item = self.item(row, 1)
            if item is None or item.data(STATUS_ROLE) != "failed":
                continue
            rect = self.visualRect(self.model().index(row, 0))
            if not rect.isValid():
                continue
            painter.fillRect(QRect(0, rect.top(), self.viewport().width(), rect.height()), QColor(113, 31, 38, 138))
            painter.fillRect(QRect(0, rect.top(), 4, rect.height()), QColor("#FF3B4D"))
        painter.end()

    def dropEvent(self, event: Any) -> None:
        source = self.currentRow()
        index = self.indexAt(event.position().toPoint())
        if source < 0:
            event.ignore()
            return
        if index.isValid():
            target = index.row()
            if event.position().y() > self.visualRect(index).center().y():
                target += 1
        else:
            target = self.rowCount()
        if target > source:
            target -= 1
        target = max(0, min(target, self.rowCount() - 1))
        if target != source:
            self.rows_moved.emit(source, target)
        # The workflow model has already moved the step. Ignoring the built-in
        # table drop prevents Qt from deleting the source row a second time.
        event.ignore()


class CropCanvas(QWidget):
    selection_changed = Signal()

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source = pixmap
        fit_scale = min(900 / max(1, pixmap.width()), 600 / max(1, pixmap.height()))
        self.scale = min(4.0, fit_scale) if fit_scale >= 1 else fit_scale
        self.display_size = QSize(
            max(1, round(pixmap.width() * self.scale)),
            max(1, round(pixmap.height() * self.scale)),
        )
        self.selection = QRect(QPoint(0, 0), self.display_size)
        self.drag_origin: QPoint | None = None
        self.setFixedSize(self.display_size)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _bounded_point(self, point: QPoint) -> QPoint:
        return QPoint(
            min(max(0, point.x()), self.width() - 1),
            min(max(0, point.y()), self.height() - 1),
        )

    def source_rect(self) -> QRect:
        rect = self.selection.normalized()
        x = max(0, round(rect.x() / self.scale))
        y = max(0, round(rect.y() / self.scale))
        width = min(self.source.width() - x, max(1, round(rect.width() / self.scale)))
        height = min(self.source.height() - y, max(1, round(rect.height() / self.scale)))
        return QRect(x, y, width, height)

    def reset_selection(self) -> None:
        self.selection = QRect(QPoint(0, 0), self.display_size)
        self.update()
        self.selection_changed.emit()

    def paintEvent(self, event: Any) -> None:
        from PySide6.QtGui import QPainter, QPen

        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.source)
        selected = self.selection.normalized()
        overlay = QColor(0, 0, 0, 125)
        painter.fillRect(QRect(0, 0, self.width(), selected.top()), overlay)
        painter.fillRect(QRect(0, selected.bottom() + 1, self.width(), self.height() - selected.bottom() - 1), overlay)
        painter.fillRect(QRect(0, selected.top(), selected.left(), selected.height()), overlay)
        painter.fillRect(
            QRect(selected.right() + 1, selected.top(), self.width() - selected.right() - 1, selected.height()),
            overlay,
        )
        painter.setPen(QPen(QColor("#42e57b"), 2))
        painter.drawRect(selected.adjusted(1, 1, -1, -1))

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.drag_origin = self._bounded_point(event.position().toPoint())
        self.selection = QRect(self.drag_origin, self.drag_origin)
        self.update()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.drag_origin is None:
            return
        self.selection = QRect(self.drag_origin, self._bounded_point(event.position().toPoint())).normalized()
        self.update()
        self.selection_changed.emit()

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.drag_origin is None:
            return
        self.selection = QRect(self.drag_origin, self._bounded_point(event.position().toPoint())).normalized()
        self.drag_origin = None
        self.update()
        self.selection_changed.emit()


class CropImageDialog(QDialog):
    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("裁剪图片素材")
        self.resize(940, 720)
        layout = QVBoxLayout(self)
        hint = QLabel("在图片上按住左键框选需要识别的部分。裁得越贴近稳定特征，移动后的识别通常越准确。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.canvas = CropCanvas(pixmap)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        self.size_label = QLabel()
        reset = QPushButton("恢复整张图片")
        reset.clicked.connect(self.canvas.reset_selection)
        bottom.addWidget(self.size_label)
        bottom.addStretch(1)
        bottom.addWidget(reset)
        layout.addLayout(bottom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存为新素材")
        buttons.accepted.connect(self._accept_crop)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.canvas.selection_changed.connect(self._update_size)
        self._update_size()

    def _update_size(self) -> None:
        rect = self.canvas.source_rect()
        self.size_label.setText(f"裁剪范围：X={rect.x()}，Y={rect.y()}，{rect.width()}×{rect.height()}")

    def _accept_crop(self) -> None:
        rect = self.canvas.source_rect()
        if rect.width() < 4 or rect.height() < 4:
            QMessageBox.warning(self, "裁剪范围过小", "裁剪区域的宽和高至少需要 4 像素。")
            return
        self.accept()


class ImageMatchResultDialog(QDialog):
    def __init__(
        self,
        pixmap: QPixmap,
        message: str,
        success: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("图片识别测试结果")
        self.resize(1040, 760)
        layout = QVBoxLayout(self)
        status = QLabel(message)
        status.setWordWrap(True)
        status.setStyleSheet(
            "padding: 10px; border-radius: 5px; font-weight: 600; "
            + ("background: #d8f5e2; color: #116a35;" if success else "background: #ffe1e1; color: #8b1e1e;")
        )
        layout.addWidget(status)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setPixmap(
            pixmap.scaled(
                980,
                650,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(image)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ScreenSnipper(QWidget):
    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setWindowOpacity(1.0)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("未找到可截图的屏幕")
        self.screen = screen
        self.background = screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.rubber = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.origin = None

    def paintEvent(self, event: Any) -> None:
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 85))

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.rubber.setGeometry(self.origin.x(), self.origin.y(), 1, 1)
            self.rubber.show()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.origin is not None:
            from PySide6.QtCore import QRect

            self.rubber.setGeometry(QRect(self.origin, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        rect = self.rubber.geometry().normalized()
        if rect.width() >= 4 and rect.height() >= 4:
            ratio = self.background.devicePixelRatio()
            pixel_rect = rect.adjusted(0, 0, 0, 0)
            pixel_rect.setRect(
                round(rect.x() * ratio),
                round(rect.y() * ratio),
                round(rect.width() * ratio),
                round(rect.height() * ratio),
            )
            result = self.background.copy(pixel_rect)
            result.setDevicePixelRatio(1.0)
            self.captured.emit(result)
        else:
            self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()


class PositionPicker(QWidget):
    picked = Signal(int, int)
    cancelled = Signal()

    def __init__(self, prompt: str) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("未找到可取坐标的屏幕")
        self.screen_geometry = screen.geometry()
        self.background = screen.grabWindow(0)
        self.prompt = prompt
        self.cursor_point = None
        self.setMouseTracking(True)
        self.setGeometry(self.screen_geometry)

    def paintEvent(self, event: Any) -> None:
        from PySide6.QtGui import QFont, QPainter, QPen

        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 55))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 13, 600))
        painter.fillRect(18, 18, 520, 48, QColor(15, 18, 23, 210))
        painter.drawText(32, 49, f"{self.prompt}（Esc 取消）")
        if self.cursor_point is not None:
            x = self.cursor_point.x()
            y = self.cursor_point.y()
            painter.setPen(QPen(QColor("#4ee58a"), 1))
            painter.drawLine(x - 18, y, x + 18, y)
            painter.drawLine(x, y - 18, x, y + 18)
            global_x = self.screen_geometry.x() + x
            global_y = self.screen_geometry.y() + y
            painter.fillRect(x + 15, y + 15, 150, 30, QColor(15, 18, 23, 220))
            painter.setPen(QColor("white"))
            painter.drawText(x + 24, y + 37, f"X={global_x}  Y={global_y}")

    def mouseMoveEvent(self, event: Any) -> None:
        self.cursor_point = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        fallback = (self.screen_geometry.x() + point.x(), self.screen_geometry.y() + point.y())
        position = automation_cursor_position(fallback)
        self.picked.emit(*position)
        self.close()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()


class RegionPicker(QWidget):
    selected = Signal(int, int, int, int)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("未找到可框选的屏幕")
        self.screen_geometry = screen.geometry()
        self.background = screen.grabWindow(0)
        self.rubber = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.logical_origin = None
        self.input_origin: tuple[int, int] | None = None
        self.setGeometry(self.screen_geometry)

    def paintEvent(self, event: Any) -> None:
        from PySide6.QtGui import QFont, QPainter

        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 13, 600))
        painter.fillRect(18, 18, 570, 48, QColor(15, 18, 23, 215))
        painter.drawText(32, 49, "按住左键框选识别区域（Esc 取消）")

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.logical_origin = event.position().toPoint()
        fallback = (
            self.screen_geometry.x() + self.logical_origin.x(),
            self.screen_geometry.y() + self.logical_origin.y(),
        )
        self.input_origin = automation_cursor_position(fallback)
        self.rubber.setGeometry(self.logical_origin.x(), self.logical_origin.y(), 1, 1)
        self.rubber.show()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.logical_origin is not None:
            from PySide6.QtCore import QRect

            self.rubber.setGeometry(QRect(self.logical_origin, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.input_origin is None:
            return
        point = event.position().toPoint()
        fallback = (self.screen_geometry.x() + point.x(), self.screen_geometry.y() + point.y())
        end = automation_cursor_position(fallback)
        x1, y1 = self.input_origin
        x2, y2 = end
        x, y = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        if width >= 4 and height >= 4:
            self.selected.emit(x, y, width, height)
        else:
            self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()


class VariableEditorDialog(QDialog):
    def __init__(self, variables: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("流程初始变量")
        self.resize(620, 480)
        self.result_variables = dict(variables)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "这里声明每次运行开始时载入的初始值，类似程序开头的 let x = 初始值；"
            "“运行时设置变量”步骤则相当于流程执行到该处时进行 x = 新值。两者不是 var 与 let 的作用域区别。\n"
            "变量随流程保存，可在输入文字、变量赋值和条件比较值中使用 ${变量名}；"
            "循环的“序号变量”会在运行时自动写入 1、2、3……"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["变量名", "初始值"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table, 1)
        for name, value in variables.items():
            self._append_row(str(name), str(value))

        tools = QHBoxLayout()
        add = QPushButton("添加变量")
        remove = QPushButton("删除选中")
        add.clicked.connect(self._add_variable)
        remove.clicked.connect(self._remove_selected)
        tools.addWidget(add)
        tools.addWidget(remove)
        tools.addStretch(1)
        layout.addLayout(tools)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存变量")
        buttons.accepted.connect(self._accept_variables)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _append_row(self, name: str, value: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))

    def _add_variable(self) -> None:
        existing = {self.table.item(row, 0).text() for row in range(self.table.rowCount()) if self.table.item(row, 0)}
        number = 1
        while f"变量{number}" in existing:
            number += 1
        self._append_row(f"变量{number}", "")
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.currentItem())

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def _accept_variables(self) -> None:
        result: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            value = value_item.text() if value_item else ""
            if not name:
                QMessageBox.warning(self, "变量名无效", f"第 {row + 1} 行的变量名不能为空。")
                return
            if any(character in name for character in "${}"):
                QMessageBox.warning(self, "变量名无效", "变量名本身不能包含 $、{ 或 }。")
                return
            if name in result:
                QMessageBox.warning(self, "变量名重复", f"变量“{name}”出现了多次。")
                return
            result[name] = value
        self.result_variables = result
        self.accept()


class RunSettingsDialog(QDialog):
    def __init__(
        self,
        repeat_count: int,
        repeat_delay: float,
        input_backend: str = "pyautogui",
        parent: QWidget | None = None,
        *,
        settings: dict[str, Any] | None = None,
        window_service: WindowService | None = None,
    ) -> None:
        super().__init__(parent)
        settings = settings or {}
        self.window_service = window_service or WindowService()
        self.available_windows = []
        self.setWindowTitle("运行设置")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        hint = QLabel("无需复制步骤：从第一步到最后一步执行完算一轮，运行器会自动重复整个流程。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.input_backend = IndustrialComboBox()
        self.input_backend.addItem("兼容模式 · PyAutoGUI", "pyautogui")
        self.input_backend.addItem("Windows 原生 · SendInput", "sendinput")
        self.input_backend.setCurrentIndex(max(0, self.input_backend.findData(input_backend)))
        form.addRow("输入后端", self.input_backend)
        self.repeat_count = QSpinBox()
        self.repeat_count.setRange(1, 100000)
        self.repeat_count.setValue(max(1, repeat_count))
        self.repeat_count.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addRow("运行次数", self._number_control(self.repeat_count))

        self.repeat_delay = QDoubleSpinBox()
        self.repeat_delay.setRange(0, 86400)
        self.repeat_delay.setDecimals(2)
        self.repeat_delay.setSingleStep(0.5)
        self.repeat_delay.setValue(max(0.0, repeat_delay))
        self.repeat_delay.setSuffix(" 秒")
        self.repeat_delay.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        form.addRow("每轮间隔", self._number_control(self.repeat_delay))

        self.coordinate_mode = IndustrialComboBox()
        self.coordinate_mode.addItem("屏幕绝对坐标", "screen")
        self.coordinate_mode.addItem("目标窗口相对坐标（自动适配尺寸）", "window")
        self.coordinate_mode.setCurrentIndex(max(0, self.coordinate_mode.findData(settings.get("coordinate_mode", "screen"))))
        form.addRow("坐标模式", self.coordinate_mode)

        target_row = QWidget()
        target_layout = QHBoxLayout(target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        self.target_window_title = IndustrialComboBox()
        self.target_window_title.setEditable(True)
        self.target_window_title.lineEdit().setPlaceholderText("输入完整标题或标题中的稳定文字")
        refresh_windows = QPushButton("刷新窗口")
        refresh_windows.clicked.connect(self._refresh_windows)
        target_layout.addWidget(self.target_window_title, 1)
        target_layout.addWidget(refresh_windows)
        form.addRow("目标窗口", target_row)

        base_row = QWidget()
        base_layout = QHBoxLayout(base_row)
        base_layout.setContentsMargins(0, 0, 0, 0)
        self.target_base_width = QSpinBox()
        self.target_base_width.setRange(0, 20000)
        self.target_base_width.setValue(int(settings.get("target_window_base_width", 0)))
        self.target_base_width.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.target_base_height = QSpinBox()
        self.target_base_height.setRange(0, 20000)
        self.target_base_height.setValue(int(settings.get("target_window_base_height", 0)))
        self.target_base_height.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        base_layout.addWidget(QLabel("宽"))
        base_layout.addWidget(self.target_base_width, 1)
        base_layout.addWidget(QLabel("高"))
        base_layout.addWidget(self.target_base_height, 1)
        form.addRow("录制时客户区", base_row)

        self.target_activate = IndustrialCheckBox("运行前恢复并激活目标窗口")
        self.target_activate.setChecked(bool(settings.get("target_window_activate", True)))
        form.addRow("窗口激活", self.target_activate)
        self.target_wait = QDoubleSpinBox()
        self.target_wait.setRange(0, 300)
        self.target_wait.setDecimals(1)
        self.target_wait.setValue(float(settings.get("target_window_wait", 10.0)))
        self.target_wait.setSuffix(" 秒")
        self.target_wait.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        form.addRow("等待窗口", self._number_control(self.target_wait))
        layout.addLayout(form)

        note = QLabel("例如设置为 10 次、间隔 2 秒：完整流程运行 10 轮，每轮结束后等待 2 秒。")
        note.setWordWrap(True)
        layout.addWidget(note)
        backend_note = QLabel(
            "SendInput 可直接发送鼠标、滚轮、组合键和 Unicode 文字，适合 Windows 前台程序及远程桌面窗口。"
            "目标程序若以管理员身份运行，AutoForge 也需要以管理员身份启动。兼容性有问题时切回 PyAutoGUI。"
        )
        backend_note.setWordWrap(True)
        layout.addWidget(backend_note)
        target_note = QLabel(
            "窗口相对模式会把坐标和识别区域限制在目标窗口客户区，并按录制时宽高自动缩放。"
            "远程桌面内部控件仍使用图片/OCR/坐标定位。宽高填 0 表示只跟随窗口位置，不缩放。"
        )
        target_note.setWordWrap(True)
        layout.addWidget(target_note)
        test_row = QHBoxLayout()
        self.backend_test = QLineEdit()
        self.backend_test.setPlaceholderText("点击右侧按钮，验证原生中文输入")
        test_button = QPushButton("测试 SendInput")
        test_button.clicked.connect(self._test_sendinput)
        test_row.addWidget(self.backend_test, 1)
        test_row.addWidget(test_button)
        layout.addLayout(test_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.coordinate_mode.currentIndexChanged.connect(self._sync_target_controls)
        self.target_window_title.currentIndexChanged.connect(self._window_selected)
        self._refresh_windows()
        requested_title = str(settings.get("target_window_title", ""))
        if requested_title:
            self.target_window_title.setEditText(requested_title)
        self._sync_target_controls()

    def _refresh_windows(self) -> None:
        current = self.target_window_title.currentText().strip()
        try:
            self.available_windows = self.window_service.list_windows()
        except Exception:
            self.available_windows = []
        self.target_window_title.blockSignals(True)
        self.target_window_title.clear()
        self.target_window_title.addItem("", None)
        for window in self.available_windows:
            self.target_window_title.addItem(f"{window.title}  [{window.width}×{window.height}]", window)
        self.target_window_title.blockSignals(False)
        if current:
            match = next((index for index, window in enumerate(self.available_windows, start=1) if window.title == current), -1)
            if match >= 0:
                self.target_window_title.setCurrentIndex(match)
                self.target_window_title.setEditText(self.target_window_title.itemData(match).title)
            else:
                self.target_window_title.setEditText(current)
        else:
            self.target_window_title.setCurrentIndex(0)

    def _window_selected(self, index: int) -> None:
        window = self.target_window_title.itemData(index) if index >= 0 else None
        if window is None:
            return
        self.target_window_title.setEditText(window.title)
        self.target_base_width.setValue(window.width)
        self.target_base_height.setValue(window.height)

    def _sync_target_controls(self) -> None:
        enabled = self.coordinate_mode.currentData() == "window"
        for widget in (
            self.target_window_title,
            self.target_base_width,
            self.target_base_height,
            self.target_activate,
            self.target_wait,
        ):
            widget.setEnabled(enabled)

    def _test_sendinput(self) -> None:
        from .input_backend import WindowsSendInputBackend

        expected = "AutoForge 测试 123"
        self.backend_test.clear()
        self.backend_test.setFocus()
        QApplication.processEvents()
        try:
            backend = WindowsSendInputBackend()
            backend.FAILSAFE = False
            backend.write(expected, interval=0.01)
        except Exception as exc:
            QMessageBox.warning(self, "SendInput 测试失败", str(exc))
            return
        QTimer.singleShot(150, lambda: self._verify_sendinput(expected))

    def _verify_sendinput(self, expected: str) -> None:
        if self.backend_test.text() == expected:
            QMessageBox.information(self, "SendInput 可用", "Windows 原生文字输入测试成功。")
        else:
            QMessageBox.warning(
                self,
                "未收到完整输入",
                "测试框没有收到完整文字。请使用兼容模式，或检查安全软件及程序权限等级。",
            )

    @staticmethod
    def _number_control(edit: QSpinBox | QDoubleSpinBox) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        minus = QPushButton("−")
        plus = QPushButton("+")
        minus.setFixedWidth(32)
        plus.setFixedWidth(32)
        minus.clicked.connect(lambda _checked=False: edit.stepDown())
        plus.clicked.connect(lambda _checked=False: edit.stepUp())
        row.addWidget(edit, 1)
        row.addWidget(minus)
        row.addWidget(plus)
        return container


class RecordingPreviewDialog(QDialog):
    ACTION_LABELS = {
        "click": "鼠标点击",
        "drag": "鼠标拖动",
        "scroll": "滚轮",
        "text": "连续文字",
        "hotkey": "组合键",
        "press_key": "按键",
    }

    def __init__(self, actions: list[RecordedAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("录制结果预览")
        self.resize(820, 520)
        self.original_actions = compact_recorded_actions(actions)
        self.actions = compact_recorded_actions(actions)

        layout = QVBoxLayout(self)
        intro = QLabel("请先删除误操作，再生成流程步骤。双击、连续滚轮、重复按键和连续文字已经自动合并。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号", "操作", "内容", "前置停顿", "目标截图"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(QSize(112, 70))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        tools = QHBoxLayout()
        remove = QPushButton("删除选中操作")
        reset = QPushButton("恢复全部")
        remove.clicked.connect(self._remove_selected)
        reset.clicked.connect(self._reset_actions)
        tools.addWidget(remove)
        tools.addWidget(reset)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.prefer_images = QCheckBox("点击操作优先生成“点击图片”（目标移动后仍可识别）")
        has_images = any(action.kind == "click" and action.data.get("image_png") for action in self.actions)
        self.prefer_images.setChecked(has_images)
        self.prefer_images.setEnabled(has_images)
        if not has_images:
            self.prefer_images.setToolTip("本次录制没有成功截取点击目标，将使用坐标点击")
        self.include_waits = QCheckBox("把 0.8 秒以上的停顿转换成等待步骤")
        self.include_waits.setChecked(True)
        layout.addWidget(self.prefer_images)
        layout.addWidget(self.include_waits)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("生成流程步骤")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_table()

    @staticmethod
    def _detail(action: RecordedAction) -> str:
        data = action.data
        if action.kind == "click":
            clicks = int(data.get("clicks", 1))
            suffix = f"，{clicks} 次" if clicks > 1 else ""
            return f"({data.get('x')}, {data.get('y')})，{data.get('button', 'left')}{suffix}"
        if action.kind == "drag":
            return f"({data.get('x')}, {data.get('y')}) → ({data.get('x2')}, {data.get('y2')})"
        if action.kind == "scroll":
            return f"滚动量 {data.get('amount', 0)}"
        if action.kind == "text":
            text = str(data.get("text", "")).replace("\n", "↵")
            return text[:80]
        if action.kind == "hotkey":
            return str(data.get("keys", ""))
        if action.kind == "press_key":
            return f"{data.get('key', '')} × {data.get('count', 1)}"
        return ""

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.actions))
        previous_end = 0.0
        for row, action in enumerate(self.actions):
            gap = max(0.0, action.started_at - previous_end)
            wait_text = f"{gap:.2f} 秒" if previous_end > 0 and gap >= 0.8 else "—"
            image_text = "—"
            if action.kind == "click" and action.data.get("image_png"):
                image_text = f"{action.data.get('image_width', '?')}×{action.data.get('image_height', '?')}"
            values = (
                str(row + 1),
                self.ACTION_LABELS.get(action.kind, action.kind),
                self._detail(action),
                wait_text,
                image_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 3, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 4 and action.kind == "click" and isinstance(action.data.get("image_png"), bytes):
                    pixmap = QPixmap()
                    if pixmap.loadFromData(action.data["image_png"], "PNG"):
                        thumbnail = pixmap.scaled(
                            112,
                            70,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        item.setIcon(QIcon(thumbnail))
                        item.setText("")
                self.table.setItem(row, column, item)
            if action.kind == "click" and action.data.get("image_png"):
                self.table.setRowHeight(row, 76)
            previous_end = max(previous_end, action.ended_at)

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.actions):
                del self.actions[row]
        self._refresh_table()

    def _reset_actions(self) -> None:
        self.actions = compact_recorded_actions(self.original_actions)
        self._refresh_table()


class AddStepDialog(QDialog):
    CATEGORIES = (
        ("图片识别", ("click_image", "wait_image", "wait_image_gone")),
        ("OCR 文字", ("click_text", "wait_text", "wait_text_gone")),
        ("鼠标操作", ("click_position", "drag_position", "drag_image_to_position", "drag_position_to_image", "drag_image", "scroll")),
        ("键盘与输入", ("type_text", "hotkey", "press_key")),
        ("流程与变量", ("run_subflow", "wait", "set_variable", "if_variable", "if_image", "if_text", "if_else", "loop_start")),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加步骤块")
        self.resize(480, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("按类别展开，或直接搜索步骤名称："))
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索：图片、拖动、变量、条件……")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        first_child: QTreeWidgetItem | None = None
        for category_name, step_types in self.CATEGORIES:
            category = QTreeWidgetItem([category_name])
            category.setData(0, Qt.ItemDataRole.UserRole, None)
            font = category.font(0)
            font.setBold(True)
            category.setFont(0, font)
            self.tree.addTopLevelItem(category)
            for step_type in step_types:
                child = QTreeWidgetItem([STEP_LABELS[step_type]])
                child.setData(0, Qt.ItemDataRole.UserRole, step_type)
                child.setToolTip(0, f"添加：{STEP_LABELS[step_type]}")
                category.addChild(child)
                first_child = first_child or child
            category.setExpanded(True)
        if first_child is not None:
            self.tree.setCurrentItem(first_child)
        self.search.textChanged.connect(self._filter_steps)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._accept_item(item))
        layout.addWidget(self.tree, 1)
        hint = QLabel("双击即可添加；条件和循环会自动生成配对的结束步骤。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(lambda: self._accept_item(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _filter_steps(self, text: str) -> None:
        query = text.strip().lower()
        first_visible: QTreeWidgetItem | None = None
        for category_index in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(category_index)
            category_match = query in category.text(0).lower()
            visible_children = 0
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                visible = not query or category_match or query in child.text(0).lower()
                child.setHidden(not visible)
                if visible:
                    visible_children += 1
                    first_visible = first_visible or child
            category.setHidden(visible_children == 0)
            category.setExpanded(bool(query) or category.isExpanded())
        if first_visible is not None:
            self.tree.setCurrentItem(first_visible)

    def step_types(self, *, visible_only: bool = False) -> list[str]:
        result: list[str] = []
        for category_index in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(category_index)
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                if not visible_only or (not category.isHidden() and not child.isHidden()):
                    result.append(str(child.data(0, Qt.ItemDataRole.UserRole)))
        return result

    def _accept_item(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        if item.data(0, Qt.ItemDataRole.UserRole):
            self.accept()
        else:
            item.setExpanded(not item.isExpanded())

    def selected_type(self) -> str:
        item = self.tree.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if value:
            return str(value)
        visible = self.step_types(visible_only=True)
        return visible[0] if visible else "wait"


class InspectorSection(QWidget):
    """Collapsible, keyboard-accessible group for dense step parameters."""

    expanded_changed = Signal(str, bool)

    def __init__(self, key: str, index: str, title: str, *, expanded: bool = True) -> None:
        super().__init__()
        self.key = key
        self.title = title
        self.setObjectName("inspectorSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QPushButton()
        self.header.setObjectName("inspectorSectionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setAccessibleName(f"{title}参数分组")
        self.header.toggled.connect(self._sync_expanded)
        layout.addWidget(self.header)

        self.content = QWidget()
        self.content.setObjectName("inspectorSectionContent")
        self.form = QFormLayout(self.content)
        self.form.setContentsMargins(10, 5, 10, 7)
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addWidget(self.content)
        self.index = index
        self._sync_expanded(expanded, notify=False)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, expanded: bool, *, notify: bool = False) -> None:
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self._sync_expanded(expanded, notify=notify)

    def _sync_expanded(self, expanded: bool, *, notify: bool = True) -> None:
        self.content.setVisible(expanded)
        arrow = "▼" if expanded else "▶"
        self.header.setText(f"{arrow}  {self.index}  {self.title}")
        self.header.setAccessibleDescription("已展开" if expanded else "已折叠")
        if notify:
            self.expanded_changed.emit(self.key, expanded)


class PropertyEditor(QScrollArea):
    changed = Signal()
    request_asset = Signal(str)
    request_capture = Signal(str)
    request_crop = Signal(str)
    request_test_asset = Signal(str)
    request_position = Signal(str)
    request_region = Signal()
    request_subflow = Signal()

    PARAM_KEYS = {
        "run_subflow": {"subflow", "variable_scope"},
        "click_image": {"image", "confidence", "region", "scales", "button", "clicks", "offset_x", "offset_y", "poll_interval"},
        "wait_image": {"image", "confidence", "region", "scales", "poll_interval"},
        "wait_image_gone": {"image", "confidence", "region", "scales", "poll_interval"},
        "click_text": {"text", "match", "region", "offset_x", "offset_y", "poll_interval"},
        "wait_text": {"text", "match", "region", "poll_interval"},
        "wait_text_gone": {"text", "match", "region", "poll_interval"},
        "click_position": {"x", "y", "button", "clicks"},
        "drag_position": {"x", "y", "x2", "y2", "duration", "button"},
        "drag_image_to_position": {"image", "x2", "y2", "confidence", "region", "scales", "duration", "button", "offset_x", "offset_y", "poll_interval"},
        "drag_position_to_image": {"x", "y", "target_image", "confidence", "region", "scales", "duration", "button", "target_offset_x", "target_offset_y", "poll_interval"},
        "drag_image": {"image", "target_image", "confidence", "region", "scales", "duration", "button", "offset_x", "offset_y", "target_offset_x", "target_offset_y"},
        "type_text": {"text", "method", "interval"},
        "hotkey": {"keys"},
        "press_key": {"keys", "count", "interval"},
        "scroll": {"amount"},
        "wait": {"seconds"},
        "set_variable": {"variable", "value", "variable_operation"},
        "if_variable": {"variable", "operator", "value"},
        "if_image": {"image", "condition_state", "confidence", "region", "scales", "poll_interval"},
        "if_text": {"text", "condition_state", "match", "region", "poll_interval"},
        "if_else": set(),
        "if_end": set(),
        "loop_start": {"loop_count", "index_variable"},
        "loop_end": set(),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("propertyBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 4, 10, 10)
        body_layout.setSpacing(4)
        self.setWidget(body)
        self.step: Step | None = None
        self.loading = False
        self.fields: dict[str, QWidget] = {}
        self.inline_segments: dict[str, QWidget] = {}
        self.row_specs: list[tuple[str, QFormLayout, QWidget, set[str]]] = []
        self.section_states: dict[str, dict[str, bool]] = {}
        self.sections: dict[str, InspectorSection] = {}
        for key, index, title, expanded in (
            ("base", "01", "基础", True),
            ("source", "02", "起点 / 主目标", True),
            ("target", "03", "终点", True),
            ("action", "04", "执行参数", True),
            ("recognition", "05", "识别设置", True),
            ("advanced", "06", "高级与失败处理", False),
        ):
            section = InspectorSection(key, index, title, expanded=expanded)
            section.expanded_changed.connect(self._section_toggled)
            self.sections[key] = section
            body_layout.addWidget(section)
        body_layout.addStretch(1)

        self.name_edit = QLineEdit()
        self.type_combo = IndustrialComboBox()
        for value, label in STEP_LABELS.items():
            self.type_combo.addItem(label, value)
        self.enabled_check = StepSwitch()
        self.enabled_check.setToolTip("控制当前步骤是否参与运行")
        self.breakpoint_check = IndustrialCheckBox("断点：运行前暂停")
        self.breakpoint_check.setToolTip("运行到此步骤前暂停（断点）")
        state_row = QWidget()
        state_row.setObjectName("parameterInlineRow")
        state_layout = QHBoxLayout(state_row)
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_layout.setSpacing(12)
        state_layout.addWidget(self.enabled_check)
        state_layout.addWidget(self.breakpoint_check, 1)
        self._add_row("base", "步骤名称", self.name_edit, {"__name"})
        self._add_row("base", "操作类型", self.type_combo, {"__type"})
        self._add_row("base", "状态", state_row, {"__state"})

        self._add_asset_field("image", "起点 / 主图片", "source")
        self._add_asset_field("target_image", "终点图片", "target")
        subflow_field = QWidget()
        subflow_layout = QHBoxLayout(subflow_field)
        subflow_layout.setContentsMargins(0, 0, 0, 0)
        subflow_edit = QLineEdit()
        subflow_edit.setReadOnly(True)
        subflow_edit.setPlaceholderText("导入 .kmflow")
        subflow_field.setProperty("editor", subflow_edit)
        subflow_layout.addWidget(subflow_edit, 1)
        choose_subflow = QPushButton("替换")
        choose_subflow.clicked.connect(self.request_subflow.emit)
        clear_subflow = QPushButton("清除")
        clear_subflow.clicked.connect(lambda: self._clear_asset("subflow"))
        subflow_layout.addWidget(choose_subflow)
        subflow_layout.addWidget(clear_subflow)
        self.fields["subflow"] = subflow_field
        self._add_row("action", "子流程文件", subflow_field, {"subflow"})
        subflow_field.setToolTip("导入的是独立副本，随主流程打包。修改原文件后请重新替换。")
        self._add_combo("variable_scope", "变量传递", [("共享：继承并回传变量", "shared"), ("独立：使用子流程初始变量", "isolated")], "action")
        self._add_text_field("text", "文字内容", "action")
        self._add_combo("match", "文字匹配", [("包含", "contains"), ("完全相同", "exact")], "action")
        self._add_combo("method", "输入方式", [("剪贴板粘贴", "paste"), ("逐键输入", "write")], "action")
        self._add_line("keys", "按键/组合键", "action")
        keys_edit = self.fields["keys"]
        keys_edit.setPlaceholderText("例如 ctrl+s；空格键填写 space")
        keys_edit.setToolTip(KEY_INPUT_HELP)
        self.keys_help = QWidget()
        keys_help_layout = QHBoxLayout(self.keys_help)
        keys_help_layout.setContentsMargins(0, 0, 0, 0)
        keys_hint = QLabel("组合键用 + 连接；空格键填写 space")
        keys_hint.setWordWrap(True)
        self.keys_help_button = QPushButton("查看全部可用按键")
        self.keys_help_button.setToolTip(KEY_INPUT_HELP)
        self.keys_help_button.clicked.connect(lambda _checked=False: self._show_key_input_help())
        keys_help_layout.addWidget(keys_hint, 1)
        keys_help_layout.addWidget(self.keys_help_button)
        self._add_row("action", "输入说明", self.keys_help, {"__keys_help"})

        self.pick_start = QPushButton("◎ 屏幕拾取")
        self.pick_end = QPushButton("◎ 屏幕拾取")
        self.pick_start.setToolTip("在屏幕上点击并取得起点")
        self.pick_end.setToolTip("在屏幕上点击并取得终点")
        self.pick_start.clicked.connect(lambda _checked=False: self.request_position.emit("start"))
        self.pick_end.clicked.connect(lambda _checked=False: self.request_position.emit("end"))
        self.start_coordinates = self._coordinate_row("x", "y", self.pick_start)
        self.target_coordinates = self._coordinate_row("x2", "y2", self.pick_end)
        self._add_row("source", "坐标", self.start_coordinates, {"x", "y"})
        self._add_row("target", "坐标", self.target_coordinates, {"x2", "y2"})

        source_offsets = self._int_pair("offset_x", "X", "offset_y", "Y", -10000, 10000)
        target_offsets = self._int_pair("target_offset_x", "X", "target_offset_y", "Y", -10000, 10000)
        self._add_row("source", "点击偏移", source_offsets, {"offset_x", "offset_y"})
        self._add_row("target", "落点偏移", target_offsets, {"target_offset_x", "target_offset_y"})

        self._add_int("amount", "滚轮量", -10000, 10000, "action")
        self._add_int("count", "按键次数", 1, 10000, "action")
        self._add_int("loop_count", "循环次数", 0, 100000, "action")
        self._add_float("seconds", "等待秒数", 0, 86400, 2, section="action")
        self._add_float("interval", "输入间隔", 0, 60, 3, section="action")

        duration = self._make_float("duration", 0, 120, 2)
        clicks = self._make_int("clicks", 1, 100)
        button = self._make_combo("button", [("左键", "left"), ("右键", "right"), ("中键", "middle")])
        pointer_action = self._inline_row((("duration", "时长", duration), ("clicks", "次数", clicks), ("button", "按键", button)))
        self._add_row("action", "鼠标执行", pointer_action, {"duration", "clicks", "button"})

        confidence = self._make_float("confidence", 0.1, 1.0, 3, 0.01)
        poll_interval = self._make_float("poll_interval", 0.03, 10, 2)
        recognition_timing = self._inline_row((("confidence", "阈值", confidence), ("poll_interval", "间隔", poll_interval)))
        self._add_row("recognition", "匹配", recognition_timing, {"confidence", "poll_interval"})
        self._add_region_field("recognition")
        self._add_line("scales", "缩放比例", "recognition")
        self._add_line("variable", "变量名", "action")
        self._add_line("value", "变量值/比较值", "action")
        self._add_line("index_variable", "循环序号变量", "action")
        self._add_combo(
            "variable_operation",
            "变量操作",
            [("设为", "set"), ("增加", "add"), ("减少", "subtract")],
            "action",
        )
        self._add_combo(
            "operator",
            "比较方式",
            [
                ("等于", "equals"),
                ("不等于", "not_equals"),
                ("包含", "contains"),
                ("不包含", "not_contains"),
                ("大于", "greater"),
                ("大于等于", "greater_equal"),
                ("小于", "less"),
                ("小于等于", "less_equal"),
                ("不为空", "not_empty"),
                ("为空", "is_empty"),
            ],
            "action",
        )
        self._add_combo(
            "condition_state",
            "判断目标",
            [("存在", "present"), ("不存在", "absent")],
            "action",
        )
        self.block_help = QLabel()
        self.block_help.setWordWrap(True)
        self._add_row("action", "块说明", self.block_help, {"__block_help"})

        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0, 86400)
        self.timeout.setDecimals(1)
        self.timeout.setSingleStep(0.5)
        self.timeout.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.timeout.setSuffix(" 秒")
        self.timeout_control = self._number_container(self.timeout)
        self.retries = QSpinBox()
        self.retries.setRange(0, 999)
        self.retries.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.retries_control = self._number_container(self.retries)
        self.failure_combo = IndustrialComboBox()
        self.failure_combo.addItem("停止流程", "stop")
        self.failure_combo.addItem("记录错误并继续", "continue")
        self._add_row("advanced", "超时时间", self.timeout_control, {"__timeout"})
        failure_row = self._inline_row((("__retries", "重试", self.retries_control), ("__failure", "最终", self.failure_combo)))
        self._add_row("advanced", "失败处理", failure_row, {"__retries", "__failure"})

        self.name_edit.textEdited.connect(self._save)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.enabled_check.toggled.connect(self._save)
        self.breakpoint_check.toggled.connect(self._save)
        self.timeout.valueChanged.connect(self._save)
        self.retries.valueChanged.connect(self._save)
        self.failure_combo.currentIndexChanged.connect(self._save)
        self.setEnabled(False)

    def _add_row(self, section: str, label: str, widget: QWidget, keys: set[str]) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("parameterLabel")
        label_widget.setMinimumWidth(54)
        form = self.sections[section].form
        form.addRow(label_widget, widget)
        self.row_specs.append((section, form, widget, keys))

    def _section_toggled(self, key: str, expanded: bool) -> None:
        if self.step is not None:
            self.section_states.setdefault(self.step.type, {})[key] = expanded

    def _add_asset_field(self, key: str, label: str, section: str) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        edit = QLineEdit()
        edit.setReadOnly(True)
        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("选择")
        capture = QPushButton("截图")
        crop = QPushButton("裁剪")
        test = QPushButton("测试")
        clear = QPushButton("清除")
        browse.clicked.connect(lambda _checked=False, k=key: self.request_asset.emit(k))
        capture.clicked.connect(lambda _checked=False, k=key: self.request_capture.emit(k))
        crop.clicked.connect(lambda _checked=False, k=key: self.request_crop.emit(k))
        test.clicked.connect(lambda _checked=False, k=key: self.request_test_asset.emit(k))
        clear.clicked.connect(lambda _checked=False, k=key: self._clear_asset(k))
        for button in (browse, capture, crop, test, clear):
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addWidget(edit)
        layout.addWidget(buttons)
        self.fields[key] = container
        container.setProperty("editor", edit)
        self._add_row(section, label, container, {key})

    def _clear_asset(self, key: str) -> None:
        if not self.step or key not in self.fields:
            return
        editor = self.fields[key].property("editor")
        editor.clear()
        self.step.params[key] = ""
        self.changed.emit()

    def _add_line(self, key: str, label: str, section: str) -> None:
        edit = QLineEdit()
        if key == "scales":
            edit.setPlaceholderText("例如 0.9,1.0,1.1")
        elif key == "variable":
            edit.setPlaceholderText("例如 登录次数")
        elif key == "value":
            edit.setPlaceholderText("可填写固定值或 ${其他变量}")
        elif key == "index_variable":
            edit.setPlaceholderText("例如 循环序号；留空则不写入")
        edit.editingFinished.connect(self._save)
        self.fields[key] = edit
        self._add_row(section, label, edit, {key})

    def _add_region_field(self, section: str) -> None:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setPlaceholderText("留空为全屏，或 x,y,宽,高")
        edit.editingFinished.connect(self._save)
        choose = QPushButton("框选")
        clear = QPushButton("清除")
        choose.clicked.connect(lambda _checked=False: self.request_region.emit())
        clear.clicked.connect(lambda _checked=False: (edit.clear(), self._save()))
        layout.addWidget(edit, 1)
        layout.addWidget(choose)
        layout.addWidget(clear)
        container.setProperty("editor", edit)
        self.fields["region"] = container
        self._add_row(section, "识别区域", container, {"region"})

    def _add_text_field(self, key: str, label: str, section: str) -> None:
        edit = QPlainTextEdit()
        edit.setMaximumHeight(76)
        edit.textChanged.connect(self._save)
        self.fields[key] = edit
        self._add_row(section, label, edit, {key})

    def _make_int(self, key: str, minimum: int, maximum: int, *, compact: bool = False) -> QWidget:
        edit = QSpinBox()
        edit.setRange(minimum, maximum)
        edit.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        edit.valueChanged.connect(self._save)
        container = self._number_container(edit, compact=compact)
        self.fields[key] = container
        return container

    def _add_int(self, key: str, label: str, minimum: int, maximum: int, section: str) -> None:
        self._add_row(section, label, self._make_int(key, minimum, maximum), {key})

    def _make_float(
        self,
        key: str,
        minimum: float,
        maximum: float,
        decimals: int,
        single_step: float | None = None,
        *,
        compact: bool = True,
    ) -> QWidget:
        edit = QDoubleSpinBox()
        edit.setRange(minimum, maximum)
        edit.setDecimals(decimals)
        if single_step is not None:
            edit.setSingleStep(single_step)
        edit.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        edit.valueChanged.connect(self._save)
        container = self._number_container(edit, compact=compact)
        self.fields[key] = container
        return container

    def _add_float(
        self,
        key: str,
        label: str,
        minimum: float,
        maximum: float,
        decimals: int,
        single_step: float | None = None,
        *,
        section: str,
    ) -> None:
        self._add_row(section, label, self._make_float(key, minimum, maximum, decimals, single_step), {key})

    @staticmethod
    def _number_container(edit: QSpinBox | QDoubleSpinBox, *, compact: bool = False) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3 if compact else 8)
        minus = QPushButton("−")
        plus = QPushButton("+")
        object_name = "microAdjustCompactButton" if compact else "microAdjustButton"
        minus.setObjectName(object_name)
        plus.setObjectName(object_name)
        button_width = 20 if compact else 34
        minus.setFixedWidth(button_width)
        plus.setFixedWidth(button_width)
        minus.setToolTip("减小")
        plus.setToolTip("增大")
        minus.clicked.connect(lambda _checked=False: edit.stepDown())
        plus.clicked.connect(lambda _checked=False: edit.stepUp())
        layout.addWidget(edit, 1)
        layout.addWidget(minus)
        layout.addWidget(plus)
        container.setProperty("editor", edit)
        return container

    def _make_combo(self, key: str, options: list[tuple[str, str]]) -> QComboBox:
        edit = IndustrialComboBox()
        for text, value in options:
            edit.addItem(text, value)
        edit.currentIndexChanged.connect(self._save)
        self.fields[key] = edit
        return edit

    def _add_combo(self, key: str, label: str, options: list[tuple[str, str]], section: str) -> None:
        self._add_row(section, label, self._make_combo(key, options), {key})

    def _inline_row(self, items: tuple[tuple[str, str, QWidget], ...], *extras: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("parameterInlineRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for key, caption, widget in items:
            segment = QWidget()
            segment.setObjectName("inlineField")
            segment_layout = QHBoxLayout(segment)
            segment_layout.setContentsMargins(0, 0, 0, 0)
            segment_layout.setSpacing(3)
            caption_label = QLabel(caption)
            caption_label.setObjectName("inlineFieldLabel")
            segment_layout.addWidget(caption_label)
            segment_layout.addWidget(widget, 1)
            segment.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.inline_segments[key] = segment
            layout.addWidget(segment, 1)
        for extra in extras:
            layout.addWidget(extra)
        return row

    def _coordinate_row(self, x_key: str, y_key: str, picker: QPushButton) -> QWidget:
        x_field = self._make_int(x_key, -100000, 100000, compact=True)
        y_field = self._make_int(y_key, -100000, 100000, compact=True)
        picker.setText("◎拾取")
        picker.setObjectName("pickPositionButton")
        picker.setFixedWidth(50)
        return self._inline_row(((x_key, "X", x_field), (y_key, "Y", y_field)), picker)

    def _int_pair(
        self,
        first_key: str,
        first_label: str,
        second_key: str,
        second_label: str,
        minimum: int,
        maximum: int,
    ) -> QWidget:
        first = self._make_int(first_key, minimum, maximum, compact=True)
        second = self._make_int(second_key, minimum, maximum, compact=True)
        return self._inline_row(((first_key, first_label, first), (second_key, second_label, second)))

    def set_step(self, step: Step | None) -> None:
        previous_id = self.step.id if self.step is not None else None
        self.loading = True
        self.step = step
        self.setEnabled(step is not None)
        if step is None:
            self.loading = False
            return
        self.name_edit.setText(step.name)
        self.type_combo.setCurrentIndex(self.type_combo.findData(step.type))
        self.enabled_check.setChecked(step.enabled)
        self.breakpoint_check.setChecked(step.breakpoint)
        self.timeout.setValue(step.timeout)
        self.retries.setValue(step.retries)
        self.failure_combo.setCurrentIndex(max(0, self.failure_combo.findData(step.on_failure)))
        for key, widget in self.fields.items():
            value = step.params.get(key, "")
            editor = widget.property("editor") or widget
            if isinstance(editor, QLineEdit):
                editor.setText(str(value))
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlainText(str(value))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value or 0))
            elif isinstance(editor, QDoubleSpinBox):
                editor.setValue(float(value or 0))
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(value)))
        remembered = self.section_states.get(step.type, {})
        for key, section in self.sections.items():
            section.set_expanded(remembered.get(key, key != "advanced"), notify=False)
        self._update_visibility()
        self.loading = False
        if previous_id != step.id:
            self.verticalScrollBar().setValue(0)

    def set_asset(self, key: str, path: str) -> None:
        if not self.step or key not in self.fields:
            return
        editor = self.fields[key].property("editor")
        editor.setText(path)
        self.step.params[key] = path
        self.changed.emit()

    def set_position(self, which: str, x: int, y: int) -> None:
        if not self.step:
            return
        self.loading = True
        if which == "end":
            self.fields["x2"].property("editor").setValue(x)
            self.fields["y2"].property("editor").setValue(y)
        else:
            self.fields["x"].property("editor").setValue(x)
            self.fields["y"].property("editor").setValue(y)
        self.loading = False
        self._save()

    def set_region(self, x: int, y: int, width: int, height: int) -> None:
        if not self.step:
            return
        editor = self.fields["region"].property("editor")
        editor.setText(f"{x},{y},{width},{height}")
        self._save()

    def _type_changed(self) -> None:
        if self.loading or not self.step:
            return
        new_type = str(self.type_combo.currentData())
        if new_type == self.step.type:
            return
        old = self.step.params
        defaults = dict(DEFAULT_PARAMS[new_type])
        self.step.params = {key: old.get(key, value) for key, value in defaults.items()}
        self.step.type = new_type
        self.set_step(self.step)
        self.changed.emit()

    def _show_key_input_help(self) -> None:
        QMessageBox.information(self, "按键和组合键输入说明", KEY_INPUT_HELP)

    def _update_visibility(self) -> None:
        if not self.step:
            return
        visible = set(self.PARAM_KEYS[self.step.type])
        visible.update({"__name", "__type", "__state"})
        uses_timeout = self.step.type in {
            "click_image", "wait_image", "wait_image_gone", "click_text", "wait_text", "wait_text_gone",
            "drag_image", "drag_image_to_position", "drag_position_to_image", "if_image", "if_text",
        }
        if uses_timeout:
            visible.add("__timeout")
        uses_start_picker = self.step.type in {"click_position", "drag_position", "drag_position_to_image"}
        uses_end_picker = self.step.type in {"drag_position", "drag_image_to_position"}
        if self.step.type in {"hotkey", "press_key"}:
            visible.add("__keys_help")
        block_marker = self.step.type in {"if_variable", "if_image", "if_text", "if_else", "if_end", "loop_start", "loop_end"}
        if block_marker:
            visible.add("__block_help")
        else:
            visible.update({"__retries", "__failure"})

        for key, widget in self.fields.items():
            widget.setVisible(key in visible)
        for key, segment in self.inline_segments.items():
            segment.setVisible(key in visible)
        self.pick_start.setVisible(uses_start_picker)
        self.pick_end.setVisible(uses_end_picker)

        block_help = {
            "if_variable": "条件成立时执行后面的步骤，直到遇到对应的“条件结束”；条件不成立会跳过整个块。",
            "if_image": "在检测时间内判断图片是否存在；可加入“否则”步骤形成另一条执行分支。",
            "if_text": "使用 OCR 判断文字是否存在；可加入“否则”步骤形成另一条执行分支。",
            "if_else": "前面的条件不成立时执行此处到“条件结束”之间的步骤。",
            "if_end": "结束最近一层“条件开始”块。",
            "loop_start": "重复执行后面的步骤，直到对应的“循环结束”；支持在块内继续嵌套条件或循环。",
            "loop_end": "结束最近一层循环，并根据循环次数决定是否返回循环开头。",
        }
        self.block_help.setText(block_help.get(self.step.type, ""))
        section_has_rows = {key: False for key in self.sections}
        for section_key, form, row_widget, keys in self.row_specs:
            row_visible = bool(keys & visible)
            form.setRowVisible(row_widget, row_visible)
            section_has_rows[section_key] = section_has_rows[section_key] or row_visible
        for key, section in self.sections.items():
            available = section_has_rows[key]
            section.setVisible(available)

        self.enabled_check.setEnabled(self.step.type not in {"if_else", "if_end", "loop_end"})
        # Changing only one marker can leave its paired block structurally
        # invalid. Markers are added explicitly and keep their original type.
        self.type_combo.setEnabled(not block_marker)

    def _value(self, key: str, widget: QWidget) -> Any:
        editor = widget.property("editor") or widget
        if isinstance(editor, QLineEdit):
            return editor.text().strip()
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if isinstance(editor, QComboBox):
            return editor.currentData()
        return None

    def _save(self) -> None:
        if self.loading or not self.step:
            return
        self.step.name = self.name_edit.text().strip() or STEP_LABELS[self.step.type]
        self.step.enabled = self.enabled_check.isChecked()
        self.step.breakpoint = self.breakpoint_check.isChecked()
        self.step.timeout = self.timeout.value()
        self.step.retries = self.retries.value()
        self.step.on_failure = str(self.failure_combo.currentData())
        visible = self.PARAM_KEYS[self.step.type]
        for key in visible:
            self.step.params[key] = self._value(key, self.fields[key])
        self.changed.emit()


class RunHistoryDialog(QDialog):
    STATUS_LABELS = {
        "running": "运行中",
        "done": "成功",
        "done_with_errors": "完成（有错误）",
        "failed": "失败",
        "stopped": "已停止",
        "interrupted": "异常中断",
    }

    def __init__(self, store: RunHistoryStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("运行历史")
        self.resize(980, 560)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["开始时间", "流程", "结果", "耗时", "步骤 / 轮数", "失败步骤", "失败截图"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setToolTip("按 Ctrl 多选记录，按 Shift 选择连续范围")
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selected_details)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_screenshot())
        layout.addWidget(self.table)

        layout.addWidget(QLabel("错误信息 / 文件位置"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(105)
        layout.addWidget(self.details)

        buttons = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh)
        self.open_button = QPushButton("打开失败截图")
        self.open_button.clicked.connect(self.open_screenshot)
        folder_button = QPushButton("打开截图目录")
        folder_button.clicked.connect(self.open_screenshot_folder)
        self.delete_button = QPushButton("删除所选记录")
        self.delete_button.setToolTip("只删除所选历史记录，不删除失败截图文件")
        self.delete_button.clicked.connect(self.delete_selected_records)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(refresh_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(folder_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        records = self.store.list_runs()
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            duration = "—" if record.duration_seconds is None else f"{record.duration_seconds:.2f} 秒"
            step_summary = f"{record.total_steps} 步 / {record.repeat_count} 轮"
            failure_step = str(record.failure_step) if record.failure_step is not None else "—"
            screenshot = "有" if record.screenshot_path else "—"
            values = [
                record.started_at.replace("T", " "),
                record.workflow_name,
                self.STATUS_LABELS.get(record.status, record.status),
                duration,
                step_summary,
                failure_step,
                screenshot,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(HISTORY_RECORD_ROLE, record)
                if column in {2, 3, 4, 5, 6}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        if records:
            self.table.selectRow(0)
        else:
            self.details.setPlainText("还没有运行记录。")
            self.open_button.setEnabled(False)
            self.delete_button.setEnabled(False)

    def _selected_records(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for index in self.table.selectionModel().selectedRows(0):
            item = self.table.item(index.row(), 0)
            record = item.data(HISTORY_RECORD_ROLE) if item else None
            if isinstance(record, RunRecord):
                records.append(record)
        return records

    def _selected_record(self) -> RunRecord | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        record = item.data(HISTORY_RECORD_ROLE) if item else None
        return record if isinstance(record, RunRecord) else None

    def _show_selected_details(self) -> None:
        self.delete_button.setEnabled(bool(self._selected_records()))
        record = self._selected_record()
        if record is None:
            self.details.clear()
            self.open_button.setEnabled(False)
            return
        lines: list[str] = []
        if record.error_message:
            lines.append(record.error_message)
        if record.workflow_path:
            lines.append(f"流程文件：{record.workflow_path}")
        if record.screenshot_path:
            lines.append(f"失败截图：{record.screenshot_path}")
        self.details.setPlainText("\n".join(lines) or "本次运行没有错误信息。")
        self.open_button.setEnabled(bool(record.screenshot_path) and Path(record.screenshot_path).is_file())

    def delete_selected_records(self) -> None:
        records = self._selected_records()
        if not records:
            return
        answer = QMessageBox.question(
            self,
            "删除运行记录",
            f"确定删除选中的 {len(records)} 条运行记录吗？\n失败截图文件会保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_runs([record.id for record in records])
        self.refresh()

    def open_screenshot(self) -> None:
        record = self._selected_record()
        if record is None or not record.screenshot_path:
            QMessageBox.information(self, "没有截图", "所选记录没有失败截图。")
            return
        target = Path(record.screenshot_path)
        if not target.is_file():
            QMessageBox.warning(self, "截图不存在", f"文件可能已被移动或删除：\n{target}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def open_screenshot_folder(self) -> None:
        record = self._selected_record()
        target = Path(record.screenshot_path).parent if record and record.screenshot_path else self.store.db_path.parent / "failures"
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


class RecordingBridge(QObject):
    stop_requested = Signal()
    emergency_stop_requested = Signal()


class MainWindow(QMainWindow):
    def __init__(self, *, persist_settings: bool = True) -> None:
        super().__init__()
        self.persist_settings = persist_settings
        self.document = WorkflowDocument.create()
        self.runner_thread: RunnerThread | None = None
        self.current_asset_key = "image"
        self.snipper: ScreenSnipper | None = None
        self.position_picker: PositionPicker | None = None
        self.region_picker: RegionPicker | None = None
        self.input_recorder: InputRecorder | None = None
        self.recording_insert_at = 0
        self.debug_paused_state = False
        self.collapsed_blocks: set[str] = set()
        self.step_clipboard: list[dict[str, Any]] = []
        self.undo_states: list[dict[str, Any]] = []
        self.redo_states: list[dict[str, Any]] = []
        self._run_history_store: RunHistoryStore | None = None
        self.current_run_id: int | None = None
        self.current_run_plan = RunPlan()
        self._normal_splitter_sizes = [720, 480]
        self._history_current = self.document.workflow.to_dict()
        self._saved_history_state = self.document.workflow.to_dict()
        self._restoring_history = False
        self.recording_bridge = RecordingBridge()
        self.recording_bridge.stop_requested.connect(self.finish_recording)
        self.recording_bridge.emergency_stop_requested.connect(self._emergency_stop_workflow)
        self.emergency_hotkey = GlobalStopHotkey(self.recording_bridge.emergency_stop_requested.emit)
        self.settings = QSettings("KeyMouse", "KeyMouse Studio")
        # AutoForge uses one deliberate visual system instead of two
        # differently tuned skins. Keep the attribute for workflow-side API
        # compatibility, but it is always dark.
        self.dark_mode = True
        self.setWindowTitle("AutoForge")
        self.resize(1180, 760)
        self._build_ui()
        geometry = self.settings.value("geometry") if self.persist_settings else None
        if geometry:
            self.restoreGeometry(geometry)
        self.refresh_table()
        self._update_title()

    def _build_ui(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setObjectName("studioToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        self.main_toolbar = toolbar

        def action(text: str, slot: Any, shortcut: str | None = None) -> QAction:
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            toolbar.addAction(item)
            return item

        file_menu = self.menuBar().addMenu("文件")
        edit_menu = self.menuBar().addMenu("编辑")
        debug_menu = self.menuBar().addMenu("调试")

        def menu_action(menu: Any, text: str, slot: Any, shortcut: str | None = None) -> QAction:
            item = QAction(text, self)
            item.triggered.connect(slot)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            menu.addAction(item)
            return item

        self.new_action = menu_action(file_menu, "新建", self.new_document, "Ctrl+N")
        self.open_action = menu_action(file_menu, "打开", self.open_document, "Ctrl+O")
        self.save_action = menu_action(file_menu, "保存", self._save_from_shortcut, "Ctrl+S")
        self.save_as_action = menu_action(file_menu, "另存为", self.save_as)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        self.undo_action = menu_action(edit_menu, "撤销", self.undo_context, "Ctrl+Z")
        self.redo_action = menu_action(edit_menu, "重做", self.redo_context, "Ctrl+Y")
        edit_menu.addSeparator()
        action("添加步骤", self.add_step, "Insert")
        self.copy_action = menu_action(edit_menu, "复制步骤", self.copy_context, "Ctrl+C")
        self.cut_action = menu_action(edit_menu, "剪切步骤", self.cut_context, "Ctrl+X")
        self.paste_action = menu_action(edit_menu, "粘贴步骤", self.paste_context, "Ctrl+V")
        self.duplicate_action = action("快速复制", self.duplicate_step)
        self.delete_action = action("删除", self.delete_context, "Delete")
        edit_menu.addAction(self.delete_action)
        menu_action(edit_menu, "上移", lambda: self.move_step(-1), "Alt+Up")
        menu_action(edit_menu, "下移", lambda: self.move_step(1), "Alt+Down")
        self.collapse_action = menu_action(edit_menu, "折叠/展开", self.toggle_block_collapsed)
        self.collapse_action.setToolTip("折叠或展开当前条件/循环块")
        toolbar.addAction(self.collapse_action)
        self.breakpoint_action = menu_action(debug_menu, "切换断点", self.toggle_breakpoint, "F6")
        menu_action(file_menu, "导入子流程", self.import_subflow)
        toolbar.addSeparator()
        toolbar_spacer = QWidget()
        toolbar_spacer.setObjectName("toolbarSpacer")
        toolbar_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(toolbar_spacer)
        self.variables_action = action("初始变量：0", self.edit_variables)
        self.run_settings_action = action("运行设置：1 次", self.edit_run_settings)
        self.record_action = action("● 录制", self.toggle_recording)
        self.run_action = menu_action(debug_menu, "运行  F5", self.run_workflow, "F5")
        self.run_button = CutActionButton("运行  F5")
        self.run_button.clicked.connect(self.run_action.trigger)
        self.run_action.changed.connect(lambda: self.run_button.setEnabled(self.run_action.isEnabled()))
        self.run_widget_action = toolbar.addWidget(self.run_button)
        self.pause_action = menu_action(debug_menu, "暂停", self.toggle_pause_workflow, "F7")
        self.step_action = menu_action(debug_menu, "单步执行", self.step_workflow, "F10")
        debug_menu.addSeparator()
        self.preflight_action = menu_action(debug_menu, "运行前检查", self.check_workflow)
        self.run_current_action = menu_action(debug_menu, "运行当前步骤", self.run_current_step, "Ctrl+F5")
        self.run_from_action = menu_action(debug_menu, "从此处运行", self.run_from_here, "Alt+F5")
        self.run_to_action = menu_action(debug_menu, "运行到此处", self.run_to_here, "Ctrl+Alt+F5")
        self.run_selected_action = menu_action(debug_menu, "运行所选步骤", self.run_selected_steps, "Ctrl+Shift+F5")
        self.safe_test_action = menu_action(debug_menu, "安全测试当前/所选", self.safe_test_steps, "Ctrl+F8")
        self.local_run_actions = (
            self.preflight_action,
            self.run_current_action,
            self.run_from_action,
            self.run_to_action,
            self.run_selected_action,
            self.safe_test_action,
        )
        self.stop_action = action("■ 停止（F9）", self.stop_workflow, "Shift+F5")
        debug_menu.addAction(self.record_action)
        debug_menu.addAction(self.stop_action)
        debug_menu.addSeparator()
        self.history_action = menu_action(debug_menu, "运行历史", self.show_run_history)
        self.pause_action.setEnabled(False)
        self.step_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        view_menu = self.menuBar().addMenu("视图")
        self.motion_action = QAction("减少动画", self)
        self.motion_action.setCheckable(True)
        self.motion_action.setChecked(self.settings.value("reduced_motion", False, type=bool))
        self.motion_action.toggled.connect(self._toggle_motion)
        view_menu.addAction(self.motion_action)
        self._toolbar_compact = False
        toolbar.widgetForAction(self.variables_action).setObjectName("tagButton")
        toolbar.widgetForAction(self.run_settings_action).setObjectName("tagButton")
        toolbar.widgetForAction(self.stop_action).setObjectName("stopButton")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter = splitter
        splitter.setHandleWidth(14)
        self.table = StepTable(0, 4)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setHorizontalHeaderLabels(["启用", "序号", "操作", "名称与内容"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setToolTip("可拖选连续步骤；按 Ctrl 多选，Shift 范围选择")
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 86)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.rows_moved.connect(self._drag_move_step)
        flow_panel = IndustrialPanel("01")
        self.flow_panel = flow_panel
        flow_panel.setObjectName("panel")
        flow_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        flow_layout = QVBoxLayout(flow_panel)
        flow_layout.setContentsMargins(14, 0, 14, 14)
        flow_layout.setSpacing(10)
        flow_heading = QHBoxLayout()
        flow_heading.setSpacing(12)
        flow_badge = CutBadge("SYS.PROC // 01")
        flow_badge.setAccessibleName("区域 01 流程步骤")
        flow_heading.addWidget(flow_badge, 0, Qt.AlignmentFlag.AlignTop)
        flow_title_block = QWidget()
        flow_title_layout = QVBoxLayout(flow_title_block)
        flow_title_layout.setContentsMargins(0, 3, 0, 0)
        flow_title_layout.setSpacing(0)
        heading = QLabel("流程步骤")
        heading.setObjectName("sectionTitle")
        flow_micro = QLabel("FLOW SEQUENCE BUILDER")
        flow_micro.setObjectName("sectionMicro")
        flow_title_layout.addWidget(heading)
        flow_title_layout.addWidget(flow_micro)
        flow_heading.addWidget(flow_title_block)
        self.flow_heading = QLabel(self.document.workflow.name)
        self.flow_heading.setObjectName("subtitle")
        flow_heading.addWidget(self.flow_heading, 1)
        flow_heading.addStretch()
        flow_watermark = QLabel("01")
        flow_watermark.setObjectName("panelWatermark")
        flow_watermark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        flow_watermark.setFixedWidth(60)
        flow_watermark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        flow_heading.addWidget(flow_watermark, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        flow_layout.addLayout(flow_heading)
        flow_layout.addWidget(self.table)
        splitter.addWidget(flow_panel)

        self.properties = PropertyEditor()
        self.properties.setMinimumWidth(355)
        self.properties.changed.connect(self._properties_changed)
        self.properties.request_asset.connect(self.choose_asset)
        self.properties.request_capture.connect(self.capture_asset)
        self.properties.request_crop.connect(self.crop_asset)
        self.properties.request_test_asset.connect(self.test_asset)
        self.properties.request_position.connect(self.pick_position)
        self.properties.request_region.connect(self.pick_region)
        self.properties.request_subflow.connect(lambda: self.import_subflow(replace=True))
        property_panel = IndustrialPanel("02")
        self.property_panel = property_panel
        property_panel.setObjectName("panel")
        property_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        property_layout = QVBoxLayout(property_panel)
        property_layout.setContentsMargins(0, 0, 0, 0)
        property_layout.setSpacing(10)
        property_heading = QLabel("步骤参数")
        property_heading.setObjectName("sectionTitle")
        inspector_header = QHBoxLayout()
        inspector_header.setContentsMargins(10, 0, 10, 0)
        inspector_header.setSpacing(8)
        self.selection_index = CutBadge("SYS.PARAM // --")
        self.selection_index.setFixedWidth(132)
        inspector_header.addWidget(self.selection_index, 0, Qt.AlignmentFlag.AlignTop)
        property_title_block = QWidget()
        property_title_block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        property_title_layout = QVBoxLayout(property_title_block)
        property_title_layout.setContentsMargins(0, 3, 0, 0)
        property_title_layout.setSpacing(0)
        property_micro = QLabel("PARAM INSPECTOR / 02")
        property_micro.setObjectName("sectionMicro")
        property_title_layout.addWidget(property_heading)
        property_title_layout.addWidget(property_micro)
        inspector_header.addWidget(property_title_block, 1)
        property_watermark = QLabel("02")
        property_watermark.setObjectName("panelWatermark")
        property_watermark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        property_watermark.setFixedWidth(60)
        property_watermark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inspector_header.addWidget(property_watermark, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        property_layout.addLayout(inspector_header)
        property_layout.addWidget(self.properties)
        splitter.addWidget(property_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes(self._normal_splitter_sizes)

        central = StageCanvas()
        central.setObjectName("stageCanvas")
        central.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        self.field_strip = FieldStrip()
        self.field_strip.reduced_motion = self.motion_action.isChecked()
        layout.addWidget(self.field_strip)
        self.compact_tabs = QTabWidget()
        self.compact_tabs.hide()
        layout.addWidget(self.compact_tabs, 1)
        layout.addWidget(splitter, 1)
        self.log_toggle = QPushButton("03 / 运行日志   收起")
        self.log_toggle.setObjectName("logToggle")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().addPermanentWidget(QLabel(f"AutoForge  {__version__}"))
        self.statusBar().showMessage("就绪")
        self.inspector_effect = QGraphicsOpacityEffect(self.properties)
        self.properties.setGraphicsEffect(self.inspector_effect)
        self.inspector_reveal = QPropertyAnimation(self.inspector_effect, b"opacity", self)
        self.inspector_reveal.setDuration(180)

        self._apply_theme()
        self.focus_pixel_filter = FocusPixelFilter(self)
        self._update_variables_action()
        self._update_run_settings_action()
        self._update_history_actions()
        self._update_clipboard_actions()

    def _toggle_log(self, visible: bool) -> None:
        self.log.setVisible(visible)
        self.log_toggle.setText("03 / 运行日志   收起" if visible else "03 / 运行日志   展开")

    def _toggle_motion(self, reduced: bool) -> None:
        if self.persist_settings:
            self.settings.setValue("reduced_motion", reduced)
        self.field_strip.reduced_motion = reduced
        if reduced:
            self.field_strip.animation.stop()
            self.inspector_reveal.stop()
            self.inspector_effect.setOpacity(1.0)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "compact_tabs"):
            return
        compact = self.width() < 980
        if compact != self._toolbar_compact:
            if compact:
                # Keep the safety-critical actions visible before Qt's toolbar
                # overflow control on narrow windows.
                self.main_toolbar.insertAction(self.duplicate_action, self.run_widget_action)
                self.main_toolbar.insertAction(self.duplicate_action, self.stop_action)
            else:
                self.main_toolbar.removeAction(self.run_widget_action)
                self.main_toolbar.removeAction(self.stop_action)
                self.main_toolbar.addAction(self.run_widget_action)
                self.main_toolbar.addAction(self.stop_action)
            self._toolbar_compact = compact
        if compact and self.compact_tabs.count() == 0:
            self.compact_tabs.addTab(self.flow_panel, "01 / 流程")
            self.compact_tabs.addTab(self.property_panel, "02 / 参数")
            self.workspace_splitter.hide()
            self.compact_tabs.show()
        elif not compact and self.compact_tabs.count():
            self.compact_tabs.removeTab(1)
            self.compact_tabs.removeTab(0)
            self.workspace_splitter.addWidget(self.flow_panel)
            self.workspace_splitter.addWidget(self.property_panel)
            self.workspace_splitter.setSizes(self._normal_splitter_sizes)
            self.compact_tabs.hide()
            self.workspace_splitter.show()

    def _update_title(self) -> None:
        marker = " *" if self.document.dirty else ""
        path = str(self.document.path) if self.document.path else "尚未保存"
        self.setWindowTitle(f"{self.document.workflow.name}{marker} — AutoForge {__version__} — {path}")
        self.flow_heading.setText(f"{self.document.workflow.name}{marker}   ·   {len(self.document.workflow.steps)} 个步骤")

    def toggle_dark_mode(self, enabled: bool) -> None:
        """Compatibility shim: AutoForge now intentionally has one dark theme."""
        del enabled
        self.dark_mode = True
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(studio_style())
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            status = item.data(STATUS_ROLE) if item else None
            if status:
                self._apply_row_status(row, str(status))

    def _confirm_discard(self) -> bool:
        if not self.document.dirty:
            return True
        result = QMessageBox.question(self, "未保存的修改", "当前流程尚未保存，是否先保存？", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save_document()
        return True

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self.document.close()
        self.document = WorkflowDocument.create()
        self.collapsed_blocks.clear()
        self._reset_history()
        self.log.clear()
        self.refresh_table()
        self._update_variables_action()
        self._update_run_settings_action()
        self._update_title()

    def open_document(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开流程", "", "AutoForge 流程 (*.kmflow)")
        if not path:
            return
        try:
            document = load_document(path)
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
            return
        self.document.close()
        self.document = document
        self.collapsed_blocks.clear()
        self._reset_history()
        self.log.clear()
        self.refresh_table()
        self._update_variables_action()
        self._update_run_settings_action()
        self._update_title()
        self.statusBar().showMessage(f"已打开 {path}", 5000)

    def save_document(self) -> bool:
        if not self.document.path:
            return self.save_as()
        try:
            save_document(self.document, self.document.path)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self._mark_history_saved()
        self._update_title()
        self.statusBar().showMessage("流程已保存", 3000)
        return True

    def _save_from_shortcut(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
            QApplication.processEvents()
        return self.save_document()

    def save_as(self) -> bool:
        default = f"{self.document.workflow.name}.kmflow"
        path, _ = QFileDialog.getSaveFileName(self, "保存流程", default, "AutoForge 流程 (*.kmflow)")
        if not path:
            return False
        previous_name = self.document.workflow.name
        self.document.workflow.name = Path(path).stem
        try:
            saved = save_document(self.document, path)
        except Exception as exc:
            self.document.workflow.name = previous_name
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self._mark_history_saved()
        self._update_title()
        self.refresh_table()
        return True

    def refresh_table(self, selected: int | None = None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.document.workflow.steps))
        tree_prefixes = workflow_tree_prefixes(self.document.workflow.steps)
        for row, step in enumerate(self.document.workflow.steps):
            number = QTableWidgetItem(str(row + 1))
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            breakpoint_marker = "● " if step.breakpoint else ""
            operation = QTableWidgetItem(tree_prefixes[row] + breakpoint_marker + f"[{STEP_LABELS[step.type]}]")
            operation.setToolTip("红点表示断点：运行到此步骤前会暂停" if step.breakpoint else "按 F6 切换断点")
            detail = QTableWidgetItem(f"{step.name}  ·  {step_summary(step)}")
            if step.type in {"if_variable", "if_image", "if_text", "if_else", "if_end", "loop_start", "loop_end"}:
                font = operation.font()
                font.setBold(True)
                operation.setFont(font)
                detail.setFont(font)
            for column, item in enumerate((number, operation, detail), start=1):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            self._install_enable_button(row, step.enabled, step.breakpoint)
        active_ids = {step.id for step in self.document.workflow.steps}
        self.collapsed_blocks.intersection_update(active_ids)
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, False)
        try:
            start_to_end, _end_to_start, _start_to_else, _else_to_start = build_block_map(self.document.workflow.steps)
        except Exception:
            start_to_end = {}
        for start, end in start_to_end.items():
            item = self.table.item(start, 2)
            if item:
                marker = "▶ " if self.document.workflow.steps[start].id in self.collapsed_blocks else "▼ "
                breakpoint_marker = "● " if self.document.workflow.steps[start].breakpoint else ""
                item.setText(tree_prefixes[start] + marker + breakpoint_marker + f"[{STEP_LABELS[self.document.workflow.steps[start].type]}]")
            if self.document.workflow.steps[start].id in self.collapsed_blocks:
                for hidden_row in range(start + 1, end + 1):
                    self.table.setRowHidden(hidden_row, True)
        self.table.blockSignals(False)
        if self.document.workflow.steps:
            row = selected if selected is not None else min(self.table.currentRow(), len(self.document.workflow.steps) - 1)
            row = max(0, row)
            self.table.selectRow(row)
            # Selection may stay on the same row while the workflow object is
            # replaced. Refresh the property editor explicitly in that case.
            self.properties.set_step(self.document.workflow.steps[row])
        else:
            self.properties.set_step(None)
        self._update_clipboard_actions()

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        step = self.document.workflow.steps[row] if 0 <= row < len(self.document.workflow.steps) else None
        self.properties.set_step(step)
        self.selection_index.setText(f"SYS.PARAM // {row + 1:02d}" if step else "SYS.PARAM // --")
        if hasattr(self, "inspector_reveal") and not self.motion_action.isChecked():
            self.inspector_reveal.stop()
            self.inspector_reveal.setStartValue(0.72)
            self.inspector_reveal.setEndValue(1.0)
            self.inspector_reveal.start()
        self._update_clipboard_actions()

    def _install_enable_button(self, row: int, enabled: bool, breakpoint: bool = False) -> None:
        button = PixelStatusButton(enabled, breakpoint=breakpoint)
        button.setToolTip("点击切换这个步骤是否执行")
        button.toggled.connect(lambda checked, r=row: self._toggle_step(r, checked))
        self.table.setCellWidget(row, 0, button)

    def _toggle_step(self, row: int, enabled: bool) -> None:
        if not 0 <= row < len(self.document.workflow.steps):
            return
        step = self.document.workflow.steps[row]
        step.enabled = enabled
        button = self.table.cellWidget(row, 0)
        if isinstance(button, PixelStatusButton) and button.isChecked() != enabled:
            button.setChecked(enabled)
        if row == self.table.currentRow():
            self.properties.loading = True
            self.properties.enabled_check.setChecked(enabled)
            self.properties.loading = False
        self._mark_dirty()

    def _snapshot_workflow(self) -> dict[str, Any]:
        return self.document.workflow.to_dict()

    def _reset_history(self) -> None:
        snapshot = self._snapshot_workflow()
        self.undo_states.clear()
        self.redo_states.clear()
        self._history_current = snapshot
        self._saved_history_state = snapshot
        self.document.dirty = False
        self._update_history_actions()

    def _mark_history_saved(self) -> None:
        snapshot = self._snapshot_workflow()
        self._history_current = snapshot
        self._saved_history_state = snapshot
        self.document.dirty = False
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self.undo_states))
            self.redo_action.setEnabled(bool(self.redo_states))

    @staticmethod
    def _focused_text_editor() -> QLineEdit | QPlainTextEdit | None:
        focus = QApplication.focusWidget()
        return focus if isinstance(focus, (QLineEdit, QPlainTextEdit)) else None

    def undo_context(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.undo()
        else:
            self.undo()

    def redo_context(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.redo()
        else:
            self.redo()

    def copy_context(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.copy()
        else:
            self.copy_steps()

    def cut_context(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.cut()
        else:
            self.cut_steps()

    def paste_context(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.paste()
        else:
            self.paste_steps()

    def delete_context(self) -> None:
        editor = self._focused_text_editor()
        if isinstance(editor, QLineEdit):
            editor.del_()
        elif isinstance(editor, QPlainTextEdit):
            cursor = editor.textCursor()
            cursor.deleteChar()
            editor.setTextCursor(cursor)
        else:
            self.delete_step()

    def _restore_history_state(self, state: dict[str, Any], selected: int) -> None:
        self._restoring_history = True
        try:
            self.document.workflow = Workflow.from_dict(state)
            self._history_current = self._snapshot_workflow()
            self.document.dirty = self._history_current != self._saved_history_state
            self.collapsed_blocks.intersection_update({step.id for step in self.document.workflow.steps})
            self.refresh_table(min(selected, len(self.document.workflow.steps) - 1))
            self._update_variables_action()
            self._update_run_settings_action()
            self._update_title()
        finally:
            self._restoring_history = False
        self._update_history_actions()

    def undo(self) -> None:
        if not self.undo_states:
            self.statusBar().showMessage("没有可撤销的操作", 2500)
            return
        selected = max(0, self.table.currentRow())
        self.redo_states.append(self._snapshot_workflow())
        state = self.undo_states.pop()
        self._restore_history_state(state, selected)
        self.statusBar().showMessage("已撤销上一步操作", 2500)

    def redo(self) -> None:
        if not self.redo_states:
            self.statusBar().showMessage("没有可重做的操作", 2500)
            return
        selected = max(0, self.table.currentRow())
        self.undo_states.append(self._snapshot_workflow())
        state = self.redo_states.pop()
        self._restore_history_state(state, selected)
        self.statusBar().showMessage("已重做操作", 2500)

    def _mark_dirty(self) -> None:
        if not self._restoring_history:
            current = self._snapshot_workflow()
            if current != self._history_current:
                self.undo_states.append(self._history_current)
                if len(self.undo_states) > 100:
                    del self.undo_states[0]
                self.redo_states.clear()
                self._history_current = current
            self.document.dirty = current != self._saved_history_state
        self._update_history_actions()
        self._update_title()

    def _properties_changed(self) -> None:
        row = self.table.currentRow()
        self._mark_dirty()
        self._refresh_row(row)

    def _refresh_row(self, row: int) -> None:
        if not 0 <= row < len(self.document.workflow.steps):
            return
        step = self.document.workflow.steps[row]
        prefix = workflow_tree_prefixes(self.document.workflow.steps)[row]
        marker = ""
        if step.type in {"if_variable", "if_image", "if_text", "loop_start"}:
            marker = "▶ " if step.id in self.collapsed_blocks else "▼ "
        breakpoint_marker = "● " if step.breakpoint else ""
        values = (str(row + 1), prefix + marker + breakpoint_marker + f"[{STEP_LABELS[step.type]}]", f"{step.name}  ·  {step_summary(step)}")
        for column, value in enumerate(values, start=1):
            item = self.table.item(row, column)
            if item:
                item.setText(value)
                if column in {2, 3}:
                    font = item.font()
                    font.setBold(step.type in {"if_variable", "if_image", "if_text", "if_else", "if_end", "loop_start", "loop_end"})
                    item.setFont(font)
        button = self.table.cellWidget(row, 0)
        if isinstance(button, PixelStatusButton):
            button.blockSignals(True)
            button.breakpoint = step.breakpoint
            button.setChecked(step.enabled)
            button._sync_text(step.enabled)
            button.blockSignals(False)

    def add_step(self) -> None:
        dialog = AddStepDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_type() == "run_subflow":
            self.import_subflow()
            return
        row = self.table.currentRow()
        insert_at = row + 1 if row >= 0 else len(self.document.workflow.steps)
        if row >= 0:
            start, end = control_block_span(self.document.workflow.steps, row)
            # A collapsed block hides its children, so inserting at row + 1
            # would place the new step inside that block. Keep the new step at
            # the same level as the collapsed block by inserting after it.
            if self.document.workflow.steps[start].id in self.collapsed_blocks:
                insert_at = end + 1
        created = new_steps_for_type(dialog.selected_type())
        self.document.workflow.steps[insert_at:insert_at] = created
        self._mark_dirty()
        self.refresh_table(insert_at)

    def import_subflow(self, replace: bool = False) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入子流程", "", "AutoForge 流程 (*.kmflow)")
        if not path:
            return
        try:
            imported = load_document(path)
            name = imported.workflow.name
            imported.close()
            reference = self.document.add_asset(path)
        except Exception as exc:
            QMessageBox.warning(self, "无法导入子流程", str(exc))
            return
        if replace and self.properties.step and self.properties.step.type == "run_subflow":
            self.properties.set_asset("subflow", reference)
            return
        row = self.table.currentRow() + 1
        self.document.workflow.steps.insert(row, Step("run_subflow", name=f"调用 · {name}", params={"subflow": reference}))
        self._mark_dirty()
        self.refresh_table(row)

    def _selected_step_indices(self) -> list[int]:
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            row = self.table.currentRow()
            selected_rows = [row] if row >= 0 else []
        steps = self.document.workflow.steps
        selected_indices: set[int] = set()
        for row in selected_rows:
            start, end = control_block_span(steps, row)
            selected_indices.update(range(start, end + 1))
        return sorted(index for index in selected_indices if 0 <= index < len(steps))

    @staticmethod
    def _copy_payloads(payloads: list[dict[str, Any]]) -> list[Step]:
        copies: list[Step] = []
        for payload in payloads:
            copied = Step.from_dict(payload)
            copied.id = Step(copied.type).id
            copies.append(copied)
        return copies

    def _update_clipboard_actions(self) -> None:
        if not hasattr(self, "copy_action"):
            return
        has_steps = bool(self.document.workflow.steps)
        self.copy_action.setEnabled(has_steps)
        self.cut_action.setEnabled(has_steps)
        self.paste_action.setEnabled(bool(self.step_clipboard))

    def copy_steps(self) -> bool:
        indices = self._selected_step_indices()
        if not indices:
            self.statusBar().showMessage("请先选择要复制的步骤", 2500)
            return False
        steps = self.document.workflow.steps
        self.step_clipboard = [steps[index].to_dict() for index in indices]
        self._update_clipboard_actions()
        self.statusBar().showMessage(f"已复制 {len(indices)} 个步骤，可按 Ctrl+V 粘贴", 3500)
        return True

    def paste_steps(self) -> None:
        if not self.step_clipboard:
            self.statusBar().showMessage("步骤剪贴板为空", 2500)
            return
        steps = self.document.workflow.steps
        selected = self._selected_step_indices()
        insert_at = selected[-1] + 1 if selected else len(steps)
        copies = self._copy_payloads(self.step_clipboard)
        steps[insert_at:insert_at] = copies
        self._mark_dirty()
        self.refresh_table(insert_at)
        self.statusBar().showMessage(f"已粘贴 {len(copies)} 个步骤", 3500)

    def cut_steps(self) -> None:
        if self.copy_steps():
            self.delete_step()

    def duplicate_step(self) -> None:
        ordered_indices = self._selected_step_indices()
        if not ordered_indices:
            return
        steps = self.document.workflow.steps
        copies = self._copy_payloads([steps[index].to_dict() for index in ordered_indices])
        copies[0].name = f"{copies[0].name} 副本"
        insert_at = ordered_indices[-1] + 1
        steps[insert_at:insert_at] = copies
        self._mark_dirty()
        self.refresh_table(insert_at)
        self.statusBar().showMessage(f"已复制 {len(copies)} 个步骤", 3500)

    def delete_step(self) -> None:
        indices = self._selected_step_indices()
        if not indices:
            return
        steps = self.document.workflow.steps
        for index in reversed(indices):
            del steps[index]
        self._mark_dirty()
        self.refresh_table(min(indices[0], len(self.document.workflow.steps) - 1))

    def move_step(self, direction: int) -> None:
        row = self.table.currentRow()
        steps = self.document.workflow.steps
        if row < 0:
            return
        start, end = control_block_span(steps, row)
        if direction < 0:
            if start <= 0:
                return
            neighbor_start, neighbor_end = control_block_span(steps, start - 1)
            if neighbor_end >= start:
                return
            block = steps[start : end + 1]
            neighbor = steps[neighbor_start:start]
            steps[neighbor_start : end + 1] = block + neighbor
            new_start = neighbor_start
        else:
            if end >= len(steps) - 1:
                return
            neighbor_start, neighbor_end = control_block_span(steps, end + 1)
            if neighbor_start <= end:
                return
            block = steps[start : end + 1]
            neighbor = steps[end + 1 : neighbor_end + 1]
            steps[start : neighbor_end + 1] = neighbor + block
            new_start = start + len(neighbor)
        self._mark_dirty()
        self.refresh_table(new_start)

    def _drag_move_step(self, source: int, target: int) -> None:
        if source == target or not (0 <= source < len(self.document.workflow.steps)):
            return
        steps = self.document.workflow.steps
        start, end = control_block_span(steps, source)
        if start <= target <= end:
            return
        block = steps[start : end + 1]
        del steps[start : end + 1]
        if target > end:
            new_start = target - len(block) + 1
        else:
            new_start = target
        new_start = min(max(0, new_start), len(steps))
        steps[new_start:new_start] = block
        self._mark_dirty()
        self.refresh_table(new_start)

    def toggle_block_collapsed(self) -> None:
        row = self.table.currentRow()
        start = containing_block_start(self.document.workflow.steps, row)
        if start is None:
            self.statusBar().showMessage("当前步骤不在条件或循环块中", 3500)
            return
        block_id = self.document.workflow.steps[start].id
        if block_id in self.collapsed_blocks:
            self.collapsed_blocks.remove(block_id)
        else:
            self.collapsed_blocks.add(block_id)
        self.refresh_table(start)

    def toggle_breakpoint(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:
            row = self.table.currentRow()
            rows = [row] if row >= 0 else []
        rows = [row for row in rows if 0 <= row < len(self.document.workflow.steps)]
        if not rows:
            self.statusBar().showMessage("请先选择要设置断点的步骤", 2500)
            return
        enable = not all(self.document.workflow.steps[row].breakpoint for row in rows)
        for row in rows:
            self.document.workflow.steps[row].breakpoint = enable
        self._mark_dirty()
        self.refresh_table(rows[0])
        state = "添加" if enable else "取消"
        self.statusBar().showMessage(f"已为 {len(rows)} 个步骤{state}断点", 3000)

    def choose_asset(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择图片素材", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            relative = self.document.add_asset(path)
        except Exception as exc:
            QMessageBox.critical(self, "添加失败", str(exc))
            return
        self.properties.set_asset(key, relative)

    def capture_asset(self, key: str) -> None:
        self.current_asset_key = key
        self.hide()
        QTimer.singleShot(350, self._start_snipper)

    def _asset_path(self, key: str) -> Path:
        step = self.properties.step
        if step is None:
            raise ValueError("请先选择一个步骤")
        reference = str(step.params.get(key, "")).strip()
        if not reference:
            raise ValueError("请先选择或截取图片素材")
        clean = reference.replace("\\", "/").removeprefix("assets/")
        root = self.document.asset_dir.resolve()
        path = (root / clean).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("找不到当前图片素材")
        return path

    def crop_asset(self, key: str) -> None:
        try:
            path = self._asset_path(key)
        except ValueError as exc:
            QMessageBox.information(self, "无法裁剪", str(exc))
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            QMessageBox.critical(self, "无法裁剪", "图片素材无法读取")
            return
        dialog = CropImageDialog(pixmap, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rect = dialog.canvas.source_rect()
        cropped = pixmap.copy(rect)
        name = datetime.now().strftime("crop_%Y%m%d_%H%M%S_%f.png")
        target = self.document.asset_dir / name
        if not cropped.save(str(target), "PNG"):
            QMessageBox.critical(self, "裁剪失败", "无法保存裁剪后的图片素材")
            return

        step = self.properties.step
        if step is None:
            return
        offset_keys = ("target_offset_x", "target_offset_y") if key == "target_image" else ("offset_x", "offset_y")
        if offset_keys[0] in step.params:
            original_click_x = pixmap.width() / 2 + int(step.params.get(offset_keys[0], 0))
            original_click_y = pixmap.height() / 2 + int(step.params.get(offset_keys[1], 0))
            step.params[offset_keys[0]] = round(original_click_x - (rect.x() + rect.width() / 2))
            step.params[offset_keys[1]] = round(original_click_y - (rect.y() + rect.height() / 2))
        self.properties.set_asset(key, f"assets/{name}")
        self.properties.set_step(step)
        self.statusBar().showMessage(f"已保存裁剪素材：{rect.width()}×{rect.height()}，点击偏移已自动校正", 6000)

    def test_asset(self, key: str) -> None:
        try:
            path = self._asset_path(key)
        except ValueError as exc:
            QMessageBox.information(self, "无法测试", str(exc))
            return
        step = self.properties.step
        if step is None:
            return
        self.hide()
        QTimer.singleShot(450, lambda: self._start_asset_test(step, key, path))

    def _start_asset_test(self, step: Step, key: str, path: Path) -> None:
        vision = VisionEngine(lambda level, message: self.append_log(level, message))
        try:
            import cv2

            region = parse_region(step.params.get("region")) if "region" in step.params else None
            scales = parse_scales(step.params.get("scales"))
            threshold = float(step.params.get("confidence", 0.88))
            match, frame = vision.find_image_candidate(path, region, scales)
            success = bool(match and match.confidence >= threshold)
            origin_x, origin_y = (region[0], region[1]) if region else (0, 0)
            click_point: tuple[int, int] | None = None
            if match is not None:
                color = (70, 210, 90) if success else (60, 60, 235)
                x1, y1 = match.x - origin_x, match.y - origin_y
                x2, y2 = x1 + match.width, y1 + match.height
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                offset_keys = ("target_offset_x", "target_offset_y") if key == "target_image" else ("offset_x", "offset_y")
                click_x = match.center[0] + int(step.params.get(offset_keys[0], 0))
                click_y = match.center[1] + int(step.params.get(offset_keys[1], 0))
                click_point = (click_x, click_y)
                cv2.drawMarker(
                    frame,
                    (click_x - origin_x, click_y - origin_y),
                    (30, 220, 255),
                    cv2.MARKER_CROSS,
                    24,
                    2,
                )
                cv2.putText(
                    frame,
                    f"score {match.confidence:.3f}",
                    (max(5, x1), max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                    cv2.LINE_AA,
                )
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError("无法生成识别结果预览")
            pixmap = QPixmap()
            if not pixmap.loadFromData(encoded.tobytes(), "PNG"):
                raise RuntimeError("无法读取识别结果预览")
        except Exception as exc:
            self.showNormal()
            self.activateWindow()
            QMessageBox.critical(self, "识别测试失败", str(exc))
            return
        finally:
            vision.close()

        self.showNormal()
        self.activateWindow()
        if match is None:
            message = f"未找到可比较的候选区域；图片可能大于识别区域。当前阈值：{threshold:.3f}。"
        elif success:
            point_text = f"，实际点击点：({click_point[0]}, {click_point[1]})" if click_point else ""
            message = f"识别成功：置信度 {match.confidence:.3f} ≥ 阈值 {threshold:.3f}{point_text}。绿色框是命中区域，黄色十字是点击点。"
        else:
            message = f"未达到阈值：最佳候选 {match.confidence:.3f} < 阈值 {threshold:.3f}。红框显示最佳候选，可据此调整裁剪或阈值。"
        ImageMatchResultDialog(pixmap, message, success, self).exec()

    def pick_position(self, which: str) -> None:
        self.hide()
        prompt = "点击目标位置" if which == "start" else "点击拖动终点"
        QTimer.singleShot(350, lambda: self._start_position_picker(which, prompt))

    def pick_region(self) -> None:
        self.hide()
        QTimer.singleShot(350, self._start_region_picker)

    def _start_region_picker(self) -> None:
        try:
            self.region_picker = RegionPicker()
        except Exception as exc:
            self.show()
            QMessageBox.critical(self, "框选失败", str(exc))
            return
        self.region_picker.selected.connect(self._region_picked)
        self.region_picker.cancelled.connect(self.show)
        self.region_picker.show()

    def _region_picked(self, x: int, y: int, width: int, height: int) -> None:
        self.show()
        self.activateWindow()
        target = self._configured_target()
        if self.document.workflow.settings.get("coordinate_mode") == "window" and target is None:
            return
        if target is not None:
            x, y = target.local_point(x, y)
            width = max(1, round(width / target.scale_x))
            height = max(1, round(height / target.scale_y))
        self.properties.set_region(x, y, width, height)
        mode = "窗口相对" if target is not None else "屏幕"
        self.statusBar().showMessage(f"已框选{mode}识别区域：{x},{y},{width},{height}", 5000)

    def _start_position_picker(self, which: str, prompt: str) -> None:
        try:
            self.position_picker = PositionPicker(prompt)
        except Exception as exc:
            self.show()
            QMessageBox.critical(self, "取坐标失败", str(exc))
            return
        self.position_picker.picked.connect(lambda x, y: self._position_picked(which, x, y))
        self.position_picker.cancelled.connect(self.show)
        self.position_picker.show()

    def _position_picked(self, which: str, x: int, y: int) -> None:
        self.show()
        self.activateWindow()
        target = self._configured_target()
        if self.document.workflow.settings.get("coordinate_mode") == "window" and target is None:
            return
        if target is not None:
            x, y = target.local_point(x, y)
        self.properties.set_position(which, x, y)
        mode = "窗口相对" if target is not None else "屏幕"
        self.statusBar().showMessage(f"已取得{mode}坐标 X={x}, Y={y}", 4000)

    def _configured_target(self) -> TargetTransform | None:
        if self.document.workflow.settings.get("coordinate_mode") != "window":
            return None
        settings = dict(self.document.workflow.settings)
        settings["target_window_activate"] = False
        settings["target_window_wait"] = 0
        try:
            return resolve_target(settings, service=WindowService())
        except WindowTargetError as exc:
            QMessageBox.warning(self, "目标窗口不可用", f"{exc}\n请先打开目标窗口，或在“运行设置”中重新选择。")
            return None

    def _start_snipper(self) -> None:
        try:
            self.snipper = ScreenSnipper()
        except Exception as exc:
            self.show()
            QMessageBox.critical(self, "截图失败", str(exc))
            return
        self.snipper.captured.connect(self._captured)
        self.snipper.cancelled.connect(self.show)
        self.snipper.show()

    def _captured(self, pixmap: QPixmap) -> None:
        name = datetime.now().strftime("capture_%Y%m%d_%H%M%S_%f.png")
        target = self.document.asset_dir / name
        if not pixmap.save(str(target), "PNG"):
            self.show()
            QMessageBox.critical(self, "截图失败", "无法保存截图素材")
            return
        self.document.dirty = True
        self.show()
        self.activateWindow()
        self.properties.set_asset(self.current_asset_key, f"assets/{name}")

    def append_log(self, level: str, message: str) -> None:
        labels = {"info": "信息", "warning": "警告", "error": "错误", "success": "完成", "debug": "调试"}
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] [{labels.get(level, level)}] {message}")

    def _update_variables_action(self) -> None:
        count = len(self.document.workflow.variables)
        self.variables_action.setText(f"初始变量：{count}")
        self.variables_action.setToolTip("每次运行开始时载入；运行中请使用“运行时设置变量”步骤修改")

    def edit_variables(self) -> None:
        dialog = VariableEditorDialog(self.document.workflow.variables, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.document.workflow.variables = dialog.result_variables
        self._mark_dirty()
        self._update_variables_action()
        self.statusBar().showMessage(f"已保存 {len(dialog.result_variables)} 个流程初始变量", 4000)

    def _update_run_settings_action(self) -> None:
        repeat_count = max(1, int(self.document.workflow.settings.get("repeat_count", 1)))
        target_label = "窗口" if self.document.workflow.settings.get("coordinate_mode") == "window" else "屏幕"
        self.run_settings_action.setText(f"运行设置：{repeat_count} 次 · {target_label}")
        backend = "Windows SendInput" if self.document.workflow.settings.get("input_backend") == "sendinput" else "PyAutoGUI"
        target = str(self.document.workflow.settings.get("target_window_title", "")).strip() or "整个屏幕"
        self.run_settings_action.setToolTip(f"设置运行次数、输入后端和目标窗口；当前：{backend} · {target}")

    def edit_run_settings(self) -> None:
        settings = self.document.workflow.settings
        dialog = RunSettingsDialog(
            int(settings.get("repeat_count", 1)),
            float(settings.get("repeat_delay", 0.0)),
            str(settings.get("input_backend", "pyautogui")),
            self,
            settings=settings,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings["repeat_count"] = dialog.repeat_count.value()
        settings["repeat_delay"] = dialog.repeat_delay.value()
        settings["input_backend"] = str(dialog.input_backend.currentData())
        settings["coordinate_mode"] = str(dialog.coordinate_mode.currentData())
        settings["target_window_title"] = dialog.target_window_title.currentText().strip()
        settings["target_window_activate"] = dialog.target_activate.isChecked()
        settings["target_window_wait"] = dialog.target_wait.value()
        settings["target_window_base_width"] = dialog.target_base_width.value()
        settings["target_window_base_height"] = dialog.target_base_height.value()
        self._mark_dirty()
        self._update_run_settings_action()
        self.statusBar().showMessage(
            f"运行设置已更新：{dialog.repeat_count.value()} 次，输入后端 {dialog.input_backend.currentText()}，坐标模式 {dialog.coordinate_mode.currentText()}",
            5000,
        )

    def toggle_recording(self) -> None:
        if self.input_recorder is not None:
            self.finish_recording()
            return
        if self.runner_thread and self.runner_thread.isRunning():
            return
        QMessageBox.information(
            self,
            "操作录制",
            "窗口最小化后开始录制。请切换到目标程序完成一次操作流程。\n\n"
            "可录制：鼠标点击、拖动、滚轮、连续文字、单键、组合键和较长停顿。点击前会自动截取目标。\n"
            "完成后按 F8 结束录制，生成的步骤会插入到当前选中步骤之后。",
        )
        row = self.table.currentRow()
        self.recording_insert_at = row + 1 if row >= 0 else len(self.document.workflow.steps)
        self.input_recorder = InputRecorder(self.recording_bridge.stop_requested.emit)
        self.record_action.setText("■ 结束录制（F8）")
        self.run_action.setEnabled(False)
        self.statusBar().showMessage("操作录制中；按 F8 结束")
        self.showMinimized()
        QTimer.singleShot(600, self._begin_recording)

    def _begin_recording(self) -> None:
        if self.input_recorder is None:
            return
        try:
            self.input_recorder.start()
        except Exception as exc:
            self.input_recorder = None
            self.record_action.setText("● 录制")
            self.run_action.setEnabled(True)
            self.showNormal()
            self.activateWindow()
            QMessageBox.critical(self, "无法开始录制", str(exc))

    def finish_recording(self) -> None:
        recorder = self.input_recorder
        if recorder is None:
            return
        self.input_recorder = None
        recorder.stop()
        actions = recorder.actions
        self.record_action.setText("● 录制")
        self.run_action.setEnabled(True)
        self.showNormal()
        self.activateWindow()
        if not actions:
            self.statusBar().showMessage("录制已结束，没有捕获到可生成的操作", 5000)
            return
        preview = RecordingPreviewDialog(actions, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("已取消生成录制步骤", 5000)
            return
        actions = preview.actions
        if preview.prefer_images.isChecked():
            self._save_recorded_click_images(actions)
        count = self._insert_recorded_actions(
            actions,
            prefer_click_images=preview.prefer_images.isChecked(),
            include_waits=preview.include_waits.isChecked(),
        )
        if count == 0:
            self.statusBar().showMessage("没有保留可生成的录制操作", 5000)
            return
        self.append_log("success", f"录制结束，已生成 {count} 个步骤")
        self.statusBar().showMessage(f"录制完成：已生成 {count} 个步骤，请检查后保存", 7000)

    def _save_recorded_click_images(self, actions: list[RecordedAction]) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for index, action in enumerate(actions, start=1):
            payload = action.data.get("image_png")
            if action.kind != "click" or not isinstance(payload, bytes):
                continue
            name = f"record_click_{stamp}_{index:03d}.png"
            try:
                (self.document.asset_dir / name).write_bytes(payload)
            except OSError as exc:
                self.append_log("warning", f"无法保存第 {index} 个点击目标截图，将使用坐标：{exc}")
                continue
            action.data["image"] = f"assets/{name}"

    def _insert_recorded_actions(
        self,
        actions: list[RecordedAction],
        *,
        prefer_click_images: bool = False,
        include_waits: bool = True,
    ) -> int:
        converted_actions = [
            RecordedAction(action.kind, action.started_at, action.ended_at, dict(action.data))
            for action in actions
        ]
        if self.document.workflow.settings.get("coordinate_mode") == "window":
            target = self._configured_target()
            if target is None:
                return 0
            for action in converted_actions:
                for x_key, y_key in (("x", "y"), ("x2", "y2")):
                    if x_key in action.data and y_key in action.data:
                        action.data[x_key], action.data[y_key] = target.local_point(
                            int(action.data[x_key]), int(action.data[y_key])
                        )
        steps = recorded_actions_to_steps(
            converted_actions,
            include_waits=include_waits,
            prefer_click_images=prefer_click_images,
        )
        if not steps:
            return 0
        insert_at = min(max(0, self.recording_insert_at), len(self.document.workflow.steps))
        self.document.workflow.steps[insert_at:insert_at] = steps
        self._mark_dirty()
        self.refresh_table(insert_at)
        return len(steps)

    def _history_store(self) -> RunHistoryStore:
        if self._run_history_store is None:
            database = Path(__file__).resolve().parent.parent / "data" / "run_history.db"
            self._run_history_store = RunHistoryStore(database)
            abandoned = self._run_history_store.mark_abandoned_runs()
            if abandoned:
                self.append_log("warning", f"已将 {abandoned} 条未结束记录标记为异常中断")
        return self._run_history_store

    def show_run_history(self) -> None:
        try:
            dialog = RunHistoryDialog(self._history_store(), self)
        except Exception as exc:
            QMessageBox.warning(self, "无法打开运行历史", str(exc))
            return
        dialog.exec()

    def _start_run_history(self) -> None:
        repeat_count = max(1, int(self.document.workflow.settings.get("repeat_count", 1)))
        workflow_path = str(self.document.path) if self.document.path else ""
        try:
            self.current_run_id = self._history_store().start_run(
                self.document.workflow.name,
                workflow_path,
                len(self.document.workflow.steps),
                repeat_count,
            )
        except Exception as exc:
            self.current_run_id = None
            self.append_log("warning", f"无法写入运行历史，但流程仍会继续：{exc}")

    def _finish_run_history(self, status: str) -> None:
        if self.current_run_id is None:
            return
        thread = self.runner_thread
        history_status = status
        failure_step: int | None = None
        error_message = ""
        screenshot_path = ""
        if thread is not None:
            if thread.failure_step >= 0:
                failure_step = thread.failure_step + 1
            error_message = thread.last_error
            if thread.failure_screenshot is not None:
                screenshot_path = str(thread.failure_screenshot)
            if status == "done" and thread.failure_step >= 0:
                history_status = "done_with_errors"
        run_id = self.current_run_id
        self.current_run_id = None
        try:
            self._history_store().finish_run(
                run_id,
                history_status,
                failure_step=failure_step,
                error_message=error_message,
                screenshot_path=screenshot_path,
            )
        except Exception as exc:
            self.append_log("warning", f"无法完成运行历史记录：{exc}")

    def _raw_selected_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        return [row for row in rows if 0 <= row < len(self.document.workflow.steps)]

    def check_workflow(self) -> bool:
        errors = preflight_workflow(self.document.workflow, self.document.asset_dir)
        if errors:
            QMessageBox.warning(self, "运行前检查未通过", "\n".join(f"• {item}" for item in errors))
            return False
        target_text = ""
        if self.document.workflow.settings.get("coordinate_mode") == "window":
            target = self._configured_target()
            if target is None:
                return False
            target_text = f"\n目标窗口：{target.title}（{target.width}×{target.height}）"
        QMessageBox.information(self, "运行前检查", f"流程结构、素材引用和运行设置检查通过。{target_text}")
        return True

    def run_current_step(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        start, end = control_block_span(self.document.workflow.steps, row)
        self._start_workflow(RunPlan("current", start, end))

    def run_from_here(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            start, end = normalize_run_span(self.document.workflow.steps, row, len(self.document.workflow.steps) - 1)
            self._start_workflow(RunPlan("from", start, end))

    def run_to_here(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            start, end = normalize_run_span(self.document.workflow.steps, 0, row)
            self._start_workflow(RunPlan("to", start, end))

    def run_selected_steps(self) -> None:
        self._start_workflow(RunPlan("selected", selected=tuple(self._raw_selected_rows())))

    def safe_test_steps(self) -> None:
        rows = self._raw_selected_rows()
        if len(rows) == 1 and self.document.workflow.steps[rows[0]].type in set(BLOCK_PAIRS) | BLOCK_END_TYPES | {"if_else"}:
            start, end = control_block_span(self.document.workflow.steps, rows[0])
            self._start_workflow(RunPlan("current", start, end, dry_run=True))
        else:
            self._start_workflow(RunPlan("selected", selected=tuple(rows), dry_run=True))

    def run_workflow(self) -> None:
        self._start_workflow(RunPlan())

    def _start_workflow(self, plan: RunPlan) -> None:
        if self.runner_thread and self.runner_thread.isRunning():
            return
        if not self.document.workflow.steps:
            QMessageBox.information(self, "没有步骤", "请先添加至少一个步骤。")
            return
        errors = preflight_workflow(self.document.workflow, self.document.asset_dir, plan)
        if errors:
            QMessageBox.warning(self, "运行前检查未通过", "\n".join(f"• {item}" for item in errors))
            return
        self._clear_step_statuses()
        self.current_run_plan = plan
        self.field_strip.report(f"{plan.label} · F9 紧急停止", 0.0)
        failure_dir = Path(__file__).resolve().parent.parent / "data" / "failures"
        self.runner_thread = RunnerThread(self.document, failure_dir, plan)
        self.runner_thread.log_message.connect(self.append_log)
        self.runner_thread.step_status.connect(self._set_step_status)
        self.runner_thread.debug_paused.connect(self._debug_paused)
        self.runner_thread.run_ended.connect(self._run_ended)
        try:
            self.emergency_hotkey.start()
        except RuntimeError as exc:
            self.append_log("warning", str(exc))
        self.record_action.setEnabled(False)
        self.run_action.setEnabled(False)
        for action in self.local_run_actions:
            action.setEnabled(False)
        self.debug_paused_state = False
        self.pause_action.setText("⏸ 暂停")
        self.pause_action.setEnabled(True)
        self.step_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        repeat_count = max(1, int(self.document.workflow.settings.get("repeat_count", 1))) if plan.mode == "full" else 1
        repeat_text = f"，共 {repeat_count} 轮" if repeat_count > 1 else ""
        self._start_run_history()
        self.statusBar().showMessage(f"{plan.label}中{repeat_text}；按 F9 或把鼠标移到屏幕左上角可紧急停止")
        self.showMinimized()
        QTimer.singleShot(450, self._begin_runner)

    def _begin_runner(self) -> None:
        if self.runner_thread and not self.runner_thread.isRunning():
            self.runner_thread.start()

    def stop_workflow(self) -> None:
        if self.runner_thread:
            self.runner_thread.request_stop()
            self.statusBar().showMessage("正在停止……")

    def toggle_pause_workflow(self) -> None:
        if not self.runner_thread or not self.runner_thread.isRunning():
            return
        if self.debug_paused_state:
            self.debug_paused_state = False
            self.pause_action.setText("⏸ 暂停")
            self.step_action.setEnabled(False)
            self.showMinimized()
            self.runner_thread.resume_workflow()
            self.statusBar().showMessage("流程已继续运行")
        else:
            self.runner_thread.request_pause()
            self.pause_action.setText("等待暂停……")
            self.statusBar().showMessage("将在当前步骤完成后暂停")

    def step_workflow(self) -> None:
        if not self.runner_thread or not self.debug_paused_state:
            return
        self.debug_paused_state = False
        self.pause_action.setText("⏸ 暂停")
        self.step_action.setEnabled(False)
        self.showMinimized()
        self.runner_thread.step_once()

    def _debug_paused(self, row: int) -> None:
        self.debug_paused_state = True
        self.pause_action.setText("▶ 继续")
        self.pause_action.setEnabled(True)
        self.step_action.setEnabled(True)
        self.showNormal()
        self.activateWindow()
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 1))
        self.statusBar().showMessage(f"已在步骤 {row + 1} 前暂停；F7 继续，F10 单步")

    def _emergency_stop_workflow(self) -> None:
        if self.runner_thread:
            self.append_log("warning", "收到全局 F9 紧急停止请求")
            self.runner_thread.request_stop()
            self.statusBar().showMessage("F9 紧急停止：正在终止流程……")

    def _set_step_status(self, row: int, status: str) -> None:
        if 0 <= row < self.table.rowCount():
            labels = {"running": "执行中", "paused": "断点暂停", "done": "步骤完成", "failed": "步骤失败", "skipped": "已跳过"}
            self.field_strip.report(f"{labels.get(status, status)} · 步骤位置 {row + 1:02d} / {self.table.rowCount():02d}", (row + 1) / self.table.rowCount())
            self._apply_row_status(row, status)
            self.table.scrollToItem(self.table.item(row, 1))

    def _apply_row_status(self, row: int, status: str) -> None:
        background, foreground = STATUS_COLORS.get(status, (QColor(), QColor()))
        button = self.table.cellWidget(row, 0)
        if isinstance(button, PixelStatusButton):
            button.set_runtime_status(status)
        for column in range(1, self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setData(STATUS_ROLE, status)
                item.setBackground(background)
                item.setForeground(foreground)

    def _clear_step_statuses(self) -> None:
        for row in range(self.table.rowCount()):
            button = self.table.cellWidget(row, 0)
            if isinstance(button, PixelStatusButton):
                button.set_runtime_status(None)
            for column in range(1, self.table.columnCount()):
                item = self.table.item(row, column)
                if item:
                    item.setData(STATUS_ROLE, None)
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def _run_ended(self, status: str) -> None:
        self.emergency_hotkey.stop()
        display_status = status
        if status == "done" and self.runner_thread is not None and self.runner_thread.failure_step >= 0:
            display_status = "done_with_errors"
        self._finish_run_history(status)
        self.debug_paused_state = False
        self.record_action.setEnabled(True)
        self.run_action.setEnabled(True)
        for action in self.local_run_actions:
            action.setEnabled(True)
        self.pause_action.setText("⏸ 暂停")
        self.pause_action.setEnabled(False)
        self.step_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        labels = {
            "done": "运行完成",
            "done_with_errors": "运行完成，但有步骤失败，请查看日志或运行历史",
            "failed": "运行失败，请查看日志或运行历史",
            "stopped": "流程已停止",
        }
        self.statusBar().showMessage(labels.get(display_status, display_status), 6000)
        self.field_strip.report(labels.get(display_status, display_status))
        self.showNormal()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.emergency_hotkey.stop()
        if self.input_recorder is not None:
            self.input_recorder.stop()
            self.input_recorder = None
        if self.runner_thread and self.runner_thread.isRunning():
            self.runner_thread.request_stop()
            if not self.runner_thread.wait(2000):
                QMessageBox.warning(self, "仍在停止", "流程仍在停止中，请稍后再关闭。")
                event.ignore()
                return
        if not self._confirm_discard():
            event.ignore()
            return
        if self.persist_settings:
            self.settings.setValue("geometry", self.saveGeometry())
        self.document.close()
        event.accept()


def run_app() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("AutoForge")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("KeyMouse")
    window = MainWindow()
    window.show()
    return app.exec()
