from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent
from typing import Optional

from .models import DrawPlan, Region
from .svg import extract_svg_fragment


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DRAWING_MODES = ("precise", "pictionary")
PICTIONARY_STRATEGIES = ("scene", "symbol", "action")

DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "viewpoint": {"type": "string"},
        "pose": {"type": "string"},
        "composition": {"type": "string"},
        "silhouette": {"type": "string"},
        "anchor_features": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {"type": "string"},
        },
        "stroke_intent": {
            "type": "array",
            "minItems": 2,
            "maxItems": 12,
            "items": {"type": "string"},
        },
        "avoid": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string"},
        },
    },
    "required": ["subject", "viewpoint", "pose", "composition", "silhouette", "anchor_features", "stroke_intent", "avoid"],
    "additionalProperties": False,
}


class PlannerError(RuntimeError):
    """Raised when the model cannot produce a usable drawing plan."""


class OpenAIPlanner:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_OPENAI_MODEL,
        timeout_seconds: int = 120,
        workdir: Optional[Path] = None,
    ) -> None:
        self.api_key = (api_key or "").strip() or None
        self.base_url = (base_url or "").strip() or None
        self.model = (model or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        self.timeout_seconds = timeout_seconds
        self.workdir = Path.cwd() if workdir is None else Path(workdir)

    def build_system_prompt(self) -> str:
        return dedent(
            """
            You are planning a desktop mouse drawing.

            Sometimes you must return strict JSON that matches a schema exactly.
            Sometimes you must return raw SVG markup only.
            Follow the requested output format exactly and do not add markdown unless the user explicitly asked for it.

            The goal is visual recognition, correct structure, and reliable mouse reproduction.
            """
        ).strip()

    def build_mode_guidance(self, drawing_mode: str, pictionary_strategy: str = "scene") -> str:
        normalized = (drawing_mode or "precise").strip().lower()
        if normalized == "precise":
            return dedent(
                """
                Drawing mode: precise.
                - Draw the literal target itself as faithfully as possible.
                - Preserve the subject's defining silhouette, structure, and proportions.
                - Do not replace the target with symbols, metaphors, or related objects.
                - Accuracy is more important than simplicity.
                - Do not intentionally reduce detail just to keep the drawing short.
                """
            ).strip()
        if normalized == "pictionary":
            strategy = (pictionary_strategy or "scene").strip().lower()
            if strategy == "scene":
                strategy_clause = (
                    "- Prefer a small scene or contextual clue that strongly evokes the target.\n"
                    "- The drawing should feel like a memorable moment associated with the word."
                )
            elif strategy == "symbol":
                strategy_clause = (
                    "- Prefer symbolic, metaphorical, or iconic clues that point to the target.\n"
                    "- Use visual association rather than a literal portrait whenever possible."
                )
            elif strategy == "action":
                strategy_clause = (
                    "- Prefer an action, effect, posture, or use-case that suggests the target.\n"
                    "- Show what the target does or causes instead of drawing only the object itself."
                )
            else:
                raise ValueError(f"Unsupported pictionary strategy: {pictionary_strategy}")
            return dedent(
                """
                Drawing mode: pictionary.
                - Use associative visual clues instead of directly drawing the target whenever possible.
                - The abstraction should come from association, not from leaving the drawing incomplete.
                - The result should still converge on one strong guess.
                - Keep the composition coherent and recognizable.
                """
            ).strip() + "\n" + strategy_clause
        raise ValueError(f"Unsupported drawing mode: {drawing_mode}")

    def build_difficulty_guidance(self, difficulty: str, drawing_mode: str) -> str:
        normalized = (difficulty or "medium").strip().lower()
        mode = (drawing_mode or "precise").strip().lower()
        if normalized == "easy":
            if mode == "precise":
                return "Detail level: clear large shapes with only the most essential defining details."
            return "Association level: direct, immediate clues."
        if normalized == "medium":
            if mode == "precise":
                return "Detail level: balanced structure plus several important defining details."
            return "Association level: balanced clues that require a little inference."
        if normalized == "hard":
            if mode == "precise":
                return "Detail level: richer structure, stronger proportions, and more identifying detail."
            return "Association level: more indirect clues, but still visually coherent."
        raise ValueError(f"Unsupported difficulty: {difficulty}")

    def build_style_guidance(self, style: str, drawing_mode: str) -> str:
        normalized = (style or "silhouette").strip().lower()
        mode = (drawing_mode or "precise").strip().lower()
        if normalized == "silhouette":
            return "Style guidance: use clean contour-first linework with readable outer shape and restrained internal detail."
        if normalized == "gesture":
            if mode == "precise":
                return (
                    "Style guidance: keep some line energy, but never let sketchiness distort anatomy, structure, or proportions."
                )
            return "Style guidance: flowing line energy is acceptable if the associative clue remains readable."
        if normalized == "cartoon":
            return "Style guidance: allow stylization, but keep the major proportions and iconic features accurate."
        raise ValueError(f"Unsupported style: {style}")

    def build_user_prompt(
        self,
        *,
        prompt: str,
        difficulty: str,
        style: str,
        drawing_mode: str,
        pictionary_strategy: str,
        region: Optional[Region],
        extra_instruction: str = "",
    ) -> str:
        extra = extra_instruction.strip() or "none"
        mode_clause = self.build_mode_guidance(drawing_mode, pictionary_strategy=pictionary_strategy)
        difficulty_clause = self.build_difficulty_guidance(difficulty, drawing_mode)
        style_clause = self.build_style_guidance(style, drawing_mode)
        if region is None:
            region_clause = "Drawing region size is unknown. Compose for a balanced rectangular canvas."
        else:
            region_clause = (
                f"Target drawing region is {region.width} by {region.height} pixels "
                f"(aspect ratio {region.aspect_ratio:.2f}). Compose for that shape."
            )

        return dedent(
            f"""
            User drawing request: {prompt}
            Difficulty: {difficulty}
            Style: {style}
            {mode_clause}
            {difficulty_clause}
            {style_clause}
            Additional instruction: {extra}
            {region_clause}

            Quality requirements:
            - Make the drawing clearly recognizable at a glance.
            - Preserve correct proportions and the subject's most distinctive structures.
            - Add meaningful internal details when they improve recognition.
            - Fill most of the 100x100 canvas while leaving a small margin.
            - Before responding, mentally verify that the result would still look correct if drawn by a mouse.
            """
        ).strip()

    def build_design_prompt(
        self,
        *,
        prompt: str,
        difficulty: str,
        style: str,
        drawing_mode: str,
        pictionary_strategy: str,
        region: Optional[Region],
        extra_instruction: str = "",
    ) -> str:
        user_prompt = self.build_user_prompt(
            prompt=prompt,
            difficulty=difficulty,
            style=style,
            drawing_mode=drawing_mode,
            pictionary_strategy=pictionary_strategy,
            region=region,
            extra_instruction=extra_instruction,
        )
        return dedent(
            f"""
            First, design the drawing before converting it into SVG.

            {user_prompt}

            Design requirements:
            - Choose the most iconic and recognizable viewpoint unless the prompt asked for a specific one.
            - For animals, vehicles, tools, and household objects, prefer a canonical side view or three-quarter view over unusual poses.
            - `anchor_features` must list the structural traits that must survive into the final SVG.
            - `stroke_intent` must describe the major stroke groups in drawing order.
            - `avoid` must list common failure modes that would make the drawing inaccurate or confusing.
            """
        ).strip()

    def build_svg_from_design_prompt(
        self,
        *,
        prompt: str,
        difficulty: str,
        style: str,
        drawing_mode: str,
        design: dict,
        region: Optional[Region],
        extra_instruction: str = "",
    ) -> str:
        region_clause = "unknown canvas shape" if region is None else f"{region.width}x{region.height} region"
        return dedent(
            f"""
            Convert the following drawing design into SVG line art for a mouse drawing bot.

            Original request: {prompt}
            Difficulty: {difficulty}
            Style: {style}
            Drawing mode: {drawing_mode}
            Canvas: {region_clause}
            Additional instruction: {extra_instruction.strip() or "none"}

            Approved design:
            {json.dumps(design, ensure_ascii=False, indent=2)}

            SVG requirements:
            - Return only valid SVG markup. No markdown, no commentary, no JSON.
            - The root must be `<svg ... viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">`.
            - Include a white background, typically with one white `<rect>` covering the full canvas.
            - All visible drawing marks must be black lines.
            - Use `fill="none"` for drawing elements. Do not use color other than white background and black strokes.
            - Accuracy is more important than simplicity. Do not limit stroke count or path complexity just to be short.
            - Occupy most of the canvas with a small margin, keeping correct proportions.
            - Prefer `<path>`, `<polyline>`, `<polygon>`, `<line>`, `<circle>`, `<ellipse>`, and `<rect>`.
            - Do not use `transform`, CSS, script, text, letters, numbers, arrows, filters, masks, or images.
            - Do not use SVG arc commands `A` or `a`; convert arcs into bezier curves instead.
            - Use smooth, coherent contours and enough detail to keep the subject recognizable.
            """
        ).strip()

    def build_repair_prompt(
        self,
        *,
        prompt: str,
        drawing_mode: str,
        style: str,
        design: dict,
        draft_svg: str,
    ) -> str:
        return dedent(
            f"""
            Review and repair this SVG drawing.

            Target request: {prompt}
            Drawing mode: {drawing_mode}
            Style: {style}

            Approved design:
            {json.dumps(design, ensure_ascii=False, indent=2)}

            Draft SVG:
            {draft_svg}

            Repair goals:
            - Improve recognition, proportions, silhouette, and structure.
            - Preserve the most distinctive anchor features.
            - Remove awkward, misleading, or low-value lines.
            - Keep the SVG white-background black-line only.
            - Return only the repaired SVG markup.
            - Accuracy still beats simplicity.
            """
        ).strip()

    def plan(
        self,
        *,
        prompt: str,
        difficulty: str,
        style: str = "silhouette",
        drawing_mode: str = "precise",
        pictionary_strategy: str = "scene",
        reveal_ratio: Optional[float] = None,
        region: Optional[Region] = None,
        extra_instruction: str = "",
    ) -> DrawPlan:
        target_ratio = None if reveal_ratio is None else max(0.2, min(1.0, reveal_ratio))
        client = self._build_client()

        try:
            design = self._request_json(
                client=client,
                schema_name="draw_design",
                schema=DESIGN_SCHEMA,
                user_prompt=self.build_design_prompt(
                    prompt=prompt,
                    difficulty=difficulty,
                    style=style,
                    drawing_mode=drawing_mode,
                    pictionary_strategy=pictionary_strategy,
                    region=region,
                    extra_instruction=extra_instruction,
                ),
            )
            draft_svg = self._request_svg(
                client=client,
                user_prompt=self.build_svg_from_design_prompt(
                    prompt=prompt,
                    difficulty=difficulty,
                    style=style,
                    drawing_mode=drawing_mode,
                    design=design,
                    region=region,
                    extra_instruction=extra_instruction,
                ),
            )
            repaired_svg = self._request_svg(
                client=client,
                user_prompt=self.build_repair_prompt(
                    prompt=prompt,
                    drawing_mode=drawing_mode,
                    style=style,
                    design=design,
                    draft_svg=draft_svg,
                ),
            )
        except Exception as exc:
            raise self._wrap_model_error(exc) from exc

        try:
            plan = DrawPlan.from_svg(
                svg=repaired_svg,
                prompt=prompt,
                difficulty=difficulty,
                word=str(design.get("subject", "")).strip(),
                description=str(design.get("silhouette", "")).strip(),
                hidden_features=tuple(str(item).strip() for item in design.get("avoid", []) if str(item).strip()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PlannerError(f"The model returned an unusable SVG drawing plan: {exc}") from exc

        fitted_plan = plan.fitted(margin=8.0)
        if target_ratio is None or target_ratio >= 0.999:
            return fitted_plan
        return fitted_plan.trimmed(target_ratio)

    def _request_json(
        self,
        *,
        client,
        schema_name: str,
        schema: dict,
        user_prompt: str,
    ) -> dict:
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )

        raw_output = (getattr(response, "output_text", "") or "").strip()
        if not raw_output:
            raise PlannerError("The model returned no structured drawing data.")
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise PlannerError("The model returned invalid JSON for the drawing design.") from exc
        if not isinstance(payload, dict):
            raise PlannerError("The model returned a non-object JSON payload.")
        return payload

    def _request_svg(
        self,
        *,
        client,
        user_prompt: str,
    ) -> str:
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw_output = (getattr(response, "output_text", "") or "").strip()
        if not raw_output:
            raise PlannerError("The model returned empty SVG content.")
        try:
            return extract_svg_fragment(raw_output)
        except ValueError as exc:
            raise PlannerError(f"The model did not return usable SVG: {exc}") from exc

    def _build_client(self):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise PlannerError("The `openai` package is required. Install project dependencies first.") from exc

        options = {"timeout": float(self.timeout_seconds)}
        if self.api_key:
            options["api_key"] = self.api_key
        if self.base_url:
            options["base_url"] = self.base_url
        return OpenAI(**options)

    def _wrap_model_error(self, exc: Exception) -> PlannerError:
        if isinstance(exc, PlannerError):
            return exc

        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
        except ImportError:
            return PlannerError(str(exc))

        if isinstance(exc, APITimeoutError):
            return PlannerError("The OpenAI request timed out while generating the drawing plan.")
        if isinstance(exc, RateLimitError):
            return PlannerError("The OpenAI request was rate limited. Try again in a moment.")
        if isinstance(exc, APIConnectionError):
            return PlannerError("The OpenAI request could not reach the configured endpoint.")
        if isinstance(exc, APIStatusError):
            return PlannerError(f"OpenAI request failed with status {exc.status_code}: {exc.message}")
        return PlannerError(str(exc))
