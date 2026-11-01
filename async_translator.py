import threading

from PyQt6.QtCore import QObject, pyqtSignal

from translator import GameTranslator


class AsyncTranslator(QObject):
    """Çeviriyi ayrı iş parçacığında yapar: ağ takılsa bile OCR döngüsü ve arayüz bloklanmaz.

    - Her zaman yalnızca EN SON istenen metin çevrilir (eskiler çöpe gider).
    - Ağ hatasında üstel geri çekilmeyle (0.5 sn -> 15 sn) kendiliğinden yeniden dener.
    - Sonuç geldiğinde metin artık güncel değilse (ekran değişmişse) yok sayılır.
    """

    result = pyqtSignal(str, str)   # kaynak metin, Türkçe çeviri
    failed = pyqtSignal(str)        # kullanıcıya gösterilecek kısa hata
    recovered = pyqtSignal()

    def __init__(self, source_lang="auto", target_lang="tr"):
        super().__init__()
        self.translator = GameTranslator(source_lang, target_lang)
        self._latest = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._stop = False
        self._in_error = False
        self.requests_done = 0
        self._thread = threading.Thread(target=self._loop, name="translate", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ dış API
    def submit(self, text):
        with self._lock:
            self._latest = text
        self._event.set()

    def cancel(self):
        with self._lock:
            self._latest = None
        self._event.set()

    def set_languages(self, source, target):
        self.translator.set_languages(source, target)

    def stop(self):
        self._stop = True
        self._event.set()

    # ------------------------------------------------------------ iç döngü
    def _current(self):
        with self._lock:
            return self._latest

    def _loop(self):
        while not self._stop:
            self._event.wait()
            self._event.clear()
            attempt = 0
            while not self._stop:
                text = self._current()
                if text is None or len(text.strip()) < 2:
                    break
                translated = self.translator.translate(text)
                self.requests_done += 1
                if translated:
                    if self._in_error:
                        self._in_error = False
                        self.recovered.emit()
                    if self._current() == text:  # hâlâ güncel mi?
                        self.result.emit(text, translated)
                    break
                attempt += 1
                if not self._in_error or attempt == 1:
                    self._in_error = True
                    self.failed.emit("Çeviri servisine ulaşılamıyor — yeniden deneniyor")
                delay = min(15.0, 0.5 * (2 ** min(attempt, 5)))
                # Yeni metin gelirse (veya iptal) beklemeyi bırak
                if self._event.wait(delay):
                    self._event.clear()
