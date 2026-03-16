from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

from .config import AppConfig, ConfigStore
from .models import DrawPlan, Region
from .mouse import DrawTiming, MouseButton, MouseControlError, WindowsMouseController
from .planner import DEFAULT_OPENAI_MODEL, DRAWING_MODES, PICTIONARY_STRATEGIES, OpenAIPlanner, PlannerError

PICTIONARY_STRATEGY_LABELS = {
    "scene": "场景联想",
    "symbol": "符号联想",
    "action": "动作联想",
}

DIFFICULTY_LABELS = {
    "easy": "简洁",
    "medium": "标准",
    "hard": "细致",
}

STYLE_LABELS = {
    "silhouette": "轮廓线稿",
    "gesture": "动态速写",
    "cartoon": "卡通线稿",
}


@dataclass(frozen=True)
class DrawJob:
    prompt: str
    region: Region
    api_key: str
    base_url: str
    model: str
    drawing_mode: str
    pictionary_strategy: str
    difficulty: str
    style: str
    extra_instruction: str
    countdown: int
    mouse_button: MouseButton


class RegionSelector:
    def __init__(self, parent: tk.Tk) -> None:
        self.parent = parent
        self.result: Optional[Region] = None
        self.start_x = 0
        self.start_y = 0
        self.start_canvas_x = 0
        self.start_canvas_y = 0
        self.rect_id: Optional[int] = None

        self.window = tk.Toplevel(parent)
        screen_width = parent.winfo_screenwidth()
        screen_height = parent.winfo_screenheight()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry(f"{screen_width}x{screen_height}+0+0")
        self.window.configure(bg="black")
        try:
            self.window.attributes("-alpha", 0.28)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(self.window, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(
            24,
            24,
            anchor="nw",
            fill="white",
            font=("Microsoft YaHei UI", 16, "bold"),
            text="拖动鼠标框选绘制区域，按 Esc 取消",
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.window.bind("<Escape>", lambda _: self._close())
        self.window.focus_force()

    def select(self) -> Optional[Region]:
        self.parent.wait_window(self.window)
        return self.result

    def _on_press(self, event: tk.Event) -> None:
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.start_canvas_x = event.x
        self.start_canvas_y = event.y
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            self.start_canvas_x,
            self.start_canvas_y,
            self.start_canvas_x,
            self.start_canvas_y,
            outline="#ffcf40",
            width=3,
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self.rect_id is None:
            return
        self.canvas.coords(self.rect_id, self.start_canvas_x, self.start_canvas_y, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        left = min(self.start_x, event.x_root)
        top = min(self.start_y, event.y_root)
        width = abs(event.x_root - self.start_x)
        height = abs(event.y_root - self.start_y)
        if width < 5 or height < 5:
            self._close()
            return

        self.result = Region(left=left, top=top, width=width, height=height)
        self._close()

    def _close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()


class DrawbotPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config_store = ConfigStore()
        self._config = self.config_store.load()
        self._persisting_config = False
        self.root.title("DrawBot 控制面板")
        self.root.geometry("760x920+40+40")
        self.root.minsize(700, 760)
        self.root.attributes("-topmost", True)

        self.keep_on_top_var = tk.BooleanVar(value=True)
        self.region_var = tk.StringVar()
        self.api_key_var = tk.StringVar(value=self._config.api_key)
        self.base_url_var = tk.StringVar(value=self._config.base_url)
        self.model_var = tk.StringVar(value=self._config.model or DEFAULT_OPENAI_MODEL)
        self.model_section_expanded = tk.BooleanVar(value=False)
        self.model_toggle_text_var = tk.StringVar(value="展开高级配置")
        self.model_summary_var = tk.StringVar()
        self.drawing_mode_var = tk.StringVar(value="precise")
        self.pictionary_strategy_var = tk.StringVar(value=PICTIONARY_STRATEGY_LABELS["scene"])
        self.difficulty_var = tk.StringVar(value=DIFFICULTY_LABELS["medium"])
        self.style_var = tk.StringVar(value=STYLE_LABELS["silhouette"])
        self.mouse_button_var = tk.StringVar(value=MouseButton.LEFT.value)
        self.countdown_var = tk.IntVar(value=3)
        self.extra_instruction_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择区域，输入提示词，然后点击绘制。")
        self.plan_summary_var = tk.StringVar(value="尚未生成绘制计划。")
        self.preview_caption_var = tk.StringVar(value="计划预览会显示在这里。")
        self._busy = False

        self._configure_styles()
        self._build_layout()
        self._bind_config_persistence()
        self._update_mode_controls()
        self._update_model_summary()

    def _configure_styles(self) -> None:
        self.root.configure(bg="#edf2f7")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("Page.TFrame", background="#edf2f7")
        style.configure("Card.TLabelframe", background="#ffffff", bordercolor="#d4dde8", relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#17324d", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Card.TLabel", background="#ffffff", foreground="#22364d", font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#60758b", font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Secondary.TButton", font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TCheckbutton", background="#ffffff", foreground="#17324d", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TRadiobutton", background="#ffffff", foreground="#17324d", font=("Microsoft YaHei UI", 10))

    def _build_layout(self) -> None:
        shell = tk.Frame(self.root, bg="#edf2f7")
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg="#17324d", height=78)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="DrawBot 控制面板",
            bg="#17324d",
            fg="white",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w", padx=20, pady=(14, 2))
        tk.Label(
            header,
            text="先生成预览，再决定是否真实绘制",
            bg="#17324d",
            fg="#d7e6f5",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=20)

        content = tk.Frame(shell, bg="#edf2f7")
        content.pack(fill="both", expand=True)

        self.scroll_canvas = tk.Canvas(content, bg="#edf2f7", highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=scrollbar.set)
        self.scroll_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y", padx=(0, 6), pady=10)

        container = ttk.Frame(self.scroll_canvas, style="Page.TFrame", padding=(18, 18, 18, 22))
        container.columnconfigure(0, weight=1)
        self._canvas_window_id = self.scroll_canvas.create_window((0, 0), window=container, anchor="nw")
        self.scroll_canvas.bind("<Configure>", self._handle_scroll_canvas_configure)
        container.bind("<Configure>", self._handle_page_configure)
        self.scroll_canvas.bind("<MouseWheel>", self._on_mousewheel)
        container.bind("<MouseWheel>", self._on_mousewheel)

        options_frame = ttk.LabelFrame(container, text="快捷操作", style="Card.TLabelframe", padding=14)
        options_frame.grid(row=0, column=0, sticky="ew")
        options_frame.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            options_frame,
            text="始终置顶",
            variable=self.keep_on_top_var,
            command=self._apply_topmost,
            style="Accent.TCheckbutton",
        ).grid(row=0, column=0, sticky="w")

        region_frame = ttk.LabelFrame(container, text="绘制区域", style="Card.TLabelframe", padding=14)
        region_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        region_frame.columnconfigure(0, weight=1)
        ttk.Label(region_frame, text="在这里确认选中的屏幕区域。", style="Muted.TLabel").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 8),
        )
        ttk.Entry(region_frame, textvariable=self.region_var).grid(row=1, column=0, sticky="ew", padx=(0, 10))
        ttk.Button(region_frame, text="框选区域", command=self._select_region, style="Secondary.TButton").grid(row=1, column=1)

        model_frame = ttk.LabelFrame(container, text="高级配置", style="Card.TLabelframe", padding=14)
        model_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        model_frame.columnconfigure(0, weight=1)
        model_header = ttk.Frame(model_frame, style="Card.TFrame")
        model_header.grid(row=0, column=0, sticky="ew")
        model_header.columnconfigure(0, weight=1)
        ttk.Label(model_header, textvariable=self.model_summary_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(
            model_header,
            textvariable=self.model_toggle_text_var,
            command=self._toggle_model_section,
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="e")

        self.model_body = ttk.Frame(model_frame, style="Card.TFrame")
        self.model_body.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.model_body.columnconfigure(1, weight=1)
        ttk.Label(self.model_body, text="API Key", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.model_body, textvariable=self.api_key_var, show="*").grid(row=0, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(self.model_body, text="Base URL", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.model_body, textvariable=self.base_url_var).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Label(self.model_body, text="Model", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Entry(self.model_body, textvariable=self.model_var).grid(row=2, column=1, sticky="ew")
        self.model_body.grid_remove()

        prompt_frame = ttk.LabelFrame(container, text="绘制提示词", style="Card.TLabelframe", padding=14)
        prompt_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        prompt_frame.columnconfigure(0, weight=1)
        ttk.Label(prompt_frame, text="直接描述你想让 AI 画什么；精准模式下会尽量贴合本体。", style="Muted.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )
        self.prompt_text = scrolledtext.ScrolledText(
            prompt_frame,
            height=6,
            wrap="word",
            font=("Microsoft YaHei UI", 11),
            relief="solid",
            borderwidth=1,
        )
        self.prompt_text.grid(row=1, column=0, sticky="ew")

        draw_frame = ttk.LabelFrame(container, text="绘制参数", style="Card.TLabelframe", padding=14)
        draw_frame.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        draw_frame.columnconfigure(1, weight=1)
        ttk.Label(draw_frame, text="模式", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        mode_frame = ttk.Frame(draw_frame, style="Card.TFrame")
        mode_frame.grid(row=0, column=1, sticky="w", pady=(0, 10))
        ttk.Radiobutton(mode_frame, text="精准绘画", value="precise", variable=self.drawing_mode_var, style="Accent.TRadiobutton").pack(side="left")
        ttk.Radiobutton(mode_frame, text="你画我猜", value="pictionary", variable=self.drawing_mode_var, style="Accent.TRadiobutton").pack(side="left", padx=(12, 0))

        ttk.Label(draw_frame, text="联想方式", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 10))
        self.pictionary_strategy_combo = ttk.Combobox(
            draw_frame,
            textvariable=self.pictionary_strategy_var,
            values=tuple(PICTIONARY_STRATEGY_LABELS[strategy] for strategy in PICTIONARY_STRATEGIES),
            state="readonly",
        )
        self.pictionary_strategy_combo.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(draw_frame, text="细节等级", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 10))
        ttk.Combobox(
            draw_frame,
            textvariable=self.difficulty_var,
            values=tuple(DIFFICULTY_LABELS[level] for level in ("easy", "medium", "hard")),
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(draw_frame, text="线稿风格", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 10))
        ttk.Combobox(
            draw_frame,
            textvariable=self.style_var,
            values=tuple(STYLE_LABELS[name] for name in ("silhouette", "gesture", "cartoon")),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(draw_frame, text="补充说明", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 10))
        ttk.Entry(draw_frame, textvariable=self.extra_instruction_var).grid(row=4, column=1, sticky="ew", pady=(0, 10))

        ttk.Label(draw_frame, text="鼠标按键", style="Card.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 10))
        button_frame = ttk.Frame(draw_frame, style="Card.TFrame")
        button_frame.grid(row=5, column=1, sticky="w", pady=(0, 10))
        ttk.Radiobutton(button_frame, text="左键", value=MouseButton.LEFT.value, variable=self.mouse_button_var, style="Accent.TRadiobutton").pack(side="left")
        ttk.Radiobutton(button_frame, text="右键", value=MouseButton.RIGHT.value, variable=self.mouse_button_var, style="Accent.TRadiobutton").pack(side="left", padx=(12, 0))

        ttk.Label(draw_frame, text="倒计时", style="Card.TLabel").grid(row=6, column=0, sticky="w")
        ttk.Spinbox(draw_frame, from_=0, to=10, textvariable=self.countdown_var, width=8).grid(row=6, column=1, sticky="w")

        action_frame = ttk.Frame(container, style="Page.TFrame")
        action_frame.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        self.preview_button = ttk.Button(
            action_frame,
            text="生成计划预览",
            command=lambda: self._start_worker(draw_after=False),
            style="Secondary.TButton",
        )
        self.preview_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.draw_button = ttk.Button(
            action_frame,
            text="开始真实绘制",
            command=lambda: self._start_worker(draw_after=True),
            style="Primary.TButton",
        )
        self.draw_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        preview_frame = ttk.LabelFrame(container, text="计划预览", style="Card.TLabelframe", padding=14)
        preview_frame.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        preview_frame.columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(
            preview_frame,
            height=200,
            bg="white",
            highlightthickness=1,
            highlightbackground="#c7d2de",
        )
        self.preview_canvas.grid(row=0, column=0, sticky="ew")
        ttk.Label(preview_frame, textvariable=self.preview_caption_var, wraplength=620, justify="left", style="Muted.TLabel").grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 0),
        )

        status_frame = ttk.LabelFrame(container, text="状态", style="Card.TLabelframe", padding=14)
        status_frame.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=620, justify="left", style="Card.TLabel").pack(fill="x")
        ttk.Label(status_frame, textvariable=self.plan_summary_var, wraplength=620, justify="left", style="Muted.TLabel").pack(fill="x", pady=(8, 0))

    def _apply_topmost(self) -> None:
        self.root.attributes("-topmost", self.keep_on_top_var.get())

    def _handle_scroll_canvas_configure(self, event: tk.Event) -> None:
        if hasattr(self, "_canvas_window_id"):
            self.scroll_canvas.itemconfigure(self._canvas_window_id, width=event.width)

    def _handle_page_configure(self, _event: tk.Event) -> None:
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_config_persistence(self) -> None:
        for variable in (self.api_key_var, self.base_url_var, self.model_var):
            variable.trace_add("write", self._handle_config_change)
        for variable in (self.api_key_var, self.base_url_var, self.model_var):
            variable.trace_add("write", lambda *_args: self._update_model_summary())
        self.drawing_mode_var.trace_add("write", lambda *_args: self._update_mode_controls())

    def _handle_config_change(self, *_args) -> None:
        if self._persisting_config:
            return
        self._save_config()

    def _save_config(self) -> None:
        self._persisting_config = True
        try:
            self._config = AppConfig(
                api_key=self.api_key_var.get().strip(),
                base_url=self.base_url_var.get().strip(),
                model=self.model_var.get().strip() or DEFAULT_OPENAI_MODEL,
            )
            self.config_store.save(self._config)
        finally:
            self._persisting_config = False

    def _update_model_summary(self) -> None:
        model = self.model_var.get().strip() or DEFAULT_OPENAI_MODEL
        endpoint = self.base_url_var.get().strip() or "官方默认"
        key_state = "已保存" if self.api_key_var.get().strip() else "未填写"
        self.model_summary_var.set(f"模型: {model} | 端点: {endpoint} | API Key: {key_state}")

    def _toggle_model_section(self) -> None:
        expanded = not self.model_section_expanded.get()
        self.model_section_expanded.set(expanded)
        if expanded:
            self.model_body.grid()
            self.model_toggle_text_var.set("收起高级配置")
        else:
            self.model_body.grid_remove()
            self.model_toggle_text_var.set("展开高级配置")
        self._handle_page_configure(None)

    def _select_region(self) -> None:
        self.root.withdraw()
        try:
            selector = RegionSelector(self.root)
            region = selector.select()
        finally:
            self.root.deiconify()
            self._apply_topmost()

        if region is not None:
            self.region_var.set(f"{region.left},{region.top},{region.width},{region.height}")
            self._set_status(f"已选择区域: {self.region_var.get()}")

    def _start_worker(self, *, draw_after: bool) -> None:
        if self._busy:
            return

        try:
            job = self._collect_job()
        except ValueError as exc:
            messagebox.showerror("输入错误", str(exc), parent=self.root)
            return

        self._set_busy(True)
        worker = threading.Thread(target=self._run_job, args=(job, draw_after), daemon=True)
        worker.start()

    def _collect_job(self) -> DrawJob:
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            raise ValueError("请先输入绘制提示词。")

        raw_region = self.region_var.get().strip()
        if not raw_region:
            raise ValueError("请先框选一个绘制区域。")

        return DrawJob(
            prompt=prompt,
            region=Region.parse(raw_region),
            api_key=self.api_key_var.get().strip(),
            base_url=self.base_url_var.get().strip(),
            model=self.model_var.get().strip() or DEFAULT_OPENAI_MODEL,
            drawing_mode=self._resolve_drawing_mode(),
            pictionary_strategy=self._resolve_pictionary_strategy(),
            difficulty=self._resolve_difficulty(),
            style=self._resolve_style(),
            extra_instruction=self.extra_instruction_var.get().strip(),
            countdown=max(0, int(self.countdown_var.get())),
            mouse_button=MouseButton.parse(self.mouse_button_var.get()),
        )

    def _run_job(self, job: DrawJob, draw_after: bool) -> None:
        try:
            self._save_config()
            self._set_status("正在请求模型生成绘制计划...")
            planner = OpenAIPlanner(
                api_key=job.api_key or None,
                base_url=job.base_url or None,
                model=job.model,
            )
            plan = planner.plan(
                prompt=job.prompt,
                difficulty=job.difficulty,
                style=job.style,
                drawing_mode=job.drawing_mode,
                pictionary_strategy=job.pictionary_strategy,
                region=job.region,
                extra_instruction=job.extra_instruction,
            )
            self._set_plan_summary(plan)
            self._render_preview(plan)

            if not draw_after:
                self._set_status("绘制计划已生成，请先看预览，确认后再开始绘制。")
                return

            controller = WindowsMouseController()
            timing = DrawTiming(countdown_seconds=job.countdown)
            self._set_status(f"计划已生成，准备使用{self._mouse_button_label(job.mouse_button)}绘制。")
            self.root.after(0, self.root.withdraw)
            controller.draw_plan(
                plan,
                job.region,
                timing,
                button=job.mouse_button,
                progress_callback=self._set_status,
            )
            self._set_status("绘制完成。")
        except (PlannerError, MouseControlError, ValueError) as exc:
            self._show_error(str(exc))
        except Exception as exc:
            self._show_error(f"发生未预期错误: {exc}")
        finally:
            self.root.after(0, self._restore_panel)
            self.root.after(0, lambda: self._set_busy(False))

    def _restore_panel(self) -> None:
        self.root.deiconify()
        self._apply_topmost()

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        state = "disabled" if value else "normal"
        self.preview_button.configure(state=state)
        self.draw_button.configure(state=state)

    def _set_status(self, message: str) -> None:
        self.root.after(0, lambda: self.status_var.set(message))

    def _set_plan_summary(self, plan: DrawPlan) -> None:
        hidden = "、".join(plan.hidden_features) if plan.hidden_features else "无"
        svg_state = "已解析 SVG" if plan.svg.strip() else "轨迹计划"
        summary = f"主题: {plan.word} | 描述: {plan.description} | 隐藏特征: {hidden} | 来源: {svg_state}"
        self.root.after(0, lambda: self.plan_summary_var.set(summary))

    def _render_preview(self, plan: DrawPlan) -> None:
        def callback() -> None:
            canvas = self.preview_canvas
            canvas.delete("all")
            width = max(1, canvas.winfo_width() or 500)
            height = max(1, canvas.winfo_height() or 220)
            padding = 18
            inner_width = max(1, width - padding * 2)
            inner_height = max(1, height - padding * 2)

            canvas.create_rectangle(
                padding,
                padding,
                width - padding,
                height - padding,
                outline="#d9d9d9",
                fill="#ffffff",
            )

            for stroke in plan.strokes:
                coords = []
                for point in stroke.points:
                    x = padding + (point.x / 100.0) * inner_width
                    y = padding + (point.y / 100.0) * inner_height
                    coords.extend((x, y))
                if len(coords) >= 4:
                    canvas.create_line(
                        *coords,
                        fill="#111111",
                        width=2,
                        smooth=True,
                    )

            caption = f"{self._drawing_mode_label()}模式"
            if self._resolve_drawing_mode() == "pictionary":
                caption += f" / {self._pictionary_strategy_label()}"
            caption += f"，共 {len(plan.strokes)} 笔，当前预览来自白底黑线 SVG 的本地解析结果。"
            self.preview_caption_var.set(caption)

        self.root.after(0, callback)

    def _show_error(self, message: str) -> None:
        def callback() -> None:
            self.status_var.set(message)
            messagebox.showerror("执行失败", message, parent=self.root)

        self.root.after(0, callback)

    def _mouse_button_label(self, button: MouseButton) -> str:
        return "左键" if button is MouseButton.LEFT else "右键"

    def _resolve_drawing_mode(self) -> str:
        mode = self.drawing_mode_var.get().strip().lower() or "precise"
        if mode not in DRAWING_MODES:
            return "precise"
        return mode

    def _resolve_pictionary_strategy(self) -> str:
        label = self.pictionary_strategy_var.get().strip()
        for strategy, strategy_label in PICTIONARY_STRATEGY_LABELS.items():
            if label == strategy_label:
                return strategy
        return "scene"

    def _resolve_difficulty(self) -> str:
        label = self.difficulty_var.get().strip()
        for difficulty, difficulty_label in DIFFICULTY_LABELS.items():
            if label == difficulty_label:
                return difficulty
        return "medium"

    def _resolve_style(self) -> str:
        label = self.style_var.get().strip()
        for style, style_label in STYLE_LABELS.items():
            if label == style_label:
                return style
        return "silhouette"

    def _drawing_mode_label(self) -> str:
        return "精准绘画" if self._resolve_drawing_mode() == "precise" else "你画我猜"

    def _pictionary_strategy_label(self) -> str:
        return PICTIONARY_STRATEGY_LABELS.get(self._resolve_pictionary_strategy(), "场景联想")

    def _update_mode_controls(self) -> None:
        if not hasattr(self, "pictionary_strategy_combo"):
            return
        if self._resolve_drawing_mode() == "pictionary":
            self.pictionary_strategy_combo.configure(state="readonly")
        else:
            self.pictionary_strategy_combo.configure(state="disabled")


def launch_gui() -> int:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    DrawbotPanel(root)
    root.mainloop()
    return 0
