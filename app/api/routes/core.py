from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse

from app.agents import matching_agent, resume_agent, verification_agent
from app.config import get_settings
from app.database import repository as repo
from app.database.connection import session_scope
from app.graph.workflow import run_search
from app.models.schemas import (ApplicationUpdate, MatchRequest, SaveJobRequest, SearchCriteria, SearchRequest,
                                VerifyRequest)
from app.agents import career_advisor_agent
from app.models.schemas import CandidateProfile
from app.services.resume_analysis import analyze, role_gap_skills
from app.tools.resume_parser import ResumeError, extract_text

router = APIRouter()
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    """Simple in-memory per-IP limiter (use a shared store such as Redis if you run multiple workers)."""
    limit, now = get_settings().rate_limit_per_min, time.time()
    q = _hits[request.client.host if request.client else "unknown"]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Rate limit exceeded; try again in a minute")
    q.append(now)


@router.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "search_provider": s.search_provider, "search_ready": s.search_provider != "tavily" or bool(s.tavily_api_key), "groq_configured": bool(s.groq_api_key)}


@router.post("/api/search", status_code=202, dependencies=[Depends(rate_limit)])
async def search(req: SearchRequest, bg: BackgroundTasks):
    s = get_settings()
    if s.search_provider == "tavily" and not s.tavily_api_key:
        raise HTTPException(503, "SEARCH_PROVIDER=tavily but TAVILY_API_KEY is not configured")
    sid = uuid.uuid4().hex[:16]
    with session_scope() as s:
        repo.create_search(s, sid, req.query)
    bg.add_task(run_search, sid, req)
    return {"search_id": sid, "status": "running"}


@router.get("/api/search/{search_id}")
def search_status(search_id: str, after_id: int = 0):
    with session_scope() as s:
        info = repo.get_search(s, search_id)
        if not info:
            raise HTTPException(404, "Search not found")
        info["events"] = repo.get_events(s, search_id, after_id)
    return info


@router.post("/api/resume/analyze", dependencies=[Depends(rate_limit)])
async def analyze_resume(file: UploadFile = File(...)):
    limit = get_settings().max_pdf_mb * 1024 * 1024
    if not (file.filename or "").lower().endswith(".pdf") or file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(415, "Only PDF files are accepted")
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"PDF exceeds {get_settings().max_pdf_mb} MB limit")
    try:
        profile = resume_agent.analyze_pdf(data)
    except ResumeError as e:
        raise HTTPException(422, str(e))
    with session_scope() as s:
        repo.save_profile(s, profile)
    return profile


@router.post("/api/resume/compare", dependencies=[Depends(rate_limit)])
async def compare_resume(file: UploadFile | None = File(None), resume_text: str = Form(""), job_description: str = Form("")):
    """Resume (PDF/TXT upload or pasted text) vs optional job description. Resume text is never stored or logged."""
    if len(resume_text) > 60_000 or len(job_description) > 20_000:
        raise HTTPException(413, "Text too long")
    text = resume_text
    if file is not None and file.filename:
        limit = get_settings().max_pdf_mb * 1024 * 1024
        name = file.filename.lower()
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"File exceeds {get_settings().max_pdf_mb} MB limit")
        if name.endswith(".pdf"):
            try:
                text = extract_text(data)
            except ResumeError as e:
                raise HTTPException(422, str(e))
        elif name.endswith(".txt"):
            text = data.decode("utf-8", "ignore")[:60_000]
        else:
            raise HTTPException(415, "Only PDF or TXT resumes are accepted")
    if len(text.strip()) < 30:
        raise HTTPException(422, "Please upload a resume or paste your resume text")
    res = analyze(text, job_description)
    prof, m = CandidateProfile(**res["profile"]), res["match"]
    if m:  # roadmap straight from the gaps against THIS job description
        gaps, targets, label = m["missing"] + m["preferred_missing"], [], "Pasted job description"
    else:
        best = res["roles"][0]["role"]
        gaps, targets, label = role_gap_skills([best], set(prof.skills)), [best], f"{best} (best-fit role for your resume)"
    res["roadmap"] = (await career_advisor_agent.advise_gaps(prof, gaps, targets, job_description)).model_dump()
    res["roadmap_target"] = label
    return res


@router.post("/api/jobs/match", dependencies=[Depends(rate_limit)])
def match_jobs(req: MatchRequest):
    with session_scope() as s:
        jobs = repo.get_jobs_by_ids(s, req.job_ids)
        if not jobs:
            raise HTTPException(404, "No matching jobs found")
        crit = SearchCriteria(roles=req.roles, location=req.location)
        res = matching_agent.match_all(jobs, resume_agent.clean_profile(req.profile), crit)
        repo.save_matches(s, None, res)
    return sorted(res.values(), key=lambda r: r.score, reverse=True)


@router.post("/api/jobs/verify", dependencies=[Depends(rate_limit)])
async def verify_jobs(req: VerifyRequest):
    with session_scope() as s:
        jobs = repo.get_jobs_by_ids(s, req.job_ids)
    if not jobs:
        raise HTTPException(404, "No matching jobs found")
    res = await verification_agent.verify_jobs(jobs)
    with session_scope() as s:
        repo.save_verifications(s, None, res)
    return list(res.values())


@router.get("/api/jobs")
def jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), search_id: str | None = None):
    with session_scope() as s:
        return repo.list_jobs(s, limit, offset, search_id)


@router.post("/api/jobs/save", status_code=201)
def save_job(req: SaveJobRequest):
    with session_scope() as s:
        if not repo.save_job(s, req.job_id, req.status, req.applied_date):
            raise HTTPException(404, "Job not found")
    return {"saved": True, "job_id": req.job_id}


@router.delete("/api/jobs/saved/{job_id}")
def remove_saved(job_id: str):
    with session_scope() as s:
        if not repo.remove_saved(s, job_id):
            raise HTTPException(404, "Saved job not found")
    return {"removed": True}


@router.get("/api/jobs/saved")
def saved(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with session_scope() as s:
        return repo.list_saved(s, limit, offset)


@router.get("/api/applications")
def applications(status: str | None = None, q: str | None = Query(None, max_length=100),
                 limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with session_scope() as s:
        return repo.list_applications(s, status, q, limit, offset)


@router.patch("/api/applications/{application_id}")
def update_application(application_id: int, body: ApplicationUpdate):
    with session_scope() as s:
        out = repo.update_application(s, application_id, body.status, body.applied_date, body.notes)
    if not out:
        raise HTTPException(404, "Application not found")
    return out


@router.get("/api/reports/{report_id}")
def report(report_id: str):
    with session_scope() as s:
        r = repo.get_report(s, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return r


@router.get("/api/reports/{report_id}/csv", response_class=PlainTextResponse)
def report_csv(report_id: str):
    with session_scope() as s:
        r = repo.get_report(s, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return PlainTextResponse(r["csv"], media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=report_{report_id}.csv"})


@router.get("/api/dashboard")
def dashboard():
    with session_scope() as s:
        return repo.dashboard(s)
