import os
from config import APP_NAME
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel, QSlider,
    QInputDialog, QFileDialog, QMessageBox,
    QTabWidget, QTabBar
)


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
    DIALOGUE:   CHARACTER,
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

_SAVE_FILTER = "Fountain files (*.fountain);;All files (*)"
_OPEN_FILTER = "Screenplay files (*.fountain *.celtx);;Fountain (*.fountain);;Celtx (*.celtx);;All files (*)"

# Celtx HTML class names → our element types.
_CELTX_CLASS_MAP: dict[str, int] = {
    "sceneheading": SCENE,  "scene":         SCENE,
    "action":       ACTION,
    "character":    CHARACTER,
    "dialog":       DIALOGUE, "dialogue":    DIALOGUE,
    "parenthetical": PAREN,
    "transition":   TRANSITION,
    "shot":         SCENE,
}

# Standard scene heading prefixes recognised by the fountain spec.
_SCENE_PREFIXES = ("INT.", "EXT.", "EST.", "INT./EXT.", "I/E.", "INT/EXT")

# Blank line not needed before these when they follow a character/dialogue block.
_NO_BLANK_BEFORE = {DIALOGUE, PAREN}


# ── Fountain serialiser ───────────────────────────────────────────────────────

def _to_fountain(document) -> str:
    """Convert a QTextDocument to Fountain plain-text format.

    Element types stored in each block's QTextBlockFormat property are used
    to produce the correct Fountain syntax. Forcing prefixes (!, ., >, @) are
    added only when the line would be misidentified without them.
    """
    lines: list[str] = []
    prev_el: int | None = None

    block = document.begin()
    while block.isValid():
        val = block.blockFormat().property(_ELEM_PROP)
        el  = int(val) if val else ACTION
        text = block.text()

        # Blank line before major elements; omit between character/paren/dialogue.
        if prev_el is not None and el not in _NO_BLANK_BEFORE:
            lines.append("")

        if el == SCENE:
            upper = text.upper()
            # Use '.' forced prefix if the heading doesn't open with INT./EXT./etc.
            if not any(upper.startswith(p) for p in _SCENE_PREFIXES):
                upper = "." + upper
            lines.append(upper)

        elif el == ACTION:
            out = text
            # All-caps action would be misread as a character cue — force with '!'.
            stripped = out.strip()
            if stripped and stripped == stripped.upper() and stripped.replace(" ", "").isalpha():
                out = "!" + out
            lines.append(out)

        elif el == CHARACTER:
            lines.append(text.upper())

        elif el == DIALOGUE:
            lines.append(text)

        elif el == PAREN:
            t = text.strip()
            if not (t.startswith("(") and t.endswith(")")):
                t = f"({t})"
            lines.append(t)

        elif el == TRANSITION:
            upper = text.strip().upper()
            # Standard fountain: all-caps ending in TO:. Use '>' prefix otherwise.
            if not upper.endswith("TO:"):
                upper = "> " + upper
            lines.append(upper)

        prev_el = el
        block = block.next()

    return "\n".join(lines)


# ── Fountain parser ───────────────────────────────────────────────────────────

def _parse_fountain(text: str) -> list[tuple[int, str]]:
    """Parse Fountain plain text into a list of (element_type, text) pairs.

    Blank lines are separators between elements and reset dialogue context;
    they do not produce output blocks. Fountain forcing characters (!, ., >, @)
    are stripped before the text is stored.
    """
    result: list[tuple[int, str]] = []
    in_dialogue = False

    for raw in text.split("\n"):
        line = raw.rstrip()

        # Blank line: separator only — resets dialogue context, no output block.
        if not line.strip():
            in_dialogue = False
            continue

        # Forced action: '!' prefix prevents all-caps lines being read as character.
        if line.startswith("!"):
            result.append((ACTION, line[1:]))
            in_dialogue = False
            continue

        # Forced transition: '>' prefix (optional trailing '<' for centred text).
        if line.startswith(">") and not line.endswith("<"):
            result.append((TRANSITION, line[1:].strip().upper()))
            in_dialogue = False
            continue

        # Forced scene heading: single '.' prefix (not '..' which is an ellipsis).
        if line.startswith(".") and not line.startswith(".."):
            result.append((SCENE, line[1:].upper()))
            in_dialogue = False
            continue

        # Forced character: '@' prefix.
        if line.startswith("@"):
            result.append((CHARACTER, line[1:].upper()))
            in_dialogue = True
            continue

        upper = line.upper()

        # Standard scene heading: starts with a recognised prefix.
        if any(upper.startswith(p) for p in _SCENE_PREFIXES):
            result.append((SCENE, upper))
            in_dialogue = False
            continue

        # Standard transition: all-caps line ending with TO:.
        if line == upper and line.endswith("TO:"):
            result.append((TRANSITION, upper))
            in_dialogue = False
            continue

        # Inside a dialogue block.
        if in_dialogue:
            stripped = line.strip()
            if stripped.startswith("(") and stripped.endswith(")"):
                result.append((PAREN, stripped))
            else:
                result.append((DIALOGUE, line))
            continue

        # Character cue: all-caps non-empty line outside dialogue.
        if line == upper and line.strip():
            result.append((CHARACTER, upper))
            in_dialogue = True
            continue

        # Everything else is action.
        result.append((ACTION, line))
        in_dialogue = False

    return result


# ── Celtx parser ──────────────────────────────────────────────────────────────

def _parse_celtx(path: str) -> list[tuple[int, str]]:
    """Parse a .celtx file (ZIP + embedded HTML) into (element_type, text) pairs.

    Celtx stores the screenplay as an HTML file inside a ZIP archive. Element
    types are identified by the CSS class on each <p> tag and mapped via
    _CELTX_CLASS_MAP. Uses only stdlib (zipfile, html.parser) — no extra deps.
    """
    import zipfile
    from html.parser import HTMLParser

    class _CeltxParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.result: list[tuple[int, str]] = []
            self._el: int | None = None
            self._buf: list[str] = []

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag == "p":
                cls = dict(attrs).get("class", "").lower().split()[0]
                self._el = _CELTX_CLASS_MAP.get(cls)
                self._buf = []

        def handle_endtag(self, tag: str) -> None:
            if tag == "p" and self._el is not None:
                text = "".join(self._buf).strip().replace("\xa0", " ")
                if text:
                    self.result.append((self._el, text))
                self._el = None

        def handle_data(self, data: str) -> None:
            if self._el is not None:
                self._buf.append(data)

    with zipfile.ZipFile(path) as zf:
        # Pick the largest HTML file in the archive — that's the screenplay.
        html_files = sorted(
            [n for n in zf.namelist() if n.lower().endswith(".html")],
            key=lambda n: zf.getinfo(n).file_size,
            reverse=True,
        )
        if not html_files:
            raise ValueError("No HTML content found inside the .celtx file.")
        html = zf.read(html_files[0]).decode("utf-8", errors="replace")

    parser = _CeltxParser()
    parser.feed(html)
    return parser.result


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
        self._paths: dict[ScreenplayEdit, str] = {}  # edit widget → saved file path

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

    # ── Internal helpers ──────────────────────────────────────────────────────

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
        widget = self._tabs.widget(index)
        if isinstance(widget, ScreenplayEdit):
            self._paths.pop(widget, None)
        self._tabs.removeTab(index)

    def _on_tab_double_clicked(self, index: int) -> None:
        current = self._tabs.tabText(index)
        name, ok = QInputDialog.getText(self, "Rename Tab", "Name:", text=current)
        if ok and name.strip():
            self._tabs.setTabText(index, name.strip())

    def _default_dir(self) -> str:
        return QSettings(APP_NAME, APP_NAME).value("workspace_folder", "")

    def _write(self, edit: ScreenplayEdit, path: str) -> bool:
        """Serialise edit's document to Fountain and write to path."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_to_fountain(edit.document()))
            return True
        except OSError as e:
            QMessageBox.warning(self, "Save Failed", str(e))
            return False

    def _load_elements(self, edit: ScreenplayEdit, elements: list[tuple[int, str]]) -> None:
        """Populate edit's document from a parsed element list, replacing all content."""
        edit.clear()
        cursor = edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        for i, (el, text) in enumerate(elements):
            if i > 0:
                cursor.insertBlock()
            edit._apply_element(cursor, el, convert=False)
            # insertText with the block's char format so bold/weight is applied.
            cursor.insertText(text, cursor.blockCharFormat())

        cursor.movePosition(QTextCursor.MoveOperation.Start)
        edit.setTextCursor(cursor)

    def _load_fountain(self, edit: ScreenplayEdit, content: str) -> None:
        self._load_elements(edit, _parse_fountain(content))

    # ── Tab signal handlers ───────────────────────────────────────────────────

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

    # ── Public API ────────────────────────────────────────────────────────────

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

    def new_file(self) -> None:
        self._add_tab(closable=True)

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Screenplay", self._default_dir(), _OPEN_FILTER
        )
        if not path:
            return

        try:
            if path.lower().endswith(".celtx"):
                elements = _parse_celtx(path)
            else:
                with open(path, encoding="utf-8") as f:
                    elements = _parse_fountain(f.read())
        except Exception as e:
            QMessageBox.warning(self, "Open Failed", str(e))
            return

        self._add_tab(closable=True)
        edit = self._current_edit()
        if edit:
            self._load_elements(edit, elements)
            self._paths[edit] = path
            self._tabs.setTabText(
                self._tabs.currentIndex(),
                os.path.splitext(os.path.basename(path))[0]
            )

    def save_file(self) -> None:
        edit = self._current_edit()
        if edit and edit in self._paths:
            self._write(edit, self._paths[edit])
        else:
            self.save_file_as()

    def save_file_as(self) -> None:
        edit = self._current_edit()
        if not edit:
            return
        default_name = self._tabs.tabText(self._tabs.currentIndex()) + ".fountain"
        default_path = os.path.join(self._default_dir(), default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenplay", default_path, _SAVE_FILTER
        )
        if not path:
            return
        if not path.endswith(".fountain"):
            path += ".fountain"
        if self._write(edit, path):
            self._paths[edit] = path
            self._tabs.setTabText(
                self._tabs.currentIndex(),
                os.path.splitext(os.path.basename(path))[0]
            )

    def export_as(self, _: str) -> None:
        pass   # placeholder — fountain is already a plain-text exchange format

    def close_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx > 0:   # tab 0 is permanent
            self._close_tab(idx)
