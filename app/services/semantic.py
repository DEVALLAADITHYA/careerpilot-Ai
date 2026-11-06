"""Text similarity: Sentence Transformers if enabled+installed, else a lexical cosine fallback."""
from __future__ import annotations

import math
import re
from collections import Counter

from app.config import get_settings

_model = None


def _tokens(t: str) -> Counter:
    return Counter(w for w in re.findall(r"[a-z0-9+#.]+", t.lower()) if len(w) > 2)


def _lexical(a: str, b: str) -> float:
    ca, cb = _tokens(a), _tokens(b)
    num = sum(ca[k] * cb[k] for k in ca.keys() & cb.keys())
    den = math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values()))
    return num / den if den else 0.0


def similarity(a: str, b: str) -> tuple[float, str]:
    """Returns (cosine similarity clipped to 0..1, backend name)."""
    global _model
    if get_settings().use_sentence_transformers:
        try:
            from sentence_transformers import SentenceTransformer, util
            if _model is None:
                _model = SentenceTransformer("all-MiniLM-L6-v2")
            e = _model.encode([a, b], convert_to_tensor=True)
            return max(0.0, min(1.0, float(util.cos_sim(e[0], e[1])))), "sentence-transformers/all-MiniLM-L6-v2"
        except ImportError:
            pass
    return max(0.0, min(1.0, _lexical(a, b))), "lexical-cosine (fallback)"
