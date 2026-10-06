from __future__ import annotations

import hashlib
import json
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
    """Inspect Meta's country controls and try to select India."""

    # 1. Native selects
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

    # 2. Inspect visible comboboxes
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

    # 3. Report whether India is visible
    try:
        india = page.get_by_text("India", exact=True)

        print(f"Visible India elements found: {india.count()}")

    except Exception as exc:
        print(f"Could not inspect India elements: {exc}")

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
def _extract_latest_india_monthly_report(html: str) -> dict | None:
    """Extract the newest India Monthly Report entry from Meta's initial HTML."""

    marker = '"static_report_series_title":"India Monthly Report'
    series_pos = html.find(marker)

    if series_pos == -1:
        print("India Monthly Report series was not found in the initial response.")
        return None

    editions_marker = '"report_editions_sorted_by_publish_date":'
    editions_pos = html.find(editions_marker, series_pos)

    if editions_pos == -1:
        print("India report edition list was not found.")
        return None

    array_start = html.find("[", editions_pos)

    if array_start == -1:
        print("Could not find start of India report edition array.")
        return None

    # Find the matching closing ] while respecting JSON strings.
    depth = 0
    in_string = False
    escaped = False
    array_end = None

    for i in range(array_start, len(html)):
        ch = html[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1

            if depth == 0:
                array_end = i + 1
                break

    if array_end is None:
        print("Could not find end of India report edition array.")
        return None

    raw_array = html[array_start:array_end]

    try:
        editions = json.loads(raw_array)
    except json.JSONDecodeError as exc:
        print(f"Could not parse India report editions: {exc}")
        return None

    if not editions:
        print("India report edition array was empty.")
        return None

    # Meta already supplies this array sorted by publish date, newest first.
    latest = editions[0]

    url = latest.get("cdn_url")

    if not url:
        print("Newest India report does not contain cdn_url.")
        return None

    print("Latest India monthly report discovered:")
    print("  Month:", latest.get("month"))
    print("  Time period:", latest.get("time_period"))
    print("  URL:", url)

    return latest


def browser_sync_one(
    profile_dir: Path,
    hub_cache: Path,
    processed_urls: set[str],
    headed: bool = True,
) -> BrowserSyncResult:
    """Open Meta once, extract the newest India monthly report, and download it."""

    with sync_playwright() as p:
        context = _launch_context(p, profile_dir, headed=headed)

        try:
            page = context.pages[0] if context.pages else context.new_page()

            _reduce_noise(page)

            print("Opening Meta regulatory transparency page once...")

            try:
                response = page.goto(
                    HUB_URL,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )
            except PlaywrightError as exc:
                raise BrowserFetchError(
                    f"Chrome could not open the Meta report hub: {exc}"
                ) from exc

            status = response.status if response else None

            if status and status >= 400:
                raise BrowserFetchError(
                    f"Meta returned HTTP {status} to Chrome automation."
                )

            if response is None:
                raise BrowserFetchError(
                    "Meta page opened without a readable HTTP response."
                )

            # IMPORTANT:
            # Use the original server response, not page.content().
            # The India report metadata is embedded here.
            try:
                initial_html = response.text()
            except Exception as exc:
                raise BrowserFetchError(
                    f"Could not read Meta's initial page response: {exc}"
                ) from exc

            print(f"Initial Meta response length: {len(initial_html)}")

            # Keep a local diagnostic copy.
            hub_cache.parent.mkdir(parents=True, exist_ok=True)
            hub_cache.write_text(
                initial_html,
                encoding="utf-8",
                errors="ignore",
            )

            latest = _extract_latest_india_monthly_report(initial_html)

            if not latest:
                print("No India Monthly Report metadata found.")
                return BrowserSyncResult(
                    hub_status=status,
                    candidates=[],
                )

            url = latest["cdn_url"]
            month = latest.get("month") or "unknown-month"

            print(f"Newest report: {month}")
            print("Downloading exactly one report from Meta CDN...")

            data, filename = _download_in_context(
                context,
                page,
                url,
            )

            print(f"Downloaded {len(data)} bytes.")

            return BrowserSyncResult(
                hub_status=status,
                candidates=[],
                downloaded_url=url,
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
