import sys
import os
import time
import logging
from logging.handlers import RotatingFileHandler
import keyboard
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QSlider, QTextEdit,
    QGroupBox, QMessageBox
)
from PyQt6.QtGui import QFont

from config import load_config, save_config
from ocr import ScreenOCR
from async_translator import AsyncTranslator
from overlay import TransparentOverlay, compute_overlay_rect
from selector import RegionSelector

# pythonw.exe konsolsuz çalıştığı için hatalar dosyaya yazılır
_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translator.log")
log = logging.getLogger("oyuncevirici")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = RotatingFileHandler(_LOG_PATH, maxBytes=512_000, backupCount=1, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)


def _excepthook(exc_type, exc, tb):
    log.error("Yakalanmayan hata", exc_info=(exc_type, exc, tb))


sys.excepthook = _excepthook


class TranslationWorker(QThread):
    """Sürekli ekranı tarayan, metin değişikliklerini takip eden ve
    daktilo (typewriter) efektini stabilize ederek asenkron çeviriciye ileten iş parçacığı.
    """
    raw_detected = pyqtSignal(str)
    clear_requested = pyqtSignal()

    def __init__(self, config, async_translator, dpr=1.0):
        super().__init__()
        self.config = config
        self.async_translator = async_translator
        self.dpr = dpr
        self.running = False
        self.paused = False
        self.ocr = None
        self.last_sent_text = ""
        self.pending_text = ""
        self.pending_ticks = 0
        self.empty_count = 0
        self._reset_flag = False

    def run(self):
        try:
            self.ocr = ScreenOCR(dpr=self.dpr)
        except Exception:
            log.exception("OCR motoru başlatılamadı")
            return

        self.running = True
        log.info("OCR tarama iş parçacığı başladı (DPR=%s)", self.dpr)

        sentence_enders = ('.', '!', '?', '…', '"', '”', '。', '！', '？')

        while self.running:
            if self.paused or not self.config.get("roi"):
                time.sleep(0.25)
                continue

            if self._reset_flag:
                self._reset_flag = False
                if self.ocr:
                    self.ocr.reset()
                self.last_sent_text = ""
                self.pending_text = ""
                self.pending_ticks = 0
                self.empty_count = 0

            roi = self.config.get("roi")
            try:
                cleaned = self.ocr.extract_text(roi).strip()

                if cleaned:
                    self.empty_count = 0
                    
                    # Eğer metin önceden gönderilenle aynıysa bir şey yapma
                    if cleaned == self.last_sent_text:
                        self.pending_text = ""
                        self.pending_ticks = 0
                    else:
                        # Daktilo / Karakter karakter beliren metin stabilizasyonu (Debounce):
                        # Cümle sonu noktalaması varsa hemen gönder; yoksa 1 döngü bekle
                        is_expanding = (
                            self.pending_text and 
                            (cleaned.startswith(self.pending_text) or self.pending_text.startswith(cleaned))
                        )
                        ends_sentence = cleaned.endswith(sentence_enders)

                        if ends_sentence or self.pending_ticks >= 1 or not is_expanding:
                            self.last_sent_text = cleaned
                            self.pending_text = ""
                            self.pending_ticks = 0
                            self.async_translator.submit(cleaned)
                            self.raw_detected.emit(cleaned)
                        else:
                            # Metin henüz yazılmaya devam ediyor, bir sonraki kareyi bekle
                            self.pending_text = cleaned
                            self.pending_ticks += 1

                else:
                    self.empty_count += 1
                    # 2 ardışık boş okumada ekrandaki altyazıyı gizle ve sıfırla
                    if self.empty_count == 2:
                        self.last_sent_text = ""
                        self.pending_text = ""
                        self.pending_ticks = 0
                        self.async_translator.cancel()
                        self.clear_requested.emit()

            except Exception:
                log.exception("Tarama döngüsü hatası")

            interval = float(self.config.get("scan_interval", 0.8))
            time.sleep(max(0.2, interval))

        if self.ocr:
            self.ocr.close()

    def reset_history(self):
        self._reset_flag = True

    def stop(self):
        self.running = False
        self.wait(1500)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.setWindowTitle("Canlı Oyun Çevirici — Maksimum Stabilite")
        self.resize(580, 720)

        # Şeffaf Altyazı Katmanı
        self.overlay = TransparentOverlay(self.config)
        self.selector = None

        # Asenkron Çevirici (Ağ istekleri ayrı iş parçacığında çalışır)
        self.async_translator = AsyncTranslator(
            source_lang=self.config.get("source_lang", "auto"),
            target_lang=self.config.get("target_lang", "tr")
        )
        self.async_translator.result.connect(self.on_translation_result)
        self.async_translator.failed.connect(self.on_translation_failed)
        self.async_translator.recovered.connect(self.on_translation_recovered)

        # OCR Tarama İş Parçacığı
        dpr = QApplication.primaryScreen().devicePixelRatio()
        self.worker = TranslationWorker(self.config, self.async_translator, dpr=dpr)
        self.worker.clear_requested.connect(self.overlay.hide_overlay)

        self.setup_ui()
        self.setup_hotkeys()
        self.reposition_overlay()

        # Otomatik bekçi zamanlayıcısı (Watchdog - iş parçacıklarının sağlığını denetler)
        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.setInterval(4000)
        self.watchdog_timer.timeout.connect(self.check_system_health)
        self.watchdog_timer.start()

        self.worker.start()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(14, 14, 14, 14)

        # Modern Dark Theme CSS
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0D1117;
                color: #C9D1D9;
                font-family: 'Segoe UI', Tahoma, sans-serif;
            }
            QGroupBox {
                border: 1px solid #30363D;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 14px;
                font-weight: bold;
                color: #58A6FF;
            }
            QPushButton {
                background-color: #21262D;
                border: 1px solid #30363D;
                border-radius: 6px;
                color: #FFFFFF;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363D;
                border-color: #58A6FF;
            }
            QPushButton#dangerBtn {
                background-color: #4C1D24;
                border-color: #F85149;
            }
            QPushButton#dangerBtn:hover {
                background-color: #DA3633;
            }
            QComboBox, QSpinBox {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 5px 8px;
                color: #E6EDF3;
            }
            QTextEdit {
                background-color: #161B22;
                border: 1px solid #30363D;
                border-radius: 6px;
                color: #C9D1D9;
                font-size: 12px;
            }
        """)

        # 1. Başlık & Durum
        title_box = QHBoxLayout()
        title_label = QLabel("🛡️ Canlı Oyun Çevirici")
        title_label.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.status_badge = QLabel("● Çeviri Aktif")
        self.status_badge.setStyleSheet("color: #7EE787; font-weight: bold;")
        title_box.addWidget(title_label)
        title_box.addStretch()
        title_box.addWidget(self.status_badge)
        main_layout.addLayout(title_box)

        # 2. Hızlı Kontroller
        action_group = QGroupBox("Kontroller & Kısayollar")
        action_layout = QVBoxLayout(action_group)

        btn_row = QHBoxLayout()
        self.btn_select_roi = QPushButton("🎯 Alanı Seç (F9)")
        self.btn_select_roi.clicked.connect(self.start_region_selection)
        
        self.btn_toggle = QPushButton("⏸️ Duraklat (F8)")
        self.btn_toggle.clicked.connect(self.toggle_translation)

        self.btn_clear = QPushButton("🧹 Ekranı Temizle (F10)")
        self.btn_clear.setObjectName("dangerBtn")
        self.btn_clear.clicked.connect(self.clear_screen)

        self.btn_preview = QPushButton("👁️ Önizleme")
        self.btn_preview.clicked.connect(self.preview_overlay)
        
        btn_row.addWidget(self.btn_select_roi)
        btn_row.addWidget(self.btn_toggle)
        btn_row.addWidget(self.btn_clear)
        btn_row.addWidget(self.btn_preview)
        action_layout.addLayout(btn_row)

        roi = self.config.get("roi")
        roi_text = f"{roi['width']}x{roi['height']} px (X:{roi['left']}, Y:{roi['top']})" if roi else "Seçilmedi (Oyundayken F9'a basıp seçin)"
        self.lbl_roi = QLabel(f"Seçili Bölge: {roi_text}")
        self.lbl_roi.setStyleSheet("color: #8B949E; font-size: 11px;")
        action_layout.addWidget(self.lbl_roi)

        main_layout.addWidget(action_group)

        # 3. Görünüm Ayarları
        style_group = QGroupBox("Türkçe Yama Görünüm Ayarları")
        style_layout = QVBoxLayout(style_group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Yerleşim Modu:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Tam Örtü Modu (Orijinal Yazıyı Kapatır)", "mask")
        self.combo_mode.addItem("Sinematik Altyazı Şeridi (Ekranın Altı)", "bottom")
        if self.config.get("overlay_mode", "mask") == "bottom":
            self.combo_mode.setCurrentIndex(1)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        mode_row.addWidget(self.combo_mode)
        style_layout.addLayout(mode_row)

        font_color_row = QHBoxLayout()
        font_color_row.addWidget(QLabel("Yazı Rengi:"))
        self.combo_color = QComboBox()
        self.combo_color.addItem("RPG Altın Sarısı (#FFDE59)", "#FFDE59")
        self.combo_color.addItem("Klasik Beyaz (#FFFFFF)", "#FFFFFF")
        self.combo_color.addItem("Buz Mavisi (#64D2FF)", "#64D2FF")
        self.combo_color.addItem("Neon Yeşil (#7EE787)", "#7EE787")
        cur_col = self.config.get("text_color", "#FFDE59")
        for i in range(self.combo_color.count()):
            if self.combo_color.itemData(i) == cur_col:
                self.combo_color.setCurrentIndex(i)
        self.combo_color.currentIndexChanged.connect(self.on_color_changed)
        font_color_row.addWidget(self.combo_color)

        font_color_row.addWidget(QLabel("Font:"))
        self.combo_font = QComboBox()
        self.combo_font.addItems(["Bahnschrift", "Trebuchet MS", "Segoe UI", "Verdana", "Arial"])
        cur_f = self.config.get("font_family", "Bahnschrift")
        self.combo_font.setCurrentText(cur_f)
        self.combo_font.currentTextChanged.connect(self.on_font_family_changed)
        font_color_row.addWidget(self.combo_font)
        style_layout.addLayout(font_color_row)

        tune_row = QHBoxLayout()
        tune_row.addWidget(QLabel("Boyut:"))
        self.spin_font = QSpinBox()
        self.spin_font.setRange(12, 38)
        self.spin_font.setValue(self.config.get("font_size", 18))
        self.spin_font.valueChanged.connect(self.on_font_size_changed)
        tune_row.addWidget(self.spin_font)

        tune_row.addWidget(QLabel("Kaybolma (sn, 0=oto):"))
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 30)
        self.spin_delay.setValue(int(self.config.get("auto_hide_delay", 0.0)))
        self.spin_delay.valueChanged.connect(self.on_delay_changed)
        tune_row.addWidget(self.spin_delay)

        tune_row.addWidget(QLabel("Opaklık (%):"))
        self.slider_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(30, 100)
        self.slider_alpha.setValue(int(self.config.get("bg_opacity", 0.90) * 100))
        self.slider_alpha.valueChanged.connect(self.on_opacity_changed)
        tune_row.addWidget(self.slider_alpha)
        style_layout.addLayout(tune_row)

        main_layout.addWidget(style_group)

        # 4. Dil ve Hız Ayarları
        lang_group = QGroupBox("Dil & Algılama")
        lang_layout = QHBoxLayout(lang_group)

        lang_layout.addWidget(QLabel("Kaynak Dil:"))
        self.combo_source = QComboBox()
        self.combo_source.addItems([
            "Otomatik Algıla (auto)",
            "İngilizce (en)",
            "Çince (zh-CN)"
        ])
        src = self.config.get("source_lang", "auto")
        for i in range(self.combo_source.count()):
            if f"({src})" in self.combo_source.itemText(i):
                self.combo_source.setCurrentIndex(i)
                break
        self.combo_source.currentIndexChanged.connect(self.on_language_changed)
        lang_layout.addWidget(self.combo_source)

        lang_layout.addWidget(QLabel("Tarama Hızı:"))
        self.combo_speed = QComboBox()
        self.combo_speed.addItem("Hızlı (0.5 sn)", 0.5)
        self.combo_speed.addItem("Normal (0.8 sn)", 0.8)
        self.combo_speed.addItem("Hafif (1.2 sn)", 1.2)
        cur_int = self.config.get("scan_interval", 0.8)
        for i in range(self.combo_speed.count()):
            if abs(self.combo_speed.itemData(i) - cur_int) < 0.1:
                self.combo_speed.setCurrentIndex(i)
        self.combo_speed.currentIndexChanged.connect(self.on_speed_changed)
        lang_layout.addWidget(self.combo_speed)

        main_layout.addWidget(lang_group)

        # 5. Canlı Çeviri Akışı
        log_group = QGroupBox("Canlı Çeviri Günlüğü")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Oyundaki metinler algılandıkça burada gösterilecektir...")
        log_layout.addWidget(self.log_view)
        main_layout.addWidget(log_group)

    def reposition_overlay(self):
        roi = self.config.get("roi")
        screen_geom = QApplication.primaryScreen().geometry()
        mode = self.config.get("overlay_mode", "mask")
        
        target_rect = compute_overlay_rect(
            roi=roi,
            screen=screen_geom,
            mode=mode,
            capture_excluded=self.overlay.capture_excluded
        )
        self.overlay.setGeometry(target_rect)

    def clear_screen(self):
        """Ekrandaki altyazıyı anında gizler ve geçmişi sıfırlar"""
        self.async_translator.cancel()
        self.overlay.hide_overlay()
        self.worker.reset_history()
        self.status_badge.setText("● Temizlendi")
        self.status_badge.setStyleSheet("color: #8B949E; font-weight: bold;")
        QTimer.singleShot(1500, lambda: self.status_badge.setText("● Çeviri Aktif" if not self.worker.paused else "● Duraklatıldı"))

    def preview_overlay(self):
        sample = "Bu diyarın kaderi senin ellerinde, cesur savaşçı!"
        self.reposition_overlay()
        self.overlay.update_text(sample)

    def start_region_selection(self):
        self.selector = RegionSelector()
        self.selector.region_selected.connect(self.on_region_selected)
        self.selector.show()

    def on_region_selected(self, roi):
        self.config["roi"] = roi
        save_config(self.config)
        self.worker.config = self.config
        self.worker.reset_history()
        self.lbl_roi.setText(f"Seçili Bölge: {roi['width']}x{roi['height']} px (X:{roi['left']}, Y:{roi['top']})")
        self.reposition_overlay()
        self.preview_overlay()

    def toggle_translation(self):
        self.worker.paused = not self.worker.paused
        if self.worker.paused:
            self.btn_toggle.setText("▶️ Başlat (F8)")
            self.status_badge.setText("● Duraklatıldı")
            self.status_badge.setStyleSheet("color: #D29922; font-weight: bold;")
            self.async_translator.cancel()
            self.overlay.hide_overlay()
        else:
            self.btn_toggle.setText("⏸️ Duraklat (F8)")
            self.status_badge.setText("● Çeviri Aktif")
            self.status_badge.setStyleSheet("color: #7EE787; font-weight: bold;")

    def setup_hotkeys(self):
        try:
            keyboard.add_hotkey("f8", lambda: QTimer.singleShot(0, self.toggle_translation))
            keyboard.add_hotkey("f9", lambda: QTimer.singleShot(0, self.start_region_selection))
            keyboard.add_hotkey("f10", lambda: QTimer.singleShot(0, self.clear_screen))
        except Exception:
            log.warning("Klavye kısayolları kaydedilemedi (Yönetici izni gerekebilir)")

    def on_mode_changed(self):
        self.config["overlay_mode"] = self.combo_mode.currentData()
        save_config(self.config)
        self.reposition_overlay()

    def on_color_changed(self):
        self.config["text_color"] = self.combo_color.currentData()
        save_config(self.config)
        self.overlay.update_config(self.config)

    def on_font_family_changed(self, font_name):
        self.config["font_family"] = font_name
        save_config(self.config)
        self.overlay.update_config(self.config)

    def on_font_size_changed(self, val):
        self.config["font_size"] = val
        save_config(self.config)
        self.overlay.update_config(self.config)

    def on_delay_changed(self, val):
        self.config["auto_hide_delay"] = float(val)
        save_config(self.config)
        self.overlay.update_config(self.config)

    def on_opacity_changed(self, val):
        opacity = val / 100.0
        self.config["bg_opacity"] = opacity
        save_config(self.config)
        self.overlay.update_config(self.config)

    def on_language_changed(self):
        text = self.combo_source.currentText()
        if "(" in text and ")" in text:
            code = text.split("(")[-1].split(")")[0]
            self.config["source_lang"] = code
            save_config(self.config)
            self.async_translator.set_languages(code, self.config.get("target_lang", "tr"))

    def on_speed_changed(self):
        self.config["scan_interval"] = self.combo_speed.currentData()
        save_config(self.config)

    def on_translation_result(self, original, translated):
        self.overlay.update_text(translated)
        self.add_log(original, translated)

    def on_translation_failed(self, msg):
        self.status_badge.setText(f"● {msg}")
        self.status_badge.setStyleSheet("color: #F85149; font-weight: bold;")

    def on_translation_recovered(self):
        if not self.worker.paused:
            self.status_badge.setText("● Çeviri Aktif")
            self.status_badge.setStyleSheet("color: #7EE787; font-weight: bold;")

    def check_system_health(self):
        # Watchdog: OCR iş parçacığı beklenmedik şekilde çökerse otomatik yeniden başlat
        if not self.worker.isRunning() and not self.worker.paused:
            log.warning("Bekçi uyarısı: OCR iş parçacığı durmuş, yeniden başlatılıyor")
            dpr = QApplication.primaryScreen().devicePixelRatio()
            self.worker = TranslationWorker(self.config, self.async_translator, dpr=dpr)
            self.worker.clear_requested.connect(self.overlay.hide_overlay)
            self.worker.start()

    def add_log(self, original, translated):
        if not self.worker.paused:
            self.status_badge.setText("● Çeviri Aktif")
            self.status_badge.setStyleSheet("color: #7EE787; font-weight: bold;")
        # Günlük sınırsız büyümesin (uzun oyun oturumlarında bellek tüketimi)
        if self.log_view.document().blockCount() > 250:
            self.log_view.clear()
        timestamp = time.strftime("%H:%M:%S")
        entry = (
            f"<div style='margin-bottom:6px;'>"
            f"<span style='color:#8B949E;'>[{timestamp}]</span> "
            f"<span style='color:#79C0FF;'>[Orijinal]</span>: {original}<br>"
            f"<span style='color:#FFDE59;'>[Türkçe]</span>: <b>{translated}</b>"
            f"</div>"
        )
        self.log_view.append(entry)

    def closeEvent(self, event):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.watchdog_timer.stop()
        self.worker.stop()
        self.async_translator.stop()
        self.overlay.hide_overlay()
        self.overlay.close()
        event.accept()


_single_instance_mutex = None

def acquire_single_instance():
    """Aynı anda birden fazla çevirici penceresinin açılmasını engeller."""
    global _single_instance_mutex
    try:
        import ctypes
        mutex_name = "Global\\HexFearGameTranslatorMutex"
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
        last_error = ctypes.windll.kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            return False
        _single_instance_mutex = mutex
        return True
    except Exception:
        return True


def main():
    if not acquire_single_instance():
        app = QApplication(sys.argv)
        QMessageBox.warning(None, "Canlı Oyun Çevirici", "Program zaten arka planda çalışıyor!\nMasaüstü tepsisinden veya pencerelerden kontrol edin.")
        sys.exit(0)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    code = app.exec()
    log.info("Uygulama başarıyla kapandı (kod=%s)", code)
    logging.shutdown()
    os._exit(code)

if __name__ == "__main__":
    main()
