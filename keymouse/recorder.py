from __future__ import annotations

import io
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import Step


class GlobalStopHotkey:
    """A temporary system-wide hotkey listener used while a workflow runs."""

    def __init__(self, callback: Callable[[], None], key_name: str = "f9") -> None:
        self.callback = callback
        self.key_name = key_name
        self._listener: Any = None
        self._target_key: Any = None
        self._triggered = False
        self._lock = threading.Lock()

    def start(self, keyboard_module: Any = None) -> None:
        if self._listener is not None:
            return
        if keyboard_module is None:
            try:
                from pynput import keyboard as keyboard_module
            except ImportError as exc:
                raise RuntimeError("全局停止热键组件未安装，请重新运行“安装依赖.bat”后再试。") from exc
        self._target_key = getattr(keyboard_module.Key, self.key_name)
        self._triggered = False
        listener = keyboard_module.Listener(on_press=self._on_press)
        listener.start()
        self._listener = listener

    def _on_press(self, key: Any) -> bool | None:
        if key != self._target_key:
            return None
        with self._lock:
            if self._triggered:
                return False
            self._triggered = True
        self.callback()
        # The hotkey is single-use for this run. The next run creates a fresh
        # listener, preventing key-repeat from sending duplicate stop requests.
        return False

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        self._target_key = None
        if listener is not None:
            listener.stop()


@dataclass
class RecordedAction:
    kind: str
    started_at: float
    ended_at: float
    data: dict[str, Any] = field(default_factory=dict)


def _same_position(first: RecordedAction, second: RecordedAction, tolerance: int = 4) -> bool:
    return (
        abs(int(first.data.get("x", 0)) - int(second.data.get("x", 0))) <= tolerance
        and abs(int(first.data.get("y", 0)) - int(second.data.get("y", 0))) <= tolerance
    )


def compact_recorded_actions(actions: list[RecordedAction]) -> list[RecordedAction]:
    merged: list[RecordedAction] = []
    for source in sorted(actions, key=lambda item: item.started_at):
        action = RecordedAction(source.kind, source.started_at, source.ended_at, dict(source.data))
        if not merged:
            merged.append(action)
            continue
        previous = merged[-1]
        gap = action.started_at - previous.ended_at
        if (
            action.kind == previous.kind == "click"
            and gap <= 0.4
            and action.data.get("button") == previous.data.get("button")
            and _same_position(previous, action)
        ):
            previous.data["clicks"] = int(previous.data.get("clicks", 1)) + int(action.data.get("clicks", 1))
            previous.ended_at = action.ended_at
        elif (
            action.kind == previous.kind == "press_key"
            and gap <= 0.3
            and action.data.get("key") == previous.data.get("key")
        ):
            previous.data["count"] = int(previous.data.get("count", 1)) + int(action.data.get("count", 1))
            previous.ended_at = action.ended_at
        elif action.kind == previous.kind == "scroll" and gap <= 0.3:
            previous.data["amount"] = int(previous.data.get("amount", 0)) + int(action.data.get("amount", 0))
            previous.ended_at = action.ended_at
        elif action.kind == previous.kind == "text" and gap <= 1.0:
            previous.data["text"] = str(previous.data.get("text", "")) + str(action.data.get("text", ""))
            previous.ended_at = action.ended_at
        else:
            merged.append(action)
    return merged


def recorded_actions_to_steps(
    actions: list[RecordedAction],
    *,
    include_waits: bool = True,
    wait_threshold: float = 0.8,
    prefer_click_images: bool = False,
) -> list[Step]:
    """Convert global input events into editable KeyMouse workflow steps."""
    steps: list[Step] = []
    previous_end = 0.0
    for action in compact_recorded_actions(actions):
        gap = max(0.0, action.started_at - previous_end)
        if include_waits and previous_end > 0 and gap >= wait_threshold:
            steps.append(Step("wait", params={"seconds": round(gap, 2)}))

        data = action.data
        if action.kind == "click":
            if prefer_click_images and str(data.get("image", "")):
                steps.append(
                    Step(
                        "click_image",
                        params={
                            "image": str(data["image"]),
                            "button": str(data.get("button", "left")),
                            "clicks": int(data.get("clicks", 1)),
                            "offset_x": int(data.get("image_offset_x", 0)),
                            "offset_y": int(data.get("image_offset_y", 0)),
                        },
                    )
                )
            else:
                steps.append(
                    Step(
                        "click_position",
                        params={
                            "x": int(data["x"]),
                            "y": int(data["y"]),
                            "button": str(data.get("button", "left")),
                            "clicks": int(data.get("clicks", 1)),
                        },
                    )
                )
        elif action.kind == "drag":
            steps.append(
                Step(
                    "drag_position",
                    params={
                        "x": int(data["x"]),
                        "y": int(data["y"]),
                        "x2": int(data["x2"]),
                        "y2": int(data["y2"]),
                        "duration": round(max(0.05, action.ended_at - action.started_at), 2),
                        "button": str(data.get("button", "left")),
                    },
                )
            )
        elif action.kind == "scroll" and int(data.get("amount", 0)):
            steps.append(Step("scroll", params={"amount": int(data["amount"])}))
        elif action.kind == "text" and str(data.get("text", "")):
            text = str(data["text"])
            duration = max(0.0, action.ended_at - action.started_at)
            interval = duration / max(1, len(text) - 1)
            steps.append(Step("type_text", params={"text": text, "method": "write", "interval": round(interval, 3)}))
        elif action.kind == "hotkey" and str(data.get("keys", "")):
            steps.append(Step("hotkey", params={"keys": str(data["keys"])}))
        elif action.kind == "press_key" and str(data.get("key", "")):
            steps.append(
                Step(
                    "press_key",
                    params={
                        "keys": str(data["key"]),
                        "count": int(data.get("count", 1)),
                        "interval": 0.05,
                    },
                )
            )
        previous_end = max(previous_end, action.ended_at)
    return steps


class InputRecorder:
    """Global mouse/keyboard recorder. pynput is imported only when recording starts."""

    MODIFIER_NAMES = {
        "Key.ctrl": "ctrl",
        "Key.ctrl_l": "ctrl",
        "Key.ctrl_r": "ctrl",
        "Key.alt": "alt",
        "Key.alt_l": "alt",
        "Key.alt_r": "alt",
        "Key.alt_gr": "alt",
        "Key.shift": "shift",
        "Key.shift_l": "shift",
        "Key.shift_r": "shift",
        "Key.cmd": "win",
        "Key.cmd_l": "win",
        "Key.cmd_r": "win",
    }
    SPECIAL_NAMES = {
        "Key.enter": "enter",
        "Key.space": "space",
        "Key.backspace": "backspace",
        "Key.tab": "tab",
        "Key.esc": "esc",
        "Key.delete": "delete",
        "Key.home": "home",
        "Key.end": "end",
        "Key.page_up": "pageup",
        "Key.page_down": "pagedown",
        "Key.left": "left",
        "Key.right": "right",
        "Key.up": "up",
        "Key.down": "down",
    }
    MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")

    def __init__(
        self,
        on_stop_requested: Callable[[], None] | None = None,
        *,
        capture_click_images: bool = True,
        capture_size: tuple[int, int] = (160, 100),
    ) -> None:
        self.on_stop_requested = on_stop_requested
        self.capture_click_images = capture_click_images
        self.capture_size = capture_size
        self._actions: list[RecordedAction] = []
        self._lock = threading.RLock()
        self._mouse_listener: Any = None
        self._keyboard_listener: Any = None
        self._camera: Any = None
        self._mouse_down: dict[str, tuple[int, int, float, dict[str, Any]]] = {}
        self._modifiers: set[str] = set()
        self._origin = 0.0
        self._stop_requested = False

    @property
    def actions(self) -> list[RecordedAction]:
        with self._lock:
            return [RecordedAction(item.kind, item.started_at, item.ended_at, dict(item.data)) for item in self._actions]

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse
        except ImportError as exc:
            raise RuntimeError("录制组件未安装，请重新运行“安装依赖.bat”后再试。") from exc

        self._origin = time.monotonic()
        try:
            import dxcam

            self._camera = dxcam.create(output_color="BGR")
            self._camera.start(target_fps=30, video_mode=True)
        except Exception:
            self._camera = False
        self._mouse_listener = mouse.Listener(on_click=self._on_click, on_scroll=self._on_scroll)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> None:
        mouse_listener, keyboard_listener = self._mouse_listener, self._keyboard_listener
        camera = self._camera
        self._mouse_listener = None
        self._keyboard_listener = None
        self._camera = None
        if mouse_listener is not None:
            mouse_listener.stop()
        if keyboard_listener is not None:
            keyboard_listener.stop()
        if camera not in (None, False):
            try:
                camera.stop()
            except Exception:
                pass

    def _now(self) -> float:
        return max(0.0, time.monotonic() - self._origin)

    @staticmethod
    def _button_name(button: Any) -> str:
        name = str(button).rsplit(".", 1)[-1].lower()
        return name if name in {"left", "right", "middle"} else "left"

    def _append(self, action: RecordedAction) -> None:
        with self._lock:
            if action.kind == "text" and self._actions:
                previous = self._actions[-1]
                if previous.kind == "text" and action.started_at - previous.ended_at <= 1.0:
                    previous.data["text"] = str(previous.data.get("text", "")) + str(action.data.get("text", ""))
                    previous.ended_at = action.ended_at
                    return
            self._actions.append(action)

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        name = self._button_name(button)
        now = self._now()
        if pressed:
            capture = self._capture_click_image(int(x), int(y)) if self.capture_click_images else {}
            self._mouse_down[name] = (int(x), int(y), now, capture)
            return
        start_x, start_y, started_at, capture = self._mouse_down.pop(name, (int(x), int(y), now, {}))
        distance = math.hypot(int(x) - start_x, int(y) - start_y)
        if distance >= 5:
            self._append(
                RecordedAction(
                    "drag",
                    started_at,
                    now,
                    {"x": start_x, "y": start_y, "x2": int(x), "y2": int(y), "button": name},
                )
            )
        else:
            data = {"x": int(x), "y": int(y), "button": name, "clicks": 1}
            data.update(capture)
            self._append(RecordedAction("click", started_at, now, data))

    def _capture_click_image(self, x: int, y: int) -> dict[str, Any]:
        try:
            width = max(32, int(self.capture_size[0]))
            height = max(24, int(self.capture_size[1]))
            if self._camera not in (None, False):
                try:
                    import cv2

                    frame = self._camera.get_latest_frame()
                    if frame is not None and 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                        width = min(width, frame.shape[1])
                        height = min(height, frame.shape[0])
                        left = min(max(int(x - width // 2), 0), frame.shape[1] - width)
                        top = min(max(int(y - height // 2), 0), frame.shape[0] - height)
                        crop = frame[top : top + height, left : left + width].copy()
                        ok, encoded = cv2.imencode(".png", crop)
                        if ok:
                            return {
                                "image_png": encoded.tobytes(),
                                "image_width": width,
                                "image_height": height,
                                "image_offset_x": int(x - (left + width / 2)),
                                "image_offset_y": int(y - (top + height / 2)),
                            }
                except Exception:
                    pass

            from PIL import ImageGrab

            try:
                import ctypes

                user32 = ctypes.windll.user32
                virtual_x = int(user32.GetSystemMetrics(76))
                virtual_y = int(user32.GetSystemMetrics(77))
                virtual_width = int(user32.GetSystemMetrics(78))
                virtual_height = int(user32.GetSystemMetrics(79))
            except Exception:
                virtual_x, virtual_y, virtual_width, virtual_height = 0, 0, 1920, 1080
            width = min(width, max(1, virtual_width))
            height = min(height, max(1, virtual_height))
            left = min(max(int(x - width // 2), virtual_x), virtual_x + virtual_width - width)
            top = min(max(int(y - height // 2), virtual_y), virtual_y + virtual_height - height)
            image = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)
            output = io.BytesIO()
            image.save(output, format="PNG")
            actual_width, actual_height = image.size
            return {
                "image_png": output.getvalue(),
                "image_width": actual_width,
                "image_height": actual_height,
                "image_offset_x": int(x - (left + actual_width / 2)),
                "image_offset_y": int(y - (top + actual_height / 2)),
            }
        except Exception:
            return {}

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        now = self._now()
        self._append(RecordedAction("scroll", now, now, {"x": int(x), "y": int(y), "amount": int(dy)}))

    @classmethod
    def _key_name(cls, key: Any) -> str:
        text = str(key)
        if text in cls.MODIFIER_NAMES:
            return cls.MODIFIER_NAMES[text]
        if text in cls.SPECIAL_NAMES:
            return cls.SPECIAL_NAMES[text]
        if text.startswith("Key.f") and text[5:].isdigit():
            return text[4:]
        char = getattr(key, "char", None)
        if isinstance(char, str) and char:
            if ord(char[0]) < 32:
                vk = getattr(key, "vk", None)
                if isinstance(vk, int) and 65 <= vk <= 90:
                    return chr(vk).lower()
            return char
        return text.removeprefix("Key.").lower()

    def _on_key_press(self, key: Any) -> bool | None:
        raw = str(key)
        name = self._key_name(key)
        if name == "f8":
            self._request_stop()
            return False
        modifier = self.MODIFIER_NAMES.get(raw)
        if modifier:
            self._modifiers.add(modifier)
            return None

        now = self._now()
        modifiers = [item for item in self.MODIFIER_ORDER if item in self._modifiers]
        char = getattr(key, "char", None)
        text_input = isinstance(char, str) and bool(char) and not ({"ctrl", "alt", "win"} & self._modifiers)
        if name == "space" and not ({"ctrl", "alt", "win"} & self._modifiers):
            text_input = True
            char = " "
        if text_input:
            self._append(RecordedAction("text", now, now, {"text": char}))
        elif modifiers:
            self._append(RecordedAction("hotkey", now, now, {"keys": "+".join([*modifiers, name])}))
        else:
            self._append(RecordedAction("press_key", now, now, {"key": name, "count": 1}))
        return None

    def _on_key_release(self, key: Any) -> None:
        modifier = self.MODIFIER_NAMES.get(str(key))
        if modifier:
            self._modifiers.discard(modifier)

    def _request_stop(self) -> None:
        with self._lock:
            if self._stop_requested:
                return
            self._stop_requested = True
        self.stop()
        if self.on_stop_requested:
            self.on_stop_requested()
