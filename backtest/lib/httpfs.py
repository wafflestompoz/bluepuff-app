"""Minimal fsspec-like range reader for public S3 over HTTPS (thread-local sessions, size cache)."""
import threading, requests, time
from requests.adapters import HTTPAdapter
BASE = "https://openmeteo.s3.amazonaws.com/"
_tl = threading.local(); _sizes = {}
def _s():
    if not hasattr(_tl, "s"):
        s = requests.Session(); s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4)); _tl.s = s
    return _tl.s
class HttpFS:
    def _url(self, path): return BASE + path.split("openmeteo/", 1)[-1]
    def size(self, path):
        if path not in _sizes:
            for i in range(5):
                try:
                    r = _s().head(self._url(path), timeout=60); r.raise_for_status(); _sizes[path] = int(r.headers["Content-Length"]); break
                except Exception:
                    if i == 4: raise
                    time.sleep(1 + i)
        return _sizes[path]
    def cat_file(self, path, start=None, end=None, **kw):
        h = {}
        if start is not None or end is not None:
            h["Range"] = f"bytes={start or 0}-{'' if end is None else end - 1}"
        for i in range(5):
            try:
                r = _s().get(self._url(path), headers=h, timeout=120); r.raise_for_status(); return r.content
            except Exception:
                if i == 4: raise
                time.sleep(1 + i)
