# ClipTube - Fast YouTube & Local Video Clipper ✂️

ClipTube is a high-performance web-based video clipping and auto batch splitting application built with **Flask**, **FFmpeg**, and **yt-dlp**.

## ✨ Features
- 🚀 **Sub-Second Local Cutting:** Uses stream copying (`-c copy`) for instant exports without re-encoding.
- ⚡ **Direct Range Extraction:** Downloads only selected timestamps (10s-30s) from YouTube in 2-3 seconds, bypassing full video downloads.
- 📱 **Social Media Formats:** Supports Standard (16:9), Vertical Reels/Shorts (9:16), and Square (1:1).
- 📦 **Auto Batch Splitter:** Automatically splits long videos into sequential parts (30s, 1m, 2m, 3m, 5m) with 1-click ZIP download.
- 🏎️ **Hardware Acceleration:** Supports Intel QuickSync (`h264_qsv`) for ultra-fast GPU rendering.
- 🧹 **Auto Cleanup:** Automatically purges temporary cache and exports to keep disk space free.

---

## 🛠️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/faysal845989/cliptube.git
   cd cliptube
   ```

2. **Install FFmpeg:**
   Make sure `ffmpeg` is installed and added to your system PATH.

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

5. **Run the Application:**
   ```bash
   python app.py
   ```
   Open your browser and visit: `http://localhost:5000`

---

## 📁 Project Structure
```text
cliptube/
├── app.py                 # Flask server & REST API
├── clipper.py             # Core FFmpeg & yt-dlp processing engine
├── bot.py                 # Optional Telegram Bot integration
├── requirements.txt       # Python dependencies
├── .env.example           # Example environment template
├── .gitignore             # Ignored temporary and secret files
├── templates/
│   └── index.html         # Modern Glassmorphic Web UI
└── static/
    ├── css/style.css      # Custom styling & animations
    ├── js/main.js         # Frontend interactivity & playback
    ├── cache/             # Temporary processing cache
    ├── exports/           # Generated video clips
    └── uploads/           # User uploaded local files
```
