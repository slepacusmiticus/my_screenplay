from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QSlider, QInputDialog, QTabWidget, QTabBar


# ── Element types ─────────────────────────────────────────────────────────────
# Integer constants mirror Trelby's numbering for future compatibility.

SCENE      = 1
ACTION     = 2
CHARACTER  = 3
DIALOGUE   = 4
PAREN      = 5
TRANSITION = 6

ELEMENT_NAMES = {
    SCENE:      "Scene Heading",
    ACTION:     "Action",
    CHARACTER:  "Character",
    DIALOGUE:   "Dialogue",
    PAREN:      "Parenthetical",
    TRANSITION: "Transition",
}

# Element that follows Enter for each type (standard screenplay flow).
NEXT_ON_ENTER = {
    SCENE:      ACTION,
    ACTION:     ACTION,
    CHARACTER:  DIALOGUE,
    DIALOGUE:   CHARACTER,   # Tab overrides this to ACTION when needed
    PAREN:      DIALOGUE,
    TRANSITION: SCENE,
}

# Order Tab/Shift-Tab cycles through.
TAB_CYCLE = [SCENE, ACTION, CHARACTER, DIALOGUE]

# Ordered list used to populate the element-type combo box in the panel header.
ELEMENT_ORDER = [SCENE, ACTION, CHARACTER, DIALOGUE, PAREN, TRANSITION]

# These element types must always be uppercase.
UPPERCASE_TYPES = {SCENE, CHARACTER, TRANSITION}

# Custom property ID stored in QTextBlockFormat to tag the element type.
# IDs >= 0x100000 are reserved for user properties.
_ELEM_PROP = 0x100000

# Pixel left/right margins derived from Trelby's character-unit indents
# (Courier 12pt ≈ 7.2px per char; total line width = 60 chars).
_MARGINS: dict[int, tuple[int, int]] = {
    SCENE:      (0,   0),    # col 0, width 60
    ACTION:     (0,   0),    # col 0, width 60
    CHARACTER:  (158, 0),    # col 22
    DIALOGUE:   (72,  108),  # col 10, width 35  → right = (60-45)*7.2
    PAREN:      (115, 137),  # col 16, width 25  → right = (60-41)*7.2
    TRANSITION: (0,   0),    # right-aligned via AlignRight
}


# ── Core editor widget ────────────────────────────────────────────────────────
# A QTextEdit that tracks a screenplay element type per paragraph and applies
# the correct indentation, alignment, and capitalisation automatically.

class ScreenplayEdit(QTextEdit):
    # Emitted immediately after the element type of the current block changes
    # due to a Tab/Enter key press. cursorPositionChanged is unreliable here:
    # Tab doesn't move the cursor, and Enter fires it before _apply_element runs.
    element_type_applied = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setFont(QFont("Courier New", 12))
        # The first block starts as a Scene Heading.
        cursor = self.textCursor()
        self._apply_element(cursor, SCENE, convert=False)
        self.setTextCursor(cursor)

    # ── Element type helpers ──────────────────────────────────────────────────

    def element_at(self, block=None) -> int:
        """Return the element type stored on a block (default: cursor block)."""
        if block is None:
            block = self.textCursor().block()
        val = block.blockFormat().property(_ELEM_PROP)
        return int(val) if val else ACTION

    def current_element(self) -> int:
        return self.element_at()

    # ── Formatting ────────────────────────────────────────────────────────────

    def _apply_element(self, cursor: QTextCursor, el: int, convert: bool = True) -> None:
        """Apply block/char format for el at the cursor's current block.

        When convert=True, existing block text is uppercased if el requires it.
        """
        block_fmt = QTextBlockFormat()
        char_fmt  = QTextCharFormat()

        block_fmt.setProperty(_ELEM_PROP, el)

        left, right = _MARGINS[el]
        block_fmt.setLeftMargin(left)
        block_fmt.setRightMargin(right)

        if el == SCENE:
            block_fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            char_fmt.setFontWeight(QFont.Weight.Bold)
        elif el == TRANSITION:
            block_fmt.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            block_fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            char_fmt.setFontWeight(QFont.Weight.Normal)

        cursor.setBlockFormat(block_fmt)
        cursor.setBlockCharFormat(char_fmt)

        if convert and el in UPPERCASE_TYPES:
            self._uppercase_block(cursor)

    def _uppercase_block(self, cursor: QTextCursor) -> None:
        """Replace the text of the cursor's block with its uppercase version."""
        block = cursor.block()
        text  = block.text()
        if text == text.upper():
            return
        pos   = cursor.positionInBlock()
        start = block.position()
        cursor.setPosition(start)
        cursor.setPosition(start + len(text), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text.upper())
        cursor.setPosition(start + pos)

    # ── Key handling ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key == Qt.Key.Key_Return:
            cursor  = self.textCursor()
            next_el = NEXT_ON_ENTER.get(self.current_element(), ACTION)
            cursor.insertBlock()
            self._apply_element(cursor, next_el, convert=False)
            self.setTextCursor(cursor)
            self.element_type_applied.emit(next_el)

        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            cursor = self.textCursor()
            el     = self.current_element()
            idx    = TAB_CYCLE.index(el) if el in TAB_CYCLE else 0
            step   = 1 if key == Qt.Key.Key_Tab else -1
            new_el = TAB_CYCLE[(idx + step) % len(TAB_CYCLE)]
            self._apply_element(cursor, new_el)
            self.setTextCursor(cursor)
            self.element_type_applied.emit(new_el)

        else:
            # Auto-uppercase typed characters for scene headings,
            # character cues, and transitions.
            if self.current_element() in UPPERCASE_TYPES and event.text():
                upper = event.text().upper()
                if upper != event.text():
                    event = QKeyEvent(
                        event.type(), event.key(),
                        event.modifiers(), upper
                    )
            super().keyPressEvent(event)


# ── ScreenplayEditor ──────────────────────────────────────────────────────────
# Tabbed wrapper around ScreenplayEdit. Each tab is an independent screenplay
# document. The first tab is permanent (no close button); subsequent tabs are
# closable. The element_changed signal fires whenever the active tab's cursor
# moves to a paragraph with a different element type.

class ScreenplayEditor(QWidget):
    name = "Screenplay"
    _BASE_FONT_SIZE = 12   # Courier New point size at 100 %

    # Emitted when the active tab's cursor enters a paragraph with a new element
    # type. Connected by Panel to keep the header combo in sync.
    element_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_switched)
        self._tabs.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        layout.addWidget(self._tabs)

        self._untitled_counter = 0   # increments with each new tab, never resets

        # ── Status bar ───────────────────────────────────────────────────────
        status = QWidget()
        status.setFixedHeight(24)
        sl = QHBoxLayout(status)
        sl.setContentsMargins(6, 0, 6, 0)
        sl.setSpacing(6)

        sl.addStretch()
        sl.addWidget(QLabel("Scale:"))

        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(50, 200)
        self._scale_slider.setValue(100)
        self._scale_slider.setFixedWidth(120)
        self._scale_slider.setTickInterval(50)
        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        sl.addWidget(self._scale_slider)

        self._scale_label = QLabel("100%")
        self._scale_label.setFixedWidth(36)
        sl.addWidget(self._scale_label)

        layout.addWidget(status)

        # Create the initial permanent tab and strip its close button.
        self._add_tab(closable=False)

    def _current_edit(self) -> ScreenplayEdit | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, ScreenplayEdit) else None

    def _current_font_size(self) -> int:
        return max(6, int(self._BASE_FONT_SIZE * self._scale_slider.value() / 100))

    def _on_scale_changed(self, value: int) -> None:
        self._scale_label.setText(f"{value}%")
        size = max(6, int(self._BASE_FONT_SIZE * value / 100))
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, ScreenplayEdit):
                font = w.font()
                font.setPointSize(size)
                w.setFont(font)

    def _add_tab(self, closable: bool = True) -> None:
        self._untitled_counter += 1
        edit = ScreenplayEdit()
        font = edit.font()
        font.setPointSize(self._current_font_size())
        edit.setFont(font)
        # cursorPositionChanged handles click/arrow navigation between blocks.
        # element_type_applied handles Tab/Enter, which either don't move the
        # cursor (Tab) or fire cursorPositionChanged before the format is set (Enter).
        edit.cursorPositionChanged.connect(
            lambda edit=edit: self._on_cursor_moved(edit)
        )
        edit.element_type_applied.connect(
            lambda el, edit=edit: self._on_element_applied(edit, el)
        )
        idx = self._tabs.addTab(edit, f"Untitled {self._untitled_counter}")
        if not closable:
            bar = self._tabs.tabBar()
            assert bar is not None
            bar.setTabButton(idx, QTabBar.ButtonPosition.RightSide, None)
        self._tabs.setCurrentIndex(idx)

    def _close_tab(self, index: int) -> None:
        self._tabs.removeTab(index)

    def _on_tab_double_clicked(self, index: int) -> None:
        current = self._tabs.tabText(index)
        name, ok = QInputDialog.getText(self, "Rename Tab", "Name:", text=current)
        if ok and name.strip():
            self._tabs.setTabText(index, name.strip())

    def _on_tab_switched(self, _: int) -> None:
        edit = self._current_edit()
        if edit:
            self.element_changed.emit(edit.current_element())

    def _on_cursor_moved(self, edit: ScreenplayEdit) -> None:
        # Only update when the signaling edit is the currently visible tab.
        if self._tabs.currentWidget() is edit:
            self.element_changed.emit(edit.current_element())

    def _on_element_applied(self, edit: ScreenplayEdit, el: int) -> None:
        # Called immediately after Tab/Enter sets a new element type — bypasses
        # the cursorPositionChanged timing issues for those two key events.
        if self._tabs.currentWidget() is edit:
            self.element_changed.emit(el)

    def current_element(self) -> int:
        """Return the element type of the active tab's current paragraph."""
        edit = self._current_edit()
        return edit.current_element() if edit else SCENE

    def set_element(self, el: int) -> None:
        """Change the element type of the current paragraph (called from the panel combo)."""
        edit = self._current_edit()
        if edit:
            cursor = edit.textCursor()
            edit._apply_element(cursor, el)
            edit.setTextCursor(cursor)
            edit.setFocus()

    def new_file(self):
        self._add_tab(closable=True)

    def open_file(self):        pass
    def save_file(self):        pass
    def save_file_as(self):     pass

    def close_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx > 0:   # tab 0 is permanent
            self._close_tab(idx)
