# Language Translator for Games 🎮🌐

**Real-Time, Anti-Cheat Safe In-Game Subtitle & Dialogue Overlay Translator**

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Framework](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![OCR Engine](https://img.shields.io/badge/OCR-RapidOCR-orange.svg)](https://github.com/RapidAI/RapidOCR)

**Language Translator for Games** is a lightweight, zero-injection in-game real-time translation tool designed for PC games. Similar to LagoFast's translation overlay, it reads on-screen text externally using high-speed OCR and projects translated subtitles directly onto your game screen with a click-through transparent HUD layer.

---

## 🌟 Key Features

- **🛡️ 100% Anti-Cheat Safe (Zero Injection):** 
  Never touches game memory or modifies game files. Fully safe for online/kernel-protected games (e.g. *Easy Anti-Cheat*, *BattlEye*, *NEPKernel*, *Vanguard*).
- **⚡ Hardware-Accelerated & Ultra Low Latency:**
  Uses `RapidOCR` (ONNX runtime) and `MSS` screen capture. Text comparison algorithms skip OCR on static frames (<5ms overhead, <0.5% CPU usage).
- **👁️ Anti-Feedback Capture Loop Protection:**
  Leverages Windows native `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` so the OCR engine never accidentally captures its own translation overlay.
- **🖱️ Click-Through HUD:**
  The transparent overlay allows all mouse clicks, movements, and aiming to pass through directly into the game without losing focus.
- **🔄 Multi-Provider Fallback Translation:**
  Dual translation providers with automatic failover and rate-limit backoff.
- **✍️ Typewriter / Fast-Text Debouncing:**
  Prevents stutter and request flooding when dialogue letters appear one by one.
- **📏 Auto-Fit Typography:**
  Dynamically scales font size to fit long translated sentences without overflowing the dialogue box.
- **🎮 Hotkeys:**
  - `F9`: Select dialogue/subtitle area on screen using crosshair.
  - `F8`: Pause / Resume translation.
  - `F10`: Instantly clear overlay and reset history.

---

## 🏗️ Architecture

```
┌────────────────────────────────┐
│      Target Game Window        │ (Running in Borderless / Windowed mode)
└────────────────────────────────┘
                │
                ▼ (MSS Screen Capture - Region of Interest)
┌────────────────────────────────┐
│      Change Detector & OCR     │ (Static frame skip -> RapidOCR)
└────────────────────────────────┘
                │
                ▼ (Text changed & debounced)
┌────────────────────────────────┐
│    Async Multi-Provider Engine │ (Google GTX / Dict Fallback + LRU Cache)
└────────────────────────────────┘
                │
                ▼ (Translated text signal)
┌────────────────────────────────┐
│ Transparent Click-Through HUD  │ (Masks original text, rendered over game)
└────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Windows 10 or 11 (64-bit)
- Python 3.11+ (or [uv](https://docs.astral.sh/uv/))

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Dolapderelisemih/language-translator-for-games.git
   cd language-translator-for-games
   ```

2. **Install dependencies:**
   *Using `uv` (recommended):*
   ```bash
   uv sync
   ```
   *Or using `pip`:*
   ```bash
   pip install -r pyproject.toml
   # or
   pip install PyQt6 rapidocr-onnxruntime mss pillow keyboard deep-translator
   ```

3. **Run the application:**
   - Double-click `Baslat.bat`
   - Or run via terminal:
     ```bash
     uv run python main.py
     # or
     python main.py
     ```

4. *(Optional)* **Create Desktop Shortcut:**
   ```bash
   python create_shortcut.py
   ```

---

## 📖 How to Use

1. Start **Language Translator for Games**.
2. Launch your game and set display mode to **Borderless Windowed** or **Windowed**.
3. Press **`F9`** in-game and drag a rectangle over the subtitle/dialogue area.
4. The translated subtitles will now appear seamlessly over the original text!

---

## 🇹🇷 Türkçe Açıklama

**Language Translator for Games**, PC oyunlarındaki diyalog ve altyazıları harici ekran yakalama ve yapay zeka OCR teknolojisi ile anlık olarak algılayıp Türkçeye çeviren, fare tıklamalarını arkadaki oyuna geçiren şeffaf arayüze (HUD) sahip yerel bir çeviri aracıdır.

- **Anti-Cheat Dostu:** Oyun dosyalarını değiştirmez, DLL enjekte etmez. Ban riski sıfırdır.
- **Tam Örtü Modu:** Orijinal yabancı altyazıyı kapatarak oyunun kendi orijinal Türkçe yaması varmış hissi verir.
- **Kısayollar:** `F9` (Altyazı kutusu seç), `F8` (Duraklat/Başlat), `F10` (Ekranı temizle).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
