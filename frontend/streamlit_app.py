"""CareerPilot AI - Streamlit UI. Run: streamlit run frontend/streamlit_app.py"""
import html
import json
import math
import hashlib
import os
import time
from collections import Counter
from urllib.parse import quote_plus

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
STATUSES = ["Interested", "Applied", "Assessment", "Interview", "Offer", "Rejected"]
VER = {  # key: (label, colour)
    "verified_open": ("Verified Open", "#16a34a"), "likely_open": ("Likely Open", "#d97706"),
    "uncertain": ("Uncertain", "#ea580c"), "expired_or_closed": ("Closed/Expired", "#dc2626"),
    "inaccessible": ("Inaccessible", "#6b7280"), "not_checked": ("Not Checked", "#94a3b8")}
PAGES = ["Dashboard", "Job Search", "Job Results", "Resume Analyzer", "Career Roadmap", "Saved Jobs",
         "Applications", "Agent Activity", "Settings"]
ICON = dict(zip(PAGES, ["🏠", "🔍", "📋", "📄", "🗺️", "🔖", "🗂️", "🤖", "⚙️"]))
esc = lambda x: html.escape(str(x if x is not None else ""))

st.set_page_config(page_title="CareerPilot AI", page_icon="🧭", layout="wide")
st.markdown("""<style>
#MainMenu, footer, header {visibility:hidden}
.stApp {background:#eef2fb}
.block-container {padding-top:1.2rem; max-width:1250px}
section[data-testid="stSidebar"] {background:linear-gradient(180deg,#0a1a3f,#0b2252); min-width:250px}
section[data-testid="stSidebar"] * {color:#cbd5e1}
div[role="radiogroup"] {gap:4px}
div[role="radiogroup"] label {padding:10px 14px; border-radius:10px; width:100%; cursor:pointer}
div[role="radiogroup"] label > div:first-child {display:none}
div[role="radiogroup"] label:has(input:checked) {background:#2563eb}
div[role="radiogroup"] label:has(input:checked) * {color:#fff !important; font-weight:600}
.logo {display:flex; align-items:center; gap:10px; font-size:1.25rem; font-weight:700; color:#fff; margin:6px 0 18px}
.logo span {background:#2563eb; border-radius:10px; padding:4px 8px}
.promo {margin-top:30px; padding:14px; border-radius:12px; background:rgba(255,255,255,.07); font-size:.85rem}
.promo b {color:#fff; display:block}
.topbar {display:flex; justify-content:flex-end; align-items:center; gap:10px; margin-bottom:6px}
.avatar {width:38px; height:38px; border-radius:50%; background:#2563eb; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700}
.who {line-height:1.1; font-size:.85rem; color:#0f172a} .who small {color:#64748b}
h1.pg {font-size:1.6rem; font-weight:800; color:#0f172a; margin:4px 0 2px}
p.sub {color:#64748b; margin:0 0 16px}
.card {background:#fff; border-radius:16px; padding:18px 20px; box-shadow:0 2px 10px rgba(15,23,42,.06); margin-bottom:14px; color:#0f172a}
.card h4 {margin:0 0 10px; font-size:1rem; color:#0f172a}
.metric small {color:#64748b} .metric .v {font-size:1.9rem; font-weight:800}
.badge {padding:3px 10px; border-radius:999px; font-size:.75rem; font-weight:600; white-space:nowrap}
.job {display:flex; gap:14px; align-items:center}
.logo-box {width:44px; height:44px; border-radius:10px; background:#e0e7ff; color:#3730a3; font-weight:800; display:flex; align-items:center; justify-content:center; flex:none}
.job .t {font-weight:700; font-size:1.02rem} .job .m {color:#64748b; font-size:.85rem}
.chip {display:inline-block; background:#e0e7ff; color:#3730a3; padding:3px 10px; border-radius:8px; font-size:.78rem; margin:2px 4px 2px 0}
.chip.miss {background:#fee2e2; color:#b91c1c}
.chip.ok {background:#dcfce7; color:#166534}
.kv {display:grid; grid-template-columns:130px 1fr; gap:4px 12px; font-size:.9rem} .kv b {color:#64748b; font-weight:600}
.sec {font-weight:700; margin:14px 0 6px; color:#0f172a}
.excerpt {background:#f8fafc; border-radius:10px; padding:10px 12px; font-size:.85rem; color:#334155; max-height:180px; overflow:auto}
.cbar {height:8px; border-radius:4px; background:#e2e8f0} .cbar div {height:8px; border-radius:4px; background:#2563eb}
.step {display:flex; flex-direction:column; align-items:center; font-size:.8rem; color:#64748b; flex:1}
.dot {width:26px; height:26px; border-radius:50%; background:#e2e8f0; display:flex; align-items:center; justify-content:center; color:#fff; font-size:.8rem; margin-bottom:4px}
.step.done .dot {background:#16a34a} .step.act .dot {background:#2563eb}
.ev {display:flex; gap:10px; padding:8px 0; border-bottom:1px solid #f1f5f9; font-size:.88rem}
.ev .d {width:10px; height:10px; border-radius:50%; margin-top:5px; flex:none}
.ev time {margin-left:auto; color:#94a3b8; font-size:.78rem}
table.tr {width:100%; border-collapse:collapse; font-size:.9rem} table.tr th {text-align:left; color:#64748b; font-weight:600; padding:8px}
table.tr td {padding:10px 8px; border-top:1px solid #f1f5f9}
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {border-radius:10px; background:#2563eb; color:#fff; border:0; font-weight:600}
.stButton>button:hover {background:#1d4ed8; color:#fff}
</style>""", unsafe_allow_html=True)


def call(method, path, quiet=False, **kw):
    try:
        r = httpx.request(method, API + path, timeout=kw.pop("timeout", 30), **kw)
    except httpx.HTTPError:
        if not quiet:
            st.error(f"Cannot reach the API at {API}. Start it with: uvicorn app.main:app --port 8000")
        return None
    if r.status_code >= 400:
        if not quiet:
            try:
                st.error(r.json().get("detail", r.text))
            except ValueError:
                st.error(r.text)
        return None
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def card(inner, cls=""):
    st.markdown(f'<div class="card {cls}">{inner}</div>', unsafe_allow_html=True)


def head(title, sub=""):
    st.markdown(f'<h1 class="pg">{esc(title)}</h1><p class="sub">{esc(sub)}</p>', unsafe_allow_html=True)


def badge(status):
    label, col = VER.get(status, VER["not_checked"])
    return f'<span class="badge" style="background:{col}22;color:{col}">{label}</span>'


def ring(score, size=52):
    score = score or 0
    r, c = 20, 2 * math.pi * 20
    col = "#16a34a" if score >= 75 else "#d97706" if score >= 50 else "#dc2626"
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 50 50"><circle cx="25" cy="25" r="{r}" fill="none" stroke="#e2e8f0" stroke-width="5"/>'
            f'<circle cx="25" cy="25" r="{r}" fill="none" stroke="{col}" stroke-width="5" stroke-linecap="round" stroke-dasharray="{c*score/100:.1f} {c:.1f}" transform="rotate(-90 25 25)"/>'
            f'<text x="25" y="29" text-anchor="middle" font-size="12" font-weight="700" fill="#0f172a">{score:.0f}%</text></svg>')


def donut(counts):
    total = sum(counts.values())
    if not total:
        return "<p style='color:#94a3b8'>No verified jobs yet.</p>"
    r, c, off, segs, legend = 40, 2 * math.pi * 40, 0.0, "", ""
    for k, v in counts.items():
        label, col = VER.get(k, VER["not_checked"])
        ln = c * v / total
        segs += f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{col}" stroke-width="14" stroke-dasharray="{ln:.1f} {c - ln:.1f}" stroke-dashoffset="{-off:.1f}" transform="rotate(-90 50 50)"/>'
        legend += f'<div style="font-size:.85rem"><span style="color:{col}">●</span> {label} <b style="float:right;margin-left:24px">{v}</b></div>'
        off += ln
    return (f'<div style="display:flex;align-items:center;gap:24px"><svg width="150" height="150" viewBox="0 0 100 100">{segs}'
            f'<text x="50" y="48" text-anchor="middle" font-size="14" font-weight="800">{total}</text><text x="50" y="60" text-anchor="middle" font-size="6" fill="#64748b">Total</text></svg><div>{legend}</div></div>')


def job_card(r, key, saveable=True):
    j, m, v = r["job"], r.get("match"), r.get("verification")
    st_key = v["status"] if v else "not_checked"
    sub = " • ".join(esc(x) for x in [j.get("company") or "Company unknown", j.get("location") or "Location not stated", j.get("experience_required")] if x)
    meta = f'Posted: {esc(j.get("posted_date") or "date not stated")} • Source: {esc(j.get("source_domain"))}'
    card(f'<div class="job"><div class="logo-box">{esc((j.get("company") or j.get("source_domain") or "?")[:1].upper())}</div>'
         f'<div style="flex:1"><div class="t">{esc(j["title"])}</div><div class="m">{sub}</div><div class="m">{meta}</div></div>'
         f'<div style="text-align:right">{badge(st_key)}</div>{ring(m["score"]) if m else ""}</div>')
    c = st.columns([1, 1.5, 1.6, 4])
    if saveable and c[0].button("Save", key="sv" + key):
        if call("POST", "/api/jobs/save", json={"job_id": j["job_id"]}):
            st.toast("Saved")
    if saveable and c[1].button("Mark as applied", key="ap" + key, help="Log that you applied on the external site"):
        if call("POST", "/api/jobs/save", json={"job_id": j["job_id"], "status": "Applied"}):
            st.toast("Logged as Applied in your tracker")
    c[2].link_button("Open listing ↗", j.get("application_url") or j["source_url"])
    with st.expander("View details"):
        details(j, m, v)


COMP = {"skills": "Skill match", "semantic": "Text similarity", "role": "Title relevance", "experience": "Experience fit",
        "education": "Education fit", "location": "Location fit"}
KIND = {"official": "company careers page", "ats": "applicant-tracking-system page", "aggregator": "job board (aggregator)", "unknown": "unrecognised site"}
WHY = {"verified_open": "An official/ATS page loaded, shows an apply option and the job title, and has no closed wording.",
       "likely_open": "The page loaded and shows apply wording, but it is not an official source or something is missing, so it is not fully confirmed.",
       "uncertain": "The page loaded, but there is no clear sign that this exact job is open.",
       "expired_or_closed": "The page says the job is closed or expired, or no longer exists.",
       "inaccessible": "The site blocked automated access or was unreachable. This does NOT mean the job is closed; check it manually.",
       "not_checked": "Only the best-matching listings are checked automatically. Use 'Open listing' to verify it yourself."}


def pretty_evidence(line):
    if line.startswith("HTTP "):
        code = line[5:]
        return ("✅", "Page loaded successfully (HTTP 200)") if code == "200" else ("⚠️", f"Page returned HTTP {code}")
    if line.startswith("source type: "):
        return "ℹ️", "Source: " + KIND.get(line[13:], line[13:])
    bad = ("NOT" in line or "blocked" in line or "looks like a general" in line or "no apply" in line)
    gone = any(x in line.lower() for x in ("closed-language", "404", "in the past"))
    return ("❌" if gone else "⚠️" if bad else "✅"), line[0].upper() + line[1:]


def details(j, m, v):
    kv = [("Company", j.get("company")), ("Location", j.get("location")), ("Experience", j.get("experience_required")),
          ("Posted", j.get("posted_date")), ("Source", j.get("source_domain"))]
    html_ = '<div class="sec">Overview</div><div class="kv">' + "".join(f"<b>{k}</b><span>{esc(x or 'Not stated in listing')}</span>" for k, x in kv) + "</div>"
    single = v and v.get("page_kind") == "single_posting" and v.get("page_excerpt")
    text = v["page_excerpt"] if single else j.get("description", "")
    html_ += '<div class="sec">Job description</div>'
    html_ += f'<div class="excerpt">{esc(text[:900]) or "No description text available."}</div>'
    if not single:
        html_ += '<small style="color:#64748b">Only a short search snippet is available here. Use “Open listing” to read the full description.</small>'
    if v and v.get("page_kind") == "listing_index":
        html_ += '<div style="margin-top:6px;color:#b45309">⚠️ This link is a general jobs page, not one specific posting.</div>'
    if m:
        html_ += f'<div class="sec">Match analysis — {m["score"]}%</div>'
        for k, val in m["breakdown"].items():
            bar = f'<div class="cbar"><div style="width:{val * 100:.0f}%"></div></div>' if val is not None else ""
            html_ += (f'<div style="display:grid;grid-template-columns:130px 1fr 60px;gap:8px;align-items:center;font-size:.85rem;margin:3px 0">'
                      f'<span>{COMP.get(k, k)}</span>{bar or "<span></span>"}<span style="text-align:right;color:#64748b">{f"{val * 100:.0f}%" if val is not None else "n/a"}</span></div>')
        req = m["required_skills"] + m["preferred_skills"]
        if req:
            html_ += '<div class="sec">Skills</div>' + "".join(f'<span class="chip ok">✓ {esc(s)}</span>' for s in m["matched_skills"])
            html_ += "".join(f'<span class="chip miss">✗ {esc(s)}</span>' for s in m["missing_skills"])
        else:
            html_ += '<div class="sec">Skills</div><span style="color:#64748b">No known skills could be detected in the text we have. Open the listing to read the real requirements.</span>'
    st_key = v["status"] if v else "not_checked"
    html_ += f'<div class="sec">Verification {badge(st_key)}</div><div style="margin-bottom:6px">{WHY[st_key]}</div>'
    if v:
        html_ += "".join(f"<div>{ic} {esc(tx)}</div>" for ic, tx in map(pretty_evidence, v["evidence"]))
        html_ += f'<small style="color:#64748b">Checked {esc(v["checked_at"][:16].replace("T", " "))} UTC</small>'
    st.markdown(html_, unsafe_allow_html=True)


ss = st.session_state
for k, d in [("profile", None), ("report", None), ("events", []), ("checklist", {}), ("nav", "Dashboard")]:
    ss.setdefault(k, d)

with st.sidebar:
    st.markdown('<div class="logo"><span>🧭</span>CareerPilot AI</div>', unsafe_allow_html=True)
    page = st.radio("nav", PAGES, key="nav", label_visibility="collapsed", format_func=lambda p: f"{ICON[p]}   {p}")
    st.markdown('<div class="promo"><b>Your Career, Our AI</b>Find better opportunities, build your future.</div>', unsafe_allow_html=True)

name = (ss.profile or {}).get("name") or "Candidate"
st.markdown(f'<div class="topbar"><div class="avatar">{esc(name[:1].upper())}</div><div class="who"><b>Hi, {esc(name.split()[0])}</b><br><small>Career Explorer</small></div></div>', unsafe_allow_html=True)

if page == "Dashboard":
    head(f"Welcome back, {name.split()[0]}! 👋", "Your AI career assistant is ready to help you find the best opportunities.")
    d = call("GET", "/api/dashboard")
    if d:
        c = st.columns(4)
        for col, (lab, val) in zip(c, [("Total Jobs Found", d["total_jobs"]), ("Verified Open", d["verified_open"]),
                                       ("Avg. Match Score", f'{d["avg_match_score"]}%' if d["avg_match_score"] is not None else "n/a"), ("Saved Jobs", d["saved_jobs"])]):
            col.markdown(f'<div class="card metric"><small>{lab}</small><div class="v">{val}</div></div>', unsafe_allow_html=True)
        l, r = st.columns([1.2, 1])
        with l:
            rows = "".join(f'<div class="ev"><div><b>{esc(s["query"][:60])}</b><br><small style="color:#94a3b8">{esc(s["created_at"][:16])} • {esc(s["status"])}</small></div></div>' for s in d["recent_searches"]) or "<p style='color:#94a3b8'>No searches yet.</p>"
            card(f"<h4>Recent Searches</h4>{rows}")
        with r:
            card(f"<h4>Job Verification Status</h4>{donut(d['by_status'])}")
        ac = d["agent_event_counts"]
        names = [("Search", "job_search_agent"), ("Matching", "matching_agent"), ("Verification", "verification_agent"), ("Report", "report_agent")]
        cells = "".join(f'<div style="flex:1;text-align:center"><b>{n}</b><br><small style="color:{"#16a34a" if ac.get(a) else "#94a3b8"}">{"Completed (" + str(ac[a]) + " events)" if ac.get(a) else "Pending"}</small></div>' for n, a in names)
        l, r = st.columns([1.6, 1])
        l.markdown(f'<div class="card"><h4>Agent Execution Summary</h4><div style="display:flex">{cells}</div></div>', unsafe_allow_html=True)
        with r:
            card("<h4>Ready to find your next opportunity?</h4>")
            st.button("Start Job Search →", on_click=lambda: ss.update(nav="Job Search"))

elif page == "Job Search":
    head("Job Search", "Search for the latest job opportunities using natural language and AI.")
    with st.form("search"):
        q = st.text_input("Search", "Find GenAI jobs for freshers in Bangalore")
        c = st.columns(4)
        role = c[0].selectbox("Role", ["Any role", "GenAI Engineer", "AI Engineer", "ML Engineer", "Python Developer", "RAG Engineer", "AI Intern", "Data Analyst"])
        loc = c[1].text_input("Location", "")
        exp = c[2].selectbox("Experience", ["fresher", "junior", "mid", "senior"])
        mode = c[3].selectbox("Work mode", ["any", "remote", "hybrid", "onsite"])
        rec = st.selectbox("Posted within (only applied where sources show dates)", ["any", "7", "30", "90"])
        go = st.form_submit_button("Search")
    if go:
        body = {"query": q, "role": None if role == "Any role" else role, "location": loc or None, "experience_level": exp,
                "work_mode": None if mode == "any" else mode, "recency_days": None if rec == "any" else int(rec), "profile": ss.profile}
        r = call("POST", "/api/search", json=body)
        if r:
            ss.events, after = [], 0
            stepper, feed = st.empty(), st.empty()
            while True:
                s = call("GET", f"/api/search/{r['search_id']}", params={"after_id": after})
                if not s:
                    break
                for e in s["events"]:
                    after = e["id"]
                    ss.events.append(e)
                seen = {e["event"] for e in ss.events}
                done = [("request_parsed" in seen), ("search_api_completed" in seen), ("verification_evidence_collected" in seen), ("final_report_generated" in seen)]
                act = next((i for i, x in enumerate(done) if not x), -1) if s["status"] == "running" else -1
                steps = "".join(f'<div class="step {"done" if done[i] else "act" if i == act else ""}"><div class="dot">{"✓" if done[i] else i + 1}</div>{n}</div>'
                                for i, n in enumerate(["Parsing Request", "Searching Web", "Analyzing Results", "Generating Report"]))
                stepper.markdown(f'<div class="card"><h4>Live Search Progress</h4><div style="display:flex">{steps}</div></div>', unsafe_allow_html=True)
                feed.markdown('<div class="card"><h4>Agent Activity</h4>' + "".join(
                    f'<div class="ev"><div class="d" style="background:#2563eb"></div><div><b>{esc(e["agent"])}</b>: {esc(e["event"])}<br><small>{esc(e["detail"])}</small></div><time>{esc(e["ts"][11:19])}</time></div>'
                    for e in ss.events[-8:]) + "</div>", unsafe_allow_html=True)
                if s["status"] != "running":
                    break
                time.sleep(1.5)
            if s and s["status"] == "completed":
                ss.report = call("GET", f"/api/reports/{s['report_id']}")
                ss.rm_src = "Job search results"
                st.success("Search complete. Open Job Results.")
                st.button("View results →", on_click=lambda: ss.update(nav="Job Results"))
            elif s:
                st.error(s.get("error") or "Search failed")

elif page == "Job Results":
    rep = ss.report
    if not rep:
        head("Job Results", "Run a search first.")
    else:
        res = rep["results"]
        head("Job Search Results", f"Found {len(res)} jobs • Sorted by verification, then match score")
        for n in rep["incomplete_notes"]:
            st.caption("⚠️ " + n)
        cnt = Counter((r["verification"]["status"] if r["verification"] else "not_checked") for r in res)
        c = st.columns([3, 1.3, 1.3])
        sel = c[0].multiselect("Verification", list(VER), default=list(VER), format_func=lambda k: f"{VER[k][0]} ({cnt.get(k, 0)})")
        min_score = c[1].slider("Min match", 0, 100, 0)
        sort = c[2].selectbox("Sort by", ["Verification", "Match score", "Title"])
        items = [r for r in res if (r["verification"]["status"] if r["verification"] else "not_checked") in sel and (r["match"]["score"] if r["match"] else 0) >= min_score]
        if sort == "Match score":
            items.sort(key=lambda r: -(r["match"]["score"] if r["match"] else 0))
        elif sort == "Title":
            items.sort(key=lambda r: r["job"]["title"].lower())
        st.download_button("⬇ Download CSV", rep["csv"], f"careerpilot_{rep['report_id']}.csv", "text/csv")
        for i, r in enumerate(items[:50]):
            job_card(r, str(i))

elif page == "Resume Analyzer":
    st.markdown("""<style>
:where(.stApp) :where(p,label,li) {color:#e5e7eb}
.stApp {background:radial-gradient(1200px 600px at 20% 0%,#2a1838 0%,#15131f 45%,#101722 100%)}
h1.pg, .who, .who b {color:#fff !important} p.sub, .who small {color:#9ca3af !important}
.card {background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.09); color:#e5e7eb; box-shadow:none}
.card h4 {color:#fff}
.stTextArea textarea, .stFileUploader section {background:#2a2a35 !important; color:#e5e7eb !important; border-radius:14px !important}
.stTextArea label, .stFileUploader label, .stMarkdown p {color:#cbd5e1}
.stFileUploader section * {color:#cbd5e1 !important}
.kick {font-family:monospace; letter-spacing:.25em; font-size:.7rem; color:#8b5cf6; text-transform:uppercase}
.big {font-size:1.45rem; font-weight:800; color:#fff}
.tile {text-align:center} .tile .v {font-size:2rem; font-weight:800} .tile small {letter-spacing:.2em; font-size:.65rem; color:#6b7280; text-transform:uppercase}
.have {display:inline-block; background:rgba(34,197,94,.12); border:1px solid #166534; color:#4ade80; padding:3px 10px; border-radius:8px; font-family:monospace; font-size:.8rem; margin:3px 4px 3px 0}
.lack {display:inline-block; background:rgba(239,68,68,.12); border:1px solid #991b1b; color:#f87171; padding:3px 10px; border-radius:8px; font-family:monospace; font-size:.8rem; margin:3px 4px 3px 0}
.role {display:flex; justify-content:space-between; background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.09); border-radius:10px; padding:10px 14px; margin-bottom:8px; color:#fff; font-weight:600}
.role.top {border-color:#8b5cf6; box-shadow:0 0 14px rgba(139,92,246,.35)} .role span:last-child {color:#c084fc}
.bar {height:16px; border-radius:4px; margin:3px 0}
.rec {background:rgba(234,179,8,.08); border:1px solid #854d0e; color:#fde68a; border-radius:10px; padding:10px 14px; margin-bottom:8px}
</style>""", unsafe_allow_html=True)
    head("AI Resume Analyzer", "Rule-based skill matching and gap analysis. Your resume is parsed in memory and never stored.")
    l, r = st.columns(2)
    with l:
        card('<div class="kick">Step 01</div><div class="big">Upload Your Resume</div>')
        up = st.file_uploader("Drag and drop file here", type=["pdf", "txt"], label_visibility="collapsed")
        rtxt = st.text_area("Or paste resume text", height=170, placeholder="Paste your full resume text here...")
    with r:
        card('<div class="kick">Step 02</div><div class="big">Paste Job Description</div>')
        jd = st.text_area("Job description", height=270, label_visibility="collapsed",
                          placeholder="Paste the full job description — include skills, responsibilities, and requirements...")
    if st.button("Analyze Resume →", use_container_width=True):
        files = {"file": (up.name, up.getvalue(), "application/octet-stream")} if up else None
        out = call("POST", "/api/resume/compare", data={"resume_text": rtxt, "job_description": jd}, files=files, timeout=60)
        if out:
            ss.analysis, ss.profile = out, out["profile"]
            ss.rm_src = "Resume vs Job Description"
    a = ss.get("analysis")
    if a:
        m = a["match"]
        st.success("Analysis complete!")
        tiles = [("Match Score", f'{m["score"]}%' if m else "n/a", "#a78bfa"), ("Skills Found", a["skills_found"], "#fff"),
                 ("Matched", len(m["matched"]) if m else "–", "#22c55e"), ("Missing", len(m["missing"]) if m else "–", "#f43f5e")]
        for col, (lab, val, colr) in zip(st.columns(4), tiles):
            col.markdown(f'<div class="card tile"><div class="v" style="color:{colr}">{val}</div><small>{lab}</small></div>', unsafe_allow_html=True)
        g, b = st.columns(2)
        with g:
            card('<div class="kick">Match Score</div><div class="big">Resume Fitness</div>')
            if m:
                s = m["score"]
                arc = lambda d, c, w=14: f'<path d="M 20 110 A 90 90 0 0 1 200 110" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-dasharray="{d} 283"/>'
                st.markdown(f'<div class="card"><svg viewBox="0 0 220 125" style="width:100%;max-width:380px;display:block;margin:auto">'
                            f'{arc(283, "#2a2438")}{arc(283 * s / 100, "#8b5cf6")}'
                            f'<text x="110" y="100" text-anchor="middle" font-size="26" font-weight="800" fill="#a78bfa">{s}%</text></svg>'
                            f'<div style="text-align:center;color:#a78bfa;font-weight:600">{esc(m["label"])}</div></div>', unsafe_allow_html=True)
            else:
                card("Paste a job description to see your fitness score.")
        with b:
            card('<div class="kick">Skill-profile similarity</div><div class="big">Best Matching Roles</div>')
            medals = ["🥇", "🥈", "🥉"]
            rows = "".join(f'<div class="role {"top" if i == 0 else ""}"><span>{medals[i]} {esc(x["role"])}</span><span>{x["fit"]}%</span></div>' for i, x in enumerate(a["roles"]))
            bars = "".join(f'<div style="display:flex;align-items:center;gap:8px;color:#9ca3af;font-size:.75rem"><span style="width:110px">{esc(x["role"])}</span><div class="bar" style="width:{x["fit"]}%;background:#8b5cf6"></div>{x["fit"]}%</div>' for x in a["roles"])
            st.markdown(f'<div class="card">{rows}{bars}<small style="color:#6b7280">Fit = share of the role\'s core skills found on your resume.</small></div>', unsafe_allow_html=True)
        sg, cv = st.columns(2)
        with sg:
            card('<div class="kick">Skill Gap</div><div class="big">What You Have vs. Need</div>')
            have = "".join(f'<span class="have">{esc(s)}</span>' for s in (m["matched"] if m else a["profile"]["skills"]))
            lack = "".join(f'<span class="lack">{esc(s)}</span>' for s in (m["missing"] if m else []))
            pref = "".join(f'<span class="lack" style="opacity:.6">{esc(s)}</span>' for s in (m["preferred_missing"] if m else []))
            st.markdown(f'<div class="card"><small style="color:#9ca3af">✓ YOU HAVE</small><br>{have or "None"}'
                        + (f'<br><small style="color:#9ca3af">✗ MISSING (REQUIRED)</small><br>{lack or "None"}' if m else "")
                        + (f'<br><small style="color:#9ca3af">NICE TO HAVE (MISSING)</small><br>{pref}' if pref else "") + '</div>', unsafe_allow_html=True)
        with cv:
            card('<div class="kick">Coverage</div><div class="big">Skill Coverage Chart</div>')
            rows = "".join(f'<div style="display:flex;align-items:center;gap:8px;color:#cbd5e1;font-size:.8rem"><span style="width:120px;text-align:right">{esc(c["skill"])}</span>'
                           f'<div style="flex:1"><div class="bar" style="background:#312e5a;width:100%"></div><div class="bar" style="background:{"#3b82f6" if c["have"] else "#7f1d1d"};width:{100 if c["have"] else 4}%"></div></div></div>' for c in a["coverage"])
            st.markdown(f'<div class="card">{rows or "No job skills detected."}<div style="color:#9ca3af;font-size:.75rem;margin-top:6px">■ Job requires &nbsp; <span style="color:#3b82f6">■</span> Your resume</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="kick">Recommendations</div><div class="big" style="margin-bottom:8px">How to Improve</div>', unsafe_allow_html=True)
        st.markdown("".join(f'<div class="rec">🎯 {esc(x)}</div>' for x in a["recommendations"]), unsafe_allow_html=True)
        with st.expander("Edit extracted profile (used in your next job search)"):
            p = ss.profile
            p["name"] = st.text_input("Name", p.get("name") or "")
            p["skills"] = [x.strip() for x in st.text_area("Skills (comma separated)", ", ".join(p["skills"])).split(",") if x.strip()]
            p["years_experience"] = st.number_input("Years of professional experience", 0.0, 40.0, float(p["years_experience"]))
        st.download_button("Download Profile", json.dumps(ss.profile, indent=2), "candidate_profile.json", "application/json")

elif page == "Career Roadmap":
    head("Personalized Career Roadmap", "Built automatically from your resume vs. a job description, or from your job-search results.")
    srcs, an, rep = {}, ss.get("analysis"), ss.report
    if an and an.get("roadmap"):
        srcs["Resume vs Job Description"] = (an["roadmap"], an.get("roadmap_target", ""))
    if rep and rep.get("advice"):
        srcs["Job search results"] = (rep["advice"], ", ".join(rep["criteria"]["roles"]) or "your search")
    if not srcs:
        st.info("Analyze your resume in the Resume Analyzer (with a job description), or run a job search, and your roadmap appears here automatically.")
    else:
        names = list(srcs)
        pick = names[0] if len(names) == 1 else st.radio("Roadmap based on", names, index=names.index(ss.rm_src) if ss.get("rm_src") in names else 0, horizontal=True)
        adv, target = srcs[pick]
        st.caption(f"Target: {target} · Source: {adv['source']} (AI-generated advice, not verified fact)")
        t1, t2, t3 = st.tabs(["Learning Plan", "Projects", "Interview Prep"])
        with t1:
            l, r = st.columns([1.7, 1])
            with l:
                rows = "".join(f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f1f5f9"><b>{esc(s)}</b>'
                               f'<a href="https://www.google.com/search?q={quote_plus("learn " + s + " tutorial for beginners")}" target="_blank">Find tutorials ↗</a></div>'
                               for s in adv["skills_to_learn"])
                card("<h4>Skills to learn</h4>" + (rows or "No skill gaps detected. Focus on projects and interview practice."))
                st.markdown("**Weekly plan**")
                done = 0
                for w in adv["weekly_plan"]:
                    done += st.checkbox(w, key="wk" + hashlib.md5(w.encode()).hexdigest()[:10])
            with r:
                card(f'<h4>Progress</h4>{ring(100 * done / max(1, len(adv["weekly_plan"])), 80)}')
        with t2:
            for p in adv["projects"] or ["No project suggestions."]:
                card(esc(p))
        with t3:
            for qa in adv["interview_questions"]:
                with st.expander(qa["question"]):
                    st.write(qa["sample_answer"] or "No sample answer (configure GROQ_API_KEY for LLM answers).")

elif page == "Saved Jobs":
    head("Saved Jobs", "Manage your saved job opportunities.")
    items = call("GET", "/api/jobs/saved") or []
    if not items:
        st.info("No saved jobs yet. Use Save or Mark as applied on a job in Job Results.")
    for sj in items:
        j = sj["job"]
        card(f'<div class="job"><div class="logo-box">{esc((j.get("company") or "?")[:1].upper())}</div><div style="flex:1"><div class="t">{esc(j["title"])}</div>'
             f'<div class="m">{esc(j.get("company") or "Company unknown")} • {esc(j.get("location") or "Location not stated")}</div><div class="m">Saved {esc(sj["saved_at"][:10])}</div></div></div>')
        c = st.columns([1.5, 1.6, 1.2, 4])
        if c[0].button("Mark as applied", key="sa" + j["job_id"]) and call("POST", "/api/jobs/save", json={"job_id": j["job_id"], "status": "Applied"}):
            st.toast("Logged as Applied")
        c[1].link_button("Open listing ↗", j.get("application_url") or j["source_url"])
        if c[2].button("Remove", key="sr" + j["job_id"]):
            call("DELETE", f"/api/jobs/saved/{j['job_id']}")
            st.rerun()

elif page == "Applications":
    head("Application Tracker", "Track your job applications and stay organized.")
    card("<h4>How tracking works</h4>You apply on the company's own website, so CareerPilot cannot see that application. "
         "<b>You log it yourself</b>: click <b>Mark as applied</b> on a job (it records today's date), then update the status "
         "(Assessment, Interview, Offer, Rejected) and notes here as things progress. It is your personal follow-up list, not an automatic sync.")
    c = st.columns([3, 2])
    f = c[0].radio("Filter", ["All"] + STATUSES, horizontal=True, label_visibility="collapsed")
    q = c[1].text_input("Search", label_visibility="collapsed", placeholder="Search title, company, notes")
    d = call("GET", "/api/applications", params={"status": None if f == "All" else f, "q": q or None})
    items = (d or {}).get("items", [])
    pill = {"Applied": "#2563eb", "Interview": "#d97706", "Offer": "#16a34a", "Rejected": "#dc2626", "Assessment": "#7c3aed", "Interested": "#64748b"}
    rows = "".join(f'<tr><td><b>{esc(a["title"])}</b></td><td>{esc(a["company"] or "—")}</td><td><span class="badge" style="background:{pill[a["status"]]}22;color:{pill[a["status"]]}">{a["status"]}</span></td><td>{esc(a["applied_date"] or "—")}</td></tr>' for a in items)
    card(f'<table class="tr"><tr><th>Job Title</th><th>Company</th><th>Status</th><th>Applied On</th></tr>{rows}</table>' if items else "No applications yet. Save a job from Job Results.")
    for a in items:
        with st.expander(f"Edit: {a['title']}"):
            ns = st.selectbox("Status", STATUSES, STATUSES.index(a["status"]), key=f"s{a['id']}")
            dt = st.text_input("Applied date (YYYY-MM-DD)", a["applied_date"] or "", key=f"d{a['id']}")
            nt = st.text_area("Notes", a["notes"], key=f"n{a['id']}")
            b = st.columns(2)
            if b[0].button("Update", key=f"u{a['id']}") and call("PATCH", f"/api/applications/{a['id']}", json={"status": ns, "applied_date": dt, "notes": nt}):
                st.toast("Updated")
            if b[1].button("Remove", key=f"r{a['id']}"):
                call("DELETE", f"/api/jobs/saved/{a['job_id']}")
                st.rerun()

elif page == "Agent Activity":
    head("Agent Activity", "Real-time view of your multi-agent workflow (events from the last search).")
    seen = {e["agent"] for e in ss.events}
    rows = "".join(f'<div class="ev"><div class="d" style="background:#16a34a"></div><div><b>{esc(e["agent"])}</b><br><small>{esc(e["event"])} — {esc(e["detail"])}</small></div><time>{esc(e["ts"][11:19])}</time></div>' for e in ss.events)
    pend = "".join(f'<div class="ev"><div class="d" style="background:#cbd5e1"></div><div><b>{a}</b><br><small>Pending</small></div></div>'
                   for a in ["supervisor", "resume_agent", "job_search_agent", "matching_agent", "verification_agent", "career_advisor_agent", "report_agent"] if a not in seen) if ss.events else ""
    card((rows + pend) or "No activity yet. Run a search.")

elif page == "Settings":
    head("Settings", "Connection status and local data. API keys are set in your .env file and are never shown here.")
    if st.button("Test Connections") or True:
        h = call("GET", "/health", quiet=True)
        ok = lambda v: '<span class="badge" style="background:#16a34a22;color:#16a34a">Connected</span>' if v else '<span class="badge" style="background:#dc262622;color:#dc2626">Not configured</span>'
        card(f'<h4>API Configuration</h4><p>API server: {ok(bool(h))}</p><p>Tavily API Key: {ok(h and h["tavily_configured"])}</p><p>Groq API Key: {ok(h and h["groq_configured"])} <small>(optional; rule-based fallbacks used without it)</small></p>')
    card("<h4>Data Management</h4>Clears this browser session only (profile, last report, activity). Saved jobs and applications stay in the database.")
    if st.button("Clear session data"):
        for k in ("profile", "report", "events", "checklist"):
            ss.pop(k, None)
        st.rerun()
