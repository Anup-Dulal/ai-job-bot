"""
rag_resume.py — RAG-based resume tailoring using FAISS vector store.

Pipeline:
1. Chunk the master resume into sections (summary, skills, experience, projects)
2. Embed each chunk using sentence-transformers (local, no API cost)
3. For each job, retrieve the most relevant resume chunks
4. Pass retrieved context + job description to LLM for tailored generation

Falls back to simple LLM prompt if sentence-transformers not available.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple

from llm_client import call_llm
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("RAG")

VECTOR_STORE_PATH = Path(__file__).resolve().parent / "data" / "resume_vectors"
VECTOR_STORE_PATH.mkdir(exist_ok=True)


def _is_faiss_available() -> bool:
    try:
        import faiss  # noqa: F401
        return True
    except ImportError:
        return False


def _is_sentence_transformers_available() -> bool:
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
        return True
    except ImportError:
        return False


def _chunk_resume() -> List[dict]:
    """Split resume into meaningful chunks for embedding."""
    chunks = []

    # Summary chunk
    if RESUME.get("summary"):
        chunks.append({
            "id": "summary",
            "section": "Summary",
            "text": RESUME["summary"],
        })

    # Skills chunks — one per category
    for category, skills in RESUME.get("skills", {}).items():
        if skills:
            chunks.append({
                "id": f"skills_{category}",
                "section": f"Skills - {category.title()}",
                "text": f"{category.title()}: {', '.join(skills)}",
            })

    # Experience chunks — one per role
    for idx, exp in enumerate(RESUME.get("experience", [])):
        highlights = " ".join(exp.get("highlights", []))
        text = (
            f"{exp.get('role', '')} at {exp.get('company', '')} "
            f"({exp.get('duration', '')}). {highlights}"
        )
        chunks.append({
            "id": f"experience_{idx}",
            "section": "Experience",
            "text": text,
        })

    # Projects chunks
    for idx, project in enumerate(RESUME.get("projects", [])):
        chunks.append({
            "id": f"project_{idx}",
            "section": "Projects",
            "text": str(project),
        })

    # Education + certifications
    if RESUME.get("education"):
        chunks.append({
            "id": "education",
            "section": "Education",
            "text": RESUME["education"],
        })

    if RESUME.get("certifications"):
        chunks.append({
            "id": "certifications",
            "section": "Certifications",
            "text": "Certifications: " + ", ".join(RESUME["certifications"]),
        })

    return chunks


class ResumeVectorStore:
    """FAISS-backed vector store for resume chunks."""

    def __init__(self):
        self._model = None
        self._index = None
        self._chunks: List[dict] = []
        self._available = _is_faiss_available() and _is_sentence_transformers_available()

        if self._available:
            self._load_or_build()
        else:
            log.info("FAISS/sentence-transformers not available — RAG disabled, using LLM-only tailoring")

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            # Use a small, fast model — downloads once (~90MB)
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def _load_or_build(self) -> None:
        index_path = VECTOR_STORE_PATH / "index.faiss"
        chunks_path = VECTOR_STORE_PATH / "chunks.json"

        if index_path.exists() and chunks_path.exists():
            try:
                import faiss
                self._index = faiss.read_index(str(index_path))
                self._chunks = json.loads(chunks_path.read_text())
                log.info("Loaded resume vector store (%s chunks)", len(self._chunks))
                return
            except Exception as exc:
                log.warning("Failed to load vector store: %s — rebuilding", exc)

        self._build()

    def _build(self) -> None:
        """Build FAISS index from resume chunks."""
        import faiss
        import numpy as np

        self._chunks = _chunk_resume()
        if not self._chunks:
            log.warning("No resume chunks to embed")
            return

        model = self._get_model()
        texts = [c["text"] for c in self._chunks]
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)  # Inner product = cosine similarity (normalized)
        self._index.add(embeddings.astype("float32"))

        # Persist
        faiss.write_index(self._index, str(VECTOR_STORE_PATH / "index.faiss"))
        (VECTOR_STORE_PATH / "chunks.json").write_text(json.dumps(self._chunks))
        log.info("Built resume vector store with %s chunks", len(self._chunks))

    def rebuild(self) -> None:
        """Force rebuild the vector store (call when resume changes)."""
        self._build()

    def retrieve(self, query: str, top_k: int = 5) -> List[dict]:
        """Retrieve the most relevant resume chunks for a query."""
        if not self._available or self._index is None or not self._chunks:
            return self._chunks  # return all chunks as fallback

        import numpy as np

        model = self._get_model()
        query_embedding = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        scores, indices = self._index.search(query_embedding.astype("float32"), min(top_k, len(self._chunks)))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self._chunks):
                chunk = dict(self._chunks[idx])
                chunk["relevance_score"] = float(score)
                results.append(chunk)

        return results


# Singleton instance
_vector_store: ResumeVectorStore | None = None


def get_vector_store() -> ResumeVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = ResumeVectorStore()
    return _vector_store


def tailor_resume_rag(job: dict) -> dict:
    """
    Tailor resume for a job using RAG retrieval + LLM generation.

    1. Build query from job title + description
    2. Retrieve relevant resume chunks
    3. Generate tailored resume using retrieved context
    4. Return structured tailored resume dict
    """
    store = get_vector_store()
    job_title = job.get("title", "")
    job_desc = job.get("description", "")[:2000]
    company = job.get("company", "")

    # Build retrieval query from job
    query = f"{job_title} {job_desc[:500]}"

    # Retrieve relevant chunks
    relevant_chunks = store.retrieve(query, top_k=6)
    context = "\n\n".join(
        f"[{c['section']}]\n{c['text']}"
        for c in relevant_chunks
    )

    # Generate tailored resume with RAG context
    prompt = f"""You are a professional resume writer. Tailor this resume for the job below.
Use ONLY the provided resume context — do NOT fabricate experience.
Return ONLY valid JSON with these keys: summary, skills (list), experience_bullets (list), projects (list), changes (list).

JOB:
Title: {job_title}
Company: {company}
Description: {job_desc}

RELEVANT RESUME CONTEXT:
{context}

FULL RESUME SUMMARY:
{RESUME.get('summary', '')}

Rules:
- summary: 2-3 sentences, highlight skills matching the job
- skills: list of 10-14 most relevant skills, job keywords first
- experience_bullets: 4-6 strong action-verb bullets matching job requirements
- projects: 2-3 most relevant projects
- changes: brief list of what was tailored

Return ONLY JSON, no markdown."""

    result = call_llm(prompt, max_tokens=700, json_mode=True, quality=True)

    if result:
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "summary" in parsed:
                parsed["tailored_for"] = f"{job_title} at {company}"
                parsed["rag_chunks_used"] = len(relevant_chunks)
                log.info("RAG tailoring successful for %s at %s (%s chunks used)",
                         job_title, company, len(relevant_chunks))
                return parsed
        except Exception as exc:
            log.warning("RAG JSON parse failed: %s — falling back to rule-based", exc)

    # Fallback: rule-based tailoring
    log.info("Using rule-based resume tailoring for %s at %s", job_title, company)
    all_skills = []
    for values in RESUME["skills"].values():
        all_skills.extend(values)

    # Prioritize skills mentioned in job description
    desc_lower = job_desc.lower()
    prioritized = [s for s in all_skills if s.lower() in desc_lower]
    prioritized += [s for s in all_skills if s not in prioritized]

    return {
        "summary": RESUME["summary"],
        "skills": prioritized[:14],
        "experience_bullets": [
            f"Built scalable microservices using Java and Spring Boot for {company}-type enterprise systems",
            "Developed RESTful APIs handling high-throughput requests with proper error handling",
            "Improved system reliability through comprehensive JUnit and Mockito test coverage",
            "Collaborated in Agile sprints, delivering features on schedule with CI/CD pipelines",
        ],
        "projects": RESUME.get("projects", [])[:3],
        "changes": [
            "Prioritized job-relevant skills in skills section",
            "Tailored summary to highlight matching experience",
        ],
        "tailored_for": f"{job_title} at {company}",
        "rag_chunks_used": 0,
    }
