import ctypes
from ctypes import wintypes

from PyQt6.QtCore import Qt, QRect, pyqtSlot, QTimer
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtGui import QFont, QFontMetrics, QColor

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
# Windows 10 (2004+): pencereyi ekran yakalamadan hariç tutar. Böylece OCR,
# kendi ürettiği Türkçe altyazıyı değil, altındaki orijinal oyun metnini okur.
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HWND_TOPMOST = -1

# Başka kütüphanelerin (keyboard vb.) ctypes ayarlarıyla çakışmamak için özel örnek
try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
except Exception:  # Windows dışı ortam
    _user32 = None


def compute_overlay_rect(roi, screen, mode, capture_excluded, strip_height=100):
    """Altyazı penceresinin konumunu hesaplar.

    mask  + yakalamadan hariç : tam ROI üzerine (orijinal metni kapatır).
    diğer durumlar            : ROI ile KESİŞMEYEN şerit (üstte, olmazsa altta).
    Katman yakalamadan hariç tutulamıyorsa (eski Windows) kesişmeme zorunludur;
    aksi halde OCR kendi çıktısını okur.
    """
    sx, sy, sw, sh = screen.x(), screen.y(), screen.width(), screen.height()
    if not roi:
        w, h = min(840, sw), strip_height
        return QRect(sx + (sw - w) // 2, sy + sh - h - 80, w, h)

    rx, ry, rw, rh = roi["left"], roi["top"], roi["width"], roi["height"]
    if mode == "mask" and capture_excluded:
        x0, y0 = max(rx, sx), max(ry, sy)
        x1, y1 = min(rx + rw, sx + sw), min(ry + rh, sy + sh)
        return QRect(x0, y0, max(40, x1 - x0), max(30, y1 - y0))

    w = min(max(rw, 520), sw)
    h = strip_height
    x = min(max(rx + (rw - w) // 2, sx), sx + sw - w)
    above = ry - h - 8
    below = ry + rh + 8
    if above >= sy:
        y = above
    elif below + h <= sy + sh:
        y = below
    else:
        y = max(sy, min(above, sy + sh - h))
    return QRect(x, y, w, h)


class TransparentOverlay(QWidget):
    PAD_X, PAD_Y, BORDER = 14, 8, 1

    def __init__(self, config=None):
        super().__init__()
        self.config = config or {}
        self.capture_excluded = False
        self._text = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.shadow = QGraphicsDropShadowEffect()
        self.shadow.setBlurRadius(8)
        self.shadow.setColor(QColor(0, 0, 0, 255))
        self.shadow.setOffset(2, 2)
        self.label.setGraphicsEffect(self.shadow)
        self.layout.addWidget(self.label)

        # Altyazı ekranda sonsuza dek takılı kalmasın (0 = kapalı)
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.timeout.connect(self.hide_overlay)

        # Oyunlar z-sırasını çalabilir: görünürken periyodik olarak en üste al
        self.topmost_timer = QTimer(self)
        self.topmost_timer.setInterval(1500)
        self.topmost_timer.timeout.connect(self._reassert_topmost)

        self.apply_style()
        # Yerel pencereyi hemen oluştur ve yakalamadan hariç tut (gizliyken de geçerli)
        self.apply_native_flags()

    # ---------------------------------------------------------------- stil
    def apply_style(self):
        cfg = self.config
        alpha = int(cfg.get("bg_opacity", 0.90) * 255)
        text_color = cfg.get("text_color", "#FFDE59")
        border_style = cfg.get("border_style", "game_box")

        if cfg.get("text_align", "center") == "left":
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        else:
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if border_style == "game_box":
            border_css = f"border: {self.BORDER}px solid rgba(255, 222, 89, 100);"
        elif border_style == "subtle":
            border_css = f"border: {self.BORDER}px solid rgba(255, 255, 255, 50);"
        else:
            border_css = "border: none;"

        self.label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                background-color: rgba(12, 14, 18, {alpha});
                border-radius: 6px;
                {border_css}
                padding: {self.PAD_Y}px {self.PAD_X}px;
            }}
        """)
        self._fit_font()

    def update_config(self, new_config):
        self.config = new_config
        self.apply_style()

    # ---------------------------------------------------------------- sığdırma
    def _fit_font(self):
        """Türkçe çeviri genelde daha uzundur: metin kutuya sığana dek yazıyı küçült."""
        family = self.config.get("font_family", "Bahnschrift")
        base = int(self.config.get("font_size", 18))
        text = self._text
        avail_w = max(40, self.width() - 2 * self.PAD_X - 2 * self.BORDER)
        avail_h = max(16, self.height() - 2 * self.PAD_Y - 2 * self.BORDER)
        flags = Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignLeft.value
        size = base
        if text:
            while size > 9:
                font = QFont(family, size, QFont.Weight.Bold)
                rect = QFontMetrics(font).boundingRect(0, 0, avail_w, 100000, flags, text)
                if rect.height() <= avail_h:
                    break
                size -= 1
        self.label.setFont(QFont(family, size, QFont.Weight.Bold))
        self.fitted_size = size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_font()

    # ---------------------------------------------------------------- Windows API
    def apply_native_flags(self):
        """Tıklama geçirgenliği + ekran yakalamadan hariç tutma."""
        if _user32 is None:
            self.capture_excluded = False
            return
        try:
            hwnd = int(self.winId())
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            _user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
            )
            self.capture_excluded = bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
        except Exception:
            self.capture_excluded = False

    def showEvent(self, event):
        super().showEvent(event)
        self.apply_native_flags()
        self.topmost_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.topmost_timer.stop()

    def _reassert_topmost(self):
        if _user32 is None or not self.isVisible():
            return
        try:
            _user32.SetWindowPos(
                int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    # ---------------------------------------------------------------- metin
    @pyqtSlot()
    def hide_overlay(self):
        self.auto_hide_timer.stop()
        self._text = ""
        self.label.setText("")
        self.hide()

    @pyqtSlot(str)
    def update_text(self, text):
        clean = text.strip()
        if not clean:
            self.hide_overlay()
            return
        if clean != self._text:
            self._text = clean
            self._fit_font()
            self.label.setText(clean)
        if not self.isVisible():
            self.show()
        delay = float(self.config.get("auto_hide_delay", 0.0))
        if delay > 0:
            self.auto_hide_timer.start(int(delay * 1000))
        else:
            self.auto_hide_timer.stop()
