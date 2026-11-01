import os
import sys
import tempfile
import time
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel

import config as cfgmod
cfgmod.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "settings.json")

import translator as trmod
from translator import GameTranslator
from async_translator import AsyncTranslator
from ocr import ScreenOCR, is_meaningful
from overlay import TransparentOverlay, compute_overlay_rect

FAILS = []

def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [HATA] ") + name + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def test_translator():
    print("1) Çeviri Modülü & Çoklu Sağlayıcı Yedeklemesi")
    calls = []
    t = GameTranslator()

    def fake_dict(text):
        calls.append(("dict", text))
        return "TR_DICT:" + text

    def fake_gtx(text):
        calls.append(("gtx", text))
        return "TR_GTX:" + text

    t.providers[0].fn = fake_dict
    t.providers[1].fn = fake_gtx

    # Temel çeviri
    res = t.translate("Defeat 5 goblins")
    check("birincil sağlayıcı çalışıyor", res == "TR_DICT:Defeat 5 goblins")
    
    # Önbellek testi
    res2 = t.translate("Defeat 5 goblins")
    check("birebir aynı metin önbellekten döndü", res2 == res and len(calls) == 1)

    # Rakam değişimi testi
    t.translate("Defeat 6 goblins")
    check("rakam değiştiğinde yeni çeviri yapıldı", len(calls) == 2)

    # Birincil sağlayıcı çökerse ikincil sağlayıcıya otomatik geçiş (Fallback)
    def broken_dict(text):
        raise OSError("Bağlantı kesildi")

    t.providers[0].fn = broken_dict
    t.providers[0].blocked_until = time.monotonic() + 10  # arızalı olarak işaretle
    res_fallback = t.translate("Find the hidden relic")
    check("arızada yedek sağlayıcı devreye girdi", res_fallback == "TR_GTX:Find the hidden relic")


def test_async_translator(app):
    print("2) Asenkron Çevirici İş Parçacığı (AsyncTranslator)")
    at = AsyncTranslator()
    results = []
    at.result.connect(lambda orig, tr: results.append((orig, tr)))

    at.translator.providers[0].fn = lambda text: "TR:" + text
    at.submit("Hello brave hero")
    
    # Cevabın arka plandan gelmesini bekle ve Qt olay döngüsünü işle
    t0 = time.time()
    while not results and time.time() - t0 < 3.0:
        app.processEvents()
        time.sleep(0.03)

    check("asenkron çeviri sinyali geldi", len(results) == 1 and results[0][1] == "TR:Hello brave hero")
    at.stop()


def test_ocr(app):
    print("3) OCR Filtreleme ve Ekran Yakalama")
    check("anlamsız gürültü metinleri filtreleniyor", not is_meaningful("---...___") and is_meaningful("Quest: Level 5"))

    game = QLabel("Collect twelve glowing mushrooms in the cave")
    game.setFont(QFont("Arial", 26, QFont.Weight.Bold))
    game.setStyleSheet("background:#202020; color:#FFFFFF; padding:20px;")
    game.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    game.setGeometry(300, 300, 1100, 110)
    game.show()

    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)
    time.sleep(0.3)

    ocr = ScreenOCR()
    roi = {"left": 300, "top": 300, "width": 1100, "height": 110}
    text = ocr.extract_text(roi)
    check("metin OCR ile doğru okundu", "mushrooms" in text.lower(), repr(text))

    # Değişmeyen karede CPU yükü testi
    t0 = time.perf_counter()
    for _ in range(10):
        ocr.extract_text(roi)
    elapsed = (time.perf_counter() - t0) * 1000 / 10
    check("değişmeyen karede OCR atlanıyor (<30ms)", ocr.skipped >= 9 and elapsed < 30.0, f"{elapsed:.1f} ms")

    ocr.close()
    game.close()


def test_overlay_autofit(app):
    print("4) Altyazı Otomatik Font Küçültme & Kırpma")
    overlay = TransparentOverlay({"font_size": 28, "font_family": "Bahnschrift"})
    overlay.setGeometry(400, 400, 500, 80)
    
    # Çok uzun bir metin gönder
    long_text = "Bu çok uzun bir Türkçe oyun diyalog cümlesidir ve kutunun dışına taşmaması için font boyutunun otomatik olarak küçültülmesi gerekmektedir."
    overlay.update_text(long_text)
    app.processEvents()

    check("uzun metinde font otomatik küçültüldü", overlay.fitted_size < 28, f"fitted: {overlay.fitted_size}")
    overlay.hide_overlay()
    overlay.close()


def main():
    app = QApplication(sys.argv)
    for fn in (test_translator, lambda: test_async_translator(app), lambda: test_ocr(app), lambda: test_overlay_autofit(app)):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            FAILS.append("istisna: " + getattr(fn, "__name__", "test"))
    print()
    print("TÜM SİSTEM VE STABİLİTE TESTLERİ GEÇTİ" if not FAILS else f"BAŞARISIZ TESTLER: {FAILS}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
