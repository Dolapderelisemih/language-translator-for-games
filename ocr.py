import numpy as np
import cv2
import mss
from rapidocr_onnxruntime import RapidOCR


def is_meaningful(text):
    """Gürültü / ikon / çizgi okumalarını eler: en az 2 harf-rakam ve makul oran."""
    t = "".join(text.split())
    if len(t) < 2:
        return False
    alnum = sum(1 for c in t if c.isalnum())
    return alnum >= 2 and alnum / len(t) >= 0.5


class ScreenOCR:
    """Ekran bölgesini yakalar ve OCR ile okur.

    - Kare önceki taramayla (neredeyse) aynıysa OCR çalıştırılmaz.
    - Bölge ekran sınırlarına kırpılır (çözünürlük/monitör değişimine dayanıklı).
    - Yakalama kapanır/bozulursa yeniden oluşturulabilir (recreate_*).
    """

    MIN_CONFIDENCE = 0.45
    CHANGE_THRESHOLD = 2.0

    def __init__(self, dpr=1.0):
        self.engine = RapidOCR()
        self.sct = mss.MSS()
        self.dpr = float(dpr) if dpr else 1.0
        self._prev_thumb = None
        self._prev_roi = None
        self._prev_text = ""
        self.ocr_runs = 0
        self.skipped = 0

    # ---------------------------------------------------------------- yaşam döngüsü
    def set_dpr(self, dpr):
        self.dpr = float(dpr) if dpr else 1.0
        self.reset()

    def reset(self):
        self._prev_thumb = None
        self._prev_roi = None
        self._prev_text = ""

    def recreate_capture(self):
        """Ekran yakalama tutamacını sıfırdan kurar (ekran modu değişimi vb. sonrası)."""
        try:
            self.sct.close()
        except Exception:
            pass
        self.sct = mss.MSS()
        self.reset()

    def recreate_engine(self):
        self.engine = RapidOCR()
        self.reset()

    # ---------------------------------------------------------------- yakalama
    def _to_physical(self, roi):
        s = self.dpr
        left = int(round(roi["left"] * s))
        top = int(round(roi["top"] * s))
        width = max(1, int(round(roi["width"] * s)))
        height = max(1, int(round(roi["height"] * s)))
        # Sanal ekran sınırlarına kırp
        screen = self.sct.monitors[0]
        x0 = max(left, screen["left"])
        y0 = max(top, screen["top"])
        x1 = min(left + width, screen["left"] + screen["width"])
        y1 = min(top + height, screen["top"] + screen["height"])
        if x1 - x0 < 10 or y1 - y0 < 10:
            return None
        return {"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}

    def grab_region(self, roi):
        box = self._to_physical(roi)
        if box is None:
            return None
        raw_img = self.sct.grab(box)
        frame = np.asarray(raw_img)  # BGRA
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    @staticmethod
    def _thumbnail(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (96, 24), interpolation=cv2.INTER_AREA).astype(np.int16)

    def _unchanged(self, image, roi):
        thumb = self._thumbnail(image)
        same = (
            self._prev_thumb is not None
            and self._prev_roi == roi
            and float(np.mean(np.abs(thumb - self._prev_thumb))) < self.CHANGE_THRESHOLD
        )
        self._prev_thumb = thumb
        self._prev_roi = dict(roi)
        return same

    # ---------------------------------------------------------------- okuma
    def read_image(self, image):
        """BGR numpy görüntüsünden metin çıkarır (test edilebilir çekirdek)."""
        results, _ = self.engine(image)
        if not results:
            return ""
        items = []
        for box, text, score in results:
            if float(score) >= self.MIN_CONFIDENCE and text.strip():
                y = min(p[1] for p in box)
                x = min(p[0] for p in box)
                items.append((y, x, text.strip()))
        items.sort(key=lambda t: (round(t[0] / 12), t[1]))
        joined = " ".join(t[2] for t in items)
        return joined if is_meaningful(joined) else ""

    def extract_text(self, roi):
        if not roi or roi.get("width", 0) <= 10 or roi.get("height", 0) <= 10:
            return ""
        try:
            image = self.grab_region(roi)
            if image is None:
                return ""
            if self._unchanged(image, roi):
                self.skipped += 1
                return self._prev_text
            self.ocr_runs += 1
            self._prev_text = self.read_image(image)
            return self._prev_text
        except Exception:
            self.reset()
            raise

    def close(self):
        try:
            self.sct.close()
        except Exception:
            pass
