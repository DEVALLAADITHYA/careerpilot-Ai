import io
from datetime import datetime, timezone

import fitz
import httpx
import pytest

from app.agents import job_search_agent, matching_agent, supervisor
from app.agents.report_agent import rank, to_csv
from app.config import Settings
from app.models.schemas import (CandidateProfile, JobListing, JobResult, SearchCriteria, SearchRequest,
                                VerificationResult, VerificationStatus)
from app.tools import web_search
from app.tools.resume_parser import ResumeError, extract_text, parse_profile
from app.tools.url_safety import UnsafeURLError, check_url
from app.tools.webpage_verifier import assess, verify_url
from app.utils.text import dedupe_jobs, job_id_for, normalize_url


def mk(url, title="AI Engineer", company="Acme", desc="Python RAG fresher", loc=None):
    return JobListing(job_id=job_id_for(url), title=title, company=company, description=desc, source_url=url, location=loc)


# ---- URL validation ----
@pytest.mark.parametrize("u", ["http://127.0.0.1/x", "http://169.254.169.254/latest", "ftp://example.com", "http://10.0.0.5",
                               "https://user:pw@8.8.8.8/", "http://8.8.8.8:8080/", "http://localhost/", "http://[::1]/"])
def test_unsafe_urls_rejected(u):
    with pytest.raises(UnsafeURLError):
        check_url(u)


def test_public_url_ok():
    assert check_url("https://8.8.8.8/jobs") == "https://8.8.8.8/jobs"
    assert check_url("https://x.com/", resolver=lambda h, p: [(0, 0, 0, "", ("93.184.216.34", 0))])


def test_dns_to_private_rejected():
    with pytest.raises(UnsafeURLError):
        check_url("https://evil.com/", resolver=lambda h, p: [(0, 0, 0, "", ("192.168.1.1", 0))])


# ---- dedup ----
def test_dedupe_by_url_and_identity():
    a = mk("https://www.x.com/jobs/1?utm_source=a")
    b = mk("https://x.com/jobs/1/")
    c = mk("https://other.com/j/9")           # same title/company/location, different URL
    d = mk("https://other.com/j/10", title="ML Engineer")
    out = dedupe_jobs([a, b, c, d])
    assert [j.source_url for j in out] == [a.source_url, d.source_url] or len(out) == 2
    assert normalize_url(a.source_url) == normalize_url(b.source_url)


# ---- matching ----
def test_match_score_and_missing_skills():
    job = mk("https://x.com/1", desc="Required: Python, RAG, Docker. Preferred: AWS. Fresher welcome.")
    prof = CandidateProfile(skills=["python", "rag"], education=["B.Tech"])
    r = matching_agent.match_job(job, prof, SearchCriteria(roles=["AI Engineer"]))
    assert r.missing_skills == ["docker"] and r.matched_skills == ["python", "rag"]
    assert r.required_skills == ["docker", "python", "rag"] and r.preferred_skills == ["aws"]
    assert 0 < r.score <= 100
    assert r.score == matching_agent.match_job(job, prof, SearchCriteria(roles=["AI Engineer"])).score  # deterministic
    better = matching_agent.match_job(job, CandidateProfile(skills=["python", "rag", "docker"]), SearchCriteria(roles=["AI Engineer"]))
    assert better.score > r.score


def test_match_without_profile_is_explained():
    r = matching_agent.match_job(mk("https://x.com/1"), CandidateProfile(), SearchCriteria(roles=["AI Engineer"]))
    assert "No resume" in r.explanation


# ---- resume parsing ----
def make_pdf(text):
    d = fitz.open()
    d.new_page().insert_text((50, 72), text)
    return d.tobytes()


def test_resume_parse():
    txt = "Jane Doe\nSkills\nPython, FastAPI, RAG\nEducation\nB.Tech Computer Science\nProjects\nChatbot using LangGraph"
    p = parse_profile(extract_text(make_pdf(txt)))
    assert {"python", "fastapi", "rag", "langgraph"} <= set(p.skills)
    assert p.years_experience == 0.0  # never inferred


def test_resume_rejects_non_pdf():
    with pytest.raises(ResumeError):
        extract_text(b"not a pdf")


# ---- verification status ----
OPEN = "<html><h1>AI Engineer</h1><a>Apply now</a></html>"


def test_assess_statuses():
    career = "https://boards.greenhouse.io/acme/jobs/1"
    assert assess(200, OPEN, career, "AI Engineer")[0] == VerificationStatus.VERIFIED_OPEN
    assert assess(200, OPEN, "https://random-blog.com/p", "AI Engineer")[0] == VerificationStatus.LIKELY_OPEN
    assert assess(200, "<p>hello</p>", career, "AI Engineer")[0] == VerificationStatus.UNCERTAIN
    assert assess(200, "<p>This job has expired</p> Apply now", career, "AI Engineer")[0] == VerificationStatus.EXPIRED
    assert assess(404, "", career)[0] == VerificationStatus.EXPIRED
    assert assess(403, "", career)[0] == VerificationStatus.INACCESSIBLE
    past = '<script type="application/ld+json">{"@type":"JobPosting","validThrough":"2020-01-01"}</script>'
    assert assess(200, past, career, "AI Engineer")[0] == VerificationStatus.EXPIRED
    # a reachable page alone is never "verified open"
    assert assess(200, "<p>AI Engineer</p>", career, "AI Engineer")[0] != VerificationStatus.VERIFIED_OPEN


async def _ok(u):
    return u


async def test_verify_follows_redirects_and_blocks_unsafe():
    def handler(req: httpx.Request):
        if req.url.path == "/old":
            return httpx.Response(302, headers={"location": "/jobs/1"})
        if req.url.path == "/ssrf":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
        return httpx.Response(200, text=OPEN, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        r = await verify_url("1", "https://careers.acme.com/old", "AI Engineer", client=c, validator=_ok)
        assert r.status == VerificationStatus.VERIFIED_OPEN and r.final_url.endswith("/jobs/1")
        from app.tools.url_safety import check_url_async
        r2 = await verify_url("2", "https://careers.acme.com/ssrf", client=c,
                              validator=lambda u: check_url_async(u) if "169" in u else _ok(u))
        assert r2.status == VerificationStatus.INACCESSIBLE and "unsafe" in r2.evidence[0]


# ---- supervisor routing + retry limits ----
def _v(status):
    return VerificationResult(job_id="x", url="u", status=status)


def test_supervisor_routing():
    s = Settings(max_iterations=2, min_good_jobs=2)
    good = {str(i): _v(VerificationStatus.VERIFIED_OPEN) for i in range(2)}
    assert supervisor.decide_next({"verifications": good, "iteration": 1}, s)[0] == "advise"
    assert supervisor.decide_next({"verifications": {}, "iteration": 1}, s)[0] == "search"
    assert supervisor.decide_next({"verifications": {}, "iteration": 2}, s)[0] == "advise"   # bounded
    assert supervisor.decide_next({"verifications": {}, "iteration": 0, "search_failed": True}, s)[0] == "advise"


async def test_search_retry_is_bounded(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(web_search.SearchError):
            await web_search.tavily_search("q", client=c, retries=2, backoff_base=0)
    assert len(calls) == 3


async def test_tavily_missing_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: None)
    with pytest.raises(web_search.SearchError, match="TAVILY_API_KEY"):
        await web_search.tavily_search("q")


async def test_parse_request_overrides_without_llm(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    c = await supervisor.parse_request(SearchRequest(query="fresher GenAI Engineer in Hyderabad", role="AI Intern", work_mode="remote"))
    assert c.roles[0] == "AI Intern" and c.work_mode == "remote" and c.parsed_by == "rule_based"
    assert c.location == "Hyderabad"


def test_csv_neutralises_formulas():
    j = mk("https://x.com/1", title="=HYPERLINK(\"evil\")")
    assert "'=HYPERLINK" in to_csv([JobResult(job=j)])


def test_rank_puts_verified_first():
    a, b = mk("https://x.com/a"), mk("https://x.com/b")
    ra = JobResult(job=a, verification=_v(VerificationStatus.EXPIRED))
    rb = JobResult(job=b, verification=_v(VerificationStatus.VERIFIED_OPEN))
    assert rank([ra, rb])[0].job.job_id == b.job_id


def test_result_to_job_does_not_fabricate():
    r = {"url": "https://x.com/careers/ai", "title": "AI Engineer Intern", "content": "We are hiring. Apply today."}
    j = job_search_agent.result_to_job(r, "q", SearchCriteria(), datetime.now(timezone.utc))
    assert j.company is None and j.location is None and j.posted_date is None
    assert job_search_agent.result_to_job({"url": "https://x.com/blog", "title": "Cooking tips", "content": "pasta"}, "q", SearchCriteria(), datetime.now(timezone.utc)) is None


# ---- DuckDuckGo provider ----
def test_ddg_normalizes_results_and_timelimit(monkeypatch):
    import types
    seen = {}

    class FakeDDGS:
        def text(self, q, **kw):
            seen.update(kw)
            return [{"title": "T", "href": "https://x.com/j", "body": "B"}]

    import ddgs
    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    out = web_search._ddg_sync("q", 5, 7)
    assert out == [{"title": "T", "url": "https://x.com/j", "content": "B"}]
    assert seen["timelimit"] == "w" and seen["max_results"] == 5
    assert web_search._timelimit(None) is None and web_search._timelimit(30) == "m" and web_search._timelimit(90) == "y"


async def test_ddg_retry_is_bounded(monkeypatch):
    calls = []

    def boom(q, n, d):
        calls.append(1)
        raise web_search.SearchError("rate limited")

    monkeypatch.setattr(web_search, "_ddg_sync", boom)
    with pytest.raises(web_search.SearchError):
        await web_search.ddg_search("q", retries=2, backoff_base=0)
    assert len(calls) == 3


def test_listing_index_page_is_never_verified_open():
    idx = "<h1>Internships</h1>" + "<a>Apply now</a>" * 6
    st, ev = assess(200, idx, "https://startups.example.com/jobs/fresher/internships", "AI Intern")
    assert st == VerificationStatus.UNCERTAIN and any("general jobs listing" in e for e in ev)
    posting = '<script type="application/ld+json">{"@type":"JobPosting"}</script><h1>AI Intern</h1><a>Apply now</a>'
    assert assess(200, posting, "https://careers.example.com/jobs/fresher/internships", "AI Intern")[0] == VerificationStatus.VERIFIED_OPEN


def test_split_weeks_and_role_gaps():
    from app.agents.career_advisor_agent import split_weeks
    from app.services.resume_analysis import role_gap_skills
    assert split_weeks(["Week 1: Learn A; Week 2: Learn B"]) == ["Week 1: Learn A", "Week 2: Learn B"]
    assert "docker" in role_gap_skills(["ML Engineer"], {"python"}) and "python" not in role_gap_skills(["ML Engineer"], {"python"})
