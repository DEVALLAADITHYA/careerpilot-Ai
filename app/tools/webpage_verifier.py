"""Fetches a job page safely and assigns a verification status from evidence.

Pages are untrusted data: they are only pattern-matched, never given to an LLM.
"""
from __future__ import annotations

import html as htmllib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import get_settings
from app.models.schemas import VerificationResult, VerificationStatus
from app.tools.url_safety import UnsafeURLError, check_url_async

log = logging.getLogger(__name__)
MAX_REDIRECTS = 5
MAX_BYTES = 400_000
UA = "Mozilla/5.0 (compatible; CareerPilotBot/1.0; job-status-check)"

ATS = ("greenhouse.io", "lever.co", "myworkdayjobs.com", "ashbyhq.com", "smartrecruiters.com",
       "workable.com", "icims.com", "jobvite.com", "breezy.hr", "recruitee.com", "darwinbox.in")
AGGREGATORS = ("linkedin.com", "indeed.com", "naukri.com", "glassdoor.com", "internshala.com",
               "foundit.in", "monster.com", "wellfound.com", "ziprecruiter.com", "simplyhired.com",
               "instahyre.com", "cutshort.io", "shine.com", "timesjobs.com")
CLOSED = ("no longer accepting applications", "position has been filled", "this job has expired",
          "job is no longer available", "this job is closed", "no longer available", "applications are closed",
          "posting has expired", "position is closed", "this position is no longer open", "job expired")
APPLY = ("apply now", "apply for this job", "apply for this position", "apply to this job",
         "apply on company site", "apply here", "easy apply", "submit application", "apply for job")


def classify_source(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in AGGREGATORS):
        return "aggregator"
    if any(host == d or host.endswith("." + d) for d in ATS):
        return "ats"
    if re.search(r"(^|\.)(careers?|jobs?)\.", host) or re.search(r"/(careers?|jobs?)(/|$)", urlsplit(url).path.lower()):
        return "official"
    return "unknown"


INDEX_SEGMENTS = {"", "jobs", "job", "careers", "career", "internships", "internship", "openings", "vacancies",
                  "fresher", "freshers", "opportunities", "join-us", "work-with-us", "current-openings"}


def _plain(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def _text(html: str) -> str:
    return _plain(html).lower()


def looks_like_index(url: str, text: str) -> bool:
    """A generic jobs page (many 'apply' buttons / generic path) is not proof one specific job is open."""
    last = urlsplit(url).path.rstrip("/").split("/")[-1].lower()
    return last in INDEX_SEGMENTS or sum(text.count(p) for p in APPLY) >= 4


def page_info(url: str, html: str) -> tuple[str, str]:
    """(page_kind, excerpt) for a successfully fetched page."""
    plain = _plain(html)
    structured = '"JobPosting"' in html
    kind = "listing_index" if (not structured and looks_like_index(url, plain.lower())) else "single_posting"
    return kind, plain[:3000]


def _title_hit(title: str | None, text: str) -> bool:
    if not title:
        return False
    t = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    if t.strip() in text:
        return True
    toks = [w for w in t.split() if len(w) > 2]
    return bool(toks) and sum(w in text for w in toks) / len(toks) >= 0.8


def assess(http_status: int, html: str, url: str, title: str | None = None,
           now: datetime | None = None) -> tuple[VerificationStatus, list[str]]:
    """Pure function: decide status from HTTP status + page content."""
    now = now or datetime.now(timezone.utc)
    kind = classify_source(url)
    ev = [f"HTTP {http_status}", f"source type: {kind}"]
    if http_status in (404, 410):
        return VerificationStatus.EXPIRED, ev + ["page not found (404/410)"]
    if http_status != 200:
        return VerificationStatus.INACCESSIBLE, ev + ["page blocked or unavailable; vacancy status NOT confirmed"]
    text = _text(html)
    for phrase in CLOSED:
        if phrase in text:
            return VerificationStatus.EXPIRED, ev + [f'closed-language found: "{phrase}"']
    m = re.search(r'"validThrough"\s*:\s*"([^"]+)"', html)
    structured = '"JobPosting"' in html
    if m:
        try:
            vt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if vt.tzinfo is None:
                vt = vt.replace(tzinfo=timezone.utc)
            if vt < now:
                return VerificationStatus.EXPIRED, ev + [f"JobPosting validThrough {m.group(1)} is in the past"]
            ev.append(f"JobPosting validThrough {m.group(1)} is in the future")
        except ValueError:
            pass
    elif structured:
        ev.append("JobPosting structured data present")
    apply_hit = next((p for p in APPLY if p in text), None)
    if apply_hit:
        ev.append(f'apply language found: "{apply_hit}"')
    hit_title = _title_hit(title, text)
    ev.append("job title found on page" if hit_title else "job title NOT found on page")
    posted = re.search(r"posted[^.]{0,40}", text)
    if posted:
        ev.append(f'date text: "{posted.group(0).strip()}"')
    has_apply = bool(apply_hit or structured)
    if not structured and looks_like_index(url, text):
        return VerificationStatus.UNCERTAIN, ev + ["page looks like a general jobs listing, not a single job posting; open it and find the exact role"]
    if kind in ("official", "ats") and has_apply and hit_title:
        return VerificationStatus.VERIFIED_OPEN, ev
    if has_apply:
        return VerificationStatus.LIKELY_OPEN, ev
    return VerificationStatus.UNCERTAIN, ev + ["page reachable but no apply/open evidence; accessible does not mean open"]


async def verify_url(job_id: str, url: str, title: str | None = None, *,
                     client: httpx.AsyncClient | None = None, validator=check_url_async) -> VerificationResult:
    s = get_settings()
    own = client is None
    client = client or httpx.AsyncClient(timeout=s.http_timeout, follow_redirects=False)
    res = VerificationResult(job_id=job_id, url=url, source_kind=classify_source(url))
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await validator(current)
            except UnsafeURLError as e:
                res.status, res.evidence = VerificationStatus.INACCESSIBLE, [f"blocked unsafe URL: {e}"]
                return res
            try:
                async with client.stream("GET", current, headers={"User-Agent": UA}) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        current = urljoin(current, r.headers["location"])
                        continue
                    body = b""
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    ctype = r.headers.get("content-type", "")
                    res.http_status, res.final_url = r.status_code, current
                    if r.status_code == 200 and "html" not in ctype and "text" not in ctype:
                        res.status, res.evidence = VerificationStatus.UNCERTAIN, [f"non-HTML content-type: {ctype}"]
                        return res
                    html_text = body.decode("utf-8", "ignore")
                    res.status, res.evidence = assess(r.status_code, html_text, current, title)
                    if r.status_code == 200:
                        res.page_kind, res.page_excerpt = page_info(current, html_text)
                    res.source_kind = classify_source(current)
                    return res
            except httpx.HTTPError as e:
                res.status, res.evidence = VerificationStatus.INACCESSIBLE, [f"request failed: {type(e).__name__}"]
                return res
        res.status, res.evidence = VerificationStatus.INACCESSIBLE, ["too many redirects"]
        return res
    finally:
        res.checked_at = datetime.now(timezone.utc)
        if own:
            await client.aclose()
