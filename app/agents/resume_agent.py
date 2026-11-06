"""Resume Intelligence Agent: PDF -> structured profile; validates/cleans user-corrected profiles."""
from __future__ import annotations

from app.models.schemas import CandidateProfile, SearchCriteria
from app.tools.resume_parser import extract_text, parse_profile
from app.utils.skills import canonicalize


def analyze_pdf(pdf_bytes: bytes) -> CandidateProfile:
    text = extract_text(pdf_bytes)  # raw text is discarded after parsing and never logged
    return parse_profile(text)


def clean_profile(p: CandidateProfile) -> CandidateProfile:
    skills = list(dict.fromkeys(canonicalize(s) for s in p.skills if s.strip()))
    return p.model_copy(update={"skills": skills})


def profile_for_search(p: CandidateProfile | None, criteria: SearchCriteria) -> CandidateProfile:
    """Uses the resume profile if present; otherwise only the skills the user explicitly typed."""
    if p:
        return clean_profile(p)
    return CandidateProfile(skills=[canonicalize(s) for s in criteria.skills], source="user_stated_skills")


def skill_gaps(p: CandidateProfile, target_skills: list[str]) -> dict[str, list[str]]:
    have = set(p.skills)
    return {"strengths": sorted(have & set(target_skills)), "missing": sorted(set(target_skills) - have)}
