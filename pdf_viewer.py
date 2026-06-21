from config import APP_NAME
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider,
    QScrollArea, QFileDialog, QMessageBox, QColorDialog
)

try:
    import fitz
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except Exception:
    _NUMPY_AVAILABLE = False

_DEFAULT_BG   = QColor(45,  45,  45)
_DEFAULT_TEXT = QColor(220, 220, 220)


class PDFViewer(QWidget):
    name = "PDF Viewer"

    def __init__(self):
        super().__init__()
        self._doc        = None
        self._page       = 0
        self._continuous = False
        self._bg_color   = QColor(_DEFAULT_BG)
        self._text_color = QColor(_DEFAULT_TEXT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)

        self._page_label = QLabel(
            "Open a PDF file to begin." if _FITZ_AVAILABLE
            else "PyMuPDF is not installed.\n\nRun: pip install PyMuPDF"
        )
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._page_label)
        layout.addWidget(self._scroll)

        # ── Status bar ────────────────────────────────────────────────────────
        status = QWidget()
        status.setFixedHeight(28)
        sl = QHBoxLayout(status)
        sl.setContentsMargins(6, 0, 6, 0)
        sl.setSpacing(4)

        self._mode_btn = QPushButton("≡")
        self._mode_btn.setFixedSize(24, 22)
        self._mode_btn.setToolTip("Switch between continuous scroll and page-by-page")
        self._mode_btn.clicked.connect(self._toggle_mode)
        sl.addWidget(self._mode_btn)

        sl.addSpacing(4)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(26)
        self._prev_btn.clicked.connect(self._prev_page)
        sl.addWidget(self._prev_btn)

        self._page_counter = QLabel("–")
        self._page_counter.setFixedWidth(70)
        self._page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self._page_counter)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(26)
        self._next_btn.clicked.connect(self._next_page)
        sl.addWidget(self._next_btn)

        sl.addStretch()

        sl.addWidget(QLabel("Colors:"))

        self._bg_btn = QPushButton()
        self._bg_btn.setFixedSize(18, 18)
        self._bg_btn.setToolTip("Background color")
        self._bg_btn.clicked.connect(self._pick_bg_color)
        sl.addWidget(self._bg_btn)

        self._text_btn = QPushButton()
        self._text_btn.setFixedSize(18, 18)
        self._text_btn.setToolTip("Text color")
        self._text_btn.clicked.connect(self._pick_text_color)
        sl.addWidget(self._text_btn)

        sl.addSpacing(8)
        sl.addWidget(QLabel("Zoom:"))

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(25, 300)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setTickInterval(25)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        sl.addWidget(self._zoom_slider)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(40)
        sl.addWidget(self._zoom_label)

        layout.addWidget(status)

        self._refresh_color_buttons()
        self._update_nav()

    # ── Color helpers ─────────────────────────────────────────────────────────

    def _refresh_color_buttons(self) -> None:
        for btn, color in ((self._bg_btn, self._bg_color), (self._text_btn, self._text_color)):
            btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")

    def _pick_bg_color(self) -> None:
        color = QColorDialog.getColor(self._bg_color, self, "Background Color")
        if color.isValid():
            self._bg_color = color
            self._refresh_color_buttons()
            self._render()

    def _pick_text_color(self) -> None:
        color = QColorDialog.getColor(self._text_color, self, "Text Color")
        if color.isValid():
            self._text_color = color
            self._refresh_color_buttons()
            self._render()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _page_pixmap(self, page_idx: int) -> QPixmap:
        page  = self._doc[page_idx]
        scale = 2.0 * (self._zoom_slider.value() / 100.0)
        mat   = fitz.Matrix(scale, scale)

        if _NUMPY_AVAILABLE:
            pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            t    = gray.astype(np.float32) / 255.0
            tx, bg = self._text_color, self._bg_color
            r = (tx.red()   + (bg.red()   - tx.red())   * t).clip(0, 255).astype(np.uint8)
            g = (tx.green() + (bg.green() - tx.green()) * t).clip(0, 255).astype(np.uint8)
            b = (tx.blue()  + (bg.blue()  - tx.blue())  * t).clip(0, 255).astype(np.uint8)
            rgb = bytes(np.ascontiguousarray(np.stack([r, g, b], axis=2)))
            img = QImage(rgb, pix.width, pix.height, pix.width * 3,
                         QImage.Format.Format_RGB888).copy()
        else:
            pix = page.get_pixmap(matrix=mat)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format.Format_RGB888)

        return QPixmap.fromImage(img)

    def _render(self) -> None:
        if not self._doc:
            return
        if self._continuous:
            self._render_continuous()
        else:
            self._render_page()

    def _render_page(self) -> None:
        if self._scroll.widget() is not self._page_label:
            old = self._scroll.takeWidget()
            if old:
                old.deleteLater()
            self._scroll.setWidget(self._page_label)
        self._page_label.setPixmap(self._page_pixmap(self._page))
        self._page_label.adjustSize()
        self._update_nav()

    def _render_continuous(self) -> None:
        if self._scroll.widget() is self._page_label:
            self._scroll.takeWidget()
        old = self._scroll.takeWidget()
        if old:
            old.deleteLater()

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)
        vbox.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        for i in range(len(self._doc)):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setPixmap(self._page_pixmap(i))
            vbox.addWidget(lbl)

        container.adjustSize()
        self._scroll.setWidget(container)
        self._update_nav()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _update_nav(self) -> None:
        total    = len(self._doc) if self._doc else 0
        paged    = not self._continuous
        has_prev = self._doc is not None and self._page > 0
        has_next = self._doc is not None and self._page < total - 1

        self._prev_btn.setVisible(paged)
        self._next_btn.setVisible(paged)
        self._prev_btn.setEnabled(has_prev)
        self._next_btn.setEnabled(has_next)
        self._page_counter.setText(
            f"{self._page + 1} / {total}" if (self._doc and paged) else
            f"{total} pages"               if self._doc else "–"
        )
        self._mode_btn.setText("□" if self._continuous else "≡")

    def _toggle_mode(self) -> None:
        self._continuous = not self._continuous
        self._render()

    def _prev_page(self) -> None:
        if self._doc and self._page > 0:
            self._page -= 1
            self._render()

    def _next_page(self) -> None:
        if self._doc and self._page < len(self._doc) - 1:
            self._page += 1
            self._render()

    def _on_zoom_changed(self, value: int) -> None:
        self._zoom_label.setText(f"{value}%")
        self._render()

    def _default_dir(self) -> str:
        return QSettings(APP_NAME, APP_NAME).value("workspace_folder", "")

    # ── File operations ───────────────────────────────────────────────────────

    def open_file(self) -> None:
        if not _FITZ_AVAILABLE:
            QMessageBox.warning(self, "Missing dependency",
                                "Install PyMuPDF first:\n  pip install PyMuPDF")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", self._default_dir(), "PDF files (*.pdf);;All files (*)"
        )
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.warning(self, "Open Failed", str(e))
            return
        if self._doc:
            self._doc.close()
        self._doc  = doc
        self._page = 0
        self._render()

    def new_file(self) -> None:          pass
    def save_file(self) -> None:         pass
    def save_file_as(self) -> None:      pass
    def export_as(self, _: str) -> None: pass
    def close_current_tab(self) -> None: pass
