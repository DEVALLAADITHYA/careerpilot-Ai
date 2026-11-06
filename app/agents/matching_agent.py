"""Matching Agent: transparent weighted score = sum(w_i * component_i) / sum(w_i of available components) * 100.

Components (each 0..1, or None when the job gives no information, in which case its weight is
redistributed): skills (required=1.0, preferred=0.5 weighting), semantic similarity, role relevance,
experience fit, education fit, location fit. NOT a probability of being hired.
"""
from __future__ import annotations

import re

from app.config import get_settings
from app.models.schemas import CandidateProfile, JobListing, MatchResult, SearchCriteria
from app.services.semantic import similarity
from app.utils.skills import extract_skills

_PREF = re.compile(r"(preferred|nice to have|good to have|bonus|a plus|desirable)", re.I)
_ENTRY = re.compile(r"fresher|entry.level|graduate|intern|trainee|0\s*-?\s*[12]\s*years?", re.I)


def split_skills(text: str) -> tuple[list[str], list[str]]:
    m = _PREF.search(text)
    req = extract_skills(text[:m.start()] if m else text)
    pref = [s for s in extract_skills(text[m.start():]) if s not in req] if m else []
    return req, pref


def _role_score(title: str, roles: list[str]) -> float | None:
    if not roles:
        return None
    tt = set(re.findall(r"[a-z]+", title.lower()))
    best = 0.0
    for r in roles:
        rt = [w for w in re.findall(r"[a-z]+", r.lower()) if w not in {"and", "the"}]
        if rt:
            best = max(best, sum(w in tt for w in rt) / len(rt))
    return best


def _exp_score(job: JobListing, cand_years: float) -> float | None:
    text = f"{job.experience_required or ''} {job.title} {job.description[:500]}"
    if _ENTRY.search(text):
        return 1.0
    m = re.search(r"(\d+)\s*\+?\s*(?:-|to)?\s*\d*\s*years?", job.experience_required or "", re.I)
    if not m:
        return None
    need = float(m.group(1))
    return 1.0 if cand_years >= need else max(0.0, 1 - (need - cand_years) / 3)


def _edu_score(job: JobListing, p: CandidateProfile) -> float | None:
    if not re.search(r"bachelor|b\.?tech|b\.?e\b|degree|graduate", job.description, re.I):
        return None
    return 1.0 if p.education else 0.3


def _loc_score(job: JobListing, c: SearchCriteria) -> float | None:
    if not c.location and not c.work_mode:
        return None
    text = f"{job.location or ''} {job.title} {job.description[:600]}".lower()
    if c.work_mode == "remote" and "remote" in text:
        return 1.0
    if c.location:
        if c.location.lower() in text:
            return 1.0
        return None if not job.location else 0.0
    return None


def match_job(job: JobListing, profile: CandidateProfile, criteria: SearchCriteria) -> MatchResult:
    s = get_settings()
    w = s.match_weights
    text = f"{job.title}. {job.description}"
    req, pref = split_skills(text)
    have = set(profile.skills)
    matched = sorted((set(req) | set(pref)) & have)
    missing = sorted(set(req) - have)
    total = len(req) + 0.5 * len(pref)
    skills = (len([x for x in req if x in have]) + 0.5 * len([x for x in pref if x in have])) / total if total else None
    prof_text = " ".join(profile.skills + profile.projects + profile.experience + profile.education)
    sem, backend = similarity(prof_text, text) if prof_text.strip() else (None, "n/a")
    comps = {"skills": skills if profile.skills else None, "semantic": sem, "role": _role_score(job.title, criteria.roles),
             "experience": _exp_score(job, profile.years_experience), "education": _edu_score(job, profile),
             "location": _loc_score(job, criteria)}
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(w[k] for k in avail)
    score = round(100 * sum(w[k] * v for k, v in avail.items()) / wsum, 1) if wsum else 0.0
    notes = []
    if not profile.skills:
        notes.append("No resume/skills provided: score reflects role relevance and available job text only")
    if matched:
        notes.append(f"Matches {len(matched)} listed skill(s): {', '.join(matched)}")
    if missing:
        notes.append(f"Missing required skill(s): {', '.join(missing)}")
    if not req:
        notes.append("No required skills could be detected in the listing text")
    return MatchResult(job_id=job.job_id, score=score, breakdown={k: (round(v, 3) if v is not None else None) for k, v in comps.items()},
                       matched_skills=matched, missing_skills=missing, required_skills=req, preferred_skills=pref,
                       explanation=". ".join(notes), similarity_backend=backend)


def match_all(jobs: list[JobListing], profile: CandidateProfile, criteria: SearchCriteria) -> dict[str, MatchResult]:
    return {j.job_id: match_job(j, profile, criteria) for j in jobs}
