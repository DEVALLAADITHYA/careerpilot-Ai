import pytest
from fastapi.testclient import TestClient

from app.database import repository as repo
from app.database.connection import session_scope
from app.main import create_app
from app.models.schemas import VerificationResult, VerificationStatus

RESULTS = [
    {"url": "https://boards.greenhouse.io/acme/jobs/1", "title": "GenAI Engineer - Acme", "content": "Fresher. Required: Python, RAG. Location: Hyderabad. Apply now"},
    {"url": "https://boards.greenhouse.io/acme/jobs/1?utm_source=x", "title": "GenAI Engineer - Acme", "content": "dup"},
    {"url": "https://globex.com/careers/ml", "title": "ML Engineer at Globex", "content": "hiring ML engineer, Python, Docker"},
]


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    async def fake_search(q, **kw):
        assert "days" in kw
        return RESULTS

    async def fake_verify(job_id, url, title=None, **kw):
        return VerificationResult(job_id=job_id, url=url, status=VerificationStatus.LIKELY_OPEN, evidence=["mock"])

    monkeypatch.setattr("app.agents.job_search_agent.web_search", fake_search)
    monkeypatch.setattr("app.agents.verification_agent.verify_url", fake_verify)
    with TestClient(create_app()) as c:
        yield c


def run(client, **extra):
    r = client.post("/api/search", json={"query": "fresher GenAI engineer in Hyderabad", **extra})
    assert r.status_code == 202
    sid = r.json()["search_id"]
    s = client.get(f"/api/search/{sid}").json()
    assert s["status"] == "completed", s
    return sid, s


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_full_workflow_and_persistence(client):
    sid, s = run(client, profile={"skills": ["python"], "education": ["B.Tech"]})
    rep = client.get(f"/api/reports/{s['report_id']}").json()
    assert len(rep["results"]) == 2                     # duplicates removed
    assert all(r["verification"]["status"] == "likely_open" for r in rep["results"])
    agents = {e["agent"] for e in s["events"]}
    assert {"supervisor", "job_search_agent", "matching_agent", "verification_agent", "career_advisor_agent", "report_agent"} <= agents
    assert "job_id,title" not in rep["csv"] and rep["csv"].startswith("title,company")
    jobs = client.get("/api/jobs", params={"limit": 1}).json()
    assert jobs["total"] == 2 and len(jobs["items"]) == 1
    assert client.get("/api/dashboard").json()["total_jobs"] == 2


def test_save_and_track_application(client):
    run(client)
    jid = client.get("/api/jobs").json()["items"][0]["job"]["job_id"]
    assert client.post("/api/jobs/save", json={"job_id": jid}).status_code == 201
    assert client.post("/api/jobs/save", json={"job_id": "nope"}).status_code == 404
    apps = client.get("/api/applications").json()
    assert apps["total"] == 1
    aid = apps["items"][0]["id"]
    r = client.patch(f"/api/applications/{aid}", json={"status": "Applied", "applied_date": "2026-10-16", "notes": "referral"})
    assert r.json()["status"] == "Applied"
    assert client.patch(f"/api/applications/{aid}", json={"status": "Bogus"}).status_code == 422
    assert client.get("/api/applications", params={"status": "Applied", "q": "refer"}).json()["total"] == 1
    assert len(client.get("/api/jobs/saved").json()) == 1
    assert client.delete(f"/api/jobs/saved/{jid}").status_code == 200
    assert client.get("/api/applications").json()["total"] == 0


def test_persists_across_restart(db, client):
    run(client)
    jid = client.get("/api/jobs").json()["items"][0]["job"]["job_id"]
    client.post("/api/jobs/save", json={"job_id": jid})
    from app.database import connection
    connection.configure()  # simulate restart on the same DB file
    with session_scope() as s:
        assert len(repo.list_saved(s)) == 1


def test_match_and_verify_endpoints(client):
    run(client)
    ids = [i["job"]["job_id"] for i in client.get("/api/jobs").json()["items"]]
    m = client.post("/api/jobs/match", json={"profile": {"skills": ["python", "rag"]}, "job_ids": ids})
    assert m.status_code == 200 and m.json()[0]["score"] >= m.json()[-1]["score"]
    v = client.post("/api/jobs/verify", json={"job_ids": ids})
    assert v.status_code == 200 and v.json()[0]["status"] == "likely_open"
    assert client.post("/api/jobs/verify", json={"job_ids": []}).status_code == 422


def test_resume_upload_validation(client):
    import fitz
    d = fitz.open(); d.new_page().insert_text((50, 72), "Jane Doe\nSkills\nPython, RAG"); pdf = d.tobytes()
    ok = client.post("/api/resume/analyze", files={"file": ("cv.pdf", pdf, "application/pdf")})
    assert ok.status_code == 200 and "python" in ok.json()["skills"]
    assert client.post("/api/resume/analyze", files={"file": ("cv.txt", b"hi", "text/plain")}).status_code == 415
    assert client.post("/api/resume/analyze", files={"file": ("cv.pdf", b"not pdf", "application/pdf")}).status_code == 422


def test_tavily_provider_without_key_fails_clearly(client, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: None)
    r = client.post("/api/search", json={"query": "ai engineer"})
    assert r.status_code == 503 and "TAVILY_API_KEY" in r.json()["detail"]


def test_search_api_outage_is_reported_not_faked(client, monkeypatch):
    from app.tools.web_search import SearchError

    async def boom(q, **kw):
        raise SearchError("Tavily returned HTTP 429 (rate limit / quota reached)")

    monkeypatch.setattr("app.agents.job_search_agent.web_search", boom)
    _, s = run(client)
    rep = client.get(f"/api/reports/{s['report_id']}").json()
    assert rep["results"] == [] and any("429" in n for n in rep["incomplete_notes"])
    assert not any(e["event"] == "retry_triggered" for e in s["events"])


def test_retry_when_too_few_good_jobs(client, monkeypatch):
    async def none(job_id, url, title=None, **kw):
        return VerificationResult(job_id=job_id, url=url, status=VerificationStatus.UNCERTAIN)

    monkeypatch.setattr("app.agents.verification_agent.verify_url", none)
    _, s = run(client)
    searches = [e for e in s["events"] if e["event"] == "search_started"]
    assert len(searches) == 2                           # MAX_ITERATIONS default = 2, then stops
    assert any(e["event"] == "retry_triggered" for e in s["events"])
    assert client.get("/api/search/zzz").status_code == 404
    assert client.get("/api/reports/zzz").status_code == 404


def test_resume_compare(client):
    jd = "Required: Python, RAG, Docker, Kubernetes. Preferred: AWS."
    r = client.post("/api/resume/compare", data={"resume_text": "Jane Doe\nSkills\nPython, RAG, FastAPI\nProjects\nBuilt chatbot that cut response time by 40%", "job_description": jd})
    assert r.status_code == 200
    d = r.json()
    assert d["match"]["matched"] == ["python", "rag"] and d["match"]["missing"] == ["docker", "kubernetes"]
    assert d["match"]["preferred_missing"] == ["aws"] and d["roles"][0]["fit"] > 0
    assert {c["skill"]: c["have"] for c in d["coverage"]}["docker"] is False
    assert not any("Quantify" in x for x in d["recommendations"])
    d2 = client.post("/api/resume/compare", data={"resume_text": "Skills: python " * 5}).json()
    assert d2["match"] is None and d2["skills_found"] == 1      # no JD -> no fake score
    assert client.post("/api/resume/compare", files={"file": ("cv.txt", b"Skills\nPython SQL and more text here to be long enough", "text/plain")}).status_code == 200
    assert client.post("/api/resume/compare", files={"file": ("cv.docx", b"x" * 50, "application/x")}).status_code == 415
    assert client.post("/api/resume/compare", data={"resume_text": "hi"}).status_code == 422


def test_roadmap_comes_with_resume_analysis(client):
    d = client.post("/api/resume/compare", data={"resume_text": "Jane Doe\nSkills\nPython, RAG\nProjects\nChatbot", "job_description": "Required: Python, Docker, Kubernetes. Preferred: AWS."}).json()
    assert d["roadmap_target"] == "Pasted job description"
    assert d["roadmap"]["skills_to_learn"] == ["docker", "kubernetes", "aws"]
    assert d["roadmap"]["weekly_plan"][0].startswith("Week 1: Learn docker")
    d2 = client.post("/api/resume/compare", data={"resume_text": "Jane Doe\nSkills\nPython, RAG, LangChain\nProjects\nBot"}).json()
    assert "best-fit role" in d2["roadmap_target"] and d2["roadmap"]["skills_to_learn"]


def test_mark_applied_tracker(client):
    run(client)
    jid = client.get("/api/jobs").json()["items"][0]["job"]["job_id"]
    assert client.post("/api/jobs/save", json={"job_id": jid, "status": "Applied"}).status_code == 201
    a = client.get("/api/applications").json()["items"][0]
    assert a["status"] == "Applied" and len(a["applied_date"]) == 10
    client.post("/api/jobs/save", json={"job_id": jid})            # plain re-save must not reset status
    assert client.get("/api/applications").json()["items"][0]["status"] == "Applied"


def test_page_text_enriches_and_rescores(client, monkeypatch):
    async def rich(job_id, url, title=None, **kw):
        return VerificationResult(job_id=job_id, url=url, status=VerificationStatus.LIKELY_OPEN, page_kind="single_posting",
                                  page_excerpt="Requirements: Python, Docker, Kubernetes. Preferred: AWS.")

    monkeypatch.setattr("app.agents.verification_agent.verify_url", rich)
    _, s = run(client, profile={"skills": ["python"]})
    rep = client.get(f"/api/reports/{s['report_id']}").json()
    assert all("docker" in r["match"]["missing_skills"] for r in rep["results"])
    assert "re-scored" in [e for e in s["events"] if e["event"] == "verification_evidence_collected"][0]["detail"]
