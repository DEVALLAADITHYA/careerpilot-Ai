"""Evaluation metrics. Values are only reported when computed from real data you supply."""
from __future__ import annotations

import statistics

from app.utils.text import normalize_url


def duplicate_rate(urls: list[str]) -> float:
    norm = [normalize_url(u) for u in urls]
    return 0.0 if not norm else 1 - len(set(norm)) / len(norm)


def search_relevance(titles: list[str], role_keywords: list[str]) -> float:
    """Share of results whose title contains any target keyword (a proxy; manual review is better)."""
    if not titles:
        return 0.0
    return sum(any(k.lower() in t.lower() for k in role_keywords) for t in titles) / len(titles)


def link_accessibility(statuses: list[str]) -> float:
    return 0.0 if not statuses else 1 - statuses.count("inaccessible") / len(statuses)


def verification_precision(predicted: dict[str, str], truth: dict[str, bool]) -> dict:
    """Precision of 'verified_open' against manually reviewed ground truth {job_id: is_actually_open}."""
    pos = [j for j, s in predicted.items() if s == "verified_open" and j in truth]
    tp = sum(truth[j] for j in pos)
    return {"verified_predictions": len(pos), "precision": (tp / len(pos)) if pos else None}


def score_consistency(scores_runs: list[list[float]]) -> float | None:
    """Max std-dev of a job's score across repeated runs (0 = perfectly consistent)."""
    per_job = list(zip(*scores_runs))
    return max((statistics.pstdev(x) for x in per_job), default=None)


def api_failure_rate(total_calls: int, failed_calls: int) -> float | None:
    return failed_calls / total_calls if total_calls else None
