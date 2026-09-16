from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable


class WindowTargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TargetTransform:
    """Map workflow-local coordinates into the current target client area."""

    title: str = ""
    handle: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    base_width: int = 0
    base_height: int = 0

    @property
    def scale_x(self) -> float:
        return self.width / self.base_width if self.width > 0 and self.base_width > 0 else 1.0

    @property
    def scale_y(self) -> float:
        return self.height / self.base_height if self.height > 0 and self.base_height > 0 else 1.0

    def point(self, x: int | float, y: int | float) -> tuple[int, int]:
        return self.x + round(float(x) * self.scale_x), self.y + round(float(y) * self.scale_y)

    def local_point(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        scale_x = self.scale_x or 1.0
        scale_y = self.scale_y or 1.0
        return round((screen_x - self.x) / scale_x), round((screen_y - self.y) / scale_y)

    def region(self, value: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
        if value is None:
            return (self.x, self.y, self.width, self.height) if self.width > 0 and self.height > 0 else None
        x, y, width, height = value
        screen_x, screen_y = self.point(x, y)
        return screen_x, screen_y, max(1, round(width * self.scale_x)), max(1, round(height * self.scale_y))


class WindowService:
    """Small Win32 adapter kept separate so targeting is unit-testable."""

    def list_windows(self) -> list[WindowInfo]:
        if os.name != "nt":
            return []
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        windows: list[WindowInfo] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            try:
                x, y, width, height = self.client_area(int(hwnd))
            except WindowTargetError:
                return True
            windows.append(WindowInfo(int(hwnd), title, x, y, width, height))
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return sorted(windows, key=lambda item: item.title.casefold())

    def client_area(self, handle: int) -> tuple[int, int, int, int]:
        if os.name != "nt":
            raise WindowTargetError("目标窗口功能仅支持 Windows")
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not user32.GetClientRect(handle, ctypes.byref(rect)):
            raise WindowTargetError("无法读取目标窗口客户区")
        if not user32.ClientToScreen(handle, ctypes.byref(origin)):
            raise WindowTargetError("无法换算目标窗口坐标")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise WindowTargetError("目标窗口已最小化或客户区不可用")
        return int(origin.x), int(origin.y), int(width), int(height)

    def find_window(self, title: str) -> WindowInfo | None:
        query = title.strip().casefold()
        if not query:
            return None
        windows = self.list_windows()
        exact = next((item for item in windows if item.title.casefold() == query), None)
        return exact or next((item for item in windows if query in item.title.casefold()), None)

    def activate(self, handle: int) -> None:
        if os.name != "nt":
            return
        import ctypes

        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)  # SW_RESTORE
        if not user32.SetForegroundWindow(handle):
            raise WindowTargetError("无法激活目标窗口，请手动点击窗口后再运行")


def resolve_target(
    settings: dict[str, Any],
    *,
    service: WindowService | None = None,
    check_stop: Callable[[], None] | None = None,
) -> TargetTransform | None:
    if str(settings.get("coordinate_mode", "screen")) != "window":
        return None
    title = str(settings.get("target_window_title", "")).strip()
    if not title:
        raise WindowTargetError("已选择窗口相对坐标，但没有设置目标窗口")
    service = service or WindowService()
    timeout = max(0.0, float(settings.get("target_window_wait", 10.0)))
    deadline = time.monotonic() + timeout
    window = service.find_window(title)
    while window is None and time.monotonic() < deadline:
        if check_stop:
            check_stop()
        time.sleep(0.1)
        window = service.find_window(title)
    if window is None:
        raise WindowTargetError(f"等待目标窗口超时：{title}")
    if bool(settings.get("target_window_activate", True)):
        service.activate(window.handle)
        x, y, width, height = service.client_area(window.handle)
        window = WindowInfo(window.handle, window.title, x, y, width, height)
    return TargetTransform(
        title=window.title,
        handle=window.handle,
        x=window.x,
        y=window.y,
        width=window.width,
        height=window.height,
        base_width=max(0, int(settings.get("target_window_base_width", 0))),
        base_height=max(0, int(settings.get("target_window_base_height", 0))),
    )
