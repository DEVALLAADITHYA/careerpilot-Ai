from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.models.schemas import (CandidateProfile, CareerAdvice, JobListing, MatchResult, Report, SearchCriteria,
                                SearchRequest, VerificationResult)


class WorkflowState(TypedDict, total=False):
    search_id: str
    request: SearchRequest
    criteria: SearchCriteria
    profile: CandidateProfile
    jobs: list[JobListing]
    matches: dict[str, MatchResult]
    verifications: dict[str, VerificationResult]
    advice: CareerAdvice
    report: Report
    iteration: int
    search_failed: bool
    next_step: str
    events: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
