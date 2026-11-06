"""Verification Agent: concurrent, bounded, SSRF-safe checks of the most promising listings."""
from __future__ import annotations

import asyncio
import logging

from app.models.schemas import JobListing, MatchResult, VerificationResult
from app.tools.webpage_verifier import verify_url

log = logging.getLogger(__name__)


def pick_candidates(jobs: list[JobListing], matches: dict[str, MatchResult], done: set[str], top_n: int) -> list[JobListing]:
    todo = [j for j in jobs if j.job_id not in done]
    todo.sort(key=lambda j: matches[j.job_id].score if j.job_id in matches else 0, reverse=True)
    return todo[:top_n]


async def verify_jobs(jobs: list[JobListing], concurrency: int = 5) -> dict[str, VerificationResult]:
    sem = asyncio.Semaphore(concurrency)

    async def one(j: JobListing):
        async with sem:
            return j.job_id, await verify_url(j.job_id, j.application_url or j.source_url, j.title)

    return dict(await asyncio.gather(*(one(j) for j in jobs)))
