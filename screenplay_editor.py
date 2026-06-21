import os
from config import APP_NAME
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLabel, QSlider,
    QInputDialog, QFileDialog, QMessageBox,
    QTabWidget, QTabBar,
    QDialog, QDialogButtonBox, QGridLayout, QSpinBox, QPushButton, QColorDialog
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
_OPEN_FILTER = (
    "Screenplay files (*.fountain *.celtx *.html *.htm);;"
    "Fountain (*.fountain);;Celtx (*.celtx);;HTML (*.html *.htm);;All files (*)"
)

# CSS class names → element types (normalised: lowercase, hyphens/underscores removed).
# Covers Celtx, Highland, Final Draft HTML exports, StudioBinder, and common formats.
_CLASS_MAP: dict[str, int] = {
    # Generic / Celtx / Highland / Final Draft
    "sceneheading": SCENE,  "scene": SCENE, "shot": SCENE, "slugline": SCENE,
    "action":       ACTION,
    "character":    CHARACTER,
    "dialog":       DIALOGUE, "dialogue": DIALOGUE,
    "parenthetical": PAREN,  "paren": PAREN,
    "transition":   TRANSITION,
    # StudioBinder HTML export
    "divtype0": SCENE,
    "divtype2": ACTION,
    "divtype3": CHARACTER,
    "divtype4": PAREN,
    "divtype5": DIALOGUE,
    "divtype6": TRANSITION,
}

# Standard scene heading prefixes recognised by the fountain spec.
_SCENE_PREFIXES = ("INT.", "EXT.", "EST.", "INT./EXT.", "I/E.", "INT/EXT")

# Blank line not needed before these when they follow a character/dialogue block.
_NO_BLANK_BEFORE = {DIALOGUE, PAREN}

# ── Per-element style persistence ─────────────────────────────────────────────

_ELEM_SKEY = {
    SCENE: "scene", ACTION: "action", CHARACTER: "character",
    DIALOGUE: "dialogue", PAREN: "paren", TRANSITION: "transition",
}
_STYLE_DEFAULT: dict[int, dict] = {el: {"size": 12.0, "color": None} for el in ELEMENT_ORDER}


def _load_elem_styles() -> dict[int, dict]:
    s = QSettings(APP_NAME, APP_NAME)
    styles: dict[int, dict] = {}
    for el in ELEMENT_ORDER:
        k = _ELEM_SKEY[el]
        size  = float(s.value(f"screenplay_style/{k}/size", 12.0))
        cstr  = str(s.value(f"screenplay_style/{k}/color", ""))
        styles[el] = {"size": size, "color": QColor(cstr) if cstr else None}
    return styles


def _save_elem_styles(styles: dict[int, dict]) -> None:
    s = QSettings(APP_NAME, APP_NAME)
    for el in ELEMENT_ORDER:
        k = _ELEM_SKEY[el]
        s.setValue(f"screenplay_style/{k}/size",  styles[el]["size"])
        c = styles[el]["color"]
        s.setValue(f"screenplay_style/{k}/color", c.name() if c else "")


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


# ── HTML / Celtx parsers ──────────────────────────────────────────────────────

def _parse_html_content(html: str) -> list[tuple[int, str]]:
    """Parse HTML with screenplay CSS classes into (element_type, text) pairs.

    Class names are normalised (lowercased, hyphens/underscores stripped) before
    lookup in _CLASS_MAP, so scene-heading, sceneheading and scene_heading all work.
    """
    from html.parser import HTMLParser

    class _Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.result: list[tuple[int, str]] = []
            self._el: int | None = None
            self._open_tag: str | None = None
            self._buf: list[str] = []

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag not in ("p", "div") or self._el is not None:
                return
            parts = dict(attrs).get("class", "").lower().split()
            raw = parts[0] if parts else ""
            cls = raw.replace("-", "").replace("_", "")
            el  = _CLASS_MAP.get(cls)
            if el is not None:
                self._el       = el
                self._open_tag = tag
                self._buf      = []

        def handle_endtag(self, tag: str) -> None:
            if tag == self._open_tag and self._el is not None:
                text = "".join(self._buf).strip().replace("\xa0", " ")
                if text:
                    self.result.append((self._el, text))
                self._el       = None
                self._open_tag = None

        def handle_data(self, data: str) -> None:
            if self._el is not None:
                self._buf.append(data)

    p = _Parser()
    p.feed(html)
    return p.result


def _parse_html(path: str) -> list[tuple[int, str]]:
    """Parse a plain .html screenplay file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return _parse_html_content(f.read())


def _parse_celtx(path: str) -> list[tuple[int, str]]:
    """Parse a .celtx file (ZIP + embedded HTML) into (element_type, text) pairs."""
    import zipfile
    with zipfile.ZipFile(path) as zf:
        html_files = sorted(
            [n for n in zf.namelist() if n.lower().endswith(".html")],
            key=lambda n: zf.getinfo(n).file_size,
            reverse=True,
        )
        if not html_files:
            raise ValueError("No HTML content found inside the .celtx file.")
        html = zf.read(html_files[0]).decode("utf-8", errors="replace")
    return _parse_html_content(html)


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
        self._scale = 1.0
        self._elem_styles: dict[int, dict] = {
            el: {"size": 12.0, "color": None} for el in ELEMENT_ORDER
        }
        cursor = self.textCursor()
        self._apply_element(cursor, SCENE, convert=False)
        self.setTextCursor(cursor)

    # ── Element type helpers ──────────────────────────────────────────────────

    def element_at(self, block=None) -> int:
        if block is None:
            block = self.textCursor().block()
        val = block.blockFormat().property(_ELEM_PROP)
        return int(val) if val else ACTION

    def current_element(self) -> int:
        return self.element_at()

    # ── Style helpers ─────────────────────────────────────────────────────────

    def update_styles(self, styles: dict, scale: float) -> None:
        self._elem_styles = styles
        self._scale       = scale
        self._reformat_all()

    def update_scale(self, scale: float) -> None:
        self._scale = scale
        self._reformat_all()

    def _char_fmt_for(self, el: int) -> QTextCharFormat:
        fmt   = QTextCharFormat()
        style = self._elem_styles[el]
        fmt.setFontPointSize(max(6.0, style["size"] * self._scale))
        fmt.setFontWeight(
            QFont.Weight.Bold if el in (SCENE, CHARACTER) else QFont.Weight.Normal
        )
        if style["color"] is not None:
            fmt.setForeground(style["color"])
        return fmt

    def _reformat_all(self) -> None:
        saved = self.textCursor()
        cur   = QTextCursor(self.document())
        cur.beginEditBlock()
        block = self.document().begin()
        while block.isValid():
            el  = self.element_at(block)
            fmt = self._char_fmt_for(el)
            cur.setPosition(block.position())
            end = block.position() + block.length() - 1
            if end > block.position():
                cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cur.setCharFormat(fmt)
                cur.clearSelection()
            self._apply_element(cur, el, convert=False)
            block = block.next()
        cur.endEditBlock()
        self.setTextCursor(saved)

    # ── Formatting ────────────────────────────────────────────────────────────

    def _apply_element(self, cursor: QTextCursor, el: int, convert: bool = True) -> None:
        block_fmt = QTextBlockFormat()
        block_fmt.setProperty(_ELEM_PROP, el)
        left, right = _MARGINS[el]
        block_fmt.setLeftMargin(left)
        block_fmt.setRightMargin(right)
        if el in (SCENE, TRANSITION):
            block_fmt.setTopMargin(14)
        elif el in (CHARACTER, ACTION):
            block_fmt.setTopMargin(7)
        else:
            block_fmt.setTopMargin(0)
        block_fmt.setAlignment(
            Qt.AlignmentFlag.AlignRight if el == TRANSITION
            else Qt.AlignmentFlag.AlignLeft
        )
        cursor.setBlockFormat(block_fmt)
        cursor.setBlockCharFormat(self._char_fmt_for(el))
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
        self._elem_styles = _load_elem_styles()

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

        self._add_tab()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _current_edit(self) -> ScreenplayEdit | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, ScreenplayEdit) else None

    def _current_font_size(self) -> int:
        return max(6, int(self._BASE_FONT_SIZE * self._scale_slider.value() / 100))

    def _on_scale_changed(self, value: int) -> None:
        self._scale_label.setText(f"{value}%")
        scale = value / 100.0
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, ScreenplayEdit):
                w.update_scale(scale)

    def _apply_styles_to_all(self) -> None:
        scale = self._scale_slider.value() / 100.0
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, ScreenplayEdit):
                w.update_styles(self._elem_styles, scale)

    def reload_styles(self) -> None:
        self._elem_styles = _load_elem_styles()
        self._apply_styles_to_all()

    def _is_empty_untitled(self, edit: ScreenplayEdit) -> bool:
        """True when a tab is an unsaved placeholder with no content typed."""
        return (
            edit not in self._paths
            and edit.document().blockCount() == 1
            and edit.document().firstBlock().text() == ""
        )

    def _update_tab_closability(self) -> None:
        """Hide close buttons when only one tab remains so it can't be closed."""
        self._tabs.setTabsClosable(self._tabs.count() > 1)

    def _add_tab(self) -> None:
        self._untitled_counter += 1
        edit = ScreenplayEdit()
        edit.cursorPositionChanged.connect(
            lambda edit=edit: self._on_cursor_moved(edit)
        )
        edit.element_type_applied.connect(
            lambda el, edit=edit: self._on_element_applied(edit, el)
        )
        edit.update_styles(self._elem_styles, self._scale_slider.value() / 100.0)
        self._tabs.addTab(edit, f"Untitled {self._untitled_counter}")
        self._tabs.setCurrentIndex(self._tabs.count() - 1)
        self._update_tab_closability()

    def _close_tab(self, index: int) -> None:
        if self._tabs.count() <= 1:
            return
        widget = self._tabs.widget(index)
        if isinstance(widget, ScreenplayEdit):
            self._paths.pop(widget, None)
        self._tabs.removeTab(index)
        self._update_tab_closability()

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
        self._add_tab()

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Screenplay", self._default_dir(), _OPEN_FILTER
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".celtx":
                elements = _parse_celtx(path)
            elif ext in (".html", ".htm"):
                elements = _parse_html(path)
            else:
                with open(path, encoding="utf-8") as f:
                    elements = _parse_fountain(f.read())
        except Exception as e:
            QMessageBox.warning(self, "Open Failed", str(e))
            return

        # If the only open tab is the empty placeholder, replace it.
        placeholder = self._current_edit()
        replace = (
            self._tabs.count() == 1
            and placeholder is not None
            and self._is_empty_untitled(placeholder)
        )

        self._add_tab()
        edit = self._current_edit()
        if edit:
            self._load_elements(edit, elements)
            if ext == ".fountain":
                self._paths[edit] = path
            self._tabs.setTabText(
                self._tabs.currentIndex(),
                os.path.splitext(os.path.basename(path))[0]
            )

        if replace and placeholder is not None:
            idx = self._tabs.indexOf(placeholder)
            if idx >= 0:
                self._tabs.removeTab(idx)
            self._update_tab_closability()

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


# ── Screenplay settings dialog ────────────────────────────────────────────────

class ScreenplaySettingsDialog(QDialog):
    """Per-element font size and color settings for the screenplay editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screenplay Formatting")
        self.setMinimumWidth(360)
        self._styles = _load_elem_styles()

        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.addWidget(QLabel("<b>Element</b>"),   0, 0)
        grid.addWidget(QLabel("<b>Size (pt)</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Color</b>"),     0, 2)

        self._spins: dict[int, QSpinBox]    = {}
        self._color_btns: dict[int, QPushButton] = {}

        for row, el in enumerate(ELEMENT_ORDER, start=1):
            grid.addWidget(QLabel(ELEMENT_NAMES[el]), row, 0)

            spin = QSpinBox()
            spin.setRange(6, 72)
            spin.setValue(int(self._styles[el]["size"]))
            self._spins[el] = spin
            grid.addWidget(spin, row, 1)

            btn = QPushButton()
            btn.setFixedWidth(60)
            self._color_btns[el] = btn
            self._refresh_color_btn(el)
            btn.clicked.connect(lambda _, e=el: self._pick_color(e))
            grid.addWidget(btn, row, 2)

            clear = QPushButton("×")
            clear.setFixedWidth(24)
            clear.setToolTip("Reset to default color")
            clear.clicked.connect(lambda _, e=el: self._clear_color(e))
            grid.addWidget(clear, row, 3)

        layout.addLayout(grid)

        bottom = QHBoxLayout()
        reset_btn = QPushButton("Reset All Defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        bottom.addWidget(reset_btn)
        bottom.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

    def _refresh_color_btn(self, el: int) -> None:
        btn = self._color_btns[el]
        c   = self._styles[el]["color"]
        if c is not None:
            btn.setText("")
            btn.setStyleSheet(f"background-color:{c.name()}; border:1px solid #888;")
        else:
            btn.setText("auto")
            btn.setStyleSheet("border:1px solid #888;")

    def _pick_color(self, el: int) -> None:
        current = self._styles[el]["color"] or QColor(220, 220, 220)
        c = QColorDialog.getColor(current, self, f"{ELEMENT_NAMES[el]} Color")
        if c.isValid():
            self._styles[el]["color"] = c
            self._refresh_color_btn(el)

    def _clear_color(self, el: int) -> None:
        self._styles[el]["color"] = None
        self._refresh_color_btn(el)

    def _reset_defaults(self) -> None:
        for el in ELEMENT_ORDER:
            self._styles[el] = {"size": 12.0, "color": None}
            self._spins[el].setValue(12)
            self._refresh_color_btn(el)

    def _on_accept(self) -> None:
        for el in ELEMENT_ORDER:
            self._styles[el]["size"] = float(self._spins[el].value())
        _save_elem_styles(self._styles)
        self.accept()

    def styles(self) -> dict:
        return self._styles
