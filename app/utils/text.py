from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.models.schemas import JobListing

_TRACK = {"gclid", "fbclid", "ref", "trk", "source", "src"}


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    q = sorted((k, v) for k, v in parse_qsl(p.query)
               if not k.lower().startswith("utm_") and k.lower() not in _TRACK)
    return f"{host}{path}" + (f"?{urlencode(q)}" if q else "")


def job_id_for(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:16]


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def dedupe_jobs(jobs: list[JobListing]) -> list[JobListing]:
    seen_urls: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    out: list[JobListing] = []
    for j in jobs:
        u = normalize_url(j.source_url)
        key = (_norm(j.title), _norm(j.company), _norm(j.location)) if j.company else None
        if u in seen_urls or (key and key in seen_keys):
            continue
        seen_urls.add(u)
        if key:
            seen_keys.add(key)
        out.append(j)
    return out
