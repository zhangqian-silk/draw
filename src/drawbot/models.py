from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable, List, Sequence


DEFAULT_REVEAL_RATIO = {
    "easy": 1.0,
    "medium": 1.0,
    "hard": 1.0,
}


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def clamped(self) -> "Point":
        return Point(x=max(0.0, min(100.0, float(self.x))), y=max(0.0, min(100.0, float(self.y))))

    @classmethod
    def from_payload(cls, payload: dict) -> "Point":
        return cls(x=float(payload["x"]), y=float(payload["y"])).clamped()

    def as_payload(self) -> dict:
        return {"x": round(self.x, 3), "y": round(self.y, 3)}


@dataclass(frozen=True)
class Stroke:
    name: str
    points: Sequence[Point]

    def cleaned(self) -> "Stroke":
        deduped: List[Point] = []
        for point in self.points:
            normalized = point.clamped()
            if not deduped or deduped[-1] != normalized:
                deduped.append(normalized)
        if len(deduped) < 2:
            raise ValueError(f"Stroke '{self.name}' must contain at least two distinct points.")
        return Stroke(name=self.name.strip() or "stroke", points=tuple(deduped))

    @classmethod
    def from_payload(cls, payload: dict) -> "Stroke":
        points = [Point.from_payload(point) for point in payload["points"]]
        return cls(name=str(payload.get("name", "stroke")), points=points).cleaned()

    def as_payload(self) -> dict:
        return {"name": self.name, "points": [point.as_payload() for point in self.points]}


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def parse(cls, raw: str) -> "Region":
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 4:
            raise ValueError("Region must be in the form left,top,width,height.")
        left, top, width, height = (int(part) for part in parts)
        region = cls(left=left, top=top, width=width, height=height)
        region.validate()
        return region

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Region width and height must be positive.")

    @property
    def aspect_ratio(self) -> float:
        self.validate()
        return self.width / self.height

    def to_screen_point(self, point: Point, padding_ratio: float = 0.06) -> tuple[int, int]:
        self.validate()
        padding_ratio = max(0.0, min(0.3, padding_ratio))
        inner_left = self.left + int(round(self.width * padding_ratio))
        inner_top = self.top + int(round(self.height * padding_ratio))
        inner_width = max(1, self.width - int(round(self.width * padding_ratio * 2)))
        inner_height = max(1, self.height - int(round(self.height * padding_ratio * 2)))
        x = inner_left + (point.x / 100.0) * inner_width
        y = inner_top + (point.y / 100.0) * inner_height
        return int(round(x)), int(round(y))

    def as_payload(self) -> dict:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class DrawPlan:
    word: str
    difficulty: str
    description: str
    strokes: Sequence[Stroke]
    hidden_features: Sequence[str]
    prompt: str = ""
    svg: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "DrawPlan":
        word = str(payload.get("word", "")).strip()
        prompt = str(payload.get("prompt", word)).strip() or word
        difficulty = str(payload.get("difficulty", "medium")).strip().lower()
        description = str(payload.get("description", "")).strip()
        hidden_features = tuple(str(item).strip() for item in payload.get("hidden_features", []))
        svg = str(payload.get("svg", "") or "").strip()
        raw_strokes = payload.get("strokes")
        if raw_strokes is None:
            if not svg:
                raise ValueError("The plan must contain either strokes or SVG.")
            try:
                from .svg import parse_svg_document
            except ImportError as exc:
                raise ValueError("SVG support is unavailable.") from exc
            strokes, svg_title, svg_description = parse_svg_document(svg)
            if not word:
                word = svg_title.strip() or prompt
            if not description:
                description = svg_description.strip()
            strokes = tuple(strokes)
        else:
            strokes = tuple(Stroke.from_payload(stroke) for stroke in raw_strokes)
        if not word:
            raise ValueError("The plan word cannot be empty.")
        if difficulty not in DEFAULT_REVEAL_RATIO:
            raise ValueError(f"Unsupported difficulty: {difficulty}")
        if not strokes:
            raise ValueError("The plan must contain at least one stroke.")
        return cls(
            word=word,
            difficulty=difficulty,
            description=description,
            strokes=strokes,
            hidden_features=hidden_features,
            prompt=prompt,
            svg=svg,
        )

    @classmethod
    def from_svg(
        cls,
        *,
        svg: str,
        prompt: str,
        difficulty: str,
        word: str = "",
        description: str = "",
        hidden_features: Sequence[str] = (),
    ) -> "DrawPlan":
        return cls.from_payload(
            {
                "word": word.strip(),
                "prompt": prompt.strip() or word.strip() or "drawing",
                "difficulty": difficulty,
                "description": description.strip(),
                "hidden_features": list(hidden_features),
                "svg": svg,
            }
        )

    def trimmed(self, reveal_ratio: float | None = None) -> "DrawPlan":
        ratio = default_reveal_ratio(self.difficulty) if reveal_ratio is None else reveal_ratio
        ratio = max(0.2, min(1.0, ratio))
        if ratio >= 0.999:
            return self

        total_points = sum(len(stroke.points) for stroke in self.strokes)
        target_points = max(2, ceil(total_points * ratio))
        remaining = target_points
        trimmed_strokes: List[Stroke] = []

        for stroke in self.strokes:
            if remaining <= 1:
                break

            point_count = len(stroke.points)
            if point_count <= remaining:
                trimmed_strokes.append(stroke)
                remaining -= point_count
                continue

            keep_points = max(2, remaining)
            trimmed_strokes.append(Stroke(name=stroke.name, points=tuple(stroke.points[:keep_points])).cleaned())
            remaining = 0
            break

        if not trimmed_strokes:
            trimmed_strokes.append(self.strokes[0])

        return DrawPlan(
            word=self.word,
            difficulty=self.difficulty,
            description=self.description,
            strokes=tuple(trimmed_strokes),
            hidden_features=self.hidden_features,
            prompt=self.prompt,
            svg="",
        )

    def fitted(self, margin: float = 8.0) -> "DrawPlan":
        if not self.strokes:
            return self

        margin = max(0.0, min(30.0, float(margin)))
        points = [point for stroke in self.strokes for point in stroke.points]
        min_x = min(point.x for point in points)
        max_x = max(point.x for point in points)
        min_y = min(point.y for point in points)
        max_y = max(point.y for point in points)

        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        available = max(1.0, 100.0 - margin * 2)
        scale = min(available / span_x, available / span_y)
        target_width = span_x * scale
        target_height = span_y * scale
        offset_x = (100.0 - target_width) / 2.0
        offset_y = (100.0 - target_height) / 2.0

        fitted_strokes = []
        for stroke in self.strokes:
            fitted_points = []
            for point in stroke.points:
                fitted_points.append(
                    Point(
                        x=offset_x + (point.x - min_x) * scale,
                        y=offset_y + (point.y - min_y) * scale,
                    ).clamped()
                )
            fitted_strokes.append(Stroke(name=stroke.name, points=tuple(fitted_points)).cleaned())

        return DrawPlan(
            word=self.word,
            difficulty=self.difficulty,
            description=self.description,
            strokes=tuple(fitted_strokes),
            hidden_features=self.hidden_features,
            prompt=self.prompt,
            svg=self.svg,
        )

    def to_screen_strokes(self, region: Region, padding_ratio: float = 0.06) -> list[list[tuple[int, int]]]:
        return [
            [region.to_screen_point(point, padding_ratio=padding_ratio) for point in stroke.points]
            for stroke in self.strokes
        ]

    def as_payload(self) -> dict:
        return {
            "word": self.word,
            "prompt": self.prompt or self.word,
            "difficulty": self.difficulty,
            "description": self.description,
            "hidden_features": list(self.hidden_features),
            "strokes": [stroke.as_payload() for stroke in self.strokes],
            "svg": self.svg,
        }


def default_reveal_ratio(difficulty: str) -> float:
    normalized = difficulty.strip().lower()
    if normalized not in DEFAULT_REVEAL_RATIO:
        raise ValueError(f"Unsupported difficulty: {difficulty}")
    return DEFAULT_REVEAL_RATIO[normalized]


def iter_segments(points: Iterable[tuple[int, int]]) -> Iterable[tuple[tuple[int, int], tuple[int, int]]]:
    previous = None
    for point in points:
        if previous is not None:
            yield previous, point
        previous = point
