"""Modal file/folder picker."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label


class BrowseScreen(ModalScreen[list]):
    BINDINGS = [Binding("escape", "dismiss_none", "Close")]

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.start = start
        self.picked: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="browse-box"):
            yield Label("Browse — select a file or folder, then press Add", id="browse-title")
            yield DirectoryTree(str(self.start), id="tree")
            yield Label("nothing selected", id="browse-sel")
            with Horizontal(id="browse-btns"):
                yield Button("Add", variant="primary", id="browse-add")
                yield Button("Cancel", id="browse-cancel")

    def _set(self, p: Path) -> None:
        self.picked = p
        self.query_one("#browse-sel", Label).update(f"→ {p}")

    @on(DirectoryTree.FileSelected)
    def _file(self, e: DirectoryTree.FileSelected) -> None:
        self._set(Path(e.path))

    @on(DirectoryTree.DirectorySelected)
    def _dir(self, e: DirectoryTree.DirectorySelected) -> None:
        self._set(Path(e.path))

    @on(Button.Pressed, "#browse-add")
    def _add(self) -> None:
        self.dismiss([self.picked] if self.picked else [])

    @on(Button.Pressed, "#browse-cancel")
    def _cancel(self) -> None:
        self.dismiss([])

    def action_dismiss_none(self) -> None:
        self.dismiss([])
