# YAYS

**Yet Another YouTube Summarizer** v0.1

AI-powered YouTube summaries delivered to your RSS reader. Self-hosted, privacy-first.

---

## What It Does

Monitor YouTube channels → Extract transcripts → Generate AI summaries → Email to your inbox or RSS reader

**Features:**
- 🤖 AI summaries using OpenAI (all current models supported)
- 📧 Email delivery to inbox or RSS reader (Inoreader, The Old Reader, etc.)
- 📱 Web UI - Mobile-first interface
- 🔄 Auto-processing (configurable 1-24 hours)
- 💾 Import/Export - Backup your data
- 🚀 One-command install and update

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/icon3333/YAYS/main/install.sh | bash
cd ~/YAYS
docker compose up -d
```

**Then open:** http://localhost:8015 and configure in the Settings tab.

---

## Update

```bash
cd ~/YAYS
./update.sh
```

The script handles everything: pulls code, rebuilds containers, restarts services.

---

## Prerequisites

- Docker & Docker Compose ([get.docker.com](https://get.docker.com))
- OpenAI API key ([platform.openai.com/api-keys](https://platform.openai.com/api-keys))
- Target email (your inbox or RSS reader email)
- Gmail SMTP app password ([myaccount.google.com/security](https://myaccount.google.com/security))

---

## Usage

### 1. Add Your First Channel

1. Open http://localhost:8015
2. Go to **Settings** tab
3. Configure API credentials (OpenAI, SMTP)
4. Paste YouTube channel URL in the input field
5. Click **Add Channel**

**Test channel:** `UCddiUEpeqJcYeBxX1IVBKvQ` (The Verge)

### 2. Configure Transcript Extraction

YAYS uses a **4-method cascade** for maximum reliability:

1. **YouTube Transcript API** (free, fast)
2. **yt-dlp Subtitles** (free, more reliable)
3. **Direct Timedtext API** (free, scraping fallback)
4. **Supadata.ai Fallback** (paid, optional)

**Default:** First 3 methods are active automatically.

**To enable Supadata fallback:**
1. Get API key from [supadata.ai](https://supadata.ai) (100 free credits, then $29/mo)
2. Go to Settings → Transcript Settings
3. Check "Activate Supadata Fallback"
4. Enter your API key
5. Save settings

### 3. Configure Processing Schedule

1. Go to **Settings** tab
2. Find **Check Interval** (default: 4 hours)
3. Adjust from 1-24 hours based on your needs
4. Changes take effect on next processing run

### 4. Add Single Videos Manually

Don't want to monitor a whole channel? Add individual videos:

1. Go to **Feed** tab
2. Click **Quick Add Video**
3. Paste YouTube video URL
4. Video processes immediately

### 5. Trigger Manual Processing

Don't wait for the scheduled interval:

```bash
docker exec youtube-summarizer python process_videos.py
```

Watch logs:
```bash
docker compose logs -f
```

---

## License

MIT License - See [LICENSE](LICENSE) file.

---

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [OpenAI Python SDK](https://github.com/openai/openai-python) - GPT API client
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - YouTube channel discovery & metadata
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) - Primary transcript extraction
- [Supadata.ai](https://supadata.ai) - Optional managed transcript fallback
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) - Timedtext API parsing
- [Docker](https://www.docker.com/) - Containerization

---

---

## Recent Updates

- Email encoding improvements for international characters (UTF-8 support)
- Check interval now dynamically reads from database settings
- Removed encryption dependencies for simplified deployment
- Enhanced Gmail app password validation

---

**Built for self-hosters who value privacy, control, and efficiency.**

For issues or contributions, open a GitHub issue at [github.com/icon3333/YAYS](https://github.com/icon3333/YAYS).
