"""Is a newer Desk Sister out? One GET of the public GitHub release; nothing is sent, nothing is downloaded."""
from __future__ import annotations

import http.client
import json
import logging
import re
import urllib.request

from . import __version__

log = logging.getLogger(__name__)

LATEST_URL = "https://api.github.com/repos/leto0309/desk-sister/releases/latest"
RELEASES_PAGE = "https://github.com/leto0309/desk-sister/releases/latest"
CHECK_EVERY_SEC = 24 * 3600
RETRY_SEC = 3600  # after a failed check (offline at start, say)
TIMEOUT_SEC = 10
MAX_BYTES = 1 << 20
_VERSION = re.compile(r"v?(\d{1,6}(?:\.\d{1,6}){1,3})")


def parse_version(text: object) -> tuple[int, ...] | None:
    match = _VERSION.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def fetch_latest(opener=urllib.request.urlopen) -> str | None:
    """The version of the latest published release ("0.1.12"), or None when it cannot be read."""
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"desk-sister/{__version__}"})
    try:
        with opener(request, timeout=TIMEOUT_SEC) as response:
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("release answer too large")
        data = json.loads(body.decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as exc:  # offline, rate limits, broken answers
        log.info("update check failed: %s", exc)
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = parse_version(data.get("tag_name"))
    return ".".join(map(str, version)) if version else None
