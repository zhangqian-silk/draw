from __future__ import annotations

import ctypes
import math
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from .models import DrawPlan, Region, iter_segments


if os.name == "nt":
    user32 = ctypes.windll.user32
else:
    user32 = None


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MouseControlError(RuntimeError):
    """Raised when mouse control is unavailable or fails."""


class MouseButton(str, Enum):
    LEFT = "left"
    RIGHT = "right"

    @classmethod
    def parse(cls, raw: str) -> "MouseButton":
        normalized = raw.strip().lower()
        for button in cls:
            if button.value == normalized:
                return button
        raise ValueError(f"Unsupported mouse button: {raw}")


@dataclass
class DrawTiming:
    countdown_seconds: int = 3
    step_delay_ms: int = 10
    between_strokes_ms: int = 180
    padding_ratio: float = 0.06


class WindowsMouseController:
    def __init__(self) -> None:
        if os.name != "nt" or user32 is None:
            raise MouseControlError("Mouse drawing is only supported on Windows.")

    def current_position(self) -> tuple[int, int]:
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise MouseControlError("Failed to read the current cursor position.")
        return point.x, point.y

    def move_to(self, x: int, y: int) -> None:
        if not user32.SetCursorPos(int(x), int(y)):
            raise MouseControlError(f"Failed to move the cursor to {x},{y}.")

    def button_down(self, button: MouseButton) -> None:
        flag = MOUSEEVENTF_LEFTDOWN if button is MouseButton.LEFT else MOUSEEVENTF_RIGHTDOWN
        user32.mouse_event(flag, 0, 0, 0, 0)

    def button_up(self, button: MouseButton) -> None:
        flag = MOUSEEVENTF_LEFTUP if button is MouseButton.LEFT else MOUSEEVENTF_RIGHTUP
        user32.mouse_event(flag, 0, 0, 0, 0)

    def drag_path(
        self,
        points: Sequence[tuple[int, int]],
        *,
        button: MouseButton = MouseButton.LEFT,
        step_delay_ms: int = 10,
    ) -> None:
        if len(points) < 2:
            return

        self.move_to(*points[0])
        time.sleep(0.03)
        self.button_down(button)
        try:
            for start, end in iter_segments(points):
                self._interpolate_segment(start, end, step_delay_ms=step_delay_ms)
        finally:
            self.button_up(button)

    def _interpolate_segment(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        step_delay_ms: int,
    ) -> None:
        distance = math.dist(start, end)
        steps = max(1, int(distance / 6))
        for index in range(1, steps + 1):
            factor = index / steps
            x = int(round(start[0] + (end[0] - start[0]) * factor))
            y = int(round(start[1] + (end[1] - start[1]) * factor))
            self.move_to(x, y)
            time.sleep(max(0.001, step_delay_ms / 1000.0))

    def draw_plan(
        self,
        plan: DrawPlan,
        region: Region,
        timing: DrawTiming,
        *,
        button: MouseButton = MouseButton.LEFT,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        reporter = progress_callback or print
        for seconds_left in range(max(0, timing.countdown_seconds), 0, -1):
            reporter(f"Drawing starts in {seconds_left}...")
            time.sleep(1)

        screen_strokes = plan.to_screen_strokes(region, padding_ratio=timing.padding_ratio)
        reporter(f"Drawing '{plan.word}' with {len(screen_strokes)} stroke(s). Press Ctrl+C to stop.")
        for index, stroke in enumerate(screen_strokes, start=1):
            reporter(f"Stroke {index}/{len(screen_strokes)}")
            self.drag_path(stroke, button=button, step_delay_ms=timing.step_delay_ms)
            time.sleep(max(0.0, timing.between_strokes_ms / 1000.0))
