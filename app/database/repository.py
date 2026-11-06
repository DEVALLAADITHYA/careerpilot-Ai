from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import models as m
from app.models.schemas import (AgentEvent, CandidateProfile, JobListing, MatchResult, Report, SearchCriteria,
                                VerificationResult)
from app.utils.text import normalize_url


def _now():
    return datetime.now(timezone.utc)


# ---- searches / events ----
def create_search(s: Session, search_id: str, query: str) -> None:
    s.add(m.SearchSession(id=search_id, query=query))


def finish_search(s: Session, search_id: str, status: str, error: str | None = None,
                  criteria: SearchCriteria | None = None, report_id: str | None = None) -> None:
    row = s.get(m.SearchSession, search_id)
    if row:
        row.status, row.error, row.finished_at = status, error, _now()
        if criteria:
            row.criteria = criteria.model_dump(mode="json")
        if report_id:
            row.report_id = report_id


def get_search(s: Session, search_id: str) -> dict | None:
    r = s.get(m.SearchSession, search_id)
    return None if not r else {"search_id": r.id, "query": r.query, "status": r.status, "error": r.error,
                               "report_id": r.report_id, "created_at": r.created_at.isoformat()}


def recent_searches(s: Session, n: int = 5) -> list[dict]:
    rows = s.scalars(select(m.SearchSession).order_by(m.SearchSession.created_at.desc()).limit(n))
    return [{"search_id": r.id, "query": r.query, "status": r.status, "created_at": r.created_at.isoformat()} for r in rows]


def add_event(s: Session, search_id: str, e: AgentEvent) -> None:
    s.add(m.AgentEventRow(search_id=search_id, agent=e.agent, event=e.event, detail=e.detail, ts=e.ts))


def get_events(s: Session, search_id: str, after_id: int = 0) -> list[dict]:
    rows = s.scalars(select(m.AgentEventRow).where(m.AgentEventRow.search_id == search_id, m.AgentEventRow.id > after_id)
                     .order_by(m.AgentEventRow.id))
    return [{"id": r.id, "agent": r.agent, "event": r.event, "detail": r.detail, "ts": r.ts.isoformat()} for r in rows]


# ---- jobs ----
def upsert_jobs(s: Session, jobs: list[JobListing]) -> None:
    for j in jobs:
        row = s.get(m.JobListingRow, j.job_id)
        if row:
            row.last_seen = _now()
            row.data = j.model_dump(mode="json")
            continue
        s.add(m.JobListingRow(job_id=j.job_id, url_key=normalize_url(j.source_url)[:1024], title=j.title[:300],
                              company=j.company, data=j.model_dump(mode="json")))
    s.flush()


def get_jobs_by_ids(s: Session, ids: list[str]) -> list[JobListing]:
    rows = s.scalars(select(m.JobListingRow).where(m.JobListingRow.job_id.in_(ids)))
    return [JobListing(**r.data) for r in rows]


def save_matches(s: Session, search_id: str | None, matches: dict[str, MatchResult]) -> None:
    for mr in matches.values():
        s.add(m.MatchRow(job_id=mr.job_id, search_id=search_id, score=mr.score, data=mr.model_dump(mode="json")))


def save_verifications(s: Session, search_id: str | None, vs: dict[str, VerificationResult]) -> None:
    for v in vs.values():
        s.add(m.VerificationRow(job_id=v.job_id, search_id=search_id, status=v.status.value, data=v.model_dump(mode="json"),
                                checked_at=v.checked_at))


def _latest(s: Session, model, ids: list[str], order_col) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in s.scalars(select(model).where(model.job_id.in_(ids)).order_by(order_col)):
        out[r.job_id] = r.data
    return out


def list_jobs(s: Session, limit: int = 20, offset: int = 0, search_id: str | None = None) -> dict:
    q = select(m.JobListingRow)
    if search_id:
        ids = select(m.MatchRow.job_id).where(m.MatchRow.search_id == search_id)
        q = q.where(m.JobListingRow.job_id.in_(ids))
    total = s.scalar(select(func.count()).select_from(q.subquery()))
    rows = list(s.scalars(q.order_by(m.JobListingRow.last_seen.desc()).limit(limit).offset(offset)))
    ids = [r.job_id for r in rows]
    matches = _latest(s, m.MatchRow, ids, m.MatchRow.id)
    verifs = _latest(s, m.VerificationRow, ids, m.VerificationRow.id)
    return {"total": total, "limit": limit, "offset": offset,
            "items": [{"job": r.data, "match": matches.get(r.job_id), "verification": verifs.get(r.job_id)} for r in rows]}


# ---- profile ----
def save_profile(s: Session, p: CandidateProfile) -> int:
    row = m.CandidateProfileRow(data=p.model_dump(mode="json"))
    s.add(row)
    s.flush()
    return row.id


# ---- reports ----
def save_report(s: Session, r: Report) -> None:
    s.merge(m.ReportRow(report_id=r.report_id, search_id=r.search_id, data=r.model_dump(mode="json")))


def get_report(s: Session, report_id: str) -> dict | None:
    row = s.get(m.ReportRow, report_id)
    return row.data if row else None


# ---- saved jobs / applications ----
def save_job(s: Session, job_id: str, status: str | None = None, applied_date: str | None = None) -> bool:
    """Save a job and/or log its application status. Re-saving without a status never changes an existing status."""
    if not s.get(m.JobListingRow, job_id):
        return False
    if status == "Applied" and not applied_date:
        applied_date = datetime.now(timezone.utc).date().isoformat()
    if not s.get(m.SavedJob, job_id):
        s.add(m.SavedJob(job_id=job_id))
        s.add(m.Application(job_id=job_id, status=status or "Interested", applied_date=applied_date))
    elif status:
        a = s.scalar(select(m.Application).where(m.Application.job_id == job_id))
        if a:
            a.status, a.updated_at = status, _now()
            if applied_date and not a.applied_date:
                a.applied_date = applied_date
    return True


def remove_saved(s: Session, job_id: str) -> bool:
    sj = s.get(m.SavedJob, job_id)
    if not sj:
        return False
    s.delete(sj)
    app = s.scalar(select(m.Application).where(m.Application.job_id == job_id))
    if app:
        s.delete(app)
    return True


def _app_dict(a: m.Application, job: m.JobListingRow) -> dict:
    return {"id": a.id, "job_id": a.job_id, "status": a.status, "applied_date": a.applied_date, "notes": a.notes,
            "updated_at": a.updated_at.isoformat(), "title": job.title, "company": job.company,
            "source_url": job.data.get("source_url")}


def list_saved(s: Session, limit: int = 50, offset: int = 0) -> list[dict]:
    q = (select(m.SavedJob, m.JobListingRow).join(m.JobListingRow, m.JobListingRow.job_id == m.SavedJob.job_id)
         .order_by(m.SavedJob.saved_at.desc()).limit(limit).offset(offset))
    return [{"saved_at": sj.saved_at.isoformat(), "job": j.data} for sj, j in s.execute(q)]


def list_applications(s: Session, status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    stmt = select(m.Application, m.JobListingRow).join(m.JobListingRow, m.JobListingRow.job_id == m.Application.job_id)
    if status:
        stmt = stmt.where(m.Application.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(m.JobListingRow.title).like(like) | func.lower(func.coalesce(m.JobListingRow.company, "")).like(like)
                          | func.lower(m.Application.notes).like(like))
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.execute(stmt.order_by(m.Application.updated_at.desc()).limit(limit).offset(offset))
    return {"total": total, "limit": limit, "offset": offset, "items": [_app_dict(a, j) for a, j in rows]}


def update_application(s: Session, app_id: int, status=None, applied_date=None, notes=None) -> dict | None:
    a = s.get(m.Application, app_id)
    if not a:
        return None
    if status is not None:
        a.status = status
    if applied_date is not None:
        a.applied_date = applied_date or None
    if notes is not None:
        a.notes = notes
    a.updated_at = _now()
    return _app_dict(a, s.get(m.JobListingRow, a.job_id))


# ---- dashboard ----
def dashboard(s: Session) -> dict:
    ids = [r for r in s.scalars(select(m.JobListingRow.job_id))]
    verifs = _latest(s, m.VerificationRow, ids, m.VerificationRow.id) if ids else {}
    scores = _latest(s, m.MatchRow, ids, m.MatchRow.id) if ids else {}
    by_status: dict[str, int] = {}
    for v in verifs.values():
        by_status[v["status"]] = by_status.get(v["status"], 0) + 1
    avg = round(sum(x["score"] for x in scores.values()) / len(scores), 1) if scores else None
    agents = dict(s.execute(select(m.AgentEventRow.agent, func.count()).group_by(m.AgentEventRow.agent)).all())
    return {"total_jobs": len(ids), "verified_open": by_status.get("verified_open", 0), "by_status": by_status,
            "avg_match_score": avg, "saved_jobs": s.scalar(select(func.count()).select_from(m.SavedJob)),
            "recent_searches": recent_searches(s), "agent_event_counts": agents}
