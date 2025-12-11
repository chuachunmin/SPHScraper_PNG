"""
Playwright script for NLB SPH Newspapers

Strategy:
- Incognito, fullscreen on macOS
- Log in
- Click through to the selected paper (PAPER_XPATH)
- At each step in the viewer:
    * Collect ALL page-like canvases/images under #app
    * For each new src (not seen before), save it
- Try to go to next page:
    * Click next-page button or press Right arrow (2 attempts)
    * After each attempt, if we see any new src, consider that a successful move
- Stop when going next no longer reveals any new page images
- Combine all saved images into a single PDF using Pillow, named:
    YYYYMMDD.pdf  (YYYYMMDD = computer date)
- Automatically exit after job is complete

Setup:
    python3 -m venv venv
    source venv/bin/activate
    pip install playwright pillow
    playwright install

Run:
    python main.py
"""

import base64
import time
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image

# -----------------------------
# EDIT ME: LOGIN + PAPER CONFIG
# -----------------------------

# NLB credentials
NLB_USERNAME = "username"
NLB_PASSWORD = r"password"  # use r"..." if you have backslashes or \+ in password

# Which paper to open (thumbnail image xpath on the main SPH page)
ST_XPATH = "/html/body/div[1]/div/div[1]/div[3]/div[1]/div/div/a/img"
BT_XPATH = "/html/body/div[1]/div/div[1]/div[3]/div[2]/div/div/a/img"

PAPER_XPATH = ST_XPATH

# -----------------------------
# CONSTANTS / SELECTORS
# -----------------------------

SPH_URL = "https://eresources.nlb.gov.sg/main/sphnewspapers"

# Login link XPath (header)
LOGIN_LINK_XPATH = "/html/body/header/div/nlb-header/div/nav/div[2]/div/div[3]/ui-others/div/a"

# Use PAPER_XPATH as the FIRST target
FIRST_TARGET_XPATH = PAPER_XPATH

# Viewer buttons you gave earlier
SECOND_TARGET_XPATH = "//*[@id='app']/div/div/div[3]/div/div/div[1]/button"
THIRD_TARGET_XPATH  = "//*[@id='app']/div/div/div[2]/div/div/div[2]/div/div[2]/button"

# Next-page button XPath (if present)
NEXT_PAGE_BUTTON_XPATH = "//*[@id='next-page-button']"

# JS: collect ALL canvases/imgs under #app with basic size info
PAGE_IMAGES_JS = r"""
(() => {
    const root = document.querySelector('#app');
    if (!root) return [];

    const els = Array.from(root.querySelectorAll('canvas, img'));
    const result = [];

    for (const el of els) {
        const tag = el.tagName.toLowerCase();
        const rect = el.getBoundingClientRect();
        let width = el.width || el.naturalWidth || rect.width || 0;
        let height = el.height || el.naturalHeight || rect.height || 0;

        // Skip tiny UI icons
        if (width < 100 || height < 100) continue;

        if (tag === 'canvas') {
            try {
                const dataUrl = el.toDataURL('image/png');
                if (dataUrl && dataUrl.startsWith('data:image')) {
                    result.push({
                        src: dataUrl,
                        width,
                        height,
                        kind: 'canvas'
                    });
                }
            } catch (e) {
                // ignore and continue
            }
        } else if (tag === 'img') {
            const src = el.src || null;
            if (src) {
                result.push({
                    src,
                    width,
                    height,
                    kind: 'img'
                });
            }
        }
    }

    return result;
})()
"""

# Login input selectors
USERNAME_SELECTOR = "#username"
PASSWORD_SELECTOR = "#password"

# Output
OUTPUT_DIR = Path("output_pages")

# Minimum width we consider "real page" (avoid thumbnails/icons)
MIN_PAGE_IMAGE_WIDTH = 800  # adjust if needed


def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def safe_get_all_page_images_info(page, timeout_ms=20000, min_width=MIN_PAGE_IMAGE_WIDTH):
    """
    Evaluate PAGE_IMAGES_JS safely, retrying if navigation destroys the context.
    Returns a list of dicts {src, width, height, kind}, filtered by min_width.
    """
    start = time.time()
    last_infos = []

    while True:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        try:
            infos = page.evaluate(PAGE_IMAGES_JS)
        except Exception as e:
            msg = str(e)
            print(f"[!]   evaluate() failed: {msg}")
            if "Execution context was destroyed" in msg or "Most likely because of a navigation" in msg:
                if (time.time() - start) * 1000 > timeout_ms:
                    print("[!]   Gave up waiting for stable context / images.")
                    return last_infos
                print("[i]   Page still navigating; waiting and retrying...")
                time.sleep(1)
                continue
            else:
                return last_infos

        if infos:
            # Filter by min_width
            filtered = [i for i in infos if (i.get("width") or 0) >= min_width]
            if filtered:
                last_infos = filtered
                print(f"[i]   Found {len(filtered)} page-like images (width ≥ {min_width}).")
                return filtered
            else:
                print("[i]   Only small images found, waiting for hi-res pages...")
        else:
            print("[i]   No page images yet, waiting...")

        if (time.time() - start) * 1000 > timeout_ms:
            print("[!]   Timeout waiting for hi-res pages; using whatever we have.")
            return last_infos

        time.sleep(1)


def save_data_url_image(data_url: str, dest: Path) -> bool:
    """Save a data:image/...;base64,... URL to disk."""
    try:
        header, b64 = data_url.split(",", 1)
    except ValueError:
        print("[!]   Invalid data URL format.")
        return False

    if not header.startswith("data:image"):
        print(f"[!]   Not an image data URL: {header}")
        return False

    try:
        binary = base64.b64decode(b64)
    except Exception as e:
        print(f"[!]   Failed to decode base64 image: {e}")
        return False

    dest.write_bytes(binary)
    print(f"[i]   Saved data-URL image to {dest}")
    return True


def download_image_via_context(context, img_url: str, dest: Path) -> bool:
    """
    Download the image:
    - If data:image/...;base64,... -> decode locally.
    - Else use Playwright's authenticated request context.
    """
    if img_url.startswith("data:image"):
        return save_data_url_image(img_url, dest)

    print(f"[i]   Downloading image via HTTP: {img_url}")
    resp = context.request.get(img_url)
    if not resp.ok:
        print(f"[!]   Failed to download image (status {resp.status})")
        return False
    dest.write_bytes(resp.body())
    print(f"[i]   Saved HTTP image to {dest}")
    return True


def go_to_next_page(page, seen_srcs: set, max_attempts: int = 2, wait_ms: int = 4000) -> bool:
    """
    Try to move to the next page:
    - Click next-page button or press Right arrow.
    - After each attempt, check if there is ANY new page image src not in seen_srcs.
    Returns True if new page images appear, False if nothing new was found.
    """
    for attempt in range(1, max_attempts + 1):
        print(f"[i]   Attempting to go to next page (attempt {attempt}/{max_attempts})")

        try:
            btn = page.locator(f"xpath={NEXT_PAGE_BUTTON_XPATH}")
            if btn.count() > 0 and btn.first.is_enabled():
                print("[i]   Clicking next-page button...")
                btn.first.click()
            else:
                print("[i]   Next-page button not usable; pressing Right arrow...")
                page.keyboard.press("ArrowRight")
        except Exception as e:
            print(f"[!]   Error clicking next-page button: {e}, trying Right arrow...")
            try:
                page.keyboard.press("ArrowRight")
            except Exception as e2:
                print(f"[!]   Error pressing Right arrow: {e2}")

        page.wait_for_timeout(wait_ms)

        # Check for any new image src not seen before
        try:
            infos = page.evaluate(PAGE_IMAGES_JS)
            if infos:
                for info in infos:
                    src = info.get("src")
                    width = info.get("width") or 0
                    if not src:
                        continue
                    if width < MIN_PAGE_IMAGE_WIDTH:
                        continue
                    if src not in seen_srcs:
                        print("[i]   New page image src detected after navigation.")
                        return True
            print("[i]   No new page images detected yet after this attempt.")
        except Exception as e:
            print(f"[!]   Error checking page images after navigation: {e}")

    print("[i]   No new page images after navigation attempts; assuming end.")
    return False


def capture_all_pages(page, context):
    """
    Main loop:
    - At each state, save ALL new page images currently loaded (no duplicates).
    - Try to move to a new page; stop when no new pages appear.
    """
    ensure_dirs()
    seen_srcs = set()
    image_paths = []
    global_page_index = 1

    while True:
        print(f"\n[i] Capturing step, current total pages saved: {len(seen_srcs)}")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        infos = safe_get_all_page_images_info(page)
        if not infos:
            print("[!]   No page-like images at this step; stopping.")
            break

        # Save all new images at this step
        new_this_step = 0
        for info in infos:
            src = info.get("src")
            kind = info.get("kind") or "unknown"
            width = info.get("width") or 0
            height = info.get("height") or 0

            if not src:
                continue
            if src in seen_srcs:
                continue

            seen_srcs.add(src)
            new_this_step += 1

            # Decide extension
            if src.startswith("data:image/png"):
                ext = ".png"
            elif src.startswith("data:image/jpeg") or src.startswith("data:image/jpg"):
                ext = ".jpg"
            else:
                ext = ".jpg" if kind == "img" else ".png"

            fname = f"page_{global_page_index:03d}{ext}"
            dest_path = OUTPUT_DIR / fname

            print(f"[i]   New page image #{global_page_index}: "
                  f"{kind}, {width}x{height}, saving as {fname}")

            if download_image_via_context(context, src, dest_path):
                image_paths.append(dest_path)
                global_page_index += 1
            else:
                print("[!]   Failed to save this page image; continuing.")

        print(f"[i]   New pages saved this step: {new_this_step}")

        # Try to move to next page; if no new pages appear after nav attempts, we are done.
        if not go_to_next_page(page, seen_srcs):
            print("[i]   No further pages available; finishing capture.")
            break

    print(f"\n[i] Finished capturing. Total unique page images saved: {len(seen_srcs)}")
    return image_paths


def images_to_pdf(image_paths, pdf_path: Path):
    """Combine images into a single PDF."""
    if not image_paths:
        print("[!] No images to convert to PDF.")
        return

    print(f"[i] Creating PDF from {len(image_paths)} images...")
    images = []
    for p in image_paths:
        img = Image.open(p).convert("RGB")
        images.append(img)

    first, rest = images[0], images[1:]
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    first.save(pdf_path, save_all=True, append_images=rest)
    print(f"[i] Saved PDF to: {pdf_path}")


def main():
    with sync_playwright() as p:
        # Launch browser maximised
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )

        # Fresh incognito context, full native window
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080}
        )

        page = context.new_page()

        # -------------------------------
        # Step 1: Open main page
        # -------------------------------
        print("[i] Opening SPH page...")
        page.goto(SPH_URL, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # -------------------------------
        # Step 2: Click login link
        # -------------------------------
        try:
            print("[i] Waiting for login link...")
            page.wait_for_selector(f"xpath={LOGIN_LINK_XPATH}", timeout=15000)
            print("[i] Clicking login link...")
            page.click(f"xpath={LOGIN_LINK_XPATH}")
            page.wait_for_timeout(2000)
        except PlaywrightTimeoutError:
            print("[!] Login link not found — continuing, maybe already on login page.")

        # -------------------------------
        # Step 3: Fill username + password
        # -------------------------------
        print("[i] Filling username...")
        page.wait_for_selector(USERNAME_SELECTOR, timeout=20000)
        page.fill(USERNAME_SELECTOR, NLB_USERNAME)

        print("[i] Filling password...")
        page.wait_for_selector(PASSWORD_SELECTOR, timeout=20000)
        page.fill(PASSWORD_SELECTOR, NLB_PASSWORD)

        print("[i] Submitting login via ENTER...")
        page.locator(PASSWORD_SELECTOR).press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        print("[i] Login complete (assuming credentials are correct).")

        # -------------------------------
        # Step 4: Click PAPER thumbnail (opens viewer in new tab)
        # -------------------------------
        print("[i] Waiting for PAPER thumbnail (FIRST_TARGET_XPATH)...")
        page.wait_for_selector(f"xpath={FIRST_TARGET_XPATH}", timeout=20000)

        print("[i] Clicking PAPER thumbnail, expecting viewer tab...")
        with context.expect_page() as new_page_event:
            page.click(f"xpath={FIRST_TARGET_XPATH}")

        new_page = new_page_event.value
        page = new_page
        page.bring_to_front()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Determine PDF name from computer date
        issue_date = datetime.today().strftime("%Y%m%d")
        pdf_path = Path("output") / f"{issue_date}.pdf"
        print(f"[i] PDF will be saved as: {issue_date}.pdf")

        # -------------------------------
        # Step 5: Click SECOND element
        # -------------------------------
        print("[i] Waiting for SECOND element (button)...")
        try:
            page.wait_for_selector(f"xpath={SECOND_TARGET_XPATH}", timeout=20000)
            print("[i] Clicking SECOND element...")
            page.click(f"xpath={SECOND_TARGET_XPATH}")
            page.wait_for_timeout(2000)
        except PlaywrightTimeoutError:
            print("[!] SECOND element not found — continuing anyway.")

        # -------------------------------
        # Step 6: Click THIRD element
        # -------------------------------
        print("[i] Waiting for THIRD element (button)...")
        try:
            page.wait_for_selector(f"xpath={THIRD_TARGET_XPATH}", timeout=20000)
            print("[i] Clicking THIRD element...")
            page.click(f"xpath={THIRD_TARGET_XPATH}")
            page.wait_for_timeout(2000)
        except PlaywrightTimeoutError:
            print("[!] THIRD element not found — continuing anyway.")

        # Optional: small extra wait so initial pages can fully load hi-res
        print("[i] Giving viewer a bit more time to load initial pages...")
        page.wait_for_timeout(4000)

        # -------------------------------
        # Step 7: Capture all pages (auto, multi-page per step)
        # -------------------------------
        print("[i] Starting page capture (auto until no new pages)...")
        image_paths = capture_all_pages(page, context)

        # -------------------------------
        # Step 8: Build PDF from images
        # -------------------------------
        images_to_pdf(image_paths, pdf_path)

        print("\n[i] Script finished. Closing browser and exiting.\n")
        browser.close()


if __name__ == "__main__":
    main()
