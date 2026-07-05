"""Shared HTTP layer with anti-ban behaviour:

  * Rotating proxy pool (round-robin, auto-drops proxies after repeated failures).
  * Retry with exponential backoff + jitter on 429/503/5xx/timeouts, honouring
    a Retry-After header when present.
  * Randomized inter-request delay (jitter) via polite_sleep().

Both the contact scraper and the Places API sourcer route through here so proxy
rotation and backoff apply everywhere outbound HTTP happens.
"""

import os
import random
import threading
import time

import requests

import config

# Statuses worth retrying (transient / rate-limit), vs. a hard 404/403.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ProxyPool:
    """Round-robin proxy rotation with per-proxy failure strikes."""

    def __init__(self, proxies: list[str], max_failures: int):
        self._proxies = list(dict.fromkeys(p.strip() for p in proxies if p.strip()))
        self._failures: dict[str, int] = {p: 0 for p in self._proxies}
        self._idx = 0
        self._max_failures = max_failures
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def __len__(self) -> int:
        return len(self._proxies)

    def next(self) -> str | None:
        """Next live proxy URL, or None if the pool is empty/exhausted."""
        with self._lock:
            if not self._proxies:
                return None
            self._idx %= len(self._proxies)
            proxy = self._proxies[self._idx]
            self._idx += 1
            return proxy

    def report_failure(self, proxy: str | None) -> None:
        if not proxy:
            return
        with self._lock:
            if proxy not in self._failures:
                return
            self._failures[proxy] += 1
            if self._failures[proxy] >= self._max_failures:
                self._proxies = [p for p in self._proxies if p != proxy]
                self._failures.pop(proxy, None)
                print(f"[proxy] dropped dead proxy ({len(self._proxies)} left): "
                      f"{_mask(proxy)}")

    def report_success(self, proxy: str | None) -> None:
        if not proxy:
            return
        with self._lock:
            if proxy in self._failures:
                self._failures[proxy] = 0


def _mask(proxy: str) -> str:
    """Hide credentials when logging a proxy URL."""
    if "@" in proxy:
        scheme, _, rest = proxy.partition("://")
        host = rest.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    return proxy


def _load_proxies() -> list[str]:
    proxies: list[str] = []
    if config.PROXY_LIST:
        proxies += [p for p in config.PROXY_LIST.split(",") if p.strip()]
    if config.PROXY_FILE and os.path.exists(config.PROXY_FILE):
        with open(config.PROXY_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    proxies.append(line)
    return proxies


# Module-level singletons.
POOL = ProxyPool(_load_proxies(), config.PROXY_MAX_FAILURES)
if POOL.enabled:
    print(f"[proxy] rotating pool active: {len(POOL)} prox{'y' if len(POOL) == 1 else 'ies'}")
else:
    print("[proxy] no proxies configured — requests use the local IP")

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})


def polite_sleep() -> None:
    """Randomized inter-request delay to avoid a detectable fixed cadence."""
    lo, hi = config.JITTER_MIN_SECONDS, config.JITTER_MAX_SECONDS
    if hi > 0 and hi >= lo:
        time.sleep(random.uniform(lo, hi))
    elif config.REQUEST_DELAY_SECONDS > 0:
        time.sleep(config.REQUEST_DELAY_SECONDS)


def _backoff_wait(attempt: int, retry_after: str | None) -> None:
    if retry_after:
        try:
            time.sleep(min(float(retry_after), config.BACKOFF_MAX_SECONDS))
            return
        except (TypeError, ValueError):
            pass
    delay = min(config.BACKOFF_BASE_SECONDS * (2 ** attempt), config.BACKOFF_MAX_SECONDS)
    time.sleep(delay + random.uniform(0, delay * 0.3))  # exponential + 30% jitter


def request(method: str, url: str, **kwargs) -> requests.Response | None:
    """HTTP request with proxy rotation + backoff. Returns Response or None.

    A different proxy is tried on each attempt. Failing proxies accrue strikes
    and are dropped from the pool. Returns None only after all retries fail.
    """
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
    last_exc = None

    for attempt in range(config.MAX_RETRIES):
        proxy = POOL.next()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = _session.request(method, url, proxies=proxies, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            POOL.report_failure(proxy)
            print(f"[http] {type(exc).__name__} on {url} "
                  f"(attempt {attempt + 1}/{config.MAX_RETRIES})")
            if attempt < config.MAX_RETRIES - 1:
                _backoff_wait(attempt, None)
            continue

        if resp.status_code in _RETRY_STATUS:
            # A proxy that keeps yielding 429/503 is likely rate-limited/blocked.
            POOL.report_failure(proxy)
            print(f"[http] {resp.status_code} on {url} "
                  f"(attempt {attempt + 1}/{config.MAX_RETRIES})")
            if attempt < config.MAX_RETRIES - 1:
                _backoff_wait(attempt, resp.headers.get("Retry-After"))
            continue

        POOL.report_success(proxy)
        return resp

    if last_exc:
        print(f"[http] giving up on {url}: {type(last_exc).__name__}")
    return None


def get(url: str, **kwargs) -> requests.Response | None:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response | None:
    return request("POST", url, **kwargs)
