from __future__ import annotations
import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

class RequestBudgetExceeded(RuntimeError):
    pass

class MetaHTTP:
    """A deliberately tiny HTTP client that never probes, HEADs, or retries Meta.

    Every call to get() consumes exactly one request from the configured budget.
    requests' automatic retrying is disabled by default; redirects are disabled so a
    request is not silently turned into multiple network requests.
    """
    def __init__(self, budget: int):
        self.budget = budget
        self.used = 0
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get(self, url: str, *, timeout: int = 45, stream: bool = False) -> requests.Response:
        if self.used >= self.budget:
            raise RequestBudgetExceeded(f"Meta request budget exhausted ({self.used}/{self.budget}).")
        self.used += 1
        r = self.session.get(url, timeout=timeout, stream=stream, allow_redirects=False)
        # Do not auto-retry a 429. One request means one request.
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            msg = "Meta returned HTTP 429. No retry was attempted."
            if retry_after:
                msg += f" Retry-After: {retry_after}."
            raise RuntimeError(msg)
        if 300 <= r.status_code < 400:
            loc = r.headers.get("Location")
            raise RuntimeError(f"Meta returned redirect HTTP {r.status_code} to {loc!r}. Redirects are disabled to keep the request count exact.")
        r.raise_for_status()
        return r
