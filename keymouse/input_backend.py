from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Callable


class SendInputError(RuntimeError):
    pass


ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", INPUTUNION)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

VK_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "win": 0x5B, "windows": 0x5B,
    "cmd": 0x5B, "command": 0x5B, "numlock": 0x90, "scrolllock": 0x91,
}
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}


def virtual_key(name: str) -> int:
    key = name.strip().lower()
    if key in VK_KEYS:
        return VK_KEYS[key]
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1
    raise SendInputError(f"SendInput 不支持按键名称：{name}")


class WindowsSendInputBackend:
    """PyAutoGUI-shaped foreground input backend implemented with Win32 SendInput."""

    def __init__(
        self,
        sleep_func: Callable[[float], None] | None = None,
        *,
        sender: Callable[[list[INPUT]], None] | None = None,
        metrics: Callable[[int], int] | None = None,
        cursor: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        if sys.platform != "win32" and sender is None:
            raise SendInputError("Windows SendInput 后端只能在 Windows 上使用")
        self.FAILSAFE = True
        self._sleep = sleep_func or time.sleep
        self._sender = sender or self._native_send
        self._metrics = metrics or ctypes.windll.user32.GetSystemMetrics
        self._cursor = cursor or self._native_cursor

    @staticmethod
    def _native_send(inputs: list[INPUT]) -> None:
        if not inputs:
            return
        array = (INPUT * len(inputs))(*inputs)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        send_input = user32.SendInput
        send_input.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        send_input.restype = wintypes.UINT
        ctypes.set_last_error(0)
        sent = send_input(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            code = ctypes.get_last_error()
            raise SendInputError(f"SendInput 仅发送 {sent}/{len(inputs)} 个事件（Windows 错误 {code}）")

    @staticmethod
    def _native_cursor() -> tuple[int, int]:
        point = wintypes.POINT()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise SendInputError("无法读取鼠标位置")
        return int(point.x), int(point.y)

    @staticmethod
    def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
        return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, data, flags, 0, 0))

    @staticmethod
    def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))

    @classmethod
    def _virtual_key_event(cls, vk: int, released: bool = False) -> INPUT:
        flags = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
        if released:
            flags |= KEYEVENTF_KEYUP
        return cls._key(vk=vk, flags=flags)

    def _check_failsafe(self) -> None:
        x, y = self._cursor()
        if self.FAILSAFE and x <= 0 and y <= 0:
            raise SendInputError("鼠标位于屏幕左上角，已触发安全停止")

    def _normalized(self, x: int, y: int) -> tuple[int, int]:
        left, top = self._metrics(76), self._metrics(77)
        width, height = max(1, self._metrics(78)), max(1, self._metrics(79))
        nx = round((min(max(x, left), left + width - 1) - left) * 65535 / max(1, width - 1))
        ny = round((min(max(y, top), top + height - 1) - top) * 65535 / max(1, height - 1))
        return nx, ny

    def moveTo(self, x: int, y: int, duration: float = 0.0) -> None:
        self._check_failsafe()
        start_x, start_y = self._cursor()
        duration = max(0.0, float(duration))
        frames = max(1, round(duration * 60))
        for frame in range(1, frames + 1):
            ratio = frame / frames
            point_x = round(start_x + (x - start_x) * ratio)
            point_y = round(start_y + (y - start_y) * ratio)
            nx, ny = self._normalized(point_x, point_y)
            self._sender([self._mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)])
            if duration:
                self._sleep(duration / frames)

    def click(self, x: int | None = None, y: int | None = None, *, clicks: int = 1, interval: float = 0.0, button: str = "left") -> None:
        if x is not None and y is not None:
            self.moveTo(int(x), int(y))
        self._check_failsafe()
        if button not in BUTTON_FLAGS:
            raise SendInputError(f"不支持鼠标按键：{button}")
        down, up = BUTTON_FLAGS[button]
        for index in range(max(1, int(clicks))):
            self._sender([self._mouse(down), self._mouse(up)])
            if index < clicks - 1 and interval:
                self._sleep(float(interval))

    def dragTo(self, x: int, y: int, *, duration: float = 0.0, button: str = "left") -> None:
        self._check_failsafe()
        if button not in BUTTON_FLAGS:
            raise SendInputError(f"不支持鼠标按键：{button}")
        down, up = BUTTON_FLAGS[button]
        self._sender([self._mouse(down)])
        try:
            self.moveTo(int(x), int(y), duration)
        finally:
            self._sender([self._mouse(up)])

    def scroll(self, amount: int) -> None:
        self._check_failsafe()
        data = ctypes.c_ulong(int(amount) * WHEEL_DELTA).value
        self._sender([self._mouse(MOUSEEVENTF_WHEEL, data=data)])

    def hotkey(self, *keys: str) -> None:
        self._check_failsafe()
        codes = [virtual_key(key) for key in keys]
        pressed: list[int] = []
        try:
            for code in codes:
                self._sender([self._virtual_key_event(code)])
                pressed.append(code)
        finally:
            for code in reversed(pressed):
                self._sender([self._virtual_key_event(code, True)])

    def press(self, key: str, *, presses: int = 1, interval: float = 0.0) -> None:
        self._check_failsafe()
        code = virtual_key(key)
        for index in range(max(1, int(presses))):
            self._sender([self._virtual_key_event(code), self._virtual_key_event(code, True)])
            if index < presses - 1 and interval:
                self._sleep(float(interval))

    def write(self, text: str, *, interval: float = 0.0) -> None:
        self._check_failsafe()
        encoded = text.encode("utf-16-le")
        units = [int.from_bytes(encoded[index:index + 2], "little") for index in range(0, len(encoded), 2)]
        for index, unit in enumerate(units):
            self._sender([
                self._key(scan=unit, flags=KEYEVENTF_UNICODE),
                self._key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ])
            if index < len(units) - 1 and interval:
                self._sleep(float(interval))
