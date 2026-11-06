from __future__ import annotations

import re

SKILLS: dict[str, list[str]] = {
    "python": ["python"], "sql": ["sql", "mysql", "postgresql", "postgres", "sqlite"],
    "pytorch": ["pytorch"], "tensorflow": ["tensorflow", "keras"],
    "scikit-learn": ["scikit-learn", "sklearn"], "pandas": ["pandas"], "numpy": ["numpy"],
    "machine learning": ["machine learning", "ml"], "deep learning": ["deep learning"],
    "nlp": ["nlp", "natural language processing"], "llm": ["llm", "llms", "large language model", "large language models"],
    "generative ai": ["generative ai", "genai", "gen ai"],
    "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "langchain": ["langchain"], "langgraph": ["langgraph"], "llamaindex": ["llamaindex", "llama-index", "llama index"],
    "prompt engineering": ["prompt engineering"], "ai agents": ["ai agents", "agentic", "multi-agent", "multi agent", "agent frameworks"],
    "vector database": ["vector database", "vector db", "faiss", "pinecone", "chroma", "chromadb", "weaviate", "qdrant"],
    "embeddings": ["embeddings", "sentence transformers", "sentence-transformers"],
    "hugging face": ["hugging face", "huggingface", "transformers"], "openai": ["openai", "gpt-4", "chatgpt"],
    "fine-tuning": ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora"],
    "fastapi": ["fastapi"], "flask": ["flask"], "django": ["django"], "streamlit": ["streamlit"],
    "rest api": ["rest api", "rest apis", "restful"], "docker": ["docker"], "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services"], "azure": ["azure"], "gcp": ["gcp", "google cloud"],
    "git": ["git", "github"], "ci/cd": ["ci/cd", "cicd"], "linux": ["linux"], "mlops": ["mlops"],
    "langfuse": ["langfuse"], "power bi": ["power bi", "powerbi"], "tableau": ["tableau"], "excel": ["excel"],
    "data analysis": ["data analysis", "data analytics"], "data visualization": ["data visualization", "data visualisation"],
    "statistics": ["statistics"], "computer vision": ["computer vision", "opencv"],
    "java": ["java"], "javascript": ["javascript"], "typescript": ["typescript"], "react": ["react", "react.js"],
    "node.js": ["node.js", "nodejs"], "c++": ["c++"], "mongodb": ["mongodb"], "redis": ["redis"],
    "spark": ["spark", "pyspark"], "airflow": ["airflow"], "pytest": ["pytest"],
}

_PATTERNS = {
    canon: re.compile(r"(?<![a-z0-9+#.])(?:%s)(?![a-z0-9+#])" % "|".join(re.escape(a) for a in aliases))
    for canon, aliases in SKILLS.items()
}


def extract_skills(text: str) -> list[str]:
    t = (text or "").lower()
    return sorted(c for c, p in _PATTERNS.items() if p.search(t))


def canonicalize(skill: str) -> str:
    s = skill.strip().lower()
    for canon, aliases in SKILLS.items():
        if s == canon or s in aliases:
            return canon
    return s
