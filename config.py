import json
import os
import re
import tempfile

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
CONFIG_VERSION = 2

# OCR motoru (RapidOCR) Latin harfleri ve Çince'yi güvenilir okur.
ALLOWED_SOURCES = ("auto", "en", "zh-CN")
ALLOWED_MODES = ("mask", "bottom")
ALLOWED_ALIGNS = ("center", "left")
ALLOWED_BORDERS = ("game_box", "subtle", "none")
SCAN_INTERVALS = (0.5, 0.8, 1.2)

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "source_lang": "auto",
    "target_lang": "tr",
    "scan_interval": 0.8,       # boşta tarama aralığı (metin değişirken otomatik hızlanır)
    "auto_hide_delay": 0.0,     # 0 = kapalı: orijinal metin ekrandan gidince altyazı gizlenir
    "font_size": 18,
    "bg_opacity": 0.90,
    "overlay_mode": "mask",     # mask = orijinal metnin üstünü kapatır; bottom = ROI dışında şerit
    "text_color": "#FFDE59",
    "font_family": "Bahnschrift",
    "text_align": "center",
    "border_style": "game_box",
    "roi": None,
}

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(value, lo, hi, default, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _sanitize_roi(roi):
    if not isinstance(roi, dict):
        return None
    try:
        out = {k: int(roi[k]) for k in ("left", "top", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if out["width"] < 20 or out["height"] < 15 or out["width"] > 20000 or out["height"] > 20000:
        return None
    if not (-20000 <= out["left"] <= 40000 and -20000 <= out["top"] <= 40000):
        return None
    return out


def sanitize(cfg):
    """Bozuk / eski / elle düzenlenmiş ayarları güvenli değerlere çevirir."""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULT_CONFIG)

    out["source_lang"] = cfg.get("source_lang") if cfg.get("source_lang") in ALLOWED_SOURCES else "auto"
    out["target_lang"] = "tr"
    out["scan_interval"] = _num(cfg.get("scan_interval"), 0.3, 5.0, 0.8)
    out["font_size"] = _num(cfg.get("font_size"), 10, 60, 18, int)
    out["bg_opacity"] = _num(cfg.get("bg_opacity"), 0.2, 1.0, 0.90)
    out["auto_hide_delay"] = _num(cfg.get("auto_hide_delay"), 0.0, 120.0, 0.0)
    if int(cfg.get("config_version", 1) or 1) < CONFIG_VERSION:
        # v1'de varsayılan 5 sn idi; artık "metin gidince gizle" varsayılan
        out["auto_hide_delay"] = 0.0

    out["overlay_mode"] = cfg.get("overlay_mode") if cfg.get("overlay_mode") in ALLOWED_MODES else "mask"
    out["text_align"] = cfg.get("text_align") if cfg.get("text_align") in ALLOWED_ALIGNS else "center"
    out["border_style"] = cfg.get("border_style") if cfg.get("border_style") in ALLOWED_BORDERS else "game_box"
    color = cfg.get("text_color")
    out["text_color"] = color if isinstance(color, str) and _COLOR.match(color) else DEFAULT_CONFIG["text_color"]
    font = cfg.get("font_family")
    out["font_family"] = font if isinstance(font, str) and 0 < len(font) < 64 else DEFAULT_CONFIG["font_family"]
    out["roi"] = _sanitize_roi(cfg.get("roi"))
    out["config_version"] = CONFIG_VERSION
    return out


def load_config():
    """Ayarları okur. Dosya bozuksa .bad olarak saklayıp varsayılanlarla devam eder."""
    path = CONFIG_PATH
    if not os.path.exists(path):
        return sanitize({})
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return sanitize(data)
    except (OSError, ValueError):
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass
        return sanitize({})


def save_config(config):
    """Atomik kayıt: yarım kalmış (bozuk) dosya riskini ortadan kaldırır."""
    path = CONFIG_PATH
    tmp = None
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sanitize(config), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except OSError:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False
