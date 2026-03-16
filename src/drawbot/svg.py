from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Iterable, List, Sequence

from .models import Point, Stroke


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
PATH_TOKEN_RE = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
DRAWABLE_TAGS = {"path", "polyline", "polygon", "line", "rect", "circle", "ellipse"}


class SvgParseError(ValueError):
    """Raised when SVG content cannot be parsed into strokes."""


def extract_svg_fragment(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        raise SvgParseError("The model returned empty SVG content.")

    fence_match = re.search(r"```(?:svg|xml)?\s*(<svg[\s\S]*?</svg>)\s*```", text, flags=re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    svg_match = re.search(r"(<svg[\s\S]*?</svg>)", text, flags=re.IGNORECASE)
    if svg_match:
        return svg_match.group(1).strip()

    raise SvgParseError("The response did not contain an <svg>...</svg> fragment.")


def parse_svg_document(svg_text: str) -> tuple[list[Stroke], str, str]:
    svg_fragment = extract_svg_fragment(svg_text)
    try:
        root = ET.fromstring(svg_fragment)
    except ET.ParseError as exc:
        raise SvgParseError("The SVG XML could not be parsed.") from exc

    if _strip_namespace(root.tag) != "svg":
        raise SvgParseError("The root element must be <svg>.")

    min_x, min_y, width, height = _read_view_box(root)
    if width <= 0 or height <= 0:
        raise SvgParseError("The SVG viewBox must have positive width and height.")

    title = _read_text_child(root, "title")
    description = _read_text_child(root, "desc")
    strokes: list[Stroke] = []

    for element in root.iter():
        tag = _strip_namespace(element.tag)
        if tag == "svg":
            continue
        if "transform" in element.attrib:
            raise SvgParseError("SVG transform attributes are not supported. Ask the model to place shapes directly.")
        if tag in DRAWABLE_TAGS and _is_background_element(element, tag):
            continue
        if tag == "path":
            strokes.extend(_parse_path_element(element, min_x, min_y, width, height))
        elif tag == "polyline":
            stroke = _parse_polyline_element(element, min_x, min_y, width, height, closed=False)
            if stroke is not None:
                strokes.append(stroke)
        elif tag == "polygon":
            stroke = _parse_polyline_element(element, min_x, min_y, width, height, closed=True)
            if stroke is not None:
                strokes.append(stroke)
        elif tag == "line":
            strokes.append(_parse_line_element(element, min_x, min_y, width, height))
        elif tag == "rect":
            strokes.append(_parse_rect_element(element, min_x, min_y, width, height))
        elif tag == "circle":
            strokes.append(_parse_circle_element(element, min_x, min_y, width, height))
        elif tag == "ellipse":
            strokes.append(_parse_ellipse_element(element, min_x, min_y, width, height))

    if not strokes:
        raise SvgParseError("The SVG did not contain any supported drawable elements.")
    return strokes, title, description


def _is_background_element(element: ET.Element, tag: str) -> bool:
    if tag != "rect":
        return False
    presentation = _read_presentation_attributes(element)
    fill = _normalize_color_token(presentation.get("fill"))
    stroke = _normalize_color_token(presentation.get("stroke"))
    if fill not in {"white", "#fff", "#ffffff"}:
        return False
    return stroke in {"", "none", "white", "#fff", "#ffffff"}


def _read_presentation_attributes(element: ET.Element) -> dict[str, str]:
    presentation = {
        "fill": str(element.attrib.get("fill", "")).strip().lower(),
        "stroke": str(element.attrib.get("stroke", "")).strip().lower(),
    }
    raw_style = str(element.attrib.get("style", "")).strip()
    if raw_style:
        for chunk in raw_style.split(";"):
            if ":" not in chunk:
                continue
            key, value = chunk.split(":", 1)
            key = key.strip().lower()
            if key in presentation:
                presentation[key] = value.strip().lower()
    return presentation


def _normalize_color_token(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return ""
    if value.startswith("rgb("):
        compact = value.replace(" ", "")
        if compact == "rgb(255,255,255)":
            return "white"
        if compact == "rgb(0,0,0)":
            return "black"
    return value


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _read_text_child(root: ET.Element, child_name: str) -> str:
    for child in root:
        if _strip_namespace(child.tag) == child_name:
            return "".join(child.itertext()).strip()
    return ""


def _read_view_box(root: ET.Element) -> tuple[float, float, float, float]:
    raw_view_box = (root.attrib.get("viewBox") or "").replace(",", " ").split()
    if len(raw_view_box) == 4:
        return tuple(float(value) for value in raw_view_box)  # type: ignore[return-value]

    width = _read_dimension(root.attrib.get("width"), fallback=100.0)
    height = _read_dimension(root.attrib.get("height"), fallback=100.0)
    return 0.0, 0.0, width, height


def _read_dimension(raw: str | None, *, fallback: float) -> float:
    if not raw:
        return fallback
    match = re.search(r"[-+]?(?:\d*\.\d+|\d+)", raw)
    if not match:
        return fallback
    return float(match.group(0))


def _to_point(x: float, y: float, min_x: float, min_y: float, width: float, height: float) -> Point:
    return Point(
        x=((x - min_x) / width) * 100.0,
        y=((y - min_y) / height) * 100.0,
    ).clamped()


def _parse_line_element(element: ET.Element, min_x: float, min_y: float, width: float, height: float) -> Stroke:
    x1 = float(element.attrib.get("x1", "0"))
    y1 = float(element.attrib.get("y1", "0"))
    x2 = float(element.attrib.get("x2", "0"))
    y2 = float(element.attrib.get("y2", "0"))
    return Stroke(
        name="line",
        points=(
            _to_point(x1, y1, min_x, min_y, width, height),
            _to_point(x2, y2, min_x, min_y, width, height),
        ),
    ).cleaned()


def _parse_rect_element(element: ET.Element, min_x: float, min_y: float, width: float, height: float) -> Stroke:
    x = float(element.attrib.get("x", "0"))
    y = float(element.attrib.get("y", "0"))
    rect_width = float(element.attrib.get("width", "0"))
    rect_height = float(element.attrib.get("height", "0"))
    points = (
        _to_point(x, y, min_x, min_y, width, height),
        _to_point(x + rect_width, y, min_x, min_y, width, height),
        _to_point(x + rect_width, y + rect_height, min_x, min_y, width, height),
        _to_point(x, y + rect_height, min_x, min_y, width, height),
        _to_point(x, y, min_x, min_y, width, height),
    )
    return Stroke(name="rect", points=points).cleaned()


def _parse_circle_element(element: ET.Element, min_x: float, min_y: float, width: float, height: float) -> Stroke:
    cx = float(element.attrib.get("cx", "0"))
    cy = float(element.attrib.get("cy", "0"))
    r = float(element.attrib.get("r", "0"))
    return _sample_ellipse("circle", cx, cy, r, r, min_x, min_y, width, height)


def _parse_ellipse_element(element: ET.Element, min_x: float, min_y: float, width: float, height: float) -> Stroke:
    cx = float(element.attrib.get("cx", "0"))
    cy = float(element.attrib.get("cy", "0"))
    rx = float(element.attrib.get("rx", "0"))
    ry = float(element.attrib.get("ry", "0"))
    return _sample_ellipse("ellipse", cx, cy, rx, ry, min_x, min_y, width, height)


def _sample_ellipse(
    name: str,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    min_x: float,
    min_y: float,
    width: float,
    height: float,
) -> Stroke:
    samples = []
    for index in range(33):
        angle = (math.tau * index) / 32.0
        x = cx + math.cos(angle) * rx
        y = cy + math.sin(angle) * ry
        samples.append(_to_point(x, y, min_x, min_y, width, height))
    return Stroke(name=name, points=tuple(samples)).cleaned()


def _parse_polyline_element(
    element: ET.Element,
    min_x: float,
    min_y: float,
    width: float,
    height: float,
    *,
    closed: bool,
) -> Stroke | None:
    raw_points = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", element.attrib.get("points", ""))
    if len(raw_points) < 4 or len(raw_points) % 2 != 0:
        return None
    points = []
    for index in range(0, len(raw_points), 2):
        points.append(
            _to_point(
                float(raw_points[index]),
                float(raw_points[index + 1]),
                min_x,
                min_y,
                width,
                height,
            )
        )
    if closed:
        points.append(points[0])
    return Stroke(name="polygon" if closed else "polyline", points=tuple(points)).cleaned()


def _parse_path_element(element: ET.Element, min_x: float, min_y: float, width: float, height: float) -> list[Stroke]:
    d_value = element.attrib.get("d", "").strip()
    if not d_value:
        return []
    tokens = PATH_TOKEN_RE.findall(d_value)
    if not tokens:
        return []

    strokes: list[Stroke] = []
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    current_points: list[Point] = []
    last_cubic_control: tuple[float, float] | None = None
    last_quadratic_control: tuple[float, float] | None = None

    def close_current_stroke() -> None:
        nonlocal current_points
        if len(current_points) >= 2:
            strokes.append(Stroke(name="path", points=tuple(current_points)).cleaned())
        current_points = []

    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"[AaCcHhLlMmQqSsTtVvZz]", token):
            command = token
            index += 1
        elif not command:
            raise SvgParseError("SVG path data started with numbers before a command.")

        if command in ("M", "m"):
            points = []
            while index + 1 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if command == "m":
                    x += current[0]
                    y += current[1]
                points.append((x, y))
            if not points:
                raise SvgParseError("SVG path move command did not contain coordinates.")
            close_current_stroke()
            current = points[0]
            start = current
            current_points = [_to_point(current[0], current[1], min_x, min_y, width, height)]
            for line_point in points[1:]:
                current = line_point
                current_points.append(_to_point(current[0], current[1], min_x, min_y, width, height))
            command = "L" if command == "M" else "l"
            last_cubic_control = None
            last_quadratic_control = None
            continue

        if command in ("L", "l"):
            while index + 1 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if command == "l":
                    x += current[0]
                    y += current[1]
                current = (x, y)
                current_points.append(_to_point(x, y, min_x, min_y, width, height))
            last_cubic_control = None
            last_quadratic_control = None
            continue

        if command in ("H", "h"):
            while index < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                x = float(tokens[index])
                index += 1
                if command == "h":
                    x += current[0]
                current = (x, current[1])
                current_points.append(_to_point(current[0], current[1], min_x, min_y, width, height))
            last_cubic_control = None
            last_quadratic_control = None
            continue

        if command in ("V", "v"):
            while index < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                y = float(tokens[index])
                index += 1
                if command == "v":
                    y += current[1]
                current = (current[0], y)
                current_points.append(_to_point(current[0], current[1], min_x, min_y, width, height))
            last_cubic_control = None
            last_quadratic_control = None
            continue

        if command in ("C", "c"):
            while index + 5 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                control1 = (float(tokens[index]), float(tokens[index + 1]))
                control2 = (float(tokens[index + 2]), float(tokens[index + 3]))
                end = (float(tokens[index + 4]), float(tokens[index + 5]))
                index += 6
                if command == "c":
                    control1 = (control1[0] + current[0], control1[1] + current[1])
                    control2 = (control2[0] + current[0], control2[1] + current[1])
                    end = (end[0] + current[0], end[1] + current[1])
                bezier_points = _sample_cubic(current, control1, control2, end, steps=16)
                for sample in bezier_points[1:]:
                    current_points.append(_to_point(sample[0], sample[1], min_x, min_y, width, height))
                current = end
                last_cubic_control = control2
                last_quadratic_control = None
            continue

        if command in ("S", "s"):
            while index + 3 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                control2 = (float(tokens[index]), float(tokens[index + 1]))
                end = (float(tokens[index + 2]), float(tokens[index + 3]))
                index += 4
                if last_cubic_control is None:
                    control1 = current
                else:
                    control1 = (2 * current[0] - last_cubic_control[0], 2 * current[1] - last_cubic_control[1])
                if command == "s":
                    control2 = (control2[0] + current[0], control2[1] + current[1])
                    end = (end[0] + current[0], end[1] + current[1])
                bezier_points = _sample_cubic(current, control1, control2, end, steps=16)
                for sample in bezier_points[1:]:
                    current_points.append(_to_point(sample[0], sample[1], min_x, min_y, width, height))
                current = end
                last_cubic_control = control2
                last_quadratic_control = None
            continue

        if command in ("Q", "q"):
            while index + 3 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                control = (float(tokens[index]), float(tokens[index + 1]))
                end = (float(tokens[index + 2]), float(tokens[index + 3]))
                index += 4
                if command == "q":
                    control = (control[0] + current[0], control[1] + current[1])
                    end = (end[0] + current[0], end[1] + current[1])
                bezier_points = _sample_quadratic(current, control, end, steps=14)
                for sample in bezier_points[1:]:
                    current_points.append(_to_point(sample[0], sample[1], min_x, min_y, width, height))
                current = end
                last_quadratic_control = control
                last_cubic_control = None
            continue

        if command in ("T", "t"):
            while index + 1 < len(tokens) and not re.fullmatch(r"[A-Za-z]", tokens[index]):
                end = (float(tokens[index]), float(tokens[index + 1]))
                index += 2
                if last_quadratic_control is None:
                    control = current
                else:
                    control = (
                        2 * current[0] - last_quadratic_control[0],
                        2 * current[1] - last_quadratic_control[1],
                    )
                if command == "t":
                    end = (end[0] + current[0], end[1] + current[1])
                bezier_points = _sample_quadratic(current, control, end, steps=14)
                for sample in bezier_points[1:]:
                    current_points.append(_to_point(sample[0], sample[1], min_x, min_y, width, height))
                current = end
                last_quadratic_control = control
                last_cubic_control = None
            continue

        if command in ("Z", "z"):
            current_points.append(_to_point(start[0], start[1], min_x, min_y, width, height))
            current = start
            close_current_stroke()
            last_cubic_control = None
            last_quadratic_control = None
            continue

        if command in ("A", "a"):
            raise SvgParseError("SVG arc commands are not supported. Ask the model to use bezier curves instead.")

        raise SvgParseError(f"Unsupported SVG path command: {command}")

    close_current_stroke()
    return strokes


def _sample_cubic(
    start: tuple[float, float],
    control1: tuple[float, float],
    control2: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int,
) -> list[tuple[float, float]]:
    points = []
    for index in range(steps + 1):
        t = index / steps
        mt = 1.0 - t
        x = (mt**3) * start[0] + 3 * (mt**2) * t * control1[0] + 3 * mt * (t**2) * control2[0] + (t**3) * end[0]
        y = (mt**3) * start[1] + 3 * (mt**2) * t * control1[1] + 3 * mt * (t**2) * control2[1] + (t**3) * end[1]
        points.append((x, y))
    return points


def _sample_quadratic(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int,
) -> list[tuple[float, float]]:
    points = []
    for index in range(steps + 1):
        t = index / steps
        mt = 1.0 - t
        x = (mt**2) * start[0] + 2 * mt * t * control[0] + (t**2) * end[0]
        y = (mt**2) * start[1] + 2 * mt * t * control[1] + (t**2) * end[1]
        points.append((x, y))
    return points
