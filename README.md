# draw

`drawbot` is a Windows-first drawing helper for guessing games such as
Pictionary. It can open a desktop control panel, let you marquee-select a
target region, ask an OpenAI-compatible model for a white-background black-line
SVG drawing, and replay that drawing with real mouse movements inside the
selected area.

## What it does

- Launches an always-on-top GUI control panel.
- Lets you drag-select a screen region before drawing.
- Sends your prompt to an OpenAI-compatible endpoint with the official Python
  SDK.
- Asks the model to return white-background black-line `SVG`, then converts that
  `SVG` into normalized strokes and scales them into the selected region.
- Draws with either the left mouse button or the right mouse button.
- Keeps the CLI workflow available for calibration, planning, dry-runs, and
  scripted drawing.

## Requirements

- Windows
- Python 3.9+
- An installed `openai` Python package
- An OpenAI API key or another OpenAI-compatible endpoint

## Quick start

The simplest way to start is:

```powershell
make
```

On the first run it will create a local `.venv`, install dependencies there,
and launch the GUI without touching your current global or Anaconda
environment. After that, `make` starts the app directly from `src` and only
re-runs installation when `pyproject.toml` changes.

If you prefer the manual route, create or activate a Python environment, then
install the package in editable mode during development:

```powershell
pip install -e .
```

Launch the GUI panel:

```powershell
python -m drawbot gui
```

Or start it with the project virtual environment:

```powershell
.\.venv\Scripts\python -m drawbot gui
```

For maintenance:

```powershell
make setup
make sync
make test
```

Use the panel to:

1. keep the window always on top,
2. click `框选区域` to capture the drawing canvas,
3. choose `精准绘画` or `你画我猜`,
4. if you pick `你画我猜`, choose whether clues should come from a `scene`, `symbol`, or `action`,
5. choose a Chinese `细节等级` and `线稿风格`,
6. choose left or right mouse drawing,
7. expand `高级配置` only when you need to modify API key, base URL, or model,
8. write a prompt, click `生成计划` to preview it,
9. confirm the preview looks right, then click `开始绘制`.

The GUI automatically remembers `API Key`, `Base URL`, and `Model` between
launches. On Windows they are stored in a local config file under
`%LOCALAPPDATA%\drawbot\config.json`.

## CLI examples

Capture a drawing box:

```powershell
python -m drawbot calibrate
```

Generate an SVG plan only:

```powershell
python -m drawbot plan --prompt "draw a cat sitting and looking left" --mode precise --model gpt-4o-mini --save cat-plan.svg
```

Preview the mapped screen coordinates without drawing:

```powershell
python -m drawbot draw --prompt "draw a cat sitting and looking left" --region 400,220,700,420 --dry-run
```

Draw for real with the right mouse button:

```powershell
python -m drawbot draw --prompt "draw a cat sitting and looking left" --mode precise --region 400,220,700,420 --mouse-button right
```

Use a custom base URL:

```powershell
python -m drawbot draw --prompt "draw a whale tail silhouette" --region 400,220,700,420 --base-url https://your-endpoint.example/v1 --model gpt-4o-mini
```

Use associative Pictionary-style clues instead of drawing the literal object:

```powershell
python -m drawbot draw --prompt "rainbow" --mode pictionary --pictionary-strategy scene --region 400,220,700,420
```

Use symbolic clues:

```powershell
python -m drawbot draw --prompt "freedom" --mode pictionary --pictionary-strategy symbol --region 400,220,700,420
```

Use action-based clues:

```powershell
python -m drawbot draw --prompt "alarm clock" --mode pictionary --pictionary-strategy action --region 400,220,700,420
```

## Notes

- `--word` is still accepted as a backward-compatible alias for `--prompt`.
- `--mode precise` tries to match the prompt literally, while `--mode pictionary` prefers associative clues.
- `--pictionary-strategy` lets associative mode lean toward scene clues, symbolic clues, or action clues.
- The model is instructed to return raw `SVG` only, with a white background and black linework.
- `drawbot plan` now prints the generated `SVG` by default. Saving to `.svg` writes the raw model output; saving to `.json` writes a richer payload with both parsed strokes and the original `SVG`.
- `drawbot draw --load-plan` accepts either `.svg` or `.json`.
- Saved GUI model settings are also reused by the CLI when the matching flags
  are omitted.
- `easy`, `medium`, and `hard` now act as detail tendencies only: concise, balanced, and detailed.
- By default the full generated drawing is kept. `--reveal-ratio` is optional if you explicitly want a partial plan.
- `Ctrl+C` interrupts the CLI draw loop if you need to stop quickly.

## Tests

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```
