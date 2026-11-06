"""Resume-vs-job-description analysis. Fully rule-based and transparent (no trained model is claimed)."""
from __future__ import annotations

import re

from app.agents.matching_agent import match_job
from app.models.schemas import JobListing, SearchCriteria
from app.tools.resume_parser import parse_profile

# Core skills per role. "Role fit" = share of these found on the resume.
ROLE_PROFILES: dict[str, list[str]] = {
    "GenAI Engineer": ["generative ai", "llm", "rag", "langchain", "langgraph", "prompt engineering", "vector database", "embeddings", "python", "fastapi"],
    "ML Engineer": ["machine learning", "python", "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "docker", "mlops", "sql"],
    "NLP Engineer": ["nlp", "hugging face", "embeddings", "python", "pytorch", "llm", "deep learning", "fine-tuning"],
    "Data Analyst": ["sql", "excel", "power bi", "tableau", "pandas", "data analysis", "data visualization", "statistics", "python"],
    "Data Scientist": ["python", "statistics", "machine learning", "pandas", "numpy", "scikit-learn", "sql", "data visualization"],
    "Python Developer": ["python", "fastapi", "flask", "django", "rest api", "sql", "git", "docker", "pytest"],
    "Software Engineer": ["git", "docker", "rest api", "sql", "python", "java", "javascript", "ci/cd", "linux"],
    "MLOps Engineer": ["mlops", "docker", "kubernetes", "ci/cd", "aws", "python", "git", "airflow"],
    "Computer Vision Engineer": ["computer vision", "deep learning", "pytorch", "tensorflow", "python", "numpy"],
}


def label_for(score: float) -> str:
    return "Strong Match" if score >= 75 else "Good Potential" if score >= 50 else "Needs Work" if score >= 30 else "Low Match"


def role_fit(have: set[str], top: int = 3) -> list[dict]:
    out = [{"role": r, "fit": round(100 * len(have & set(sk)) / len(sk), 1), "matched": sorted(have & set(sk))}
           for r, sk in ROLE_PROFILES.items()]
    return sorted(out, key=lambda x: -x["fit"])[:top]


def analyze(resume_text: str, job_description: str = "") -> dict:
    profile = parse_profile(resume_text)
    have = set(profile.skills)
    jd = job_description.strip()
    res: dict = {"profile": profile.model_dump(), "skills_found": len(have), "roles": role_fit(have), "match": None,
                 "coverage": [], "recommendations": []}
    quantified = bool(re.search(r"\d+\s*%|(?:increased|reduced|improved|cut|saved|built|served)[^.\n]{0,40}\d", resume_text, re.I))
    recs: list[str] = []
    if jd:
        job = JobListing(job_id="pasted-jd", title="Pasted job description", description=jd[:20000],
                         source_url="https://pasted.invalid/job-description")
        m = match_job(job, profile, SearchCriteria())
        pref_missing = sorted(set(m.preferred_skills) - have)
        res["match"] = {"score": m.score, "label": label_for(m.score), "matched": m.matched_skills, "missing": m.missing_skills,
                        "preferred_missing": pref_missing, "required": m.required_skills, "preferred": m.preferred_skills,
                        "breakdown": m.breakdown, "explanation": m.explanation, "backend": m.similarity_backend}
        res["coverage"] = [{"skill": s, "have": s in have} for s in m.required_skills + m.preferred_skills][:15]
        if not (m.required_skills or m.preferred_skills):
            recs.append("No known skills were detected in the job description; paste the full requirements section for a better score.")
        recs.append({"Strong Match": "Strong match! Tailor your cover letter to this role and quantify your achievements.",
                     "Good Potential": "Good potential. Close the skill gaps below and tailor your resume wording to the job description.",
                     "Needs Work": "Several required skills are missing. Build one project that demonstrates them before applying.",
                     "Low Match": "Low match for this role. Consider roles closer to your current skills (see Best Matching Roles)."}[res["match"]["label"]])
        if m.missing_skills:
            recs.append("Required skills not found on your resume: " + ", ".join(m.missing_skills) + ". List them only if you truly have them; otherwise learn them and show proof in a project.")
        if pref_missing:
            recs.append("Nice-to-have skills missing: " + ", ".join(pref_missing) + ".")
    else:
        recs.append("Paste a job description to get a match score and a skill-gap analysis.")
    if not quantified:
        recs.append("Quantify your achievements with numbers (percentages, users, time saved).")
    if not profile.projects:
        recs.append("No Projects section was detected; add 2-3 projects with the tools you used.")
    res["recommendations"] = recs
    return res


def role_profile_for(targets: list[str]) -> str | None:
    for t in targets:
        for key in ROLE_PROFILES:
            if t.lower() == key.lower():
                return key
    for t in targets:
        for key in ROLE_PROFILES:
            if t.lower() in key.lower() or key.lower() in t.lower():
                return key
    return None


def role_gap_skills(targets: list[str], have: set[str]) -> list[str]:
    key = role_profile_for(targets)
    return [s for s in ROLE_PROFILES[key] if s not in have] if key else []
