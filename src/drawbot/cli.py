from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .config import AppConfig, ConfigStore
from .models import DrawPlan, Region
from .mouse import DrawTiming, MouseButton, MouseControlError, WindowsMouseController
from .planner import DEFAULT_OPENAI_MODEL, DRAWING_MODES, PICTIONARY_STRATEGIES, OpenAIPlanner, PlannerError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drawbot",
        description="OpenAI-assisted mouse drawing helper for guessing games.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    gui_parser = subparsers.add_parser("gui", help="Launch the always-on-top desktop control panel.")
    gui_parser.set_defaults(func=command_gui)

    calibrate_parser = subparsers.add_parser("calibrate", help="Capture a drawing region from the current cursor position.")
    calibrate_parser.set_defaults(func=command_calibrate)

    plan_parser = subparsers.add_parser("plan", help="Generate a drawing plan without moving the mouse.")
    add_plan_arguments(plan_parser)
    plan_parser.add_argument("--save", type=Path, help="Optional file path to save the generated SVG or plan JSON.")
    plan_parser.set_defaults(func=command_plan)

    draw_parser = subparsers.add_parser("draw", help="Generate a plan and draw it inside the requested region.")
    add_plan_arguments(draw_parser)
    draw_parser.add_argument("--region", help="Drawing region as left,top,width,height.")
    draw_parser.add_argument("--load-plan", type=Path, help="Load an existing SVG or plan JSON instead of calling the model.")
    draw_parser.add_argument("--save-plan", type=Path, help="Save the generated SVG or plan JSON before drawing.")
    draw_parser.add_argument("--countdown", type=int, default=3, help="Countdown before drawing starts.")
    draw_parser.add_argument("--step-delay-ms", type=int, default=10, help="Delay between interpolated mouse points.")
    draw_parser.add_argument("--between-strokes-ms", type=int, default=180, help="Pause between strokes.")
    draw_parser.add_argument("--padding", type=float, default=0.06, help="Inner padding ratio for the drawing box.")
    draw_parser.add_argument(
        "--mouse-button",
        choices=[button.value for button in MouseButton],
        default=MouseButton.LEFT.value,
        help="Choose which mouse button is held while drawing.",
    )
    draw_parser.add_argument("--dry-run", action="store_true", help="Print the final plan and mapped screen points without drawing.")
    draw_parser.set_defaults(func=command_draw)

    return parser


def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", help="Prompt that describes what and how the bot should draw.")
    parser.add_argument("--word", help="Backward-compatible alias for --prompt.")
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        default="medium",
        help="Controls how much of the object is revealed.",
    )
    parser.add_argument(
        "--style",
        choices=["silhouette", "gesture", "cartoon"],
        default="silhouette",
        help="High-level sketch style for the model.",
    )
    parser.add_argument(
        "--mode",
        choices=list(DRAWING_MODES),
        default="precise",
        help="`precise` draws the literal subject; `pictionary` uses associative clues.",
    )
    parser.add_argument(
        "--pictionary-strategy",
        choices=list(PICTIONARY_STRATEGIES),
        default="scene",
        help="When `--mode pictionary` is used, choose whether clues come from a scene, symbol, or action.",
    )
    parser.add_argument(
        "--reveal-ratio",
        type=float,
        help="How much of the overall plan to keep, from 0.2 to 1.0. Defaults depend on difficulty.",
    )
    parser.add_argument("--instruction", default="", help="Extra guidance, such as side view or top view.")
    parser.add_argument("--api-key", help="OpenAI API key. Defaults to OPENAI_API_KEY if omitted.")
    parser.add_argument("--base-url", help="Optional custom OpenAI-compatible base URL.")
    parser.add_argument(
        "--model",
        help=f"Model to use. Defaults to saved config or {DEFAULT_OPENAI_MODEL} if nothing is saved.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Planner timeout in seconds.")


def command_gui(_: argparse.Namespace) -> int:
    from .gui import launch_gui

    return launch_gui()


def command_calibrate(_: argparse.Namespace) -> int:
    controller = WindowsMouseController()
    print("Move the cursor to the TOP-LEFT corner of the drawing area, then press Enter.")
    input()
    left, top = controller.current_position()
    print(f"Top-left captured at {left},{top}")

    print("Move the cursor to the BOTTOM-RIGHT corner of the drawing area, then press Enter.")
    input()
    right, bottom = controller.current_position()
    width = right - left
    height = bottom - top
    region = Region(left=left, top=top, width=width, height=height)
    region.validate()
    print(f"Region: {region.left},{region.top},{region.width},{region.height}")
    print(json.dumps(region.as_payload(), indent=2))
    return 0


def command_plan(args: argparse.Namespace) -> int:
    persist_runtime_config(args)
    plan = generate_plan_from_args(args)
    payload = plan.svg.strip() or json.dumps(plan.as_payload(), indent=2, ensure_ascii=False)
    print(payload)
    if args.save:
        save_plan_file(args.save, plan)
        print(f"Saved plan to {args.save}")
    return 0


def command_draw(args: argparse.Namespace) -> int:
    persist_runtime_config(args)
    region = Region.parse(args.region) if args.region else None
    if region is None:
        raise SystemExit("--region is required when drawing.")

    plan = load_or_generate_plan(args, region=region)

    if args.save_plan and not args.load_plan:
        save_plan_file(args.save_plan, plan)
        print(f"Saved plan to {args.save_plan}")

    if args.dry_run:
        print(json.dumps(plan.as_payload(), indent=2, ensure_ascii=False))
        print(
            json.dumps(
                {
                    "mouse_button": args.mouse_button,
                    "screen_strokes": plan.to_screen_strokes(region, padding_ratio=args.padding),
                },
                indent=2,
            )
        )
        return 0

    controller = WindowsMouseController()
    timing = DrawTiming(
        countdown_seconds=max(0, args.countdown),
        step_delay_ms=max(1, args.step_delay_ms),
        between_strokes_ms=max(0, args.between_strokes_ms),
        padding_ratio=max(0.0, min(0.3, args.padding)),
    )
    controller.draw_plan(plan, region, timing, button=MouseButton.parse(args.mouse_button))
    return 0


def load_or_generate_plan(args: argparse.Namespace, *, region: Optional[Region] = None) -> DrawPlan:
    if args.load_plan:
        prompt = resolve_prompt(args, require=False) or args.load_plan.stem.replace("-", " ")
        return load_plan_file(args.load_plan, difficulty=args.difficulty, prompt=prompt)
    prompt = resolve_prompt(args, require=True)
    return generate_plan_from_args(args, prompt=prompt, region=region)


def load_plan_file(path: Path, *, difficulty: str, prompt: str) -> DrawPlan:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".svg" or "<svg" in raw_text.lower():
        return DrawPlan.from_svg(
            svg=raw_text,
            prompt=prompt or path.stem.replace("-", " "),
            difficulty=difficulty,
            word=path.stem.replace("-", " "),
        )
    payload = json.loads(raw_text)
    return DrawPlan.from_payload(payload)


def save_plan_file(path: Path, plan: DrawPlan) -> None:
    if path.suffix.lower() == ".svg":
        if not plan.svg.strip():
            raise ValueError("The current plan does not contain raw SVG content.")
        path.write_text(plan.svg.strip() + "\n", encoding="utf-8")
        return
    path.write_text(json.dumps(plan.as_payload(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate_plan_from_args(
    args: argparse.Namespace,
    *,
    prompt: Optional[str] = None,
    region: Optional[Region] = None,
) -> DrawPlan:
    config = resolve_runtime_config(args)
    planner = OpenAIPlanner(
        api_key=config.api_key or None,
        base_url=config.base_url or None,
        model=config.model or DEFAULT_OPENAI_MODEL,
        timeout_seconds=args.timeout,
    )
    return planner.plan(
        prompt=prompt or resolve_prompt(args, require=True),
        difficulty=args.difficulty,
        style=args.style,
        drawing_mode=args.mode,
        pictionary_strategy=args.pictionary_strategy,
        reveal_ratio=args.reveal_ratio,
        region=region,
        extra_instruction=args.instruction,
    )


def resolve_prompt(args: argparse.Namespace, *, require: bool) -> str:
    prompt = str(getattr(args, "prompt", "") or getattr(args, "word", "")).strip()
    if not prompt and require:
        raise ValueError("--prompt is required. --word is accepted as a backward-compatible alias.")
    return prompt


def resolve_runtime_config(args: argparse.Namespace) -> AppConfig:
    saved = ConfigStore().load()
    return AppConfig(
        api_key=(args.api_key if args.api_key is not None else saved.api_key).strip(),
        base_url=(args.base_url if args.base_url is not None else saved.base_url).strip(),
        model=(args.model if args.model is not None else saved.model).strip() or DEFAULT_OPENAI_MODEL,
    )


def persist_runtime_config(args: argparse.Namespace) -> None:
    if not any(getattr(args, name, None) is not None for name in ("api_key", "base_url", "model")):
        return
    ConfigStore().save(resolve_runtime_config(args))


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlannerError as exc:
        parser.exit(status=1, message=f"Planner error: {exc}\n")
    except MouseControlError as exc:
        parser.exit(status=1, message=f"Mouse control error: {exc}\n")
    except ValueError as exc:
        parser.exit(status=1, message=f"Input error: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(status=1, message="Drawing interrupted by user.\n")
