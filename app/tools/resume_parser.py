"""PDF text extraction and rule-based profile extraction. Nothing is inferred beyond what the text says."""
from __future__ import annotations

import re

from app.models.schemas import CandidateProfile
from app.utils.skills import extract_skills

MAX_PAGES = 10
MAX_CHARS = 60_000


class ResumeError(ValueError):
    pass


def extract_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF"):
        raise ResumeError("File is not a valid PDF")
    try:
        import fitz  # PyMuPDF
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ResumeError("Encrypted PDFs are not supported")
            text = "\n".join(p.get_text() for i, p in enumerate(doc) if i < MAX_PAGES)
    except ResumeError:
        raise
    except Exception as e:  # corrupt PDFs etc.
        raise ResumeError("Could not read PDF") from e
    if not text.strip():
        raise ResumeError("No extractable text found (scanned PDF?). OCR is not supported.")
    return text[:MAX_CHARS]


_HEADINGS = {
    "education": ("education", "academic background", "academics"),
    "projects": ("projects", "personal projects", "academic projects"),
    "experience": ("experience", "work experience", "internships", "internship", "professional experience"),
    "certifications": ("certifications", "certificates", "courses", "certification"),
    "skills": ("skills", "technical skills", "tech stack"),
}
_STOP = {"summary", "objective", "profile", "achievements", "languages", "interests", "references", "declaration"}


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {k: [] for k in _HEADINGS}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        key = re.sub(r"[^a-z ]", "", line.lower()).strip()
        match = next((k for k, v in _HEADINGS.items() if key in v), None)
        if match:
            cur = match
            continue
        if key in _STOP:
            cur = None
            continue
        if cur and line:
            out[cur].append(re.sub(r"^[\-\u2022*\u25cf\u25aa\s]+", "", line)[:200])
    return {k: v[:15] for k, v in out.items()}


def parse_profile(text: str) -> CandidateProfile:
    sec = _sections(text)
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    name = first if 2 <= len(first) <= 40 and re.fullmatch(r"[A-Za-z .'\-]+", first) else None
    yrs = re.search(r"(\d+(?:\.\d+)?)\+?\s*years?\s+of\s+(?:professional\s+)?experience", text, re.I)
    return CandidateProfile(
        name=name, skills=extract_skills(text), education=sec["education"], projects=sec["projects"],
        experience=sec["experience"], certifications=sec["certifications"],
        years_experience=float(yrs.group(1)) if yrs else 0.0, source="resume")
