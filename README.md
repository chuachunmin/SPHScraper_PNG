# 📰 SPHScraper_PNG — Automated SPH Newspaper Downloader (NLB eResources)

SPHScraper_PNG is a fully automated **Playwright-based scraper** that logs into Singapore’s National Library Board (NLB) eResources portal, opens the SPH Newspaper viewer, downloads **every high-resolution page**, and compiles them into a single PDF.

✔ Supports **The Straits Times, Business Times, Zaobao, Berita Harian**, etc.
✔ Automatically downloads **all pages** (no need to specify page count)
✔ Uses **hi-res canvas rendering** instead of thumbnails
✔ Detects & skips duplicates
✔ Auto-saves PDF as `YYYYMMDD.pdf`
✔ Runs in **macOS**, supports virtual environments
✔ Fully headful browser automation (no reverse engineering or API needed)

---

## 🚀 Features

* Logs in to NLB using your credentials
* Opens any newspaper issue you specify via XPath
* Captures **every available page**, even when multiple pages preload
* Robust handling of:

  * Navigation delays
  * Canvas rendering
  * Low-resolution placeholders
  * Ads / blocked pages
  * Next-page failure recovery
* Automatically assembles all pages into a clean sequential PDF
* Closes browser and exits cleanly (suitable for automation)

---

## 📁 Project Structure

```
SPHScraper_PNG/
│
├── main.py          # The main scraper script
├── venv/            # Your Python virtual environment
├── output_pages/    # All captured page images (auto-created)
└── output/          # Final PDF output (auto-created)
```

---

## 🧰 Requirements

* macOS
* Python 3.10+
* Playwright
* Pillow
* Chrome/Chromium (automatically installed by Playwright)

---

## 🔧 Installation

### 1. Clone the repo

```bash
git clone https://github.com/chuachunmin/SPHScraper_PNG.git
cd SPHScraper_PNG
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install playwright pillow
playwright install
```

---

## ✏️ Configuration

All user-editable settings are located at the **top** of `main.py`:

```python
# NLB credentials
NLB_USERNAME = "username"
NLB_PASSWORD = r"password"

# Which paper to open (thumbnail image xpath on the main SPH page)
ST_XPATH = "/html/body/div[1]/div/div[1]/div[3]/div[1]/div/div/a/img"
BT_XPATH = "/html/body/div[1]/div/div[1]/div[3]/div[2]/div/div/a/img"

PAPER_XPATH = ST_XPATH
```

### Changing the newspaper

On the NLB SPH page, right-click the thumbnail → Inspect → Copy XPath.
Paste it into `PAPER_XPATH`.

---

## ▶️ Running the scraper

```bash
source venv/bin/activate
python main.py
```

The script will:

1. Launch a full browser window
2. Log into NLB
3. Open your selected newspaper
4. Capture **all** pages
5. Save a PDF into:

```
output/YYYYMMDD.pdf
```

---

## 📄 Output Example

```
output/
└── 20250211.pdf
```

Page images are stored in:

```
output_pages/
    page_001.png
    page_002.png
    page_003.jpg
    ...
```

---

## 🛠 How It Works (Technical Overview)

### Page Capture Logic

* Extracts all `canvas` and `img` elements inside `#app`
* Filters out thumbnails (<800px width)
* Saves every unique page image (via data URL or authenticated HTTP)
* Preloaded pages are captured too
* Navigation retries ensure progress even with slow rendering

### PDF Builder

Uses Pillow to assemble all pages, preserving order, resolution, and color.

---

## ⚠️ Notes & Limitations

* Requires an active NLB account with SPH access
* Must be run manually unless scheduled using `launchd` or cron
* Browser must remain visible (headful mode required)
* Heavy newspapers (40–60 pages) may take ~10–15m to download
