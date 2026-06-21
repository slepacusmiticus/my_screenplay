import sys
import signal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar,
    QSplitter, QStackedWidget,
    QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QTextEdit, QLabel
)


# ── Editors ───────────────────────────────────────────────────────────────────
# Each editor is a self-contained widget representing one type of content.
# Add new editor types here — they'll automatically appear in every Panel's
# type selector dropdown as long as they are added to the EDITORS list.

class TextEditor(QTextEdit):
    name = "Text Editor"


class ScriptEditor(QTextEdit):
    name = "Script Editor"


class ImageViewer(QLabel):
    name = "Image Viewer"

    def __init__(self):
        super().__init__("[ Image Viewer ]")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# Central registry — order here controls order in the dropdown.
EDITORS = [TextEditor, ScriptEditor, ImageViewer]


# ── Panel ─────────────────────────────────────────────────────────────────────
# A Panel is one slot in the workspace. It has two parts:
#   - a thin header bar with a dropdown to choose the active editor type
#   - a QStackedWidget that holds one instance of every editor type
#
# Switching the dropdown swaps the visible page in the stack.
# Editor instances are created once and kept alive for the session,
# so content is preserved when the user switches types and switches back.

class Panel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar ───────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(28)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 2)

        self._type_selector = QComboBox()
        for cls in EDITORS:
            self._type_selector.addItem(cls.name)
        self._type_selector.currentIndexChanged.connect(self._on_type_changed)
        header_layout.addWidget(self._type_selector)
        header_layout.addStretch()

        # ── Editor stack ─────────────────────────────────────────────────────
        # One widget per editor type; only the active one is visible.
        self._stack = QStackedWidget()
        for cls in EDITORS:
            self._stack.addWidget(cls())

        layout.addWidget(header)
        layout.addWidget(self._stack)

    def _on_type_changed(self, index):
        self._stack.setCurrentIndex(index)

    def set_editor(self, index):
        """Set the active editor by EDITORS list index."""
        self._type_selector.setCurrentIndex(index)


# ── Workspace ─────────────────────────────────────────────────────────────────
# The workspace owns a fixed pool of Panel instances and arranges them inside
# nested QSplitters. On every layout switch:
#   1. Current splitter sizes are saved under the layout's name.
#   2. _detach_all() moves panels to a hidden stash to keep them alive.
#   3. A new splitter tree is built and handed to _rebuild().
#   4. Previously saved sizes are restored, or equal splits are applied
#      if this layout has never been visited before.
#
# No QLayout is used — the root splitter's geometry is managed directly so
# Qt's layout engine can never misplace it after a switch.
#
# To add a new layout:
#   1. Add a set_<name>(self) method following the pattern below.
#   2. Wire it up in MyMainWindow._build_menu().

class WorkspaceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # _stash is a hidden widget used as a temporary parent for panels that
        # are not part of the current layout. Parenting to a hidden widget
        # (rather than calling hide() on each panel directly) is deliberate:
        # Qt will auto-show a child when its new parent becomes visible only
        # if the child was never explicitly hidden.
        self._stash = QWidget()
        self._stash.hide()

        self._panels = [Panel(self._stash) for _ in range(3)]
        self._splitter = None
        self._all_splitters = []
        self._current_layout = None
        self._layout_sizes = {}   # saved splitter sizes keyed by layout name

        # Default editor types for the three-panel layout.
        self._panels[0].set_editor(0)   # Text Editor   — top-left
        self._panels[1].set_editor(1)   # Script Editor — top-right
        self._panels[2].set_editor(2)   # Image Viewer  — bottom

        self.set_three()

    def resizeEvent(self, a0):
        """Keep the root splitter filling the entire workspace on window resize.

        Qt's splitter automatically maintains children's proportional sizes when
        it is resized, so we only need to stretch it to fill the workspace.
        We do NOT re-equalize here — that would reset any custom splits the
        user has dragged.
        """
        super().resizeEvent(a0)
        if self._splitter:
            self._splitter.setGeometry(self.rect())

    def _save_current_sizes(self):
        """Snapshot the current splitter sizes before switching to another layout.

        Stored in _layout_sizes under the current layout name so they can be
        restored when the user returns to this layout.
        """
        if self._current_layout and self._all_splitters:
            self._layout_sizes[self._current_layout] = [
                s.sizes() for s in self._all_splitters
            ]

    def _detach_all(self):
        """Move every panel to _stash before rebuilding the splitter tree.

        Must be called before building the new splitter so that addWidget()
        reparents panels into the new splitter correctly. Also prevents unused
        panels from being destroyed when the old splitter is deleted.
        """
        for panel in self._panels:
            panel.setParent(self._stash)

    def _rebuild(self, splitter, all_splitters, layout_name):
        """Replace the current splitter tree and restore or equalise sizes.

        The new splitter is parented directly to the workspace and given the
        full geometry immediately — no layout manager or deferred flush needed.
        Saved sizes for this layout are restored if they exist; otherwise the
        panels are divided equally.
        """
        if self._splitter:
            self._splitter.deleteLater()

        self._splitter = splitter
        self._all_splitters = all_splitters
        self._current_layout = layout_name

        splitter.setParent(self)
        splitter.setGeometry(self.rect())
        splitter.show()

        saved = self._layout_sizes.get(layout_name)
        if saved:
            for s, sizes in zip(all_splitters, saved):
                s.setSizes(sizes)
        else:
            self._equalize()

    def _equalize(self):
        """Divide every splitter in the current tree into equal-sized panels.

        Used only when a layout is visited for the first time and has no saved
        sizes yet. Outer splitter is processed first so inner splitters inherit
        correct dimensions before their own sizes are set.
        """
        for s in self._all_splitters:
            n = s.count()
            if n < 2:
                continue
            total = s.width() if s.orientation() == Qt.Orientation.Horizontal else s.height()
            if total > 0:
                s.setSizes([total // n] * n)

    # ── Layout definitions ───────────────────────────────────────────────────
    # Pattern: save → detach → build → rebuild.
    # _save_current_sizes() must come before _detach_all() so the old splitter
    # is still intact when sizes are read.

    def set_twov(self):
        """Two panels side by side (vertical divider)."""
        self._save_current_sizes()
        self._detach_all()
        s = QSplitter(Qt.Orientation.Horizontal)
        s.addWidget(self._panels[0])
        s.addWidget(self._panels[1])
        self._rebuild(s, [s], 'twov')

    def set_twoh(self):
        """Two panels stacked (horizontal divider)."""
        self._save_current_sizes()
        self._detach_all()
        s = QSplitter(Qt.Orientation.Vertical)
        s.addWidget(self._panels[0])
        s.addWidget(self._panels[1])
        self._rebuild(s, [s], 'twoh')

    def set_three(self):
        """Two panels on top, one spanning the bottom. Default on startup."""
        self._save_current_sizes()
        self._detach_all()
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self._panels[0])
        top.addWidget(self._panels[1])
        s = QSplitter(Qt.Orientation.Vertical)
        s.addWidget(top)
        s.addWidget(self._panels[2])
        # [s, top] order matters: _equalize and size restore process the outer
        # vertical split first so top's height is known before its width is set.
        self._rebuild(s, [s, top], 'three')


# ── Main Window ───────────────────────────────────────────────────────────────

class MyMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My App")
        self.resize(900, 600)
        self._workspace = WorkspaceWidget()
        self.setCentralWidget(self._workspace)
        self._build_menu()

    def _build_menu(self):
        mb = QMenuBar(self)
        self.setMenuBar(mb)

        file_menu = mb.addMenu("File")
        assert file_menu
        file_menu.addAction(QAction("New",  self))
        file_menu.addAction(QAction("Open", self))

        mb.addMenu("Edit")
        mb.addMenu("View")
        mb.addMenu("Help")

        layout_menu = mb.addMenu("Layout")
        assert layout_menu
        layout_menu.addAction(self._action("twov",  self._workspace.set_twov))
        layout_menu.addAction(self._action("twoh",  self._workspace.set_twoh))
        layout_menu.addAction(self._action("three", self._workspace.set_three))

    def _action(self, label, slot):
        """Convenience: create a QAction with a connected slot."""
        a = QAction(label, self)
        a.triggered.connect(slot)
        return a


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Restore default SIGINT handler — Qt replaces it with a no-op.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    window = MyMainWindow()
    window.show()
    sys.exit(app.exec())
