# Contributing

Thanks for taking the time to help. This project is small on purpose: a
compression engine, a CLI, and a Textual UI. Keep changes focused and explain
*why* they are needed in the pull request.

## Setup

```bash
git clone https://github.com/faridhafizh/image-shrinker.git
cd image-shrinker
python -m venv .venv
```

Activate it (`.\.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
elsewhere) and install the project with its dev tools:

```bash
pip install -e ".[dev]"
```

That gives you the `imgshrink` command, plus `pytest` and `ruff`.

## Where things live

| You want to change… | Open |
| --- | --- |
| Encoding, resizing, target-size search | `imgshrink/imaging.py` |
| Format tables, presets, byte formatting | `imgshrink/constants.py`, `imgshrink/config.py` |
| Output naming, skipping, CSV reports | `imgshrink/pipeline.py` |
| Pasted-path parsing, folder walking | `imgshrink/paths.py` |
| Flags, headless mode, entry point | `imgshrink/cli.py` |
| Layout, bindings, queue behaviour | `imgshrink/tui/app.py` |
| The settings form | `imgshrink/tui/settings.py` |
| Preview widget / folder picker | `imgshrink/tui/widgets.py`, `imgshrink/tui/screens.py` |
| Colours and spacing | `imgshrink/tui/app.tcss` |

Rules of thumb:

- `imaging.py` takes Pillow images and returns bytes. It must not know about
  paths, the CLI, or the TUI.
- The CLI must stay importable without Textual, so never import
  `imgshrink.tui` at module scope. `cli.main()` imports it lazily.
- The TUI must not parse `argv`; all of that lives in `cli.py`.

## Tests and lint

```bash
pytest
ruff check .
```

The suite covers the engine, path handling, the per-file pipeline, and a
headless smoke test of the TUI. If you touch the settings form or the queue,
extend `tests/test_tui.py`. Add a regression test with every bug fix.

Both entry points should keep working:

```bash
python -m imgshrink --cli <paths>   # headless
python -m imgshrink                 # TUI
```

## Pull requests

- One concern per PR; avoid mixing refactors with behaviour changes.
- Keep the public CLI flags and the saved config keys backward compatible.
- Mention which OS you tested on. Windows and Linux/macOS are both supported.
