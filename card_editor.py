from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel,
    QTabWidget, QTabBar, QSlider, QInputDialog
)


# ── CardEditor ────────────────────────────────────────────────────────────────
# A tabbed editor for cards. Currently shares the same tabbed+scale behaviour
# as TabbedEditor but is kept separate because card layout and interaction
# will diverge significantly from plain text editors.

class CardEditor(QWidget):
    name = "Card"
    _BASE_FONT_SIZE = 12   # point size at 100 %

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
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
        editor = QTextEdit()
        font = editor.font()
        font.setPointSize(self._current_font_size())
        editor.setFont(font)
        idx = self._tabs.addTab(editor, f"Untitled {self._untitled_counter}")
        if not closable:
            bar = self._tabs.tabBar()
            assert bar is not None
            bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, None)
        self._tabs.setCurrentIndex(idx)

    def _close_tab(self, index):
        self._tabs.removeTab(index)

    def _on_tab_double_clicked(self, index: int) -> None:
        current = self._tabs.tabText(index)
        name, ok = QInputDialog.getText(self, "Rename Tab", "Name:", text=current)
        if ok and name.strip():
            self._tabs.setTabText(index, name.strip())

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
        self._add_tab(closable=True)

    def save_file(self):        pass
    def save_file_as(self):     pass
    def export_as(self, _: str) -> None: pass

    def close_current_tab(self):
        idx = self._tabs.currentIndex()
        if idx > 0:   # tab 0 is permanent
            self._close_tab(idx)
