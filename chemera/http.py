"""Small HTTP helper layer with Windows-friendly standard-library defaults."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


class FetchError(RuntimeError):
    """Raised when an HTTP request cannot be completed."""


@dataclass(slots=True)
class HttpClient:
    """HTTP client with explicit timeout and bounded retries."""

    timeout: float = 20.0
    retries: int = 2
    retry_backoff: float = 1.5
    headers: Mapping[str, str] = field(default_factory=lambda: DEFAULT_HEADERS.copy())

    def get_text(self, url: str, headers: Mapping[str, str] | None = None) -> str:
        body = self.get_bytes(url, headers=headers)
        return body.decode("utf-8", errors="replace")

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> object:
        text = self.get_text(url, headers=headers)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"Response from {url!r} is not valid JSON: {exc}") from exc

    def get_bytes(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        merged_headers = dict(self.headers)
        if headers:
            merged_headers.update(headers)

        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                request = Request(url, headers=merged_headers)
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code not in {408, 429}:
                    break
            except URLError as exc:
                last_error = exc
            except TimeoutError as exc:
                last_error = exc

            if attempt < self.retries:
                time.sleep(self.retry_backoff * (attempt + 1))

        raise FetchError(f"Failed to fetch {url!r}: {last_error}") from last_error
