import os
import json
import re
import secrets
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator, field_validator
import requests

import pypdf
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

# Configure structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("paper_generator")

# Environment & Directory Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_db")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.2")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

# C-01: optional API token. Empty (default) preserves the existing local
# single-user workflow; set APP_AUTH_TOKEN to require a token on every request.
# This is a shared secret, not per-user authorization: every client that knows
# the token can see the same history. Never expose this API publicly on the
# strength of this token alone.
APP_AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "").strip()

# M1 hardening constants
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", str(25 * 1024 * 1024)))  # 25 MB per file
MAX_FILES_PER_REQUEST = int(os.environ.get("MAX_FILES_PER_REQUEST", "10"))
ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt", ".md"}
ALLOWED_SECTION_TYPES = {"MCQ", "Short", "Long", "True/False", "Fill-in-blanks"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# H-03: single source of truth for cosine-distance relevance. nomic-embed-text
# returns lower distance for closer matches; the same value is used by legacy
# generation, structured generation and single-question regeneration.
RAG_RELEVANCE_THRESHOLD = min(max(_env_float("RAG_RELEVANCE_THRESHOLD", 0.60), 0.0), 2.0)

app = FastAPI(
    title="Local Question Paper Generator API",
    description="Offline RAG Question Paper Generation for Teachers using Ollama & ChromaDB",
    version="1.0.0"
)

# C-01: loopback allow-list used when no shared secret is configured.
_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient", "::ffff:127.0.0.1"}


def _is_loopback_client(request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in _LOOPBACK_CLIENTS


# Enable CORS for React frontend (explicit origins only; proxy uses same-origin so this is a fallback)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_token(request, call_next):
    """C-01: optional shared-secret gate + loopback-only default.

    - OPTIONS (CORS preflight) is never gated.
    - With APP_AUTH_TOKEN set, every request needs ``X-API-Key: <token>`` or
      ``Authorization: Bearer <token>``.
    - With APP_AUTH_TOKEN unset, only loopback clients are allowed. This keeps
      the existing local frontend working while blocking LAN clients even if the
      process is accidentally started with APP_HOST=0.0.0.0.
    """
    if request.method == "OPTIONS":
        return await call_next(request)

    if not APP_AUTH_TOKEN:
        if _is_loopback_client(request):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Remote access is disabled. Set APP_AUTH_TOKEN to allow "
                          "authenticated remote clients."
            },
        )

    supplied = request.headers.get("X-API-Key", "").strip()
    if not supplied:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()

    if not secrets.compare_digest(
        supplied.encode("utf-8"), APP_AUTH_TOKEN.encode("utf-8")
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized. Provide a valid API token."},
        )
    return await call_next(request)


if APP_AUTH_TOKEN:
    logger.info("[AUTH] API token authentication enabled (X-API-Key or Bearer).")
else:
    logger.warning("[AUTH] APP_AUTH_TOKEN is not set: the API is unauthenticated. Keep it bound to localhost.")

# -----------------------------------------------------------------------------
# Ollama Helper Functions & Custom Chroma Embedding Function
# -----------------------------------------------------------------------------

class OllamaEmbeddingFunction(EmbeddingFunction):
    """Custom ChromaDB Embedding Function using Ollama nomic-embed-text."""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = EMBEDDING_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for text in input:
            try:
                # Try standard /api/embed endpoint
                resp = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": text},
                    headers={"Connection": "close"},
                    timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "embeddings" in data and len(data["embeddings"]) > 0:
                        embeddings.append(data["embeddings"][0])
                        continue

                # Fallback to legacy /api/embeddings
                resp = requests.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    headers={"Connection": "close"},
                    timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "embedding" in data:
                        embeddings.append(data["embedding"])
                        continue

                raise Exception(f"Ollama embedding HTTP {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"[EMBEDDING] Failed via Ollama model '{self.model}': {e}")
                raise RuntimeError(f"Ollama embedding service error ({self.model}): {e}")
        return embeddings



# Initialize ChromaDB Client
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
ollama_ef = OllamaEmbeddingFunction(base_url=OLLAMA_BASE_URL, model=EMBEDDING_MODEL)

notes_collection = chroma_client.get_or_create_collection(
    name="question_paper_notes",
    embedding_function=ollama_ef,
    metadata={"hnsw:space": "cosine"}
)

# M2: Exam Blueprint engine (deterministic, no LLM). Import lazily so a
# missing/invalid blueprint.py never breaks the core RAG endpoints.
try:
    from blueprint import BlueprintRequest as _BlueprintRequest, validate_blueprint as _validate_blueprint
    _BLUEPRINT_AVAILABLE = True
except Exception as _bp_err:  # pragma: no cover
    _BlueprintRequest = None  # type: ignore
    _validate_blueprint = None  # type: ignore
    _BLUEPRINT_AVAILABLE = False
    logger.warning(f"[BLUEPRINT] Module unavailable: {_bp_err}")

# M4: structured generation module (lazy so legacy endpoints never break).
try:
    from generate import (
        expand_slots as _expand_slots,
        build_structured_prompt as _build_structured_prompt,
        parse_structured_output as _parse_structured_output,
        validate_structured_paper as _validate_structured_paper,
        trim_unmatched_questions as _trim_unmatched_questions,
        post_fill_sources as _post_fill_sources,
        call_ollama_structured as _call_ollama_structured,
    )
    _GENERATE_AVAILABLE = True
except Exception as _gen_err:  # pragma: no cover
    _expand_slots = None  # type: ignore
    _GENERATE_AVAILABLE = False
    logger.warning(f"[GENERATE] Module unavailable: {_gen_err}")

# M5: deterministic critic engine (lazy; offline-capable).
try:
    from validator import validate_paper as _validate_paper
    _VALIDATOR_AVAILABLE = True
except Exception as _val_err:  # pragma: no cover
    _validate_paper = None  # type: ignore
    _VALIDATOR_AVAILABLE = False
    logger.warning(f"[VALIDATOR] Module unavailable: {_val_err}")

# M6: duplicate detection + single-question regeneration (lazy).
try:
    from duplicates import find_duplicates as _find_duplicates
    _DUPLICATES_AVAILABLE = True
except Exception as _dup_err:  # pragma: no cover
    _find_duplicates = None  # type: ignore
    _DUPLICATES_AVAILABLE = False
    logger.warning(f"[DUPLICATES] Module unavailable: {_dup_err}")

# M7: analytics + heuristic quality (lazy; offline).
try:
    from analytics import compute_analytics as _compute_analytics
    _ANALYTICS_AVAILABLE = True
except Exception as _an_err:  # pragma: no cover
    _compute_analytics = None  # type: ignore
    _ANALYTICS_AVAILABLE = False
    logger.warning(f"[ANALYTICS] Module unavailable: {_an_err}")

# M9: server-side PDF export (lazy; reportlab).
try:
    from export_pdf import build_pdf as _build_pdf
    _PDF_AVAILABLE = True
except Exception as _pdf_err:  # pragma: no cover
    _build_pdf = None  # type: ignore
    _PDF_AVAILABLE = False
    logger.warning(f"[PDF] Module unavailable: {_pdf_err}")

# M10: lightweight history (stdlib sqlite; lazy).
try:
    from history import init_db as _history_init, save_paper as _history_save, \
        list_papers as _history_list, get_paper as _history_get, delete_paper as _history_delete
    _history_init(os.path.join(BASE_DIR, "papers.db"))
    _HISTORY_AVAILABLE = True
except Exception as _hist_err:  # pragma: no cover
    _HISTORY_AVAILABLE = False
    logger.warning(f"[HISTORY] Module unavailable: {_hist_err}")

# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

class SectionConfig(BaseModel):
    type: str = Field(..., description="e.g. MCQ, Short, Long, True/False, Fill in the blanks")
    count: int = Field(..., ge=1, le=50, description="Number of questions in this section")
    marks_per_q: int = Field(..., ge=1, le=100, description="Marks per question")

    @field_validator("type")
    @classmethod
    def validate_section_type(cls, v: str) -> str:
        # FIX 1: single shared allowlist enforced on SectionConfig itself, so the
        # legacy (/generate-paper) and structured (/api/generate-structured) paths
        # reject invalid types identically with HTTP 422. Allowed set is unchanged (M1).
        if v not in ALLOWED_SECTION_TYPES:
            raise ValueError(
                f"Invalid section type '{v}'. Allowed: {sorted(ALLOWED_SECTION_TYPES)}"
            )
        return v

class GeneratePaperRequest(BaseModel):
    subject: str = Field(..., description="Subject or Topic name")
    total_marks: int = Field(..., ge=1, description="Total marks for the question paper")
    difficulty: str = Field("Medium", description="Easy, Medium, or Hard")
    instructions: Optional[List[str]] = Field(None, description="General exam instructions")
    sections: List[SectionConfig] = Field(..., description="List of question sections")
    # Header-only metadata for the Symbiosis exam layout (subject, programme,
    # semester, batch, course_code, date, day, time_slot...). Never influences
    # generation or validation; missing keys render as blanks.
    exam_meta: Optional[Dict[str, str]] = Field(None)

    @model_validator(mode="after")
    def validate_types_and_difficulty(self):
        # Section types are enforced on SectionConfig itself (FIX 1: shared by both
        # generation paths). Marks-sum stays in the endpoint AFTER RAG gates so that
        # "no documents" (400) and "bad topic" (400) keep priority for existing clients/tests.
        # Validate difficulty value
        if self.difficulty not in {"Easy", "Medium", "Hard"}:
            raise ValueError("Difficulty must be one of: Easy, Medium, Hard")
        return self

# -----------------------------------------------------------------------------
# Helper Utils & Parsers
# -----------------------------------------------------------------------------

def resolve_session_id(x_session_id: Optional[str]) -> str:
    if x_session_id and x_session_id.strip():
        return x_session_id.strip()
    return f"session_{uuid.uuid4().hex[:8]}"

def check_ollama_status():
    """Checks live connection to local Ollama instance with fast 2s timeout and anti-connection reuse."""
    try:
        resp = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags",
            headers={"Cache-Control": "no-cache", "Connection": "close"},
            timeout=2
        )
        if resp.status_code != 200:
            return False, f"Ollama HTTP {resp.status_code}", []
        
        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        return True, "Ollama Online", models
    except Exception as e:
        return False, f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Ensure Ollama service is running.", []

def validate_educational_topic(subject: str) -> str:
    """Validate that the input is a meaningful educational subject/topic.

    Short but legitimate acronyms and technical terms (AI, OS, C++, R, Rhythm)
    must pass, so this deliberately avoids a minimum length, a 2+ letter word
    regex and a fixed vowel ratio. It rejects empty/no-letter input, repeated
    patterns and obvious keyboard mash instead.
    """
    clean = subject.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Subject title cannot be empty.")
    if len(clean) > 200:
        raise HTTPException(status_code=400, detail="Subject title must be at most 200 characters long.")

    # A single lowercase letter ("a") is not a meaningful topic; single
    # uppercase letters ("R") are valid course/acronym inputs.
    if len(clean) == 1 and clean.isalpha() and clean.islower():
        raise HTTPException(status_code=400, detail="Subject title must contain a meaningful educational topic.")

    letters = re.findall(r'[a-zA-Z]', clean)
    if not letters:
        raise HTTPException(status_code=400, detail="Subject title must contain recognizable educational words or terminology.")
    # Technical names (C++, C#, 3D, COVID-19) still contain enough letters;
    # strings that are almost entirely digits/symbols do not.
    compact = re.sub(r'\s+', '', clean)
    if len(letters) / len(compact) < 0.25:
        raise HTTPException(status_code=400, detail="Subject title must contain valid educational text.")

    # Reject repeated single character (e.g. 'aaaa', '1111') or repeated
    # short pattern ('xyzxyz', 'abcabc').
    if re.fullmatch(r'(.)\1+', clean, re.IGNORECASE) or re.fullmatch(r'(.{2,4})\1+', clean, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Please enter a meaningful educational subject title.")

    # Tokens keep technical punctuation (C++, C#, COVID-19) but always start
    # with a letter, so pure numbers/symbols are rejected above.
    tokens = re.findall(r'[A-Za-z][A-Za-z0-9+#._-]*', clean)
    if not tokens:
        raise HTTPException(status_code=400, detail="Subject title must contain recognizable educational words or terminology.")

    keyboard_rows = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
    for token in tokens:
        word = re.sub(r'[^a-z]', '', token.lower())
        # Short acronyms/terms (AI, OS, DBMS, HTML, R) are valid as-is.
        if len(word) < 5:
            continue
        vowels = len(re.findall(r'[aeiouy]', word))
        # Low threshold: real words such as "rhythms" have few vowels. Pure
        # consonant strings and keyboard rows are still rejected below.
        if vowels == 0 or (vowels / len(word)) < 0.12:
            raise HTTPException(status_code=400, detail="Invalid educational subject input detected. Please provide a real topic or subject name.")
        # Keyboard mash such as qwerty / asdfgh / zxcvbn.
        if any(word in row or word in row[::-1] for row in keyboard_rows):
            raise HTTPException(status_code=400, detail="Invalid educational subject input detected. Please provide a real topic or subject name.")

    return clean



def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from PDF using pypdf with pdfplumber fallback (kept for compat)."""
    return "\n\n".join(seg["text"] for seg in extract_segments_from_pdf(filepath))


def extract_segments_from_pdf(filepath: str) -> List[Dict[str, str]]:
    """M3: page-aware PDF extraction → [{locator: 'p.3', text}]."""
    segments: List[Dict[str, str]] = []
    try:
        reader = pypdf.PdfReader(filepath)
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                segments.append({"locator": f"p.{i + 1}", "text": t})
    except Exception as e:
        logger.warning(f"[PARSING] pypdf issue on {filepath}: {e}")

    if not segments or len("".join(s["text"] for s in segments).strip()) < 50:
        segments = []
        try:
            with pdfplumber.open(filepath) as pdf:
                for i, page in enumerate(pdf.pages):
                    try:
                        t = page.extract_text() or ""
                    except Exception:
                        t = ""
                    if t and t.strip():
                        segments.append({"locator": f"p.{i + 1}", "text": t})
        except Exception as e:
            logger.error(f"[PARSING] pdfplumber issue on {filepath}: {e}")

    return segments

def extract_text_from_pptx(filepath: str) -> str:
    """Extract text from PowerPoint presentations (kept for compat)."""
    return "\n\n".join(seg["text"] for seg in extract_segments_from_pptx(filepath))


def extract_segments_from_pptx(filepath: str) -> List[Dict[str, str]]:
    """M3: slide-aware PPTX extraction → [{locator: 'Slide 2', text}]."""
    segments: List[Dict[str, str]] = []
    try:
        import pptx
        prs = pptx.Presentation(filepath)
        for idx, slide in enumerate(prs.slides):
            slide_texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    slide_texts.append(shape.text.strip())
            if slide_texts:
                segments.append({"locator": f"Slide {idx + 1}", "text": "\n".join(slide_texts)})
    except Exception as e:
        logger.error(f"[PARSING] PPTX extraction issue on {filepath}: {e}")
    return segments

def extract_text_from_docx(filepath: str) -> str:
    """Extract text from Word documents (kept for compat)."""
    return "\n\n".join(seg["text"] for seg in extract_segments_from_docx(filepath))


def extract_segments_from_docx(filepath: str) -> List[Dict[str, str]]:
    """M3: paragraph-group-aware DOCX extraction → [{locator: 'para 1-10', text}].

    Groups of 10 paragraphs keep a rough source position without
    exploding the chunk count on long documents.
    """
    segments: List[Dict[str, str]] = []
    try:
        import docx
        doc = docx.Document(filepath)
        paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        for start in range(0, len(paras), 10):
            group = paras[start:start + 10]
            if group:
                end = min(start + 10, len(paras))
                segments.append({"locator": f"para {start + 1}-{end}", "text": "\n".join(group)})
    except Exception as e:
        logger.error(f"[PARSING] DOCX extraction issue on {filepath}: {e}")
    return segments

def clean_json_response(raw_response: str) -> str:
    """Extract valid JSON from LLM markdown codeblock wrappers."""
    raw = raw_response.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    
    match = re.search(r'(\{[\s\S]*\})', raw)
    if match:
        return match.group(1)
    return raw


def validate_legacy_paper_shape(paper: Any) -> None:
    """Reject structurally unusable LLM output from the legacy generator.

    The legacy endpoint historically returned whatever JSON the model produced
    (after only checking for an ``error`` key). A response with no ``sections``
    reached the UI as a successful paper and broke downstream review/export.

    This keeps the response contract unchanged for valid papers and raises
    ``ValueError`` so the endpoint can convert malformed model output into a
    controlled HTTP 502.
    """
    if not isinstance(paper, dict):
        raise ValueError("paper output must be a JSON object")

    sections = paper.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("'sections' must be a non-empty list")

    for s_idx, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise ValueError(f"section {s_idx} must be a JSON object")
        questions = section.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"section {s_idx} must contain a non-empty 'questions' list")
        for q_idx, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                raise ValueError(f"section {s_idx}, question {q_idx} must be a JSON object")
            if not str(question.get("question", "")).strip():
                raise ValueError(f"section {s_idx}, question {q_idx} is missing 'question' text")


def retrieve_relevant(
    query: str,
    session_id: str,
    unit: Optional[str] = None,
    n_results: int = 8,
    allow_fallback: bool = True,
) -> dict:
    """M3: targeted retrieval helper (topic/unit-aware).

    Filters by session_id and optionally unit. Old chunks without a
    'unit' field simply never match a unit filter (backward compatible).
    Returns {documents, distances, metadatas} lists (possibly empty).

    ``allow_fallback=False`` is used by generation/regeneration: a unit with
    no matching chunks must be reported as missing rather than silently
    replaced with another unit's material.
    """
    unit_filter = unit.strip() if unit and unit.strip() and unit.strip().lower() != "all" else None
    where: Dict[str, Any] = {"session_id": session_id}
    if unit_filter:
        where = {"$and": [{"session_id": session_id}, {"unit": unit_filter}]}
    try:
        count_res = notes_collection.get(where={"session_id": session_id})
        doc_count = len(count_res.get("ids", []))
    except Exception:
        doc_count = 0
    if doc_count == 0:
        return {"documents": [], "distances": [], "metadatas": []}
    try:
        res = notes_collection.query(
            query_texts=[query],
            where=where,
            n_results=min(max(1, n_results), doc_count),
            include=["documents", "distances", "metadatas"],
        )
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        if unit_filter:
            # Never return another unit's chunks, even if the vector store
            # ignores the filter or the metadata is malformed.
            matched = [(d, dist, m) for d, dist, m in zip(docs, dists, metas)
                       if str((m or {}).get("unit", "")).strip().casefold() == unit_filter.casefold()]
            docs = [d for d, _, _ in matched]
            dists = [dist for _, dist, _ in matched]
            metas = [m for _, _, m in matched]
        # Fallback: unit filter too strict → retry without it (caller sees fallback=True).
        if not docs and unit_filter and allow_fallback:
            res = notes_collection.query(
                query_texts=[query],
                where={"session_id": session_id},
                n_results=min(max(1, n_results), doc_count),
                include=["documents", "distances", "metadatas"],
            )
            docs = (res.get("documents") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            return {"documents": docs, "distances": dists, "metadatas": metas, "fallback": True}
        return {"documents": docs, "distances": dists, "metadatas": metas}
    except Exception as e:
        logger.error(f"[RETRIEVAL] Targeted query failed: {e}")
        return {"documents": [], "distances": [], "metadatas": []}

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@app.get("/health")
@app.get("/api/status")
def get_status(
    response: Response,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """Health check endpoint to report live Ollama & session database status with anti-caching headers."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    session_id = resolve_session_id(x_session_id)
    connected, message, models = check_ollama_status()
    
    has_llm = any(LLM_MODEL in m for m in models)
    has_embed = any(EMBEDDING_MODEL in m for m in models)
    
    # Get document count for current session
    doc_count = 0
    try:
        res = notes_collection.get(where={"session_id": session_id})
        doc_count = len(res.get("ids", []))
    except Exception as e:
        logger.warning(f"[SESSION] Failed to count session docs for '{session_id}': {e}")

    logger.info(f"[STATUS] Checked Ollama ({'Online' if connected else 'Offline'}), Session: '{session_id}', Chunks: {doc_count}")

    return {
        "status": "online" if connected else "offline",
        "ollama_connected": connected,
        "ollama_url": OLLAMA_BASE_URL,
        "message": message,
        "models_installed": models,
        "required_models": {
            "llm": {"name": LLM_MODEL, "installed": has_llm},
            "embedding": {"name": EMBEDDING_MODEL, "installed": has_embed}
        },
        "chromadb": {
            "status": "ready",
            "document_count": doc_count,
            "session_id": session_id
        }
    }

@app.post("/upload-notes")
@app.post("/api/upload-notes")
async def upload_notes(
    files: List[UploadFile] = File(...),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    unit_label: Optional[str] = Form(None),
):
    """
    1. Validates files and extracts page-aware segments.
    2. Splits each segment into text chunks (1000 chars, 100 overlap).
    3. Embeds chunks via Ollama nomic-embed-text with session_id + page/unit/section
       metadata into ChromaDB (M3).
    Optional form field `unit_label` overrides heuristic unit detection for all
    files in this request (e.g. teacher tags upload as 'Unit 3').
    """
    """
    FIX 3 order (cheap deterministic checks first — Ollama is never needed to
    reject an obviously invalid file):
      count → extension → filename sanitization → size → empty →
      duplicate/content-hash → Ollama availability → parse → embed → store.
    """
    session_id = resolve_session_id(x_session_id)
    # Sanitize session_id for filesystem use (M1: prevent path traversal via header)
    safe_session = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64] or "session_default"
    logger.info(f"[UPLOAD] Processing request for session: '{session_id}' with {len(files)} file(s)")

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum {MAX_FILES_PER_REQUEST} files per request."
        )

    processed_files = []
    skipped_files = []
    total_chunks = 0

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )

    # ---- Phase 1: deterministic intake validation (no Ollama needed) ----
    import hashlib
    accepted: List[Dict[str, Any]] = []
    for file in files:
        raw_name = file.filename or "unnamed"
        safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", os.path.basename(raw_name))[:150]
        file_ext = os.path.splitext(safe_filename)[1].lower()
        # M1: strict extension whitelist; legacy .ppt is NOT supported (python-pptx needs .pptx)
        if file_ext == ".ppt":
            skipped_files.append({"filename": safe_filename, "reason": "Legacy .ppt not supported. Please save as .pptx and re-upload."})
            logger.warning(f"[UPLOAD] Rejected legacy .ppt file '{safe_filename}'")
            continue
        if file_ext not in ALLOWED_EXTENSIONS:
            skipped_files.append({"filename": safe_filename, "reason": f"Unsupported type '{file_ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"})
            logger.warning(f"[UPLOAD] Rejected unsupported type '{safe_filename}' ({file_ext})")
            continue

        logger.info(f"[UPLOAD] Ingesting file '{safe_filename}' ({file_ext})")

        contents = await file.read()
        if len(contents) == 0:
            logger.warning(f"[UPLOAD] File '{safe_filename}' is empty (0 bytes)")
            skipped_files.append({"filename": safe_filename, "reason": "Empty file (0 bytes)."})
            continue
        if len(contents) > MAX_FILE_SIZE_BYTES:
            logger.warning(f"[UPLOAD] File '{safe_filename}' exceeds {MAX_FILE_SIZE_BYTES} bytes")
            skipped_files.append({"filename": safe_filename, "reason": f"File exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit."})
            continue

        # M1: content-hash deduplication within this session (avoid re-embedding identical uploads)
        file_hash = hashlib.sha256(contents).hexdigest()[:16]
        try:
            existing = notes_collection.get(where={"session_id": session_id}, include=["metadatas"])
            if any((m or {}).get("file_hash") == file_hash for m in existing.get("metadatas", [])):
                logger.info(f"[UPLOAD] Duplicate content detected for '{safe_filename}' (hash {file_hash}), skipping.")
                skipped_files.append({"filename": safe_filename, "reason": "Duplicate content already indexed in this session."})
                continue
        except Exception as e:
            logger.warning(f"[UPLOAD] Dedup check failed for '{safe_filename}': {e}")

        accepted.append({
            "safe_filename": safe_filename, "file_ext": file_ext,
            "contents": contents, "file_hash": file_hash,
        })

    if not accepted:
        # FIX 3: purely invalid batches are rejected here with file-specific
        # reasons — this path never touches Ollama, so it works offline.
        reasons = "; ".join(f"{s['filename']}: {s['reason']}" for s in skipped_files) or "no files"
        raise HTTPException(status_code=400, detail=f"No valid files to process. {reasons}")

    # ---- Phase 2: Ollama-dependent processing ----
    connected, msg, _ = check_ollama_status()
    if not connected:
        logger.error(f"[UPLOAD] Ollama service offline: {msg}")
        raise HTTPException(status_code=503, detail=f"Ollama Service Offline. Please start Ollama and try again.")

    for item in accepted:
        safe_filename = item["safe_filename"]
        file_ext = item["file_ext"]
        contents = item["contents"]
        file_hash = item["file_hash"]
        # Session-prefixed storage name so DELETE /api/notes can clean up per-session files (M1)
        file_path = os.path.join(UPLOADS_DIR, f"{safe_session}_{uuid.uuid4().hex}_{safe_filename}")

        with open(file_path, "wb") as f:
            f.write(contents)

        # M3: page-aware segment extraction (each segment keeps its locator).
        segments: List[Dict[str, str]] = []
        if file_ext == ".pdf":
            segments = extract_segments_from_pdf(file_path)
        elif file_ext == ".pptx":
            segments = extract_segments_from_pptx(file_path)
        elif file_ext == ".docx":
            segments = extract_segments_from_docx(file_path)
        else:
            try:
                decoded = contents.decode("utf-8", errors="ignore")
                # Chunk plain text into ~3000-char pseudo-segments for locator granularity.
                segments = [
                    {"locator": f"part {i + 1}", "text": decoded[j:j + 3000]}
                    for i, j in enumerate(range(0, len(decoded), 3000))
                    if decoded[j:j + 3000].strip()
                ]
            except Exception as e:
                logger.error(f"[PARSING] Failed decoding '{safe_filename}': {e}")

        total_chars = sum(len(s["text"]) for s in segments)
        logger.info(f"[PARSING] Extracted {total_chars} characters in {len(segments)} segment(s) from '{safe_filename}'")

        if total_chars < 50 or not segments:
            logger.warning(f"[PARSING] Insufficient readable text ({total_chars} chars) extracted from '{safe_filename}'")
            try:
                os.remove(file_path)
            except OSError:
                pass
            skipped_files.append({"filename": safe_filename, "reason": "Insufficient readable text (<50 chars). Scanned PDFs need OCR."})
            continue

        # M3: split per segment so every chunk inherits page/unit/section.
        try:
            from metadata_enrich import enrich_segment as _enrich_segment
        except Exception:
            _enrich_segment = lambda text, filename="", override_unit="": {"unit": (override_unit or "General"), "section": ""}  # noqa: E731
        override = (unit_label or "").strip()
        all_chunks: List[str] = []
        all_metas: List[Dict[str, Any]] = []
        for seg in segments:
            seg_chunks = text_splitter.split_text(seg["text"].strip())
            enrich = _enrich_segment(seg["text"], filename=safe_filename, override_unit=override)
            for c in seg_chunks:
                all_chunks.append(c)
                all_metas.append({"page": seg["locator"], "unit": enrich["unit"], "section": enrich.get("section", "")})
        if not all_chunks:
            continue

        file_uuid = uuid.uuid4().hex[:8]
        ids = [f"{session_id}_{file_uuid}_{i}" for i in range(len(all_chunks))]
        uploaded_at = datetime.now().isoformat()
        metadatas = [{
            "session_id": session_id,
            "filename": safe_filename,
            "chunk_index": i,
            "total_chunks": len(all_chunks),
            "file_hash": file_hash,
            "stored_path": os.path.basename(file_path),
            "page": all_metas[i].get("page", ""),
            "unit": all_metas[i].get("unit", "General"),
            "section": all_metas[i].get("section", ""),
            "uploaded_at": uploaded_at
        } for i in range(len(all_chunks))]

        try:
            logger.info(f"[CHUNKING] Split '{safe_filename}' into {len(all_chunks)} chunks across {len(segments)} segment(s). Generating embeddings...")
            notes_collection.add(
                documents=all_chunks,
                metadatas=metadatas,
                ids=ids
            )
            total_chunks += len(all_chunks)
            units = sorted({m["unit"] for m in metadatas})
            processed_files.append({
                "filename": safe_filename,
                "chunks_count": len(all_chunks),
                "segments": len(segments),
                "units": units,
            })
            logger.info(f"[EMBEDDING] Embedded & stored {len(all_chunks)} chunks for '{safe_filename}'")
        except Exception as e:
            logger.error(f"[EMBEDDING] Ingestion error for '{safe_filename}': {e}")
            raise HTTPException(status_code=502, detail=f"Failed to embed document '{safe_filename}'. Please retry.")

    if not processed_files:
        raise HTTPException(
            status_code=400,
            detail="Could not extract sufficient readable text from the uploaded file(s). Please upload valid text documents, PDFs, PPTX, or DOCX."
        )

    # Get updated session count
    res = notes_collection.get(where={"session_id": session_id})
    session_count = len(res.get("ids", []))

    return {
        "message": f"Successfully processed {len(processed_files)} file(s) into {total_chunks} chunks.",
        "processed_files": processed_files,
        "skipped_files": skipped_files,
        "total_documents_in_db": session_count
    }

@app.get("/api/notes")
def get_notes(x_session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """Lists current files stored in vector database for the active session (M3: + pages/units)."""
    session_id = resolve_session_id(x_session_id)
    try:
        results = notes_collection.get(where={"session_id": session_id}, include=["metadatas"])
        ids = results.get("ids", [])
        if not ids:
            return {"documents_count": 0, "files": []}

        file_stats: Dict[str, Dict[str, Any]] = {}
        for meta in results.get("metadatas", []):
            if not meta or "filename" not in meta:
                continue
            fname = meta["filename"]
            entry = file_stats.setdefault(fname, {"filename": fname, "chunks": 0, "pages": set(), "units": set()})
            entry["chunks"] += 1
            if meta.get("page"):
                entry["pages"].add(str(meta["page"]))
            if meta.get("unit"):
                entry["units"].add(str(meta["unit"]))

        files_list = [{
            "filename": v["filename"],
            "chunks": v["chunks"],
            "pages": sorted(v["pages"]),
            "units": sorted(v["units"]),
        } for v in file_stats.values()]
        return {
            "documents_count": len(ids),
            "files": files_list
        }
    except Exception as e:
        logger.error(f"[SESSION] Error fetching notes for session '{session_id}': {e}")
        return {"documents_count": 0, "files": []}


class RetrievalPreviewRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    unit: Optional[str] = Field(None, description="Optional unit filter, e.g. 'Unit 3'")
    top_k: int = Field(5, ge=1, le=20)


class StructuredGenerateRequest(BaseModel):
    """M4: sections define counts/marks (as legacy); blueprint optionally steers
    per-question unit/difficulty/Bloom assignment. Total marks must match sections."""
    subject: str = Field(..., min_length=3, max_length=200)
    total_marks: int = Field(..., ge=1)
    difficulty: str = Field("Medium")
    instructions: Optional[List[str]] = Field(None)
    sections: List[SectionConfig] = Field(..., min_length=1)
    exam_name: Optional[str] = Field(None, max_length=200)
    institution: Optional[str] = Field(None, max_length=200)
    duration_minutes: Optional[int] = Field(None, ge=15, le=600)
    blueprint: Optional[Dict[str, Any]] = Field(None, description="BlueprintRequest JSON (optional)")
    # Header-only metadata, same contract as GeneratePaperRequest.exam_meta.
    exam_meta: Optional[Dict[str, str]] = Field(None)

    @model_validator(mode="after")
    def validate_difficulty(self):
        # FIX 1: same difficulty values as the legacy path (SectionConfig types
        # are shared automatically). Marks-sum is checked in the endpoint after
        # RAG gates, mirroring legacy behavior.
        if self.difficulty not in {"Easy", "Medium", "Hard"}:
            raise ValueError("Difficulty must be one of: Easy, Medium, Hard")
        return self


@app.post("/api/retrieval/preview")
def retrieval_preview(
    request: RetrievalPreviewRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """M3: debug/viva endpoint — show what RAG would retrieve for a query.

    No LLM call. Returns top-k chunks with distance + page/unit/section metadata
    so teachers (and viva examiners) can see grounding before generation.
    """
    session_id = resolve_session_id(x_session_id)
    res = retrieve_relevant(request.query, session_id, unit=request.unit, n_results=request.top_k)
    docs = res.get("documents", [])
    dists = res.get("distances", [])
    metas = res.get("metadatas", [])
    results = []
    for i, (doc, dist, meta) in enumerate(zip(docs, dists, metas)):
        meta = meta or {}
        results.append({
            "rank": i + 1,
            "distance": round(float(dist), 4),
            "similarity": round(1.0 - float(dist), 4),
            "filename": meta.get("filename", ""),
            "page": meta.get("page", ""),
            "unit": meta.get("unit", "General"),
            "section": meta.get("section", ""),
            "snippet": (doc or "")[:500],
        })
    return {
        "query": request.query,
        "unit_filter": request.unit,
        "fallback_to_unfiltered": bool(res.get("fallback", False)),
        "count": len(results),
        "results": results,
    }

@app.delete("/api/notes")
def clear_notes(x_session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """Clears all stored notes for the active session from ChromaDB + per-session upload files."""
    session_id = resolve_session_id(x_session_id)
    safe_session = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64] or "session_default"
    try:
        # Collect stored filenames before deleting vectors (for file cleanup)
        stored_to_delete = set()
        try:
            existing = notes_collection.get(where={"session_id": session_id}, include=["metadatas"])
            for m in existing.get("metadatas", []):
                if m and m.get("stored_path"):
                    stored_to_delete.add(m["stored_path"])
        except Exception as e:
            logger.warning(f"[SESSION] Could not list stored paths for '{session_id}': {e}")
        notes_collection.delete(where={"session_id": session_id})
        # M1 fix (P4): remove orphaned per-session files from uploads/ (old files without prefix are left alone)
        removed_files = 0
        for fname in list(stored_to_delete):
            try:
                fpath = os.path.join(UPLOADS_DIR, os.path.basename(fname))
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    removed_files += 1
            except OSError as e:
                logger.warning(f"[SESSION] Could not remove upload file '{fname}': {e}")
        # Best-effort: also remove any session-prefixed leftovers
        try:
            for fname in os.listdir(UPLOADS_DIR):
                if fname.startswith(safe_session + "_") and fname not in stored_to_delete:
                    try:
                        os.remove(os.path.join(UPLOADS_DIR, fname))
                        removed_files += 1
                    except OSError:
                        pass
        except OSError as e:
            logger.warning(f"[SESSION] Upload dir scan failed: {e}")
        logger.info(f"[SESSION] Cleared all vector chunks for session: '{session_id}' ({removed_files} files removed)")
        return {"message": "Session reference notes cleared successfully.", "documents_count": 0, "files_removed": removed_files}
    except Exception as e:
        logger.error(f"[SESSION] Error clearing session '{session_id}': {e}")
        raise HTTPException(status_code=500, detail="Failed to clear session notes.")

@app.post("/api/blueprint/validate")
def validate_blueprint_endpoint(payload: dict):
    """M2: Validate exam blueprint math (topics/difficulty/bloom sum to 100, type marks reconcile).

    Accepts the BlueprintRequest JSON shape; returns {ok, errors, expanded}.
    Deterministic — no Ollama/Chroma dependency so teachers get instant feedback.
    """
    if not _BLUEPRINT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Blueprint engine unavailable.")
    try:
        bp = _BlueprintRequest(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid blueprint shape: {e}")
    result = _validate_blueprint(bp)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail="; ".join(result["errors"]))
    return result


@app.post("/generate-paper")
@app.post("/api/generate-paper")
def generate_paper(
    request: GeneratePaperRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """
    Strict RAG Groundedness Pipeline:
    1. Check Ollama live connectivity.
    2. RAG GATE 1: Verify active session document availability (No docs = No generation).
    3. RAG GATE 2: Educational Topic Sanity Validation.
    4. RAG GATE 3: Semantic retrieval & strict relevance check using the shared
       RAG_RELEVANCE_THRESHOLD (env-configurable cosine distance).
    5. Construct strict grounded prompt (Zero external knowledge allowed).
    6. Send request to Ollama 'llama3.2' for structured JSON question paper.
    7. Validate JSON & grounding output.
    """
    session_id = resolve_session_id(x_session_id)
    logger.info(f"[RAG_GATE] Starting question paper generation for session '{session_id}', Subject: '{request.subject}'")

    # Step 1: Check Ollama Live Status
    connected, msg, models = check_ollama_status()
    if not connected:
        logger.error(f"[OLLAMA] Service offline at {OLLAMA_BASE_URL}")
        raise HTTPException(
            status_code=503,
            detail="Ollama Service is currently offline. Please start Ollama locally and try again."
        )

    # Step 2: RAG GATE 1 - Active Session Document Availability Check
    try:
        session_docs = notes_collection.get(where={"session_id": session_id})
        doc_count = len(session_docs.get("ids", []))
    except Exception as e:
        logger.error(f"[RAG_GATE] Failed checking session docs for '{session_id}': {e}")
        doc_count = 0

    if doc_count == 0:
        logger.warning(f"[RAG_GATE] Refused generation: No documents in session '{session_id}'")
        raise HTTPException(
            status_code=400,
            detail="No study material is available yet. Please upload valid notes, PPT, PDF, or reference material before generating a question paper."
        )

    # Step 3: RAG GATE 2 - Educational Topic Input Sanity Validation
    clean_subject = validate_educational_topic(request.subject)

    # Step 3b (M1): Backend marks consistency check (was missing entirely).
    # Placed AFTER gates 1-2 so empty-session / bad-topic errors keep priority.
    expected_marks = sum(s.count * s.marks_per_q for s in request.sections)
    if request.total_marks != expected_marks:
        logger.warning(f"[VALIDATION] total_marks {request.total_marks} != sections sum {expected_marks}")
        raise HTTPException(
            status_code=400,
            detail=f"total_marks ({request.total_marks}) does not match sections sum ({expected_marks}). Please fix the section marks."
        )

    # Step 4: RAG GATE 3 - Semantic Retrieval & Strict Cosine Distance Relevance Gate
    search_query = f"{clean_subject} " + " ".join([s.type for s in request.sections])
    logger.info(f"[RETRIEVAL] Querying ChromaDB for session '{session_id}' with: '{search_query}'")

    try:
        search_results = notes_collection.query(
            query_texts=[search_query],
            where={"session_id": session_id},
            n_results=min(8, doc_count),
            include=["documents", "distances", "metadatas"]
        )
    except Exception as e:
        logger.error(f"[RETRIEVAL] ChromaDB query error: {e}")
        raise HTTPException(status_code=500, detail=f"Database retrieval error: {e}")

    retrieved_docs = search_results.get("documents", [[]])[0]
    distances = search_results.get("distances", [[]])[0]

    if not retrieved_docs or not distances:
        logger.warning(f"[RAG_GATE] Refused generation: Zero chunks returned from query")
        raise HTTPException(
            status_code=422,
            detail=f"No relevant content found in your uploaded study material for topic '{clean_subject}'."
        )

    min_distance = min(distances)
    logger.info(f"[RELEVANCE] Retrieved {len(retrieved_docs)} chunks. Best similarity cosine distance: {min_distance:.4f}")

    # H-03: shared cosine-distance threshold (see RAG_RELEVANCE_THRESHOLD).
    valid_chunks = []
    for doc, dist in zip(retrieved_docs, distances):
        if dist <= RAG_RELEVANCE_THRESHOLD:
            valid_chunks.append(doc)

    # Check for keyword overlap as additional grounding check
    subject_words = set(re.findall(r'\w+', clean_subject.lower()))
    context_text_lower = " ".join(retrieved_docs).lower()
    has_keyword_overlap = any(word in context_text_lower for word in subject_words if len(word) > 2)

    if not valid_chunks or min_distance > RAG_RELEVANCE_THRESHOLD or not has_keyword_overlap:
        logger.warning(
            f"[RAG_GATE] Refused generation: Best distance {min_distance:.4f} > {RAG_RELEVANCE_THRESHOLD} or keyword overlap missing"
        )
        raise HTTPException(
            status_code=422,
            detail=f"No relevant content found in your uploaded study material for topic: '{clean_subject}'. Please upload notes covering this topic."
        )

    logger.info(f"[RAG_GATE] Grounding Passed! Using {len(valid_chunks)} highly relevant chunks for prompt.")
    retrieved_context = "\n---\n".join(valid_chunks)

    # Step 5: Construct Strict Grounded System & User Prompt
    sections_prompt_desc = []
    for s in request.sections:
        sections_prompt_desc.append(
            f"- {s.count} question(s) of type '{s.type}' ({s.marks_per_q} mark(s) each, Total: {s.count * s.marks_per_q} marks)"
        )

    system_instruction = (
        "You are an expert academic examiner creating a professional question paper for students.\n"
        "STRICT GROUNDING REQUIREMENT:\n"
        "1. You MUST generate all questions and answer keys using ONLY the facts, definitions, and formulas provided in the REFERENCE STUDY MATERIAL below.\n"
        "2. Do NOT use external pretrained knowledge. Do NOT introduce topics or concepts not present in the material.\n"
        "3. Do NOT invent definitions, chapters, or concepts.\n"
        "4. If the supplied material does NOT contain sufficient information for the requested topic, respond ONLY with JSON: {\"error\": \"insufficient_context\", \"message\": \"The uploaded study material does not contain sufficient information for this topic.\"}.\n"
        "5. Respond ONLY with valid JSON. Do NOT include markdown commentary or text outside the JSON structure."
    )

    prompt = f"""
=== REFERENCE STUDY MATERIAL (STRICT SOURCE) ===
{retrieved_context}

=== EXAMINATION SPECIFICATIONS ===
Subject / Topic: {clean_subject}
Difficulty Level: {request.difficulty}
Total Marks Required: {request.total_marks}

Required Sections Breakdown:
{chr(10).join(sections_prompt_desc)}

=== REQUIRED JSON OUTPUT STRUCTURE ===
Output MUST be a single JSON object with this exact structure:
{{
  "title": "Examination Paper: {clean_subject}",
  "subject": "{clean_subject}",
  "total_marks": {request.total_marks},
  "difficulty": "{request.difficulty}",
  "instructions": [
    "Read all questions carefully before answering.",
    "Answer all questions strictly based on prescribed guidelines.",
    "Figures to the right indicate full marks assigned to each question."
  ],
  "sections": [
    {{
      "section_title": "Section A: Multiple Choice Questions",
      "type": "MCQ",
      "marks_per_question": 1,
      "questions": [
        {{
          "id": "Q1",
          "question": "Question statement directly from source notes?",
          "options": ["A. Option 1", "B. Option 2", "C. Option 3", "D. Option 4"],
          "answer": "A. Option 1",
          "explanation": "Explanation citing source material."
        }}
      ]
    }},
    {{
      "section_title": "Section B: Short Answer Questions",
      "type": "Short",
      "marks_per_question": 5,
      "questions": [
        {{
          "id": "Q2",
          "question": "Short answer question from source notes...",
          "options": [],
          "answer": "Model answer based on context...",
          "explanation": "Marking scheme criteria."
        }}
      ]
    }}
  ]
}}

Generate the exact number of questions requested for each section. For MCQ questions, provide 4 options. For non-MCQ questions, leave "options" as [].
Respond ONLY with the JSON structure.
"""

    # Step 6: Dispatch Request to Ollama Inference API
    try:
        logger.info(f"[OLLAMA] Sending request to model '{LLM_MODEL}' at {OLLAMA_BASE_URL}")
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "system": system_instruction,
            "stream": False,
            "format": "json",
            "options": {
                "num_gpu": 99,
                "temperature": 0.1,
                "num_ctx": 4096
            }
        }
        
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            headers={"Connection": "close"},
            timeout=300
        )

        if response.status_code != 200:
            # M1: log full body server-side but expose only truncated message (avoid leaking internals)
            logger.error(f"[OLLAMA] Error response HTTP {response.status_code}: {response.text[:1000]}")
            raise HTTPException(
                status_code=502,
                detail=f"Ollama generation failed (HTTP {response.status_code}). Please retry; if it persists check Ollama logs."
            )

        res_json = response.json()
        raw_text = res_json.get("response", "")
        cleaned_json_text = clean_json_response(raw_text)

        parsed_data = json.loads(cleaned_json_text)

        if not isinstance(parsed_data, dict):
            logger.error(f"[GENERATION] Model output is not a JSON object: {type(parsed_data).__name__}")
            raise HTTPException(
                status_code=502,
                detail="Model returned an invalid paper structure (expected a JSON object). Please retry generation."
            )

        if "error" in parsed_data:
            logger.warning(f"[RAG_GATE] LLM rejected generation: {parsed_data.get('message')}")
            raise HTTPException(
                status_code=422,
                detail=parsed_data.get("message", "The uploaded study material does not contain sufficient information for this topic.")
            )

        # H-01: never hand structurally invalid model output to the client as 200.
        try:
            validate_legacy_paper_shape(parsed_data)
        except ValueError as shape_err:
            logger.error(f"[GENERATION] Model output failed schema validation: {shape_err}")
            raise HTTPException(
                status_code=502,
                detail=f"Model returned an invalid paper structure ({shape_err}). Please retry generation."
            )

        logger.info(f"[GENERATION] Question paper successfully generated for subject '{clean_subject}'!")
        # Header-only metadata passthrough (no effect on generation/validation).
        parsed_data["exam_meta"] = request.exam_meta or {}
        return parsed_data

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"[GENERATION] LLM JSON parsing error: {e}\nRaw snippet: {raw_text[:200]}")
        raise HTTPException(
            status_code=502,
            detail="Model returned malformed output. Please retry generation."
        )
    except requests.exceptions.Timeout:
        logger.error("[GENERATION] Ollama request timed out")
        raise HTTPException(status_code=504, detail="Model timed out. Try fewer questions or retry.")
    except Exception as e:
        logger.error(f"[GENERATION] Unexpected error during paper generation: {e}")
        raise HTTPException(status_code=500, detail="Question generation failed. Please retry.")


@app.post("/api/generate-structured")
def generate_structured(
    request: StructuredGenerateRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """M4: blueprint-aware structured generation.

    Same RAG gates as legacy (Ollama → docs → topic → marks-sum), plus:
    optional blueprint validation → per-question slot expansion →
    per-unit targeted retrieval → single LLM call with slot table →
    repair-parse → deterministic source post-fill.

    Every returned question carries type/marks/difficulty/bloom_level/unit/
    topic/source_documents. Legacy /generate-paper is unchanged.
    """
    if not _GENERATE_AVAILABLE:
        raise HTTPException(status_code=500, detail="Structured generation engine unavailable.")
    session_id = resolve_session_id(x_session_id)
    logger.info(f"[STRUCT] Structured generation for session '{session_id}', subject '{request.subject}'")

    connected, msg, _ = check_ollama_status()
    if not connected:
        raise HTTPException(status_code=503, detail="Ollama Service is currently offline. Please start Ollama locally and try again.")

    try:
        session_docs = notes_collection.get(where={"session_id": session_id})
        doc_count = len(session_docs.get("ids", []))
    except Exception as e:
        logger.error(f"[STRUCT] Failed checking session docs: {e}")
        doc_count = 0
    if doc_count == 0:
        raise HTTPException(status_code=400, detail="No study material is available yet. Please upload valid notes, PDF, PPT, or reference material before generating a question paper.")

    clean_subject = validate_educational_topic(request.subject)

    expected_marks = sum(s.count * s.marks_per_q for s in request.sections)
    if request.total_marks != expected_marks:
        raise HTTPException(status_code=400, detail=f"total_marks ({request.total_marks}) does not match sections sum ({expected_marks}). Please fix the section marks.")

    # Blueprint validation (optional but strict when provided).
    bp_topics = None
    bp_diff = None
    bp_bloom = None
    if request.blueprint is not None:
        if not _BLUEPRINT_AVAILABLE:
            raise HTTPException(status_code=500, detail="Blueprint engine unavailable.")
        try:
            bp = _BlueprintRequest(**request.blueprint)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid blueprint: {e}")
        res = _validate_blueprint(bp)
        if not res["ok"]:
            raise HTTPException(status_code=400, detail="; ".join(res["errors"]))
        # H-12: the blueprint is the generation plan, so its total must match
        # the marks actually requested by the section configuration.
        if bp.total_marks != request.total_marks:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Blueprint total marks ({bp.total_marks}) must match requested "
                    f"total marks ({request.total_marks})."
                ),
            )
        bp_topics = [{"name": t.name, "percentage": t.percentage} for t in bp.topics]
        bp_diff = {"easy": bp.difficulty.easy, "medium": bp.difficulty.medium, "hard": bp.difficulty.hard}
        bp_bloom = {"remember": bp.bloom.remember, "understand": bp.bloom.understand,
                    "apply": bp.bloom.apply, "analyze": bp.bloom.analyze,
                    "evaluate": bp.bloom.evaluate, "create": bp.bloom.create}

    sections_in = [{"type": s.type, "count": s.count, "marks_per_q": s.marks_per_q} for s in request.sections]
    slots = _expand_slots(sections_in, topics=bp_topics, difficulty=bp_diff, bloom=bp_bloom)
    if not slots:
        raise HTTPException(status_code=400, detail="No questions requested.")

    # Per-unit targeted retrieval (one query per distinct unit to bound embedding calls).
    # H-03: shared threshold. H-15: no cross-unit fallback; a real unit must
    # have its own chunks, and its metadata must actually name that unit.
    units = sorted({s["unit"] for s in slots})
    context_by_unit: Dict[str, str] = {}
    sources_by_unit: Dict[str, List[str]] = {}
    all_valid = 0
    for unit in units:
        unit_types = sorted({s["type"] for s in slots if s["unit"] == unit})
        query = f"{clean_subject} {unit} {' '.join(unit_types)}"
        res = retrieve_relevant(
            query,
            session_id,
            unit=None if unit == "General" else unit,
            n_results=8,
            allow_fallback=False,
        )
        docs = res.get("documents", [])
        dists = res.get("distances", [])
        metas = res.get("metadatas", [])
        kept, files = [], []
        for doc, dist, meta in zip(docs, dists, metas):
            if unit != "General":
                meta_unit = str((meta or {}).get("unit", "")).strip()
                if meta_unit.casefold() != unit.casefold():
                    continue
            if dist is not None and float(dist) <= RAG_RELEVANCE_THRESHOLD and doc:
                kept.append(doc)
                fn = (meta or {}).get("filename", "")
                if fn and fn not in files:
                    files.append(fn)
        if kept:
            context_by_unit[unit] = "\n---\n".join(kept)[:3000]
            sources_by_unit[unit] = files
            all_valid += len(kept)

    missing_units = [u for u in units if u != "General" and u not in context_by_unit]
    if missing_units:
        raise HTTPException(
            status_code=422,
            detail=(
                "No relevant content found for unit(s): "
                + ", ".join(missing_units)
                + ". Upload notes covering these units or remove them from the blueprint."
            ),
        )
    if all_valid == 0:
        raise HTTPException(status_code=422, detail=f"No relevant content found in your uploaded study material for topic: '{clean_subject}'. Please upload notes covering this topic.")

    system_instruction, prompt = _build_structured_prompt(
        clean_subject, request.difficulty, request.total_marks, slots, context_by_unit)

    # Single LLM call + one retry on shape/slot mismatch (M4: bounded, no loops).
    # The retry receives the exact validation errors but the same original slots,
    # blueprint and retrieved context.
    paper = None
    last_err = ""
    attempt_prompt = prompt
    for _ in range(2):
        try:
            raw = _call_ollama_structured(
                OLLAMA_BASE_URL, LLM_MODEL, system_instruction, attempt_prompt)
            candidate = _parse_structured_output(raw)
            candidate, dropped = _trim_unmatched_questions(candidate, slots)
            if dropped:
                logger.warning(
                    f"[STRUCT] Removed {dropped} unambiguous extra question(s) "
                    f"not present in the slot plan.")
            validation = _validate_structured_paper(candidate, slots)
            if not validation["ok"]:
                last_err = "; ".join(validation["errors"])
                logger.warning(f"[STRUCT] Slot validation failed: {last_err} Retrying once.")
                attempt_prompt = _build_structured_prompt(
                    clean_subject, request.difficulty, request.total_marks,
                    slots, context_by_unit, validation_feedback=last_err,
                )[1]
                continue
            paper = validation["paper"]
            break
        except (RuntimeError, ValueError) as e:
            last_err = str(e)
            logger.warning(f"[STRUCT] Attempt failed: {last_err}")
            attempt_prompt = _build_structured_prompt(
                clean_subject, request.difficulty, request.total_marks,
                slots, context_by_unit,
                validation_feedback=f"Previous output was unusable: {last_err}",
            )[1]
    if paper is None:
        raise HTTPException(status_code=502, detail=f"Model output failed validation ({last_err}). Please retry.")

    paper = _post_fill_sources(paper, sources_by_unit)
    paper.setdefault("subject", clean_subject)
    # Header-only metadata passthrough (no effect on generation/validation).
    paper["exam_meta"] = request.exam_meta or {}
    if request.exam_name:
        paper["exam_name"] = request.exam_name
    if request.institution:
        paper["institution"] = request.institution
    if request.duration_minutes:
        paper["duration_minutes"] = request.duration_minutes
    paper["generation_info"] = {
        "engine": "structured-v1",
        "slots": slots,
        "retrieval_units": sorted(context_by_unit.keys()),
        "blueprint_used": request.blueprint is not None,
    }
    logger.info(f"[STRUCT] Generated {len(slots)} structured questions for '{clean_subject}'.")
    return paper


class ValidatePaperRequest(BaseModel):
    paper: Dict[str, Any] = Field(..., description="Generated paper JSON to validate")


@app.post("/api/validate")
def validate_paper_endpoint(
    request: ValidatePaperRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """M5: deterministic critic — validates every question against session chunks.

    Offline-capable (uses collection.get, no embeddings). Returns per-question
    {checks, overall, reasons} + summary counts. Never calls the LLM.
    """
    if not _VALIDATOR_AVAILABLE:
        raise HTTPException(status_code=500, detail="Validation engine unavailable.")
    session_id = resolve_session_id(x_session_id)
    try:
        stored = notes_collection.get(
            where={"session_id": session_id}, include=["documents", "metadatas"])
    except Exception as e:
        logger.error(f"[VALIDATE] Chroma fetch failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to read session material.")
    docs = stored.get("documents", []) or []
    metas = stored.get("metadatas", []) or []
    if not docs:
        raise HTTPException(status_code=400, detail="No study material in this session to validate against.")
    chunks = [{
        "text": d or "",
        "filename": (m or {}).get("filename", ""),
        "unit": (m or {}).get("unit", "General"),
        "page": (m or {}).get("page", ""),
    } for d, m in zip(docs, metas)]
    try:
        return _validate_paper(request.paper, chunks)
    except Exception as e:
        logger.error(f"[VALIDATE] Engine error: {e}")
        raise HTTPException(status_code=500, detail="Validation failed. Please retry.")


@app.post("/api/duplicates")
def duplicates_endpoint(request: ValidatePaperRequest):
    """M6: semantic duplicate detection over a paper (deterministic, offline).

    Returns {pairs: [{q1, q2, similarity, similarity_pct}], count}.
    No session needed — compares question texts only.
    """
    if not _DUPLICATES_AVAILABLE:
        raise HTTPException(status_code=500, detail="Duplicate engine unavailable.")
    questions = []
    for section in request.paper.get("sections", []):
        for q in section.get("questions", []):
            questions.append({"id": q.get("id", "?"), "question": q.get("question", "")})
    try:
        pairs = _find_duplicates(questions)
    except Exception as e:
        logger.error(f"[DUPLICATES] Engine error: {e}")
        raise HTTPException(status_code=500, detail="Duplicate check failed. Please retry.")
    return {"pairs": pairs, "count": len(pairs), "threshold": 0.75}


def _parse_regeneration_marks(value: Any) -> int:
    """M-01: convert a question's marks to a positive whole number.

    Regeneration must preserve the original slot exactly. Invalid input is a
    client/data error (422), never a silent default and never an HTTP 500.
    """
    invalid = HTTPException(
        status_code=422,
        detail="Invalid question marks for regeneration: marks must be a positive whole number.",
    )
    if value is None or isinstance(value, bool):
        raise invalid
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise invalid
        try:
            parsed = int(text, 10)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                raise invalid
            if not number.is_integer():
                raise invalid
            parsed = int(number)
    elif isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            raise invalid
        parsed = int(value)
    else:
        raise invalid
    if parsed <= 0:
        raise invalid
    return parsed


class RegenerateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    question: Dict[str, Any] = Field(..., description="Question to replace (carries slot metadata)")
    avoid: Optional[List[str]] = Field(None, description="Question texts to differ from")


@app.post("/api/questions/regenerate")
def regenerate_question_endpoint(
    request: RegenerateRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
):
    """M6: regenerate ONLY one question, preserving its slot constraints.

    Slot (type/marks/difficulty/bloom/unit/topic) is read from the given
    question with safe fallbacks. Replacement is validated for JSON shape
    (not auto-approved — caller should re-run /api/validate).
    Requires Ollama (generation); retrieval uses the unit-targeted helper.
    """
    if not _GENERATE_AVAILABLE:
        raise HTTPException(status_code=500, detail="Generation engine unavailable.")
    session_id = resolve_session_id(x_session_id)
    connected, _, _ = check_ollama_status()
    if not connected:
        raise HTTPException(status_code=503, detail="Ollama Service is currently offline. Please start Ollama and try again.")
    clean_subject = validate_educational_topic(request.subject)

    q = request.question or {}
    slot = {
        "slot_id": q.get("id", "Q?"),
        "type": q.get("type", "Short") or "Short",
        "marks": _parse_regeneration_marks(q.get("marks")),
        "difficulty": (q.get("difficulty", "Medium") or "Medium"),
        "bloom_level": (q.get("bloom_level", "Understand") or "Understand"),
        "unit": (q.get("unit", "General") or "General"),
        "topic": (q.get("topic", "") or ""),
    }
    if slot["type"] not in ALLOWED_SECTION_TYPES:
        slot["type"] = "Short"

    res = retrieve_relevant(
        f"{clean_subject} {slot['unit']} {slot['topic']} {slot['type']}",
        session_id,
        unit=None if slot["unit"] == "General" else slot["unit"],
        n_results=8,
        allow_fallback=False,
    )
    docs = []
    for d, dist, meta in zip(res.get("documents", []), res.get("distances", []), res.get("metadatas", [])):
        if slot["unit"] != "General":
            meta_unit = str((meta or {}).get("unit", "")).strip()
            if meta_unit.casefold() != str(slot["unit"]).casefold():
                continue
        if d and dist is not None and float(dist) <= RAG_RELEVANCE_THRESHOLD:
            docs.append(d)
    if not docs:
        raise HTTPException(status_code=422, detail=f"No relevant content for unit '{slot['unit']}'. Upload covering notes or pick another unit.")
    context = "\n---\n".join(docs)[:3000]
    avoid_lines = ""
    if request.avoid:
        avoid_lines = "Avoid repeating these existing questions:\n" + "\n".join(f"- {a[:200]}" for a in request.avoid[:10]) + "\n"

    from generate import _extract_json_object, BLOOM_HINTS, DIFFICULTY_HINTS, TYPE_HINTS
    system_instruction = (
        "You are an expert academic examiner. Use ONLY the REFERENCE STUDY MATERIAL. "
        "Respond ONLY with valid JSON for ONE question."
    )
    prompt = f"""=== REFERENCE STUDY MATERIAL ===
{context}

=== SLOT (regenerate exactly one question for this slot) ===
type={slot['type']}, marks={slot['marks']}, difficulty={slot['difficulty']}, bloom={slot['bloom_level']}, unit={slot['unit']}, topic={slot['topic'] or slot['unit']}
Bloom hint ({slot['bloom_level']}): {BLOOM_HINTS.get(slot['bloom_level'], '')}
Difficulty hint ({slot['difficulty']}): {DIFFICULTY_HINTS.get(slot['difficulty'], '')}
Type hint ({slot['type']}): {TYPE_HINTS.get(slot['type'], '')}
{avoid_lines}
=== REQUIRED JSON (single object) ===
{{"question": "...", "options": [...], "answer": "...", "explanation": "..."}}
MCQ → 4 options; other types → []. Respond ONLY with the JSON object."""

    try:
        raw = _call_ollama_structured(OLLAMA_BASE_URL, LLM_MODEL, system_instruction, prompt)
        cleaned = _extract_json_object(raw)
        data = json.loads(cleaned)
    except Exception as e:
        logger.error(f"[REGEN] Parse/call failed: {e}")
        raise HTTPException(status_code=502, detail="Regeneration failed. Please retry.")
    if not data.get("question") or not data.get("answer"):
        raise HTTPException(status_code=502, detail="Model returned an incomplete question. Please retry.")
    if data.get("question") == "INSUFFICIENT_CONTEXT":
        raise HTTPException(status_code=422, detail="Study material lacks information for this slot.")

    files: List[str] = []
    try:
        metas = res.get("metadatas", [])[:3]
        for m in metas:
            fn = (m or {}).get("filename", "")
            if fn and fn not in files:
                files.append(fn)
    except Exception:
        pass
    replacement = {
        "id": slot["slot_id"],
        "question": data["question"],
        "type": slot["type"],
        "marks": slot["marks"],
        "difficulty": slot["difficulty"],
        "bloom_level": slot["bloom_level"],
        "unit": slot["unit"],
        "topic": slot["topic"] or slot["unit"],
        "source_documents": files[:3],
        "options": data.get("options", []) or [],
        "answer": data.get("answer", ""),
        "explanation": data.get("explanation", ""),
    }
    return {"question": replacement}


class AnalyticsRequest(BaseModel):
    paper: Dict[str, Any] = Field(...)
    blueprint: Optional[Dict[str, Any]] = Field(None)
    validation: Optional[Dict[str, Any]] = Field(None)
    duplicates: Optional[Dict[str, Any]] = Field(None)


@app.post("/api/analytics")
def analytics_endpoint(request: AnalyticsRequest):
    """M7: target-vs-actual coverage + heuristic quality score (deterministic, offline)."""
    if not _ANALYTICS_AVAILABLE:
        raise HTTPException(status_code=500, detail="Analytics engine unavailable.")
    try:
        return _compute_analytics(request.paper, request.blueprint, request.validation, request.duplicates)
    except Exception as e:
        logger.error(f"[ANALYTICS] Engine error: {e}")
        raise HTTPException(status_code=500, detail="Analytics failed. Please retry.")


class ExportPdfRequest(BaseModel):
    paper: Dict[str, Any] = Field(...)


@app.post("/api/export/pdf")
def export_pdf_endpoint(request: ExportPdfRequest, include_answers: bool = False):
    """M9/M14: render the final paper (or separate answer key) as PDF.

    include_answers=false → question paper; true → answer key.
    Browser print remains available; this is the archival/ distributable copy.
    """
    if not _PDF_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF export unavailable (reportlab missing).")
    try:
        pdf_bytes = _build_pdf(request.paper, include_answers=include_answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[PDF] Render failed: {e}")
        raise HTTPException(status_code=500, detail="PDF rendering failed. Please retry.")
    subject = str((request.paper.get("subject") or "paper")).replace(" ", "_")[:40]
    kind = "with_key" if include_answers else "paper"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{subject}_{kind}.pdf"'},
    )


class SavePaperRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    paper: Dict[str, Any] = Field(...)
    blueprint: Optional[Dict[str, Any]] = Field(None)
    validation: Optional[Dict[str, Any]] = Field(None)


@app.post("/api/papers")
def save_paper_endpoint(request: SavePaperRequest):
    """M10: snapshot the current paper (+ blueprint/validation) into history."""
    if not _HISTORY_AVAILABLE:
        raise HTTPException(status_code=500, detail="History unavailable.")
    paper = request.paper or {}
    sections = paper.get("sections", []) or []
    n_q = sum(len(s.get("questions", []) or []) for s in sections)
    try:
        total = int(paper.get("total_marks", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    subject = str(paper.get("subject", "") or "")
    title = (request.title or paper.get("exam_name") or paper.get("title") or f"{subject} paper").strip()[:200]
    try:
        pid = _history_save(title, subject, total, n_q, paper, request.blueprint, request.validation)
    except Exception as e:
        logger.error(f"[HISTORY] Save failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save paper.")
    return {"id": pid, "title": title}


@app.get("/api/papers")
def list_papers_endpoint():
    """M10: list saved paper snapshots (metadata only)."""
    if not _HISTORY_AVAILABLE:
        raise HTTPException(status_code=500, detail="History unavailable.")
    try:
        return {"papers": _history_list()}
    except Exception as e:
        logger.error(f"[HISTORY] List failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to list papers.")


@app.get("/api/papers/{paper_id}")
def get_paper_endpoint(paper_id: int):
    """M10: reopen one snapshot (paper + blueprint + validation)."""
    if not _HISTORY_AVAILABLE:
        raise HTTPException(status_code=500, detail="History unavailable.")
    try:
        data = _history_get(paper_id)
    except Exception as e:
        logger.error(f"[HISTORY] Get failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to load paper.")
    if not data:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return data


@app.delete("/api/papers/{paper_id}")
def delete_paper_endpoint(paper_id: int):
    """M10: delete one snapshot."""
    if not _HISTORY_AVAILABLE:
        raise HTTPException(status_code=500, detail="History unavailable.")
    try:
        ok = _history_delete(paper_id)
    except Exception as e:
        logger.error(f"[HISTORY] Delete failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete paper.")
    if not ok:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return {"deleted": paper_id}

def get_server_settings():
    """C-01: safe local defaults, overridable for deliberate deployments.

    Defaults to loopback + no auto-reload so ``python main.py`` is not reachable
    from the LAN. Set APP_HOST/APP_PORT/APP_RELOAD explicitly to change this.
    """
    host = (os.environ.get("APP_HOST", "127.0.0.1").strip() or "127.0.0.1")
    try:
        port = int(os.environ.get("APP_PORT", "8000"))
    except ValueError:
        port = 8000
    reload_enabled = os.environ.get("APP_RELOAD", "0").strip().lower() in {"1", "true", "yes", "on"}
    return host, port, reload_enabled


if __name__ == "__main__":
    import uvicorn
    host, port, reload_enabled = get_server_settings()
    if host not in {"127.0.0.1", "localhost", "::1"} and not APP_AUTH_TOKEN:
        logger.warning(
            "[AUTH] APP_HOST=%s exposes this API beyond localhost without authentication. "
            "Set APP_AUTH_TOKEN before sharing it on a network.", host
        )
    uvicorn.run("main:app", host=host, port=port, reload=reload_enabled)

