from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


FORMAT_NAME = "keymouse-flow"
FORMAT_VERSION = 1

DEFAULT_WORKFLOW_SETTINGS: dict[str, Any] = {
    "step_delay": 0.2,
    "failsafe": True,
    "input_backend": "pyautogui",
    "repeat_count": 1,
    "repeat_delay": 0.0,
    "coordinate_mode": "screen",
    "target_window_title": "",
    "target_window_activate": True,
    "target_window_wait": 10.0,
    "target_window_base_width": 0,
    "target_window_base_height": 0,
}


STEP_LABELS: dict[str, str] = {
    "run_subflow": "调用子流程",
    "click_image": "点击图片",
    "wait_image": "等待图片出现",
    "wait_image_gone": "等待图片消失",
    "click_text": "点击文字（OCR）",
    "wait_text": "等待文字出现（OCR）",
    "wait_text_gone": "等待文字消失（OCR）",
    "click_position": "点击坐标",
    "drag_position": "拖动：位置 → 位置",
    "drag_image_to_position": "拖动：图片 → 位置",
    "drag_position_to_image": "拖动：位置 → 图片",
    "drag_image": "拖动：图片 → 图片",
    "type_text": "输入文字",
    "hotkey": "组合键",
    "press_key": "按键",
    "scroll": "滚轮",
    "wait": "等待",
    "set_variable": "运行时设置变量",
    "if_variable": "条件开始（变量）",
    "if_image": "条件开始（图片）",
    "if_text": "条件开始（OCR 文字）",
    "if_else": "否则",
    "if_end": "条件结束",
    "loop_start": "循环开始",
    "loop_end": "循环结束",
}


DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "run_subflow": {"subflow": "", "variable_scope": "shared"},
    "click_image": {"image": "", "confidence": 0.88, "region": "", "scales": "1.0", "button": "left", "clicks": 1, "offset_x": 0, "offset_y": 0, "poll_interval": 0.15},
    "wait_image": {"image": "", "confidence": 0.88, "region": "", "scales": "1.0", "poll_interval": 0.15},
    "wait_image_gone": {"image": "", "confidence": 0.88, "region": "", "scales": "1.0", "poll_interval": 0.15},
    "click_text": {"text": "", "match": "contains", "region": "", "offset_x": 0, "offset_y": 0, "poll_interval": 0.4},
    "wait_text": {"text": "", "match": "contains", "region": "", "poll_interval": 0.4},
    "wait_text_gone": {"text": "", "match": "contains", "region": "", "poll_interval": 0.4},
    "click_position": {"x": 0, "y": 0, "button": "left", "clicks": 1},
    "drag_position": {"x": 0, "y": 0, "x2": 0, "y2": 0, "duration": 0.5, "button": "left"},
    "drag_image_to_position": {"image": "", "x2": 0, "y2": 0, "confidence": 0.88, "region": "", "scales": "1.0", "duration": 0.5, "button": "left", "offset_x": 0, "offset_y": 0, "poll_interval": 0.15},
    "drag_position_to_image": {"x": 0, "y": 0, "target_image": "", "confidence": 0.88, "region": "", "scales": "1.0", "duration": 0.5, "button": "left", "target_offset_x": 0, "target_offset_y": 0, "poll_interval": 0.15},
    "drag_image": {"image": "", "target_image": "", "confidence": 0.88, "region": "", "scales": "1.0", "duration": 0.5, "button": "left", "offset_x": 0, "offset_y": 0, "target_offset_x": 0, "target_offset_y": 0},
    "type_text": {"text": "", "method": "paste", "interval": 0.02},
    "hotkey": {"keys": "ctrl+s"},
    "press_key": {"keys": "enter", "count": 1, "interval": 0.05},
    "scroll": {"amount": -3},
    "wait": {"seconds": 1.0},
    "set_variable": {"variable": "变量名", "value": "", "variable_operation": "set"},
    "if_variable": {"variable": "变量名", "operator": "equals", "value": ""},
    "if_image": {"image": "", "condition_state": "present", "confidence": 0.88, "region": "", "scales": "1.0", "poll_interval": 0.15},
    "if_text": {"text": "", "condition_state": "present", "match": "contains", "region": "", "poll_interval": 0.4},
    "if_else": {},
    "if_end": {},
    "loop_start": {"loop_count": 2, "index_variable": "循环序号"},
    "loop_end": {},
}


@dataclass
class Step:
    type: str
    name: str = ""
    id: str = field(default_factory=lambda: f"step_{uuid4().hex[:10]}")
    enabled: bool = True
    breakpoint: bool = False
    timeout: float = 10.0
    retries: int = 0
    on_failure: str = "stop"
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in STEP_LABELS:
            raise ValueError(f"未知步骤类型：{self.type}")
        defaults = dict(DEFAULT_PARAMS[self.type])
        defaults.update(self.params)
        self.params = defaults
        if not self.name:
            self.name = STEP_LABELS[self.type]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Step":
        return cls(
            id=str(value.get("id") or f"step_{uuid4().hex[:10]}"),
            type=str(value["type"]),
            name=str(value.get("name") or ""),
            enabled=bool(value.get("enabled", True)),
            breakpoint=bool(value.get("breakpoint", False)),
            timeout=float(value.get("timeout", 10.0)),
            retries=max(0, int(value.get("retries", 0))),
            on_failure=str(value.get("on_failure", "stop")),
            params=dict(value.get("params") or {}),
        )


@dataclass
class Workflow:
    name: str = "未命名流程"
    steps: list[Step] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_WORKFLOW_SETTINGS))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = dict(DEFAULT_WORKFLOW_SETTINGS)
        normalized.update(self.settings)
        normalized["repeat_count"] = max(1, int(normalized.get("repeat_count", 1)))
        normalized["repeat_delay"] = max(0.0, float(normalized.get("repeat_delay", 0.0)))
        if normalized.get("input_backend") not in {"pyautogui", "sendinput"}:
            normalized["input_backend"] = "pyautogui"
        if normalized.get("coordinate_mode") not in {"screen", "window"}:
            normalized["coordinate_mode"] = "screen"
        normalized["target_window_title"] = str(normalized.get("target_window_title", ""))
        normalized["target_window_activate"] = bool(normalized.get("target_window_activate", True))
        normalized["target_window_wait"] = max(0.0, float(normalized.get("target_window_wait", 10.0)))
        normalized["target_window_base_width"] = max(0, int(normalized.get("target_window_base_width", 0)))
        normalized["target_window_base_height"] = max(0, int(normalized.get("target_window_base_height", 0)))
        self.settings = normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "name": self.name,
            "settings": self.settings,
            "variables": self.variables,
            "metadata": self.metadata,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Workflow":
        if value.get("format") != FORMAT_NAME:
            raise ValueError("这不是 KeyMouse Studio 流程文件")
        version = int(value.get("version", 0))
        if version > FORMAT_VERSION:
            raise ValueError(f"流程版本 {version} 过新，请升级程序")
        return cls(
            name=str(value.get("name") or "未命名流程"),
            settings=dict(value.get("settings") or {}),
            variables=dict(value.get("variables") or {}),
            metadata=dict(value.get("metadata") or {}),
            steps=[Step.from_dict(item) for item in value.get("steps", [])],
        )
