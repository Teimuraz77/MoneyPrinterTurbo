"""URL normalisation and near-duplicate title detection (64-bit simhash)."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmpid|ito$|at_)", re.IGNORECASE)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower().removeprefix("www."),
                       path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()


def _tokens(title: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 2]


def simhash(title: str) -> int:
    v = [0] * 64
    toks = _tokens(title)
    shingles = toks + [" ".join(toks[i:i + 2]) for i in range(len(toks) - 1)]
    for sh in shingles:
        h = int.from_bytes(hashlib.md5(sh.encode()).digest()[:8], "big")
        for i in range(64):
            v[i] += 1 if h >> i & 1 else -1
    return sum(1 << i for i in range(64) if v[i] > 0)


def title_hash(title: str) -> str:
    return f"{simhash(title):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def is_near_duplicate(th: str, existing: list[str], max_distance: int = 6) -> bool:
    return any(hamming(th, e) <= max_distance for e in existing)
