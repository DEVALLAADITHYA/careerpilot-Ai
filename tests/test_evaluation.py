import pytest
from app.services import evaluation as ev


def test_metrics():
    assert ev.duplicate_rate(["https://a.com/x", "https://www.a.com/x/", "https://b.com"]) == pytest.approx(1 / 3)
    assert ev.verification_precision({"1": "verified_open", "2": "verified_open", "3": "uncertain"}, {"1": True, "2": False, "3": True})["precision"] == 0.5
    assert ev.verification_precision({}, {})["precision"] is None
    assert ev.score_consistency([[50.0, 60.0], [50.0, 60.0]]) == 0.0
    assert ev.api_failure_rate(0, 0) is None
