from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import Step, Workflow
from .window_target import TargetTransform, WindowService, WindowTargetError, resolve_target


LogCallback = Callable[[str, str], None]
StepCallback = Callable[[int, str], None]
PauseCallback = Callable[[int], None]
FailureCallback = Callable[[int, Step, Exception], None]


class AutomationError(RuntimeError):
    pass


class StopRequested(AutomationError):
    pass


@dataclass(frozen=True)
class RunPlan:
    mode: str = "full"
    start: int = 0
    end: int | None = None
    selected: tuple[int, ...] = ()
    dry_run: bool = False

    @property
    def label(self) -> str:
        labels = {
            "full": "完整运行",
            "current": "运行当前步骤",
            "from": "从此处运行",
            "to": "运行到此处",
            "selected": "运行所选步骤",
        }
        prefix = "安全测试 · " if self.dry_run else ""
        return prefix + labels.get(self.mode, self.mode)


@dataclass
class Match:
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


def parse_region(value: Any) -> tuple[int, int, int, int] | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        result = tuple(int(item) for item in value)
    else:
        parts = [part.strip() for part in str(value).replace(";", ",").split(",")]
        if len(parts) != 4:
            raise AutomationError("识别区域应为 x,y,宽,高")
        result = tuple(int(part) for part in parts)
    if result[2] <= 0 or result[3] <= 0:
        raise AutomationError("识别区域的宽和高必须大于 0")
    return result  # type: ignore[return-value]


def parse_scales(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        scales = [float(item) for item in value]
    else:
        scales = [float(item.strip()) for item in str(value or "1.0").split(",") if item.strip()]
    scales = [item for item in scales if 0.25 <= item <= 4.0]
    return scales or [1.0]


CONDITION_STARTS = {"if_variable", "if_image", "if_text"}
BLOCK_PAIRS = {**{name: "if_end" for name in CONDITION_STARTS}, "loop_start": "loop_end"}
BLOCK_END_TYPES = {"if_end", "loop_end"}


def build_block_map(
    steps: list[Step],
) -> tuple[dict[int, int], dict[int, int], dict[int, int], dict[int, int]]:
    """Validate nested control blocks and return start/end index maps."""
    stack: list[tuple[str, int]] = []
    start_to_end: dict[int, int] = {}
    end_to_start: dict[int, int] = {}
    start_to_else: dict[int, int] = {}
    else_to_start: dict[int, int] = {}
    for index, step in enumerate(steps):
        if step.type in BLOCK_PAIRS:
            stack.append((step.type, index))
        elif step.type == "if_else":
            if not stack or stack[-1][0] not in CONDITION_STARTS:
                raise AutomationError(f"步骤 {index + 1} 的“{step.name}”没有对应的条件开始")
            _start_type, start_index = stack[-1]
            if start_index in start_to_else:
                raise AutomationError(f"步骤 {index + 1} 的“{step.name}”所在条件已经有一个否则分支")
            start_to_else[start_index] = index
            else_to_start[index] = start_index
        elif step.type in BLOCK_END_TYPES:
            valid_start = bool(stack) and (
                (step.type == "if_end" and stack[-1][0] in CONDITION_STARTS)
                or (step.type == "loop_end" and stack[-1][0] == "loop_start")
            )
            if not valid_start:
                raise AutomationError(f"步骤 {index + 1} 的“{step.name}”没有对应的开始步骤")
            _start_type, start_index = stack.pop()
            start_to_end[start_index] = index
            end_to_start[index] = start_index
    if stack:
        _start_type, start_index = stack[-1]
        raise AutomationError(f"步骤 {start_index + 1} 的“{steps[start_index].name}”缺少结束步骤")
    return start_to_end, end_to_start, start_to_else, else_to_start


def normalize_run_span(steps: list[Step], start: int, end: int) -> tuple[int, int]:
    """Expand a partial range until it contains every intersected control block."""
    if not steps:
        return 0, -1
    start = min(max(0, start), len(steps) - 1)
    end = min(max(start, end), len(steps) - 1)
    start_to_end, _end_to_start, _start_to_else, _else_to_start = build_block_map(steps)
    changed = True
    while changed:
        changed = False
        for block_start, block_end in start_to_end.items():
            if block_end < start or block_start > end:
                continue
            new_start, new_end = min(start, block_start), max(end, block_end)
            if (new_start, new_end) != (start, end):
                start, end, changed = new_start, new_end, True
    return start, end


def preflight_workflow(workflow: Workflow, asset_dir: Path, plan: RunPlan | None = None) -> list[str]:
    """Return actionable errors before minimizing the editor or sending input."""
    plan = plan or RunPlan()
    errors: list[str] = []
    try:
        build_block_map(workflow.steps)
    except AutomationError as exc:
        errors.append(str(exc))
    if not workflow.steps:
        errors.append("流程没有步骤")
        return errors
    if workflow.settings.get("coordinate_mode") == "window" and not str(workflow.settings.get("target_window_title", "")).strip():
        errors.append("窗口相对坐标模式尚未设置目标窗口")

    if plan.mode == "selected":
        indices = sorted(set(plan.selected))
        if not indices:
            errors.append("没有选择要运行的步骤")
        control_types = set(BLOCK_PAIRS) | BLOCK_END_TYPES | {"if_else"}
        if any(0 <= index < len(workflow.steps) and workflow.steps[index].type in control_types for index in indices):
            errors.append("所选步骤包含条件或循环标记；请改用“从此处运行”或“运行到此处”")
    elif plan.mode != "full" and not (0 <= plan.start < len(workflow.steps)):
        errors.append("局部运行的起始步骤无效")

    if plan.mode == "selected":
        relevant_indices = sorted({index for index in plan.selected if 0 <= index < len(workflow.steps)})
    elif plan.mode == "full":
        relevant_indices = list(range(len(workflow.steps)))
    else:
        start, end = normalize_run_span(workflow.steps, plan.start, plan.end if plan.end is not None else plan.start)
        relevant_indices = list(range(start, end + 1))

    image_keys = {
        "click_image": ("image",), "wait_image": ("image",), "wait_image_gone": ("image",),
        "drag_image_to_position": ("image",), "drag_position_to_image": ("target_image",),
        "drag_image": ("image", "target_image"), "if_image": ("image",), "run_subflow": ("subflow",),
    }
    for index in relevant_indices:
        step = workflow.steps[index]
        if not step.enabled:
            continue
        for key in image_keys.get(step.type, ()):
            reference = str(step.params.get(key, "")).strip()
            label = "子流程" if key == "subflow" else "图片"
            if not reference:
                errors.append(f"步骤 {index + 1}“{step.name}”缺少{label}")
                continue
            clean = reference.replace("\\", "/").removeprefix("assets/")
            path = (asset_dir / clean).resolve()
            if asset_dir.resolve() not in path.parents or not path.is_file():
                errors.append(f"步骤 {index + 1}“{step.name}”的{label}不存在：{reference}")
        if "region" in step.params:
            try:
                parse_region(step.params.get("region"))
            except AutomationError as exc:
                errors.append(f"步骤 {index + 1}“{step.name}”：{exc}")
        if step.type in {"click_text", "wait_text", "wait_text_gone", "if_text"} and not str(step.params.get("text", "")).strip():
            errors.append(f"步骤 {index + 1}“{step.name}”缺少 OCR 文字")
    return errors


class VisionEngine:
    """Fast screenshot and deterministic image/OCR location services."""

    def __init__(self, log: LogCallback | None = None) -> None:
        self.log = log or (lambda _level, _message: None)
        self._camera: Any = None
        self._template_cache: dict[tuple[str, int], Any] = {}
        self._ocr: Any = None

    @staticmethod
    def _imports() -> tuple[Any, Any]:
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise AutomationError("缺少图像识别组件，请运行：pip install -r requirements.txt") from exc
        return cv2, np

    def capture(self, region: tuple[int, int, int, int] | None = None) -> Any:
        _, np = self._imports()
        if self._camera is not False:
            try:
                if self._camera is None:
                    import dxcam

                    self._camera = dxcam.create(output_color="BGR")
                    self._camera.start(target_fps=30, video_mode=True)
                frame = self._camera.get_latest_frame()
                if frame is not None:
                    if region:
                        x, y, width, height = region
                        if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
                            raise AutomationError("识别区域位于 DXcam 当前屏幕之外")
                        frame = frame[y : y + height, x : x + width]
                        if frame.size == 0:
                            raise AutomationError("识别区域超出屏幕范围")
                    # DXcam uses a ring buffer. Detach the frame so OpenCV never
                    # keeps reading a slot while the capture thread overwrites it.
                    return frame.copy()
            except Exception as exc:
                self.log("warning", f"DXcam 不可用，已切换普通截图：{exc}")
                self._camera = False
        try:
            import pyautogui

            screenshot = pyautogui.screenshot(region=region)
            rgb = np.asarray(screenshot)
            return rgb[:, :, ::-1].copy()
        except ImportError as exc:
            raise AutomationError("缺少截图组件 PyAutoGUI") from exc

    def close(self) -> None:
        if self._camera not in (None, False):
            try:
                self._camera.stop()
            except Exception:
                pass
        self._camera = None

    def _read_template(self, path: Path) -> Any:
        cv2, np = self._imports()
        if not path.is_file():
            raise AutomationError(f"找不到图片素材：{path.name}")
        key = (str(path.resolve()), path.stat().st_mtime_ns)
        if key not in self._template_cache:
            encoded = np.fromfile(path, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if image is None:
                raise AutomationError(f"无法读取图片素材：{path.name}")
            self._template_cache = {k: v for k, v in self._template_cache.items() if k[0] != key[0]}
            self._template_cache[key] = image
        return self._template_cache[key]

    def find_image(
        self,
        path: Path,
        confidence: float = 0.88,
        region: tuple[int, int, int, int] | None = None,
        scales: list[float] | None = None,
    ) -> Match | None:
        best, _screen = self.find_image_candidate(path, region, scales)
        return best if best and best.confidence >= confidence else None

    def find_image_candidate(
        self,
        path: Path,
        region: tuple[int, int, int, int] | None = None,
        scales: list[float] | None = None,
    ) -> tuple[Match | None, Any]:
        """Return the best candidate and captured frame, even below the execution threshold."""
        screen = self.capture(region)
        return self.match_image_on_frame(screen, path, region, scales), screen

    def match_image_on_frame(
        self,
        screen: Any,
        path: Path,
        region: tuple[int, int, int, int] | None = None,
        scales: list[float] | None = None,
    ) -> Match | None:
        cv2, _ = self._imports()
        template = self._read_template(path)
        best: Match | None = None
        origin_x, origin_y = (region[0], region[1]) if region else (0, 0)
        gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        for scale in scales or [1.0]:
            if scale == 1.0:
                candidate = template
            else:
                width = max(1, round(template.shape[1] * scale))
                height = max(1, round(template.shape[0] * scale))
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                candidate = cv2.resize(template, (width, height), interpolation=interpolation)
            height, width = candidate.shape[:2]
            if height > gray_screen.shape[0] or width > gray_screen.shape[1] or height < 2 or width < 2:
                continue
            gray_template = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(gray_screen, gray_template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            match = Match(origin_x + location[0], origin_y + location[1], width, height, float(score))
            if best is None or match.confidence > best.confidence:
                best = match
        return best

    def _get_ocr(self) -> Any:
        if self._ocr is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise AutomationError("OCR 未安装，请运行：pip install -r requirements-ocr.txt") from exc
            self._ocr = RapidOCR()
        return self._ocr

    def find_text(
        self,
        query: str,
        region: tuple[int, int, int, int] | None = None,
        match_mode: str = "contains",
    ) -> Match | None:
        image = self.capture(region)
        result = self._get_ocr()(image)
        items: list[tuple[Any, str, float]] = []
        if hasattr(result, "boxes"):
            boxes = getattr(result, "boxes", None)
            texts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            boxes = [] if boxes is None else boxes
            texts = [] if texts is None else texts
            scores = [] if scores is None else scores
            items = list(zip(boxes, texts, scores))
        elif isinstance(result, tuple) and result and result[0]:
            items = [(item[0], str(item[1]), float(item[2])) for item in result[0]]
        origin_x, origin_y = (region[0], region[1]) if region else (0, 0)
        for box, text, score in items:
            matched = text == query if match_mode == "exact" else query in text
            if not matched:
                continue
            xs = [int(point[0]) for point in box]
            ys = [int(point[1]) for point in box]
            return Match(origin_x + min(xs), origin_y + min(ys), max(xs) - min(xs), max(ys) - min(ys), float(score))
        return None


class AutomationRunner:
    def __init__(
        self,
        workflow: Workflow,
        asset_dir: Path,
        log: LogCallback | None = None,
        step_changed: StepCallback | None = None,
        paused: PauseCallback | None = None,
        failure: FailureCallback | None = None,
        plan: RunPlan | None = None,
        window_service: WindowService | None = None,
        target: TargetTransform | None = None,
    ) -> None:
        self.workflow = workflow
        self.asset_dir = asset_dir
        self.log = log or (lambda _level, _message: None)
        self.step_changed = step_changed or (lambda _index, _status: None)
        self.paused = paused or (lambda _index: None)
        self.failure = failure or (lambda _index, _step, _error: None)
        self.stop_event = threading.Event()
        self._debug_condition = threading.Condition()
        self._pause_requested = False
        self._debug_command: str | None = None
        self._step_budget: int | None = None
        self.current_index = -1
        self.vision = VisionEngine(self.log)
        self.variables = dict(workflow.variables)
        self.active_child: AutomationRunner | None = None
        self.call_depth = 0
        self.plan = plan or RunPlan()
        self.window_service = window_service
        self.target = target

    def stop(self) -> None:
        self.stop_event.set()
        if self.active_child:
            self.active_child.stop()
        with self._debug_condition:
            self._debug_condition.notify_all()

    def request_pause(self) -> None:
        if self.active_child:
            self.active_child.request_pause()
            return
        with self._debug_condition:
            self._pause_requested = True

    def resume(self) -> None:
        if self.active_child:
            self.active_child.resume()
            return
        with self._debug_condition:
            self._debug_command = "run"
            self._debug_condition.notify_all()

    def step_once(self) -> None:
        if self.active_child:
            self.active_child.step_once()
            return
        with self._debug_condition:
            self._debug_command = "step"
            self._debug_condition.notify_all()

    def _debug_gate(self, index: int, step: Step) -> None:
        with self._debug_condition:
            should_pause = self._pause_requested or self._step_budget == 0 or (step.enabled and step.breakpoint)
            if should_pause:
                self._pause_requested = False
                self._debug_command = None
                self.step_changed(index, "paused")
                self.paused(index)
                while self._debug_command is None and not self.stop_event.is_set():
                    self._debug_condition.wait(timeout=0.1)
                self._check_stop()
                command = self._debug_command
                self._debug_command = None
                self._step_budget = 1 if command == "step" else None
            if self._step_budget is not None:
                self._step_budget -= 1

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested("用户已停止流程")

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self._check_stop()
            time.sleep(min(0.05, deadline - time.monotonic()))

    def _asset(self, name: str) -> Path:
        clean = name.replace("\\", "/").removeprefix("assets/")
        path = (self.asset_dir / clean).resolve()
        if self.asset_dir.resolve() not in path.parents:
            raise AutomationError("非法图片素材路径")
        return path

    def _substitute(self, value: Any) -> str:
        text = str(value)
        return re.sub(r"\$\{([^}]+)}", lambda match: str(self.variables.get(match.group(1), match.group(0))), text)

    def _input(self) -> Any:
        if self.workflow.settings.get("input_backend") == "sendinput":
            from .input_backend import WindowsSendInputBackend

            return WindowsSendInputBackend(self._sleep)
        try:
            import pyautogui
        except ImportError as exc:
            raise AutomationError("缺少鼠标键盘组件 PyAutoGUI") from exc
        return pyautogui

    def _point(self, x: Any, y: Any) -> tuple[int, int]:
        point = (int(x or 0), int(y or 0))
        return self.target.point(*point) if self.target else point

    def _region(self, value: Any) -> tuple[int, int, int, int] | None:
        region = parse_region(value)
        return self.target.region(region) if self.target else region

    def _wait_match(self, finder: Callable[[], Match | None], timeout: float, want_present: bool = True, interval: float = 0.15) -> Match | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self._check_stop()
            match = finder()
            if bool(match) == want_present:
                if want_present and match is not None:
                    # Confirm on a second fresh frame and use its coordinates.
                    # This avoids clicking the previous position immediately
                    # after a remote-desktop element has moved.
                    self._sleep(min(max(interval, 0.03), 0.08))
                    confirmed = finder()
                    if confirmed is None:
                        continue
                    return confirmed
                return match
            if time.monotonic() >= deadline:
                state = "出现" if want_present else "消失"
                raise AutomationError(f"等待目标{state}超时")
            self._sleep(interval)

    def run(self) -> None:
        errors = preflight_workflow(self.workflow, self.asset_dir, self.plan)
        if errors:
            raise AutomationError("运行前检查失败：\n" + "\n".join(f"- {item}" for item in errors))
        if self.target is None:
            try:
                self.target = resolve_target(
                    self.workflow.settings,
                    service=self.window_service,
                    check_stop=self._check_stop,
                )
            except WindowTargetError as exc:
                raise AutomationError(str(exc)) from exc
        if self.target:
            self.log(
                "info",
                f"目标窗口：{self.target.title}，客户区 {self.target.width}×{self.target.height}，"
                f"缩放 {self.target.scale_x:.3f}×{self.target.scale_y:.3f}",
            )
        pyautogui = self._input()
        pyautogui.FAILSAFE = bool(self.workflow.settings.get("failsafe", True))
        self.variables = dict(self.workflow.variables)
        enabled_steps = [step for step in self.workflow.steps if step.enabled]
        repeat_count = max(1, int(self.workflow.settings.get("repeat_count", 1))) if self.plan.mode == "full" else 1
        repeat_delay = max(0.0, float(self.workflow.settings.get("repeat_delay", 0.0)))
        repeat_text = f"，完整运行 {repeat_count} 次" if repeat_count > 1 else ""
        backend_label = "Windows SendInput" if self.workflow.settings.get("input_backend") == "sendinput" else "PyAutoGUI"
        self.log("info", f"开始运行：{self.workflow.name} · {self.plan.label}，共 {len(enabled_steps)} 个有效步骤{repeat_text}，输入后端：{backend_label}")
        try:
            block_maps = build_block_map(self.workflow.steps)
            for cycle in range(repeat_count):
                if repeat_count > 1:
                    self.log("info", f"第 {cycle + 1}/{repeat_count} 轮")
                if self.plan.mode == "selected":
                    self._run_selected(pyautogui)
                else:
                    if self.plan.mode == "full":
                        start, end = 0, len(self.workflow.steps) - 1
                    else:
                        requested_end = self.plan.end if self.plan.end is not None else self.plan.start
                        start, end = normalize_run_span(self.workflow.steps, self.plan.start, requested_end)
                    self._run_cycle(pyautogui, *block_maps, start_index=start, end_index=end)
                if cycle < repeat_count - 1 and repeat_delay > 0:
                    self.log("info", f"本轮完成，等待 {repeat_delay:g} 秒后开始下一轮")
                    self._sleep(repeat_delay)
        except StopRequested:
            self.log("warning", "流程已停止")
            raise
        else:
            self.log("success", "流程运行完成")
        finally:
            self.vision.close()

    def _run_cycle(
        self,
        pyautogui: Any,
        start_to_end: dict[int, int],
        end_to_start: dict[int, int],
        start_to_else: dict[int, int],
        else_to_start: dict[int, int],
        *,
        start_index: int = 0,
        end_index: int | None = None,
    ) -> None:
        loop_states: dict[int, tuple[int, int]] = {}
        index = start_index
        last_index = len(self.workflow.steps) - 1 if end_index is None else end_index
        while index <= last_index:
            self._check_stop()
            step = self.workflow.steps[index]
            self.current_index = index
            self._debug_gate(index, step)

            if step.type in BLOCK_PAIRS and not step.enabled:
                end = start_to_end[index]
                self.step_changed(index, "skipped")
                self._mark_skipped(index + 1, end)
                index = end + 1
                continue
            if not step.enabled and step.type not in BLOCK_END_TYPES | {"if_else"}:
                self.step_changed(index, "skipped")
                index += 1
                continue

            if step.type in CONDITION_STARTS:
                self.step_changed(index, "running")
                matched = self._condition_matches(step)
                self.step_changed(index, "done")
                self.log("info", f"条件 {step.name}：{'成立' if matched else '不成立'}")
                if not matched:
                    end = start_to_end[index]
                    else_index = start_to_else.get(index)
                    if else_index is not None:
                        self._mark_skipped(index + 1, else_index - 1)
                        self.step_changed(else_index, "done")
                        index = else_index + 1
                    else:
                        self._mark_skipped(index + 1, end)
                        index = end + 1
                else:
                    index += 1
                continue

            if step.type == "if_else":
                start = else_to_start[index]
                end = start_to_end[start]
                self.step_changed(index, "done")
                self._mark_skipped(index + 1, end)
                index = end + 1
                continue

            if step.type == "if_end":
                self.step_changed(index, "done")
                index += 1
                continue

            if step.type == "loop_start":
                self.step_changed(index, "running")
                try:
                    count = max(0, int(float(self._substitute(step.params.get("loop_count", 1)))))
                except ValueError as exc:
                    raise AutomationError(f"循环次数不是有效数字：{step.params.get('loop_count')}") from exc
                if count == 0:
                    end = start_to_end[index]
                    self.step_changed(index, "done")
                    self._mark_skipped(index + 1, end)
                    index = end + 1
                    continue
                loop_states[index] = (count, 1)
                index_name = str(step.params.get("index_variable", "")).strip()
                if index_name:
                    self.variables[index_name] = 1
                self.step_changed(index, "done")
                self.log("info", f"开始循环：{count} 次")
                index += 1
                continue

            if step.type == "loop_end":
                start = end_to_start[index]
                count, iteration = loop_states.get(start, (1, 1))
                if iteration < count:
                    iteration += 1
                    loop_states[start] = (count, iteration)
                    index_name = str(self.workflow.steps[start].params.get("index_variable", "")).strip()
                    if index_name:
                        self.variables[index_name] = iteration
                    self.step_changed(index, "done")
                    self.log("info", f"循环第 {iteration}/{count} 次")
                    index = start + 1
                else:
                    loop_states.pop(start, None)
                    self.step_changed(index, "done")
                    index += 1
                continue

            self._run_action_step(index, step, pyautogui)
            index += 1

    def _run_selected(self, pyautogui: Any) -> None:
        for index in sorted(set(self.plan.selected)):
            self._check_stop()
            if not 0 <= index < len(self.workflow.steps):
                continue
            step = self.workflow.steps[index]
            self.current_index = index
            self._debug_gate(index, step)
            if not step.enabled:
                self.step_changed(index, "skipped")
                continue
            self._run_action_step(index, step, pyautogui)

    def _mark_skipped(self, start: int, end: int) -> None:
        for index in range(start, min(end + 1, len(self.workflow.steps))):
            self.step_changed(index, "skipped")

    def _run_action_step(self, index: int, step: Step, pyautogui: Any) -> None:
        self.step_changed(index, "running")
        self.log("info", f"步骤 {index + 1}：{step.name}")
        last_error: Exception | None = None
        for attempt in range(step.retries + 1):
            try:
                self._execute(step, pyautogui)
                last_error = None
                break
            except StopRequested:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < step.retries:
                    self.log("warning", f"执行失败，准备第 {attempt + 2} 次尝试：{exc}")
                    self._sleep(0.4)
        if last_error:
            self.step_changed(index, "failed")
            self.log("error", f"步骤失败：{last_error}")
            try:
                self.failure(index, step, last_error)
            except Exception as capture_error:
                self.log("warning", f"保存失败现场时出错：{capture_error}")
            if step.on_failure != "continue":
                raise AutomationError(str(last_error)) from last_error
        else:
            self.step_changed(index, "done")
        self._sleep(float(self.workflow.settings.get("step_delay", 0.2)))

    def _condition_matches(self, step: Step) -> bool:
        if step.type == "if_image":
            path = self._asset(str(step.params.get("image", "")))
            region = self._region(step.params.get("region"))
            scales = parse_scales(step.params.get("scales"))
            confidence = float(step.params.get("confidence", 0.88))
            interval = float(step.params.get("poll_interval", 0.15))
            want_present = str(step.params.get("condition_state", "present")) == "present"
            return self._wait_condition(
                lambda: self.vision.find_image(path, confidence, region, scales),
                want_present,
                step.timeout,
                interval,
            )
        if step.type == "if_text":
            query = self._substitute(step.params.get("text", ""))
            if not query:
                raise AutomationError("OCR 条件文字不能为空")
            region = self._region(step.params.get("region"))
            match_mode = str(step.params.get("match", "contains"))
            interval = float(step.params.get("poll_interval", 0.4))
            want_present = str(step.params.get("condition_state", "present")) == "present"
            return self._wait_condition(
                lambda: self.vision.find_text(query, region, match_mode),
                want_present,
                step.timeout,
                interval,
            )
        name = str(step.params.get("variable", "")).strip()
        if not name:
            raise AutomationError("条件变量名不能为空")
        actual = self.variables.get(name, "")
        expected = self._substitute(step.params.get("value", ""))
        operator = str(step.params.get("operator", "equals"))
        if operator == "equals":
            return str(actual) == expected
        if operator == "not_equals":
            return str(actual) != expected
        if operator == "contains":
            return expected in str(actual)
        if operator == "not_contains":
            return expected not in str(actual)
        if operator == "not_empty":
            return str(actual) != ""
        if operator == "is_empty":
            return str(actual) == ""
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError) as exc:
            raise AutomationError(f"变量“{name}”和值“{expected}”不能进行数字比较") from exc
        comparisons = {
            "greater": left > right,
            "greater_equal": left >= right,
            "less": left < right,
            "less_equal": left <= right,
        }
        if operator not in comparisons:
            raise AutomationError(f"未知条件比较方式：{operator}")
        return comparisons[operator]

    def _wait_condition(
        self,
        finder: Callable[[], Match | None],
        want_present: bool,
        timeout: float,
        interval: float,
    ) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self._check_stop()
            match = finder()
            if bool(match) == want_present:
                if want_present and match is not None:
                    self._sleep(min(max(interval, 0.03), 0.08))
                    if finder() is None:
                        continue
                return True
            if time.monotonic() >= deadline:
                return False
            self._sleep(max(0.03, interval))

    def _run_subflow(self, step: Step) -> None:
        from .storage import load_document

        if self.call_depth >= 8:
            raise AutomationError("子流程嵌套不能超过 8 层，请检查循环调用")
        reference = str(step.params.get("subflow", ""))
        if not reference:
            raise AutomationError("请先导入子流程文件")
        document = load_document(self._asset(reference))
        index = self.current_index
        shared = step.params.get("variable_scope", "shared") == "shared"
        try:
            if shared:
                document.workflow.variables.update(self.variables)
            child = AutomationRunner(
                document.workflow, document.asset_dir,
                lambda level, message: self.log(level, f"[{document.workflow.name}] {message}"),
                lambda _row, status: self.step_changed(index, status) if status == "paused" else None,
                lambda _row: self.paused(index),
                lambda row, _step, error: self.failure(index, step, AutomationError(
                    f"子流程 {document.workflow.name} / 步骤 {row + 1}：{error}")),
                plan=RunPlan(dry_run=self.plan.dry_run),
                window_service=self.window_service,
                target=self.target,
            )
            child.call_depth = self.call_depth + 1
            child._input = self._input
            child.stop_event = self.stop_event
            self.active_child = child
            child.run()
            if shared:
                self.variables.update(child.variables)
        except StopRequested:
            raise
        except Exception as exc:
            child_index = self.active_child.current_index + 1 if self.active_child else 0
            raise AutomationError(f"子流程 {document.workflow.name} / 步骤 {child_index}：{exc}") from exc
        finally:
            self.active_child = None
            document.close()

    def _execute(self, step: Step, pyautogui: Any) -> None:
        if step.type == "run_subflow":
            if self.plan.dry_run:
                self.log("debug", "安全测试：已验证子流程文件，未执行子流程")
                return
            previous_failsafe = pyautogui.FAILSAFE
            try:
                self._run_subflow(step)
            finally:
                pyautogui.FAILSAFE = previous_failsafe
            return
        p = step.params
        region = self._region(p.get("region")) if "region" in p else (self.target.region(None) if self.target else None)
        interval = float(p.get("poll_interval", 0.15))

        def image_finder(key: str = "image") -> Callable[[], Match | None]:
            image = self._asset(str(p.get(key, "")))
            return lambda: self.vision.find_image(image, float(p.get("confidence", 0.88)), region, parse_scales(p.get("scales")))

        def text_finder() -> Callable[[], Match | None]:
            query = self._substitute(p.get("text", ""))
            return lambda: self.vision.find_text(query, region, str(p.get("match", "contains")))

        if step.type in {"click_image", "wait_image", "wait_image_gone"}:
            want_present = step.type != "wait_image_gone"
            match = self._wait_match(image_finder(), step.timeout, want_present, interval)
            if step.type == "click_image" and match:
                x, y = match.center
                point = (x + int(p.get("offset_x", 0)), y + int(p.get("offset_y", 0)))
                if not self.plan.dry_run:
                    pyautogui.click(*point, clicks=int(p.get("clicks", 1)), interval=0.12, button=str(p.get("button", "left")))
                self.log("debug", f"图片匹配 {match.confidence:.3f}，{'安全定位' if self.plan.dry_run else '点击'} {point}")
        elif step.type in {"click_text", "wait_text", "wait_text_gone"}:
            want_present = step.type != "wait_text_gone"
            match = self._wait_match(text_finder(), step.timeout, want_present, interval)
            if step.type == "click_text" and match:
                x, y = match.center
                point = (x + int(p.get("offset_x", 0)), y + int(p.get("offset_y", 0)))
                if not self.plan.dry_run:
                    pyautogui.click(*point)
                self.log("debug", f"文字匹配 {match.confidence:.3f}，{'安全定位' if self.plan.dry_run else '点击'} {point}")
        elif step.type == "click_position":
            point = self._point(p.get("x", 0), p.get("y", 0))
            if self.plan.dry_run:
                self.log("debug", f"安全测试：坐标点击定位 {point}，未发送鼠标")
            else:
                pyautogui.click(*point, clicks=int(p.get("clicks", 1)), interval=0.12, button=str(p.get("button", "left")))
        elif step.type == "drag_position":
            start_point = self._point(p.get("x", 0), p.get("y", 0))
            target_point = self._point(p.get("x2", 0), p.get("y2", 0))
            if self.plan.dry_run:
                self.log("debug", f"安全测试：拖动定位 {start_point} → {target_point}，未发送鼠标")
            else:
                pyautogui.moveTo(*start_point)
                pyautogui.dragTo(*target_point, duration=float(p.get("duration", 0.5)), button=str(p.get("button", "left")))
        elif step.type == "drag_image_to_position":
            start = self._wait_match(image_finder("image"), step.timeout, True, interval)
            if start:
                start_x, start_y = start.center
                start_point = (start_x + int(p.get("offset_x", 0)), start_y + int(p.get("offset_y", 0)))
                target_point = self._point(p.get("x2", 0), p.get("y2", 0))
                if not self.plan.dry_run:
                    pyautogui.moveTo(*start_point)
                    pyautogui.dragTo(*target_point, duration=float(p.get("duration", 0.5)), button=str(p.get("button", "left")))
                self.log("debug", f"{'安全测试：' if self.plan.dry_run else ''}图片到位置 {start_point} → {target_point}")
        elif step.type == "drag_position_to_image":
            target_path = self._asset(str(p.get("target_image", "")))
            target = self._wait_match(lambda: self.vision.find_image(target_path, float(p.get("confidence", 0.88)), region, parse_scales(p.get("scales"))), step.timeout, True, interval)
            if target:
                target_x, target_y = target.center
                start_point = self._point(p.get("x", 0), p.get("y", 0))
                target_point = (target_x + int(p.get("target_offset_x", 0)), target_y + int(p.get("target_offset_y", 0)))
                if not self.plan.dry_run:
                    pyautogui.moveTo(*start_point)
                    pyautogui.dragTo(*target_point, duration=float(p.get("duration", 0.5)), button=str(p.get("button", "left")))
                self.log("debug", f"{'安全测试：' if self.plan.dry_run else ''}位置到图片 {start_point} → {target_point}")
        elif step.type == "drag_image":
            start = self._wait_match(image_finder("image"), step.timeout, True, interval)
            target_path = self._asset(str(p.get("target_image", "")))
            target = self._wait_match(lambda: self.vision.find_image(target_path, float(p.get("confidence", 0.88)), region, parse_scales(p.get("scales"))), step.timeout, True, interval)
            if start and target:
                start_x, start_y = start.center
                target_x, target_y = target.center
                start_point = (start_x + int(p.get("offset_x", 0)), start_y + int(p.get("offset_y", 0)))
                target_point = (target_x + int(p.get("target_offset_x", 0)), target_y + int(p.get("target_offset_y", 0)))
                if not self.plan.dry_run:
                    pyautogui.moveTo(*start_point)
                    pyautogui.dragTo(*target_point, duration=float(p.get("duration", 0.5)), button=str(p.get("button", "left")))
                self.log("debug", f"{'安全测试：' if self.plan.dry_run else ''}图片拖动 {start_point} → {target_point}")
        elif step.type == "type_text":
            text = self._substitute(p.get("text", ""))
            if self.plan.dry_run:
                self.log("debug", f"安全测试：未输入文字（{len(text)} 个字符）")
                return
            if p.get("method", "paste") == "paste":
                try:
                    import pyperclip
                except ImportError as exc:
                    raise AutomationError("缺少剪贴板组件 pyperclip") from exc
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.write(text, interval=float(p.get("interval", 0.02)))
        elif step.type == "hotkey":
            keys = [item.strip() for item in str(p.get("keys", "")).split("+") if item.strip()]
            if not keys:
                raise AutomationError("组合键不能为空")
            if self.plan.dry_run:
                self.log("debug", f"安全测试：未发送组合键 {'+'.join(keys)}")
            else:
                pyautogui.hotkey(*keys)
        elif step.type == "press_key":
            key = str(p.get("keys", "enter")).strip()
            if self.plan.dry_run:
                self.log("debug", f"安全测试：未发送按键 {key}")
            else:
                pyautogui.press(key, presses=int(p.get("count", 1)), interval=float(p.get("interval", 0.05)))
        elif step.type == "scroll":
            if self.plan.dry_run:
                self.log("debug", "安全测试：未发送滚轮")
            else:
                pyautogui.scroll(int(p.get("amount", -3)))
        elif step.type == "wait":
            if self.plan.dry_run:
                self.log("debug", "安全测试：已跳过固定等待")
            else:
                self._sleep(float(p.get("seconds", 1.0)))
        elif step.type == "set_variable":
            name = str(p.get("variable", "")).strip()
            if not name:
                raise AutomationError("变量名不能为空")
            value = self._substitute(p.get("value", ""))
            operation = str(p.get("variable_operation", "set"))
            if operation == "set":
                result: Any = value
            else:
                if operation not in {"add", "subtract"}:
                    raise AutomationError(f"未知变量操作：{operation}")
                try:
                    current = float(self.variables.get(name, 0))
                    amount = float(value)
                except (TypeError, ValueError) as exc:
                    raise AutomationError(f"变量“{name}”不能进行加减运算") from exc
                result = current + amount if operation == "add" else current - amount
                if result.is_integer():
                    result = int(result)
            self.variables[name] = result
            self.log("debug", f"变量 {name} = {result}")
        else:
            raise AutomationError(f"尚未支持步骤类型：{step.type}")
