from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel,
    QTabWidget, QTabBar, QSlider
)


# ── Document registry ─────────────────────────────────────────────────────────
# Maps (editor_class, label) → QTextDocument so that the same label opened in
# two different panels of the same editor type shares one live document.
# Edits in either panel are reflected immediately — no polling or prompts.
# Keys are (type, str) so NoteEditor "Untitled 1" ≠ ScreenplayEditor "Untitled 1".
_DOC_REGISTRY: dict[tuple, QTextDocument] = {}


# ── TabbedEditor ──────────────────────────────────────────────────────────────
# Shared base class for all tabbed text editors.
# Provides: tabbed pages, permanent first tab, incremented Untitled N naming,
# scale slider status bar, and file operation stubs (new/open/save/close).
# Subclasses only need to set `name` for the Panel dropdown label.

class TabbedEditor(QWidget):
    name = ""
    _BASE_FONT_SIZE = 12   # point size at 100 %

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tabs)

        self._untitled_counter = 0   # increments with each new tab, never resets

        # ── Status bar ───────────────────────────────────────────────────────
        status = QWidget()
        status.setFixedHeight(24)
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(6, 0, 6, 0)
        status_layout.setSpacing(6)

        status_layout.addStretch()
        status_layout.addWidget(QLabel("Scale:"))

        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(50, 200)
        self._scale_slider.setValue(100)
        self._scale_slider.setFixedWidth(120)
        self._scale_slider.setTickInterval(50)
        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        status_layout.addWidget(self._scale_slider)

        self._scale_label = QLabel("100%")
        self._scale_label.setFixedWidth(36)
        status_layout.addWidget(self._scale_label)

        layout.addWidget(status)

        # Create the initial permanent tab and strip its close button.
        self._add_tab(closable=False)

    def _add_tab(self, closable=True):
        self._untitled_counter += 1
        label = f"Untitled {self._untitled_counter}"

        # Share one QTextDocument per (editor type, label) so that the same
        # document open in multiple panels stays in sync automatically.
        key = (type(self), label)
        if key not in _DOC_REGISTRY:
            _DOC_REGISTRY[key] = QTextDocument()
        doc = _DOC_REGISTRY[key]

        editor = QTextEdit()
        editor.setDocument(doc)
        font = editor.font()
        font.setPointSize(self._current_font_size())
        editor.setFont(font)
        idx = self._tabs.addTab(editor, label)
        if not closable:
            bar = self._tabs.tabBar()
            assert bar is not None
            bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, None)
        self._tabs.setCurrentIndex(idx)

    def _close_tab(self, index):
        self._tabs.removeTab(index)

    def _current_font_size(self):
        return max(6, int(self._BASE_FONT_SIZE * self._scale_slider.value() / 100))

    def _on_scale_changed(self, value):
        self._scale_label.setText(f"{value}%")
        size = max(6, int(self._BASE_FONT_SIZE * value / 100))
        for i in range(self._tabs.count()):
            widget = self._tabs.widget(i)
            if isinstance(widget, QTextEdit):
                font = widget.font()
                font.setPointSize(size)
                widget.setFont(font)

    def new_file(self):
        self._add_tab(closable=True)

    def open_file(self):
        # Placeholder — will open a file dialog and load content.
        self._add_tab(closable=True)

    def save_file(self):    pass
    def save_file_as(self): pass

    def close_current_tab(self):
        idx = self._tabs.currentIndex()
        if idx > 0:   # tab 0 is permanent
            self._close_tab(idx)


# ── Concrete tabbed editors ───────────────────────────────────────────────────
# Full TabbedEditor subclasses — add editor-specific behaviour here as needed.

class NoteEditor(TabbedEditor):
    name = "Note"


class NovelEditor(TabbedEditor):
    name = "Novel"


class ScratchPadEditor(TabbedEditor):
    name = "Scratch Pad"


# ── Simple stub editors ───────────────────────────────────────────────────────
# Plain QTextEdit wrappers — placeholders until each gets its own implementation.

class TimelineEditor(QTextEdit):
    name = "Timeline Editor"


class ScratchBoardEditor(QTextEdit):
    name = "Scratch Board"


class CharacterEditor(QTextEdit):
    name = "Character Editor"
