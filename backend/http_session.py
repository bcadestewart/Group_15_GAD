"""
Shared `requests.Session` with retry policy for upstream API calls.

NWS (api.weather.gov) and Nominatim (nominatim.openstreetmap.org)
occasionally have transient slow responses or 5xx blips, especially
NWS forecast offices in the central US during high-load periods. Plain
`requests.get(...)` would surface every blip as a user-facing 503;
mounting an HTTPAdapter with a Retry policy means we silently retry
those before giving up.

Retry policy:
    - total=2 retries (3 attempts total).
    - backoff_factor=0.5 → waits ~0.5s, ~1.0s before the 2nd and 3rd
      attempts. Total worst-case extra latency is ~1.5s on top of the
      8s timeout.
    - Retry on 502, 503, 504 (transient upstream errors) and on
      ConnectionError / ReadTimeout (urllib3 retries those by default
      when total > 0).
    - Don't retry 4xx — those are real errors (e.g. NWS 404 for
      non-US coordinates) and retrying would just waste time.

Usage:
    from http_session import http
    r = http.get(url, timeout=8)
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "GAD/1.0 (cs4398@group15.com)"

_retry = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),
    raise_on_status=False,
    respect_retry_after_header=True,
)
_adapter = HTTPAdapter(max_retries=_retry)


def make_session() -> requests.Session:
    """Return a fresh Session with retry adapter and User-Agent applied.

    Exported separately from the module-level `http` instance so tests
    can build isolated sessions when needed.
    """
    s = requests.Session()
    s.mount("https://", _adapter)
    s.mount("http://", _adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# Module-level session, reused across requests so the connection pool
# stays warm.
http = make_session()
