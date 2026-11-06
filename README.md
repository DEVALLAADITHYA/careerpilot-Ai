<div align="center">

# 🧭 CareerPilot AI

**Multi-Agent Career & Job Intelligence System**

Live job search · explainable resume matching · evidence-based job verification · automatic skill roadmap

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-purple) ![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688) ![Streamlit](https://img.shields.io/badge/Streamlit-UI-ff4b4b) ![Tests](https://img.shields.io/badge/tests-42%20passing-brightgreen)

</div>

## Overview

CareerPilot AI is a **multi-agent system built on LangGraph** that finds real job listings on the live web, scores each one against your resume, checks whether the job is actually open, and generates a personalised learning roadmap for the skills you are missing.

It is designed around one rule: **the LLM never writes job data.** Listings come only from search results, unknown fields stay empty, scores come from a documented formula, and a job is marked *Verified open* only when page evidence supports it.

### Features

- 🔍 **Natural-language job search**: "fresher GenAI engineer in Hyderabad" becomes structured criteria (Groq tool calling, with a rule-based fallback).
- 📄 **Resume Analyzer**: upload a PDF/TXT or paste text, paste a job description, and get a match score, skill gaps, best-fit roles and recommendations.
- ✅ **Job verification with evidence**: *Verified open*, *Likely open*, *Uncertain*, *Expired/Closed* or *Inaccessible*, with the reasons shown.
- 🗺️ **Automatic career roadmap**: weekly plan, projects and interview questions generated from your resume-vs-JD gaps.
- 🗂️ **Application tracker**: save jobs, mark them applied, and track Interview / Offer / Rejected with notes (persisted in the database).
- 🤖 **Live agent activity**: every event in the UI is written by a graph node as it actually runs.

## Architecture

```mermaid
flowchart LR
  UI[Streamlit UI] -->|REST| API[FastAPI]
  API -->|background task| G[LangGraph workflow]
  G --> DB[(SQLite / PostgreSQL)]
  G --> S[Web search: DuckDuckGo or Tavily]
  G --> L[Groq LLM]
  G --> W[Job pages - safe fetch]
```

### Agent workflow

```mermaid
flowchart TD
  plan[Supervisor: parse request] --> resume[Resume agent: build profile]
  resume --> search[Job Search agent]
  search --> match[Matching agent]
  match --> verify[Verification agent]
  verify --> review{Supervisor review}
  review -- too few good jobs and rounds left --> search
  review -- otherwise --> advise[Career Advisor agent]
  advise --> report[Report agent]
  report --> END((Done))
```

| # | Agent | Responsibility | Tools / method |
|---|---|---|---|
| 1 | **Supervisor** | Parses the request, reviews result quality, routes (re-search or continue), capped retries | Groq tool calling; rule-based fallback |
| 2 | **Job Search** | Concurrent live searches, filters non-job pages, de-duplicates | DuckDuckGo (`ddgs`) or Tavily |
| 3 | **Resume** | PDF/text to structured profile; never infers missing facts | PyMuPDF + skill vocabulary |
| 4 | **Matching** | Transparent weighted score and skill gaps | Rules + cosine similarity |
| 5 | **Verification** | Safe page fetch, evidence-based status, re-scoring from real page text | httpx, SSRF guard |
| 6 | **Career Advisor** | Skills to learn, weekly plan, projects, interview questions (labelled AI-generated) | Groq JSON mode; rule-based fallback |
| 7 | **Report** | Ranks results (verified first), CSV export | Pure Python |

### Match score

`score = 100 × Σ wᵢ·cᵢ / Σ wᵢ` over the components that have data (missing components are dropped and the weights re-balanced).

| Component | Default weight |
|---|---|
| Skills (required = 1.0, preferred = 0.5) | 0.40 |
| Semantic similarity | 0.20 |
| Role / title relevance | 0.15 |
| Experience fit | 0.10 |
| Location fit | 0.10 |
| Education fit | 0.05 |

Weights are configurable through `MATCH_WEIGHTS`. This is an interpretable heuristic, **not** a probability of getting hired.

### Verification statuses

| Status | Meaning |
|---|---|
| 🟢 Verified open | HTTP 200 + official/ATS source + apply option + job title on page + no closed wording |
| 🟡 Likely open | Apply evidence found but not fully confirmed (e.g. a job board) |
| 🟠 Uncertain | Page reachable but no clear evidence, or it is a general jobs index rather than one posting |
| 🔴 Expired / Closed | 404/410, closed wording, or a past `validThrough` date |
| ⚫ Inaccessible | Blocked or unreachable. **Not** treated as closed |

Web pages are only pattern-matched and never sent to an LLM, which protects against prompt injection.

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Orchestration | **LangGraph** | Typed state, conditional edges, bounded retry loop |
| LLM | **Groq** (Llama 3.3 70B) | Fast, free tier, tool calling |
| Search | **DuckDuckGo (`ddgs`)** default, **Tavily** optional | Free, no key / structured AI-search API |
| Backend | **FastAPI** + Pydantic | Async, validated schemas, auto docs |
| Frontend | **Streamlit** | Fast Python UI with live progress polling |
| Resume parsing | **PyMuPDF** | Reliable PDF text extraction |
| Similarity | **Sentence Transformers** (optional) / lexical cosine fallback | Semantic matching |
| Database | **SQLAlchemy** + SQLite / PostgreSQL | Persistence for jobs, matches, verifications, applications, events |
| HTTP | **httpx** | Async, timeouts, manual redirect control |
| Testing | **pytest** | 42 tests with mocked external services |

## Getting started

### 1. Clone and install

**Windows (Command Prompt):**
```bat
git clone https://github.com/<your-username>/careerpilot-ai.git
cd careerpilot-ai
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
```

**macOS / Linux / PowerShell:**
```bash
python -m venv .venv && source .venv/bin/activate    # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                  # PowerShell: Copy-Item .env.example .env
```

### 2. Configure `.env`

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | – | Optional. Without it, parsing and advice use rule-based fallbacks |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Must support tool calling |
| `SEARCH_PROVIDER` | `duckduckgo` | `duckduckgo` (no key) or `tavily` |
| `TAVILY_API_KEY` | – | Required only when `SEARCH_PROVIDER=tavily` |
| `DATABASE_URL` | `sqlite:///./careerpilot.db` | PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/db` |
| `MAX_ITERATIONS` | `2` | Max search rounds |
| `MIN_GOOD_JOBS` | `3` | Verified/likely-open jobs needed before stopping |
| `VERIFY_TOP_N` | `10` | Listings verified per round |
| `MAX_PDF_MB` / `RATE_LIMIT_PER_MIN` | `5` / `30` | Upload and rate limits |
| `USE_SENTENCE_TRANSFORMERS` | `0` | `1` enables embeddings (`pip install sentence-transformers`) |
| `MATCH_WEIGHTS` | built-in | JSON override of the scoring weights |

Never commit `.env`; it is already in `.gitignore`.

### 3. Run

```bat
:: Terminal 1: API
uvicorn app.main:app --port 8000

:: Terminal 2: UI (run from the project root)
streamlit run frontend\streamlit_app.py
```

- UI: http://localhost:8501
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### 4. Test

```bash
pytest -q
```

## Using the app

1. **Resume Analyzer**: upload a resume, paste a job description, click *Analyze Resume*. This gives the match score, gaps, role fit and a roadmap, and saves your profile for searches.
2. **Job Search**: describe what you want, search, and watch the agents work live.
3. **Job Results**: sort and filter, open *View details* for the match breakdown and verification evidence, then *Save* or *Mark as applied*.
4. **Career Roadmap**: generated automatically from your analysis or search results.
5. **Applications**: applications happen on external sites, so this is your personal log. Mark jobs as applied, then update the status and notes as things progress.

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Service and search-provider status |
| POST | `/api/search` | Start a search (returns `search_id`, runs in background) |
| GET | `/api/search/{id}` | Status and live agent events |
| POST | `/api/resume/analyze` | Parse a PDF resume into a profile |
| POST | `/api/resume/compare` | Resume (file or text) + job description: score, gaps, roles, roadmap |
| POST | `/api/jobs/match` | Score stored jobs against a profile |
| POST | `/api/jobs/verify` | Verify stored jobs |
| GET | `/api/jobs` | List jobs with match and verification (paginated) |
| POST | `/api/jobs/save` | Save a job and/or log a status (e.g. `Applied`) |
| GET / DELETE | `/api/jobs/saved`, `/api/jobs/saved/{id}` | List / remove saved jobs |
| GET / PATCH | `/api/applications`, `/api/applications/{id}` | Tracker list and updates |
| GET | `/api/reports/{id}`, `/api/reports/{id}/csv` | Full report / CSV download |
| GET | `/api/dashboard` | Dashboard statistics |

```bash
curl -X POST http://localhost:8000/api/search -H "Content-Type: application/json" \
  -d '{"query": "fresher GenAI engineer in Hyderabad"}'
```

## Project structure

```
careerpilot-ai/
├── app/
│   ├── main.py                  # FastAPI app
│   ├── config.py                # env-based settings
│   ├── agents/                  # supervisor, job_search, resume, matching,
│   │                            # verification, career_advisor, report
│   ├── graph/                   # LangGraph state + workflow
│   ├── tools/                   # web_search, webpage_verifier, resume_parser, url_safety
│   ├── services/                # llm, semantic similarity, resume analysis, evaluation
│   ├── database/                # SQLAlchemy models, connection, repository
│   ├── api/routes/              # REST endpoints
│   └── models/schemas.py        # Pydantic schemas
├── frontend/streamlit_app.py    # UI
├── .streamlit/config.toml       # light theme
├── scripts/evaluate.py          # evaluation metrics on your data
├── tests/                       # pytest suite (mocked external APIs)
├── requirements.txt
└── .env.example
```

## Security and reliability

- **SSRF protection**: only public `http/https` on ports 80/443; credentials in URLs rejected; every redirect hop re-validated (max 5); 400 KB response cap.
- **Prompt-injection safe**: page text is never sent to an LLM; text sent to the LLM is passed as data.
- **Resume privacy**: PDFs are parsed in memory; resume text is never stored or logged (only the structured profile is kept).
- **Hardening**: upload type/size/magic-byte checks, per-IP rate limiting, bounded retries, secrets only in environment variables, CSV formula-injection protection.
- **Honest failures**: if search or the LLM is unavailable, the app reports it clearly. It never substitutes fabricated data.

## Evaluation

`python scripts/evaluate.py report.json labels.json` computes duplicate rate, link accessibility and verification precision against labels you create by hand. `app/services/evaluation.py` also provides relevance, score-consistency and API-failure helpers. No accuracy numbers are claimed here; measure them on your own data.

## Limitations

- No authentication (single-user). Add auth and a `user_id` per record before multi-user hosting.
- DuckDuckGo search uses an unofficial library and can be rate-limited or change; switch to Tavily with `SEARCH_PROVIDER=tavily` if needed.
- JavaScript-rendered or login-walled sites (e.g. LinkedIn) usually end up *Inaccessible*.
- Job fields come from search snippets plus the fetched page, so company, location and posted date can be empty.
- DNS rebinding between URL validation and fetch is not fully closed (pin the resolved IP in a custom transport).
- "Best Matching Roles" is skill-profile overlap, not a trained model.
- Application tracking is manual because applications happen on external sites.
- No OCR for scanned PDFs, no PDF report export; progress uses polling, not SSE; background tasks run in-process.

## Roadmap ideas

Authentication and multi-user support · task queue (Celery/RQ) · SSE streaming · Playwright-based verification for JS pages · embeddings by default · email reminders for application follow-ups · PDF report export.

## Deployment

- **API:** Render / Railway / Fly.io. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set env vars and use a managed PostgreSQL `DATABASE_URL`. Run a single worker (the rate limiter is in-memory).
- **UI:** Streamlit Community Cloud with `frontend/streamlit_app.py` and the secret `API_URL=https://<your-api>`. Add the UI origin to the CORS list in `app/main.py`.
