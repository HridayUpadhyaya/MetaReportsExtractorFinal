from __future__ import annotations
import html as htmllib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from .http_client import MetaHTTP

HUB_URL = "https://transparency.meta.com/reports/regulatory-transparency-reports/"

@dataclass(frozen=True)
class Candidate:
    url: str
    label: str
    date_key: str


def _decode_blob(text: str) -> str:
    text = htmllib.unescape(text)
    text = text.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")
    text = text.replace(r"\u0026", "&").replace(r"\u003A", ":")
    return text


def _date_key(text: str) -> str:
    s = unquote(text)
    # ISO first.
    m = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    months = {m.lower(): i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
    m = re.search(r"(?i)(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-_ ]?(\d{1,2})[-_ ,]?(20\d{2})", s)
    if m:
        return f"{int(m.group(3)):04d}-{months[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(?i)(\d{1,2})[-_ ]?(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-_ ,]?(20\d{2})", s)
    if m:
        return f"{int(m.group(3)):04d}-{months[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    return "0000-00-00"


def extract_india_pdf_links(html_text: str, base_url: str = HUB_URL) -> list[Candidate]:
    decoded = _decode_blob(html_text)
    soup = BeautifulSoup(decoded, "html.parser")
    found: dict[str, Candidate] = {}

    # Direct anchor links.
    for a in soup.find_all("a", href=True):
        href = _decode_blob(a.get("href", "")).strip()
        if ".pdf" not in href.lower():
            continue
        url = urljoin(base_url, href)
        context = " ".join([
            a.get_text(" ", strip=True),
            a.parent.get_text(" ", strip=True) if a.parent else "",
            href,
        ])
        if "india" not in context.lower():
            continue
        found[url] = Candidate(url, a.get_text(" ", strip=True) or url.rsplit("/",1)[-1], _date_key(context + " " + url))

    # URLs embedded in Next/React JSON or script strings.
    patterns = [
        r"https?://[^\s\"'<>\\]+?\.pdf(?:\?[^\s\"'<>\\]*)?",
        r"/[A-Za-z0-9_./%?=&+\-]+?\.pdf(?:\?[A-Za-z0-9_./%?=&+\-]*)?",
    ]
    for pat in patterns:
        for m in re.finditer(pat, decoded, re.I):
            raw = m.group(0)
            url = urljoin(base_url, raw)
            context = decoded[max(0, m.start()-900):min(len(decoded), m.end()+900)]
            if "india" not in context.lower() and "india" not in url.lower():
                continue
            found.setdefault(url, Candidate(url, url.rsplit("/",1)[-1], _date_key(context + " " + url)))

    # Deep-inspect valid JSON script tags as another way to catch nested file URLs.
    def walk(obj, context=""):
        if isinstance(obj, dict):
            local = context + " " + " ".join(str(v)[:200] for v in obj.values() if isinstance(v, (str,int,float)))
            for v in obj.values():
                walk(v, local)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, context)
        elif isinstance(obj, str) and ".pdf" in obj.lower():
            val = _decode_blob(obj)
            for m in re.finditer(r"https?://[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]*)?", val, re.I):
                url = m.group(0)
                if "india" in (context + " " + val + " " + url).lower():
                    found.setdefault(url, Candidate(url, url.rsplit("/",1)[-1], _date_key(context + " " + url)))

    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        text = text.strip()
        if not text or text[0:1] not in "[{":
            continue
        try:
            walk(json.loads(text))
        except Exception:
            pass

    return sorted(found.values(), key=lambda c: (c.date_key, c.url))


def fetch_hub_once(client: MetaHTTP, cache_file: Path) -> tuple[str, list[Candidate]]:
    r = client.get(HUB_URL, timeout=45)
    text = r.text
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8", errors="ignore")
    return text, extract_india_pdf_links(text)
