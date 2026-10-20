"""Polite HTTP: one shared session, retries with backoff, per-host delay."""
import time
import threading
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_UA = "skincare-data-hub/1.0 (+https://github.com/Arnitah/skincare-data-hub)"
_lock = threading.Lock()
_last = {}


def session(user_agent=None):
    s = requests.Session()
    s.headers["User-Agent"] = user_agent or _UA
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
    return s


def get(s, url, delay=0.5, timeout=45, **kw):
    """GET with a minimum gap between requests to the same host."""
    host = urlparse(url).netloc
    with _lock:
        wait = _last.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()
    r = s.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r
