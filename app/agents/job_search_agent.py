"""Job Search Agent: live Tavily searches -> structured, deduplicated candidate listings."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.config import get_settings
from app.models.schemas import JobListing, SearchCriteria
from app.tools.web_search import SearchError, web_search
from app.utils.text import dedupe_jobs, job_id_for

log = logging.getLogger(__name__)
JOBISH = re.compile(r"\b(job|jobs|career|careers|hiring|intern|internship|engineer|developer|opening|apply|vacancy|trainee)\b", re.I)
TEMPLATES = [
    ["{role} {level} job opening {loc}", "{role} careers apply {level} {loc}"],
    ["{role} internship OR graduate trainee {loc}", "{role} entry level hiring {loc}"],
    ["{role} jobs hiring now {loc}", "{role} vacancy apply"],
]


def build_queries(c: SearchCriteria, attempt: int) -> list[str]:
    level = "fresher entry level" if c.experience_level == "fresher" else c.experience_level
    loc = " ".join(x for x in [c.location, c.work_mode] if x) if attempt < 2 else (c.location or "")
    tmpl = TEMPLATES[min(attempt, len(TEMPLATES) - 1)]
    qs = [t.format(role=r, level=level, loc=loc).strip() for r in c.roles[:3] for t in tmpl]
    return list(dict.fromkeys(re.sub(r"\s+", " ", q) for q in qs))


def result_to_job(r: dict, query: str, criteria: SearchCriteria, searched_at: datetime) -> JobListing | None:
    url, title, content = r.get("url") or "", (r.get("title") or "").strip(), r.get("content") or ""
    if not url or not title or not JOBISH.search(f"{title} {url} {content[:300]}"):
        return None
    company = None
    m = re.search(r"\bat\s+([A-Z][\w&.\- ]{1,40}?)(?:\s[-|•]|$)", title)
    if m:
        company = m.group(1).strip()
    else:
        parts = re.split(r"\s[-|•–]\s", title)
        if len(parts) > 1 and len(parts[-1]) <= 40 and not re.search(r"job|career|hiring|naukri|indeed|linkedin", parts[-1], re.I):
            company = parts[-1].strip()
    text = f"{title} {content}"
    loc = criteria.location if criteria.location and criteria.location.lower() in text.lower() else None
    if not loc:
        lm = re.search(r"Location[:\s]+([A-Z][\w ,]{2,40})", content)
        loc = lm.group(1).strip() if lm else None
    em = re.search(r"(\d+\s*(?:-|to)\s*\d+|\d+\+?)\s*years?", content, re.I)
    exp = em.group(0) if em else ("fresher / entry level" if re.search(r"fresher|entry.level|graduate|intern", text, re.I) else None)
    posted = r.get("published_date")
    if not posted:
        pm = re.search(r"posted\s+(\d+\s+\w+\s+ago)", content, re.I)
        posted = pm.group(1) if pm else None
    return JobListing(
        job_id=job_id_for(url), title=title[:200], company=company, location=loc, experience_required=exp,
        posted_date=posted, description=content[:2000], source_url=url,
        application_url=url if "apply" in url.lower() else None,
        source_domain=(urlsplit(url).hostname or "").removeprefix("www."), search_query=query, searched_at=searched_at)


async def search_jobs(criteria: SearchCriteria, attempt: int = 0) -> tuple[list[JobListing], list[str], dict]:
    """Returns (jobs, error_messages, stats). Raises nothing; errors are reported."""
    s = get_settings()
    queries = build_queries(criteria, attempt)
    sem, now = asyncio.Semaphore(4), datetime.now(timezone.utc)
    errors: list[str] = []

    async def one(q: str):
        async with sem:
            try:
                return q, await web_search(q, max_results=s.max_results_per_query, days=criteria.recency_days)
            except SearchError as e:
                errors.append(f"'{q}': {e}")
                return q, []

    batches = await asyncio.gather(*(one(q) for q in queries))
    raw = sum(len(res) for _, res in batches)
    jobs = [j for q, res in batches for r in res if (j := result_to_job(r, q, criteria, now))]
    unique = dedupe_jobs(jobs)
    stats = {"queries": len(queries), "raw_results": raw, "job_like": len(jobs), "unique": len(unique),
             "failed_queries": len(errors)}
    return unique, list(dict.fromkeys(errors)), stats
