from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VerificationStatus(str, Enum):
    VERIFIED_OPEN = "verified_open"
    LIKELY_OPEN = "likely_open"
    UNCERTAIN = "uncertain"
    EXPIRED = "expired_or_closed"
    INACCESSIBLE = "inaccessible"
    NOT_CHECKED = "not_checked"


STATUS_LABEL = {
    "verified_open": "Verified open",
    "likely_open": "Likely open, not fully confirmed",
    "uncertain": "Uncertain",
    "expired_or_closed": "Expired or closed",
    "inaccessible": "Inaccessible",
    "not_checked": "Not checked",
}

ApplicationStatus = Literal["Interested", "Applied", "Assessment", "Interview", "Offer", "Rejected"]


class SearchCriteria(BaseModel):
    roles: list[str] = Field(default_factory=list)
    location: str | None = None
    experience_level: str = "fresher"
    skills: list[str] = Field(default_factory=list)
    work_mode: Literal["remote", "hybrid", "onsite"] | None = None
    recency_days: int | None = None
    raw_query: str = ""
    parsed_by: str = "rule_based"  # "llm_tool_call" | "rule_based"


class CandidateProfile(BaseModel):
    name: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    years_experience: float = 0.0  # only set when stated explicitly in the resume
    source: str = "resume"


class JobListing(BaseModel):
    job_id: str
    title: str
    company: str | None = None
    location: str | None = None
    experience_required: str | None = None
    posted_date: str | None = None
    description: str = ""
    source_url: str
    application_url: str | None = None
    source_domain: str = ""
    search_query: str = ""
    searched_at: datetime = Field(default_factory=utcnow)


class MatchResult(BaseModel):
    job_id: str
    score: float
    breakdown: dict[str, float | None] = Field(default_factory=dict)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    explanation: str = ""
    similarity_backend: str = ""


class VerificationResult(BaseModel):
    job_id: str
    url: str
    status: VerificationStatus = VerificationStatus.NOT_CHECKED
    http_status: int | None = None
    final_url: str | None = None
    source_kind: str = "unknown"
    evidence: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utcnow)
    page_kind: str = "unknown"  # single_posting | listing_index | unknown
    page_excerpt: str = ""  # first ~3000 chars of page text (display + skill detection only)


class JobResult(BaseModel):
    job: JobListing
    match: MatchResult | None = None
    verification: VerificationResult | None = None


class InterviewQA(BaseModel):
    question: str
    sample_answer: str | None = None


class CareerAdvice(BaseModel):
    source: str = "rule_based"  # AI-generated advice is labelled; it is not verified fact
    skills_to_learn: list[str] = Field(default_factory=list)
    weekly_plan: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    interview_questions: list[InterviewQA] = Field(default_factory=list)
    evidence_job_ids: list[str] = Field(default_factory=list)


class AgentEvent(BaseModel):
    agent: str
    event: str
    detail: str = ""
    ts: datetime = Field(default_factory=utcnow)


class Report(BaseModel):
    report_id: str
    search_id: str
    criteria: SearchCriteria
    results: list[JobResult] = Field(default_factory=list)
    advice: CareerAdvice | None = None
    incomplete_notes: list[str] = Field(default_factory=list)
    csv: str = ""
    markdown: str = ""
    generated_at: datetime = Field(default_factory=utcnow)


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    role: str | None = Field(None, max_length=100)
    location: str | None = Field(None, max_length=100)
    experience_level: str | None = Field(None, max_length=30)
    work_mode: Literal["remote", "hybrid", "onsite"] | None = None
    recency_days: int | None = Field(None, ge=1, le=365)
    profile: CandidateProfile | None = None


class MatchRequest(BaseModel):
    profile: CandidateProfile
    job_ids: list[str] = Field(min_length=1, max_length=50)
    roles: list[str] = Field(default_factory=list)
    location: str | None = None


class VerifyRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=20)


class SaveJobRequest(BaseModel):
    job_id: str
    status: ApplicationStatus | None = None  # e.g. "Applied" to log an external application
    applied_date: str | None = Field(None, max_length=10)


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    applied_date: str | None = Field(None, max_length=10)
    notes: str | None = Field(None, max_length=2000)
