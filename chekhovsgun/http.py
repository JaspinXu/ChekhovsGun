"""A small, polite HTTP client shared by every adapter.

Both YouTube and Bilibili will throttle or soft-ban a client that hammers them.
This wrapper adds bounded retries with exponential backoff and jitter, honours
``Retry-After``, and keeps one connection pool per adapter so ingest of a large
library reuses TLS sessions instead of renegotiating for every video.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        min_interval: float = 0.0,
    ) -> None:
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_request = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            headers=headers or {},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                log.debug("request error (%s) %s attempt=%d", exc, url, attempt)
            else:
                if response.status_code not in RETRY_STATUS:
                    return response
                last_error = HttpError(
                    f"{response.status_code} from {url}", response.status_code
                )
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(30.0, float(retry_after)))
                    continue
            if attempt < self.max_retries:
                time.sleep(min(8.0, (2**attempt) * 0.8) + random.uniform(0, 0.4))
        raise HttpError(f"request failed after retries: {url} ({last_error})")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.get(url, **kwargs)
        if response.status_code >= 400:
            raise HttpError(f"{response.status_code} from {url}: {response.text[:200]}",
                            response.status_code)
        return response.json()
