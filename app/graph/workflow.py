"""LangGraph workflow:
START -> plan -> resume -> search -> match -> verify -> review --(search | advise)--> advise -> report -> END
Every node emits real events (persisted immediately) so the UI shows actual execution.
"""
from __future__ import annotations

import logging
import time

from langgraph.graph import END, START, StateGraph

from app.agents import (career_advisor_agent, job_search_agent, matching_agent, report_agent, resume_agent,
                        supervisor, verification_agent)
from app.config import get_settings
from app.database import repository as repo
from app.database.connection import session_scope
from app.graph.state import WorkflowState
from app.models.schemas import AgentEvent, JobResult
from app.utils.text import dedupe_jobs

log = logging.getLogger(__name__)


def emit(state: WorkflowState, agent: str, event: str, detail: str = "") -> dict:
    e = AgentEvent(agent=agent, event=event, detail=detail)
    try:
        with session_scope() as s:
            repo.add_event(s, state["search_id"], e)
    except Exception as ex:  # event logging must never break the workflow
        log.warning("could not persist event: %s", type(ex).__name__)
    return e.model_dump(mode="json")


async def plan_node(state: WorkflowState) -> dict:
    crit = await supervisor.parse_request(state["request"])
    ev = emit(state, "supervisor", "request_parsed",
              f"roles={crit.roles}, location={crit.location}, level={crit.experience_level}, parser={crit.parsed_by}")
    return {"criteria": crit, "events": [ev]}


async def resume_node(state: WorkflowState) -> dict:
    prof = resume_agent.profile_for_search(state["request"].profile, state["criteria"])
    ev = emit(state, "resume_agent", "profile_ready", f"source={prof.source}, skills={len(prof.skills)}")
    return {"profile": prof, "events": [ev]}


async def search_node(state: WorkflowState) -> dict:
    attempt = state.get("iteration", 0)
    evs = [emit(state, "job_search_agent", "search_started", f"attempt {attempt + 1}")]
    new, errors, stats = await job_search_agent.search_jobs(state["criteria"], attempt)
    evs.append(emit(state, "job_search_agent", "search_api_completed",
                    f"{stats['raw_results']} raw results, {stats['unique']} unique candidate listings, {stats['failed_queries']} failed queries"))
    merged = dedupe_jobs(state.get("jobs", []) + new)
    with session_scope() as s:
        repo.upsert_jobs(s, merged)
    failed = bool(errors) and stats["raw_results"] == 0
    if attempt > 0:
        evs.append(emit(state, "supervisor", "retry_triggered", f"search attempt {attempt + 1} added {len(merged) - len(state.get('jobs', []))} new listings"))
    return {"jobs": merged, "iteration": attempt + 1, "search_failed": failed, "events": evs, "errors": errors}


async def match_node(state: WorkflowState) -> dict:
    jobs = [j for j in state["jobs"] if j.job_id not in state.get("matches", {})]
    new = matching_agent.match_all(jobs, state["profile"], state["criteria"])
    with session_scope() as s:
        repo.save_matches(s, state["search_id"], new)
    ev = emit(state, "matching_agent", "matching_completed", f"scored {len(new)} listings")
    return {"matches": {**state.get("matches", {}), **new}, "events": [ev]}


async def verify_node(state: WorkflowState) -> dict:
    s_ = get_settings()
    done = set(state.get("verifications", {}))
    todo = verification_agent.pick_candidates(state["jobs"], state.get("matches", {}), done, s_.verify_top_n)
    new = await verification_agent.verify_jobs(todo) if todo else {}
    with session_scope() as s:
        repo.save_verifications(s, state["search_id"], new)
    tally: dict[str, int] = {}
    for v in new.values():
        tally[v.status.value] = tally.get(v.status.value, 0) + 1
    jobs, changed = list(state["jobs"]), []
    idx = {j.job_id: i for i, j in enumerate(jobs)}
    for jid, v in new.items():
        if v.page_kind == "single_posting" and v.page_excerpt and jid in idx and v.page_excerpt[:200] not in jobs[idx[jid]].description:
            jobs[idx[jid]] = jobs[idx[jid]].model_copy(update={"description": (jobs[idx[jid]].description + "\n\n" + v.page_excerpt)[:6000]})
            changed.append(jobs[idx[jid]])
    out: dict = {"verifications": {**state.get("verifications", {}), **new}}
    if changed:  # richer text from the real page -> re-score those listings
        rem = matching_agent.match_all(changed, state["profile"], state["criteria"])
        with session_scope() as s:
            repo.upsert_jobs(s, changed)
            repo.save_matches(s, state["search_id"], rem)
        out.update({"jobs": jobs, "matches": {**state.get("matches", {}), **rem}})
    ev = emit(state, "verification_agent", "verification_evidence_collected",
              f"checked {len(new)} listings: {tally}; re-scored {len(changed)} using full page text")
    out["events"] = [ev]
    return out


async def review_node(state: WorkflowState) -> dict:
    step, reason = supervisor.decide_next(state)
    return {"next_step": step, "events": [emit(state, "supervisor", f"review_decision:{step}", reason)]}


def route_after_review(state: WorkflowState) -> str:
    return state["next_step"]


async def advise_node(state: WorkflowState) -> dict:
    ranked = report_agent.rank([JobResult(
        job=j, match=state.get("matches", {}).get(j.job_id), verification=state.get("verifications", {}).get(j.job_id))
        for j in state.get("jobs", [])])
    adv = await career_advisor_agent.advise(ranked, state["profile"], state["criteria"])
    return {"advice": adv, "events": [emit(state, "career_advisor_agent", "advice_generated", f"source={adv.source}")]}


async def report_node(state: WorkflowState) -> dict:
    rep = report_agent.build_report(state["search_id"], state["criteria"], state.get("jobs", []), state.get("matches", {}),
                                    state.get("verifications", {}), state.get("advice"), state.get("errors", []))
    with session_scope() as s:
        repo.save_report(s, rep)
    return {"report": rep, "events": [emit(state, "report_agent", "final_report_generated", f"report_id={rep.report_id}")]}


def build_graph():
    g = StateGraph(WorkflowState)
    for name, fn in [("plan", plan_node), ("resume", resume_node), ("search", search_node), ("match", match_node),
                     ("verify", verify_node), ("review", review_node), ("advise", advise_node), ("report", report_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "resume")
    g.add_edge("resume", "search")
    g.add_edge("search", "match")
    g.add_edge("match", "verify")
    g.add_edge("verify", "review")
    g.add_conditional_edges("review", route_after_review, {"search": "search", "advise": "advise"})
    g.add_edge("advise", "report")
    g.add_edge("report", END)
    return g.compile()


async def run_search(search_id: str, request) -> None:
    """Background entry point: runs the graph and records final status."""
    t0 = time.time()
    state: WorkflowState = {"search_id": search_id, "request": request, "iteration": 0, "jobs": [], "matches": {},
                            "verifications": {}, "events": [], "errors": []}
    try:
        final = await build_graph().ainvoke(state, {"recursion_limit": 40})
        rep = final["report"]
        with session_scope() as s:
            repo.finish_search(s, search_id, "completed", criteria=final.get("criteria"), report_id=rep.report_id)
        log.info("search %s done in %.1fs", search_id, time.time() - t0)
    except Exception as e:  # surface a clear error; never fabricate results
        log.exception("search %s failed", search_id)
        with session_scope() as s:
            repo.add_event(s, search_id, AgentEvent(agent="supervisor", event="workflow_failed", detail=type(e).__name__))
            repo.finish_search(s, search_id, "failed", error=f"{type(e).__name__}: {str(e)[:300]}")
