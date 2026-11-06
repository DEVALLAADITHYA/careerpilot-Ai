"""Report Agent: ranks results, lists uncertainty, builds CSV (formula-injection safe) and Markdown."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from app.models.schemas import (STATUS_LABEL, CareerAdvice, JobListing, JobResult, MatchResult, Report,
                                SearchCriteria, VerificationResult, VerificationStatus)

_ORDER = {"verified_open": 0, "likely_open": 1, "uncertain": 2, "not_checked": 3, "inaccessible": 4, "expired_or_closed": 5}


def _recency(j: JobListing) -> float:
    try:
        return datetime.fromisoformat((j.posted_date or "")[:10]).timestamp()
    except ValueError:
        return 0.0


def rank(results: list[JobResult]) -> list[JobResult]:
    def key(r: JobResult):
        st = (r.verification.status if r.verification else VerificationStatus.NOT_CHECKED).value
        return (_ORDER[st], -(r.match.score if r.match else 0), -_recency(r.job))
    return sorted(results, key=key)


def _safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def to_csv(results: list[JobResult]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "company", "location", "experience", "posted", "match_score", "verification", "missing_skills",
                "source_url", "application_url", "verified_at"])
    for r in results:
        v, m, j = r.verification, r.match, r.job
        w.writerow([_safe(x) for x in (j.title, j.company, j.location, j.experience_required, j.posted_date,
                                      m.score if m else "", STATUS_LABEL[v.status.value] if v else "Not checked",
                                      "; ".join(m.missing_skills) if m else "", j.source_url, j.application_url,
                                      v.checked_at.isoformat() if v else "")])
    return buf.getvalue()


def to_markdown(results: list[JobResult], advice: CareerAdvice | None, notes: list[str]) -> str:
    lines = ["# CareerPilot AI Report", ""]
    for i, r in enumerate(results, 1):
        st = STATUS_LABEL[(r.verification.status if r.verification else VerificationStatus.NOT_CHECKED).value]
        lines += [f"## {i}. {r.job.title} ({r.job.company or 'company unknown'})",
                  f"- Verification: **{st}**", f"- Match: {r.match.score if r.match else 'n/a'}",
                  f"- Source: {r.job.source_url}", f"- Missing skills: {', '.join(r.match.missing_skills) if r.match else 'n/a'}", ""]
    if advice:
        lines += [f"## Advice ({advice.source}; AI-generated, not verified fact)", *[f"- {s}" for s in advice.skills_to_learn], ""]
    if notes:
        lines += ["## Limitations of this run", *[f"- {n}" for n in notes]]
    return "\n".join(lines)


def build_report(search_id: str, criteria: SearchCriteria, jobs: list[JobListing], matches: dict[str, MatchResult],
                 verifs: dict[str, VerificationResult], advice: CareerAdvice | None, errors: list[str]) -> Report:
    results = rank([JobResult(job=j, match=matches.get(j.job_id), verification=verifs.get(j.job_id)) for j in jobs])
    notes = list(errors)
    if not jobs:
        notes.append("No candidate listings were found.")
    unchecked = sum(1 for r in results if not r.verification)
    if unchecked:
        notes.append(f"{unchecked} listing(s) were not verified (only top matches are checked).")
    blocked = sum(1 for r in results if r.verification and r.verification.status == VerificationStatus.INACCESSIBLE)
    if blocked:
        notes.append(f"{blocked} listing(s) could not be accessed; their status is unconfirmed, not closed.")
    notes.append("Search results are candidate listings, not proof a job is open.")
    return Report(report_id=uuid.uuid4().hex[:12], search_id=search_id, criteria=criteria, results=results,
                  advice=advice, incomplete_notes=notes, csv=to_csv(results), markdown=to_markdown(results, advice, notes))
