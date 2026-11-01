import difflib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

_DIGITS = re.compile(r"\d+")
MAX_CHARS = 900
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def normalize(text):
    return " ".join(str(text).split())


def texts_similar(a, b, threshold=0.93):
    """İki OCR okumasının aynı metin (yalnızca OCR gürültüsü farkı) olup olmadığı.
    Rakamlar farklıysa ('5 goblin' / '6 goblin') metin farklı sayılır."""
    a, b = normalize(a).lower(), normalize(b).lower()
    if a == b:
        return True
    if not a or not b:
        return False
    if _DIGITS.findall(a) != _DIGITS.findall(b):
        return False
    sm = difflib.SequenceMatcher(None, a, b)
    return sm.quick_ratio() >= threshold and sm.ratio() >= threshold


class TranslationError(Exception):
    pass


class Provider:
    """Tek bir çeviri uç noktası + kendi bekleme (cooldown) durumu."""

    def __init__(self, name, fn):
        self.name = name
        self.fn = fn
        self.blocked_until = 0.0
        self.failures = 0

    def available(self, now):
        return now >= self.blocked_until

    def mark_failure(self, now, rate_limited):
        self.failures += 1
        base = 20 if rate_limited else 4
        self.blocked_until = now + min(180, base * (2 ** min(self.failures - 1, 4)))

    def mark_success(self):
        self.failures = 0
        self.blocked_until = 0.0


class GameTranslator:
    """Çok sağlayıcılı (otomatik yedekli) çeviri + LRU önbellek.

    Bir sağlayıcı hız sınırına (HTTP 429) takılırsa ya da hata verirse kendi
    bekleme süresine alınır ve diğerine geçilir.
    """

    CACHE_SIZE = 300
    TIMEOUT = 5

    def __init__(self, source_lang="auto", target_lang="tr"):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.cache = OrderedDict()
        self.last_original_text = ""
        self.last_translated_text = ""
        self.last_error = None
        self._lock = threading.Lock()
        self.providers = [
            Provider("dict-chrome-ex", self._request_dict),
            Provider("gtx", self._request_gtx),
        ]
        self.active_provider = None

    # ------------------------------------------------------------ yardımcılar
    def set_languages(self, source_lang, target_lang):
        with self._lock:
            if self.source_lang != source_lang or self.target_lang != target_lang:
                self.source_lang = source_lang
                self.target_lang = target_lang
                self.cache.clear()
                self.last_original_text = ""
                self.last_translated_text = ""

    def _key(self, text):
        return f"{self.source_lang}->{self.target_lang}:{text}"

    def _remember(self, original, translated):
        key = self._key(original)
        self.cache[key] = translated
        self.cache.move_to_end(key)
        while len(self.cache) > self.CACHE_SIZE:
            self.cache.popitem(last=False)
        self.last_original_text = original
        self.last_translated_text = translated

    def _post(self, url, text):
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"q": text}).encode("utf-8"),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------ sağlayıcılar
    def _request_dict(self, text):
        url = (
            "https://clients5.google.com/translate_a/t?client=dict-chrome-ex"
            f"&sl={self.source_lang}&tl={self.target_lang}"
        )
        data = self._post(url, text)
        parts = []
        for item in data:
            parts.append(item[0] if isinstance(item, list) else str(item))
        return "".join(parts)

    def _request_gtx(self, text):
        url = (
            "https://translate.googleapis.com/translate_a/single?client=gtx"
            f"&sl={self.source_lang}&tl={self.target_lang}&dt=t"
        )
        data = self._post(url, text)
        return "".join(part[0] for part in data[0] if part and part[0])

    # ------------------------------------------------------------ ana işlev
    def _request(self, text):
        """Kullanılabilir sağlayıcıları sırayla dener. Hepsi başarısızsa TranslationError."""
        now = time.monotonic()
        candidates = [p for p in self.providers if p.available(now)]
        if not candidates:
            wait = min(p.blocked_until for p in self.providers) - now
            raise TranslationError(f"tüm çeviri servisleri beklemede (~{max(1, int(wait))} sn)")
        last = None
        for p in candidates:
            try:
                result = p.fn(text)
                if not isinstance(result, str):
                    raise TranslationError("beklenmeyen yanıt biçimi")
                p.mark_success()
                self.active_provider = p.name
                return result
            except urllib.error.HTTPError as e:
                p.mark_failure(time.monotonic(), rate_limited=(e.code == 429))
                last = f"{p.name}: HTTP {e.code}"
            except Exception as e:
                p.mark_failure(time.monotonic(), rate_limited=False)
                last = f"{p.name}: {type(e).__name__}"
        raise TranslationError(last or "bilinmeyen hata")

    def is_similar_to_last(self, text):
        return bool(self.last_original_text) and texts_similar(text, self.last_original_text)

    def translate(self, text):
        """Çeviriyi döndürür. Başarısızlıkta '' döner ve last_error doldurulur."""
        clean = normalize(text)[:MAX_CHARS]
        if len(clean) < 2:
            return ""

        with self._lock:
            if self.is_similar_to_last(clean):
                return self.last_translated_text
            key = self._key(clean)
            if key in self.cache:
                self.cache.move_to_end(key)
                self.last_original_text = clean
                self.last_translated_text = self.cache[key]
                return self.last_translated_text

        try:
            translated = self._request(clean)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return ""

        self.last_error = None
        translated = translated.strip()
        if translated:
            with self._lock:
                self._remember(clean, translated)
        return translated
