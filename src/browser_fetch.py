from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, sync_playwright

from .discovery import Candidate, HUB_URL, extract_india_pdf_links


class BrowserFetchError(RuntimeError):
    pass


@dataclass
class BrowserSyncResult:
    hub_status: int | None
    candidates: list[Candidate]
    downloaded_url: str | None = None
    pdf_bytes: bytes | None = None
    filename: str | None = None
    browser_name: str = "Chrome/Chromium"


def _safe_filename(url: str, fallback: str = "meta-india-report.pdf") -> str:
    name = Path(urlparse(url).path).name or fallback
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _launch_context(playwright, profile_dir: Path, headed: bool) -> BrowserContext:
    """Launch a real browser context. Prefer installed Google Chrome on Windows.

    A dedicated profile is used so Meta cookies can persist across runs without
    touching the user's normal Chrome profile.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    common = dict(
        user_data_dir=str(profile_dir),
        headless=not headed,
        viewport={"width": 1400, "height": 900},
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=TranslateUI",
        ],
    )
    try:
        return playwright.chromium.launch_persistent_context(channel="chrome", **common)
    except Exception:
        try:
            return playwright.chromium.launch_persistent_context(**common)
        except Exception as exc:
            raise BrowserFetchError(
                "Could not launch Chrome/Chromium. Run setup.bat again so Playwright Chromium is installed."
            ) from exc


def _reduce_noise(page: Page) -> None:
    # Do NOT block scripts/XHR because Meta uses them to render report links.
    # We only block large cosmetic assets to reduce unnecessary traffic.
    def handler(route):
        rtype = route.request.resource_type
        if rtype in {"image", "media", "font"}:
            route.abort()
        else:
            route.continue_()

    page.route("**/*", handler)


def _try_select_india(page: Page) -> None:
    """Best-effort selection of India on Meta's report page."""

    # 1. Try normal HTML <select> first.
    for i in range(page.locator("select").count()):
        sel = page.locator("select").nth(i)
        try:
            labels = sel.locator("option").all_text_contents()
            if any(x.strip().lower() == "india" for x in labels):
                sel.select_option(label="India")
                page.wait_for_timeout(3000)
                print("Selected India using native select.")
                return
        except Exception:
            pass

   # 2. Inspect visible ARIA comboboxes/custom dropdowns.
try:
    combos = page.locator('[role="combobox"]:visible')

    print(f"Visible comboboxes found: {combos.count()}")

    for i in range(combos.count()):
        combo = combos.nth(i)

        try:
            print(
                f"COMBO {i}: "
                f"text={combo.inner_text()!r}, "
                f"aria-label={combo.get_attribute('aria-label')!r}, "
                f"placeholder={combo.get_attribute('placeholder')!r}, "
                f"name={combo.get_attribute('name')!r}"
            )
        except Exception as exc:
            print(f"COMBO {i}: could not inspect: {exc}")

except Exception as exc:
    print(f"Could not inspect comboboxes: {exc}")

    # 3. Try text-based dropdown triggers such as Country / Select country.
    trigger_texts = [
        "Country",
        "Select country",
        "Select a country",
        "All countries",
        "Location",
    ]

    for trigger_text in trigger_texts:
        try:
            trigger = page.get_by_text(trigger_text, exact=True)

            if trigger.count() > 0:
                trigger.first.click()
                page.wait_for_timeout(1000)

                india_option = page.get_by_text("India", exact=True)

                if india_option.count() > 0:
                    india_option.first.click()
                    page.wait_for_timeout(3000)
                    print(f"Selected India using trigger: {trigger_text}")
                    return
        except Exception:
            pass

    # 4. Last attempt: inspect visible India elements.
    try:
        india = page.get_by_text("India", exact=True)

        print(f"Visible India elements found: {india.count()}")

        if india.count() > 0:
            india.first.click()
            page.wait_for_timeout(3000)
            print("Clicked visible India element.")
            return
    except Exception:
        pass

    print("Could not automatically select India.")


def _download_in_context(context: BrowserContext, page: Page, url: str) -> tuple[bytes, str]:
    """One explicit PDF fetch call using the browser's cookie jar and UA.

    Meta/CDN redirects are allowed because signed file URLs often redirect.
    This is one application-level fetch call, not URL probing or retrying.
    """
    ua = page.evaluate("() => navigator.userAgent")
    headers = {
        "User-Agent": ua,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Referer": HUB_URL,
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = context.request.get(url, headers=headers, timeout=90_000, fail_on_status_code=False)
    except PlaywrightError as exc:
        raise BrowserFetchError(f"Browser PDF fetch failed before receiving a response: {exc}") from exc

    if resp.status == 429:
        raise BrowserFetchError("Meta returned HTTP 429 for the PDF. No retry was attempted.")
    if resp.status >= 400:
        raise BrowserFetchError(f"Meta returned HTTP {resp.status} for the PDF. No retry was attempted.")

    data = resp.body()
    ctype = (resp.headers.get("content-type") or "").lower()
    if not data.startswith(b"%PDF") and "application/pdf" not in ctype:
        raise BrowserFetchError(
            f"The selected URL did not return a PDF (HTTP {resp.status}, Content-Type={ctype!r})."
        )

    final_url = resp.url or url
    return data, _safe_filename(final_url)


def browser_sync_one(
    profile_dir: Path,
    hub_cache: Path,
    processed_urls: set[str],
    headed: bool = True,
) -> BrowserSyncResult:
    """Open Meta once in Chrome, discover links from that loaded page, fetch one PDF.

    There is no requests.get() call to the Meta hub, no HEAD request, no URL
    guessing, no retry loop, and PDFs are processed sequentially one at a time.
    """
    with sync_playwright() as p:
        context = _launch_context(p, profile_dir, headed=headed)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            _reduce_noise(page)

            try:
                response = page.goto(HUB_URL, wait_until="domcontentloaded", timeout=90_000)
            except PlaywrightError as exc:
                raise BrowserFetchError(f"Chrome could not open the Meta report hub: {exc}") from exc

            status = response.status if response else None
            if status and status >= 400:
                raise BrowserFetchError(
                    f"Meta returned HTTP {status} even to Chrome automation. "
                    "No retry was attempted. You can still use local-file mode, which makes zero scripted Meta requests."
                )

            # Give the React/Next page time to render. No repeated reloads.
            page.wait_for_timeout(7000)
            _try_select_india(page)
            page.wait_for_timeout(2000)

            html = page.content()
            print(f"Page title: {page.title()}")
            print(f"Current URL: {page.url}")
            print(f"HTML length: {len(html)}")

            lower_html = html.lower()

            print("India occurrences in HTML:", lower_html.count("india"))
            print("PDF occurrences in HTML:", lower_html.count(".pdf"))
            print("Download occurrences in HTML:", lower_html.count("download"))

            for keyword in ["india", ".pdf", "download"]:
                pos = lower_html.find(keyword)
                if pos != -1:
                    start = max(0, pos - 500)
                    end = min(len(html), pos + 1000)
                    print(f"\n===== FIRST {keyword.upper()} MATCH =====")
                    print(html[start:end])
                    print("===== END MATCH =====\n")

            buttons = page.locator("button").evaluate_all(
                "(els) => els.map(e => e.innerText)"
            )

            print(f"Total buttons: {len(buttons)}")

            for text in buttons:
                text = (text or "").strip()
                if text:
                    print("BUTTON:", text[:200])

            hub_cache.parent.mkdir(parents=True, exist_ok=True)
            hub_cache.write_text(html, encoding="utf-8", errors="ignore")

            candidates = extract_india_pdf_links(html)
            pending = [c for c in candidates if c.url not in processed_urls]
            pending.sort(key=lambda c: (c.date_key, c.url), reverse=True)
            if not pending:
                return BrowserSyncResult(hub_status=status, candidates=candidates)

            chosen = pending[0]
            data, filename = _download_in_context(context, page, chosen.url)
            return BrowserSyncResult(
                hub_status=status,
                candidates=candidates,
                downloaded_url=chosen.url,
                pdf_bytes=data,
                filename=filename,
            )
        finally:
            context.close()


def browser_download_direct(url: str, profile_dir: Path, headed: bool = True) -> tuple[bytes, str]:
    """Fetch one known direct PDF URL using Chrome cookies/headers, with no hub call."""
    if not re.match(r"^https?://", url, re.I):
        raise BrowserFetchError("The PDF URL must start with http:// or https://")
    if url.strip().upper() in {"DIRECT_PDF_URL", "PASTE_URL_HERE"}:
        raise BrowserFetchError("Replace the placeholder with the real official PDF URL.")

    with sync_playwright() as p:
        context = _launch_context(p, profile_dir, headed=headed)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            # Opening about:blank does not contact Meta. It just gives us Chrome's UA.
            page.goto("about:blank")
            return _download_in_context(context, page, url)
        finally:
            context.close()
