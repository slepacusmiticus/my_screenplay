from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel,
    QTabWidget, QTabBar, QSlider
)


# ── TextEditor ────────────────────────────────────────────────────────────────
# A tabbed text editor. Each open file gets its own tab.
# The first tab is permanent (no close button); all subsequent tabs are closable.
# A status bar at the bottom holds a scale slider that zooms all tabs together.

class TextEditor(QWidget):
    name = "Text Editor"
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
        editor = QTextEdit()
        font = editor.font()
        font.setPointSize(self._current_font_size())
        editor.setFont(font)
        idx = self._tabs.addTab(editor, "Untitled")
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
