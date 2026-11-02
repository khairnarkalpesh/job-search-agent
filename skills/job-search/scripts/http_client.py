"""Polite HTTP access. Blocked pages are reported and skipped, never worked around."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

USER_AGENT = "job-search-agent/1.0 (personal job search; public listings only)"


class FetchError(Exception):
    """kind is one of: not_found, blocked, network, malformed."""

    def __init__(self, kind: str, url: str, detail: str = ""):
        super().__init__(f"{kind}: {url} {detail}".strip())
        self.kind = kind
        self.url = url


class HttpClient:
    def __init__(self, min_interval: float = 1.0, timeout: int = 45, retries: int = 2, cache_dir=None):
        self.min_interval = min_interval
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.retries = retries
        self._last_call: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait_for_host(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_call.get(host, 0)
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call[host] = time.monotonic()

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait_for_host(parts.netloc)
                request = urllib.request.Request(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    parser.parse(response.read().decode("utf-8", "replace").splitlines())
                self._robots[origin] = parser
            except (urllib.error.URLError, TimeoutError, OSError):
                self._robots[origin] = None  # no readable robots.txt means no stated restriction
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def get(self, url: str, check_robots: bool = False) -> str:
        if check_robots and not self._allowed_by_robots(url):
            raise FetchError("blocked", url, "disallowed by robots.txt")
        host = urllib.parse.urlsplit(url).netloc
        for attempt in range(self.retries + 1):
            self._wait_for_host(host)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    raise FetchError("not_found", url, f"HTTP {error.code}") from error
                if error.code in (401, 403, 407, 451):
                    raise FetchError("blocked", url, f"HTTP {error.code}") from error
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    kind = "blocked" if error.code == 429 else "network"
                    raise FetchError(kind, url, f"HTTP {error.code}") from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == self.retries:
                    raise FetchError("network", url, str(error)) from error
            time.sleep(2 ** (attempt + 1))
        raise FetchError("network", url, "retries exhausted")

    def get_json(self, url: str, cache_hours: float = 0):
        """cache_hours > 0 reuses a saved response that young, for APIs that ask for few calls."""
        cache_file = None
        if cache_hours and self.cache_dir:
            cache_file = self.cache_dir / f"{hashlib.sha1(url.encode()).hexdigest()}.json"
            if cache_file.exists() and time.time() - cache_file.stat().st_mtime < cache_hours * 3600:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        body = self.get(url)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as error:
            raise FetchError("malformed", url, "response is not JSON") from error
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(body, encoding="utf-8")
        return data
