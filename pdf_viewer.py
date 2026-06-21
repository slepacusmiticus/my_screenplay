from config import APP_NAME
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider,
    QScrollArea, QFileDialog, QMessageBox
)

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False


class PDFViewer(QWidget):
    name = "PDF Viewer"

    def __init__(self):
        super().__init__()
        self._doc  = None
        self._page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Page display ──────────────────────────────────────────────────────
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
        sl.setSpacing(6)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(self._prev_page)
        sl.addWidget(self._prev_btn)

        self._page_counter = QLabel("–")
        self._page_counter.setFixedWidth(70)
        self._page_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(self._page_counter)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(28)
        self._next_btn.clicked.connect(self._next_page)
        sl.addWidget(self._next_btn)

        sl.addStretch()
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
        self._update_nav()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self) -> None:
        if not self._doc:
            return
        page  = self._doc[self._page]
        # Render at 2× base DPI so text stays crisp; zoom scales from there.
        scale = 2.0 * (self._zoom_slider.value() / 100.0)
        mat   = fitz.Matrix(scale, scale)
        pix   = page.get_pixmap(matrix=mat)
        img   = QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QImage.Format.Format_RGB888)
        self._page_label.setPixmap(QPixmap.fromImage(img))
        self._page_label.adjustSize()
        self._update_nav()

    def _update_nav(self) -> None:
        total = len(self._doc) if self._doc else 0
        self._prev_btn.setEnabled(self._doc is not None and self._page > 0)
        self._next_btn.setEnabled(self._doc is not None and self._page < total - 1)
        self._page_counter.setText(f"{self._page + 1} / {total}" if self._doc else "–")

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

    # Stubs so the _FileEditor protocol is satisfied and the File menu doesn't
    # try to call methods that don't apply to a read-only viewer.
    def new_file(self) -> None:       pass
    def save_file(self) -> None:      pass
    def save_file_as(self) -> None:   pass
    def export_as(self, _: str) -> None: pass
    def close_current_tab(self) -> None: pass
