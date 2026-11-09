"""Exam Blueprint engine (M2).

Validates teacher-configured exam distributions BEFORE generation and
expands them into a concrete marks breakdown. Deterministic, no LLM calls.

Design notes (keeps existing APIs compatible):
- /generate-paper is untouched; this module only validates + previews.
- M4 will consume BlueprintRequest.expanded slots for slot-aware generation.
- Tolerances: percentage sums must be 100 +/- 1.0 to allow slider rounding.
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


BLOOM_LEVELS = ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"]
BLOOM_VERBS: Dict[str, List[str]] = {
    "Remember": ["define", "list", "recall", "identify", "name", "state"],
    "Understand": ["explain", "describe", "summarize", "interpret", "classify"],
    "Apply": ["apply", "solve", "demonstrate", "compute", "implement", "schedule"],
    "Analyze": ["analyze", "compare", "differentiate", "examine", "distinguish"],
    "Evaluate": ["evaluate", "justify", "assess", "critique", "defend"],
    "Create": ["design", "construct", "develop", "formulate", "propose"],
}
DIFFICULTY_LEVELS = ["Easy", "Medium", "Hard"]
PCT_TOLERANCE = 1.0


class TopicWeight(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    percentage: float = Field(..., ge=0, le=100)


class DifficultyDist(BaseModel):
    easy: float = Field(0, ge=0, le=100)
    medium: float = Field(0, ge=0, le=100)
    hard: float = Field(0, ge=0, le=100)


class BloomDist(BaseModel):
    remember: float = Field(0, ge=0, le=100)
    understand: float = Field(0, ge=0, le=100)
    apply: float = Field(0, ge=0, le=100)
    analyze: float = Field(0, ge=0, le=100)
    evaluate: float = Field(0, ge=0, le=100)
    create: float = Field(0, ge=0, le=100)


class QTypeMarks(BaseModel):
    type: str = Field(...)
    marks: int = Field(..., ge=1)


class BlueprintRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    exam_name: str = Field("Mid-Semester Examination", max_length=200)
    institution: Optional[str] = Field(None, max_length=200)
    total_marks: int = Field(..., ge=1, le=1000)
    duration_minutes: int = Field(120, ge=15, le=600)
    topics: List[TopicWeight] = Field(..., min_length=1)
    difficulty: DifficultyDist = Field(...)
    types: List[QTypeMarks] = Field(..., min_length=1)
    bloom: BloomDist = Field(...)
    instructions: Optional[List[str]] = Field(None)


def _pct_sum_ok(values: List[float]) -> bool:
    return abs(sum(values) - 100.0) <= PCT_TOLERANCE


def validate_blueprint(bp: BlueprintRequest) -> dict:
    """Deterministic validation. Returns dict with ok/errors/expanded breakdown."""
    errors: List[str] = []

    if not bp.subject.strip():
        errors.append("Subject is required.")

    # Topic/unit names must be present and unique (case-insensitive).
    names = [t.name.strip().lower() for t in bp.topics]
    if any(not name for name in names):
        errors.append("Every topic/unit must have a non-empty name.")
    if len(set(names)) != len(names):
        errors.append("Topic/unit names must be unique.")

    if not _pct_sum_ok([t.percentage for t in bp.topics]):
        errors.append(
            f"Topic percentages must sum to 100 (±{PCT_TOLERANCE}). "
            f"Current sum: {sum(t.percentage for t in bp.topics):.1f}"
        )

    d = bp.difficulty
    if not _pct_sum_ok([d.easy, d.medium, d.hard]):
        errors.append(
            f"Difficulty percentages must sum to 100 (±{PCT_TOLERANCE}). "
            f"Current sum: {d.easy + d.medium + d.hard:.1f}"
        )

    b = bp.bloom
    bloom_vals = [b.remember, b.understand, b.apply, b.analyze, b.evaluate, b.create]
    if not _pct_sum_ok(bloom_vals):
        errors.append(
            f"Bloom percentages must sum to 100 (±{PCT_TOLERANCE}). "
            f"Current sum: {sum(bloom_vals):.1f}"
        )

    # Question-type marks must reconcile with total
    type_total = sum(t.marks for t in bp.types)
    if type_total != bp.total_marks:
        errors.append(
            f"Question-type marks ({type_total}) must equal total marks ({bp.total_marks})."
        )
    # Allowed types mirror SectionConfig allowlist (M1)
    allowed = {"MCQ", "Short", "Long", "True/False", "Fill-in-blanks"}
    type_names = [t.type.strip().lower() for t in bp.types]
    if len(set(type_names)) != len(type_names):
        errors.append("Question types must be unique.")
    for t in bp.types:
        if t.type not in allowed:
            errors.append(f"Invalid question type '{t.type}'. Allowed: {sorted(allowed)}")

    if errors:
        return {"ok": False, "errors": errors, "expanded": None}

    # Expansion: proportional marks per axis (M4 will cross-join into slots)
    expanded = {
        "topics": [
            {"name": t.name, "percentage": t.percentage,
             "marks": round(bp.total_marks * t.percentage / 100.0, 2)}
            for t in bp.topics
        ],
        "difficulty": [
            {"level": "Easy", "percentage": d.easy,
             "marks": round(bp.total_marks * d.easy / 100.0, 2)},
            {"level": "Medium", "percentage": d.medium,
             "marks": round(bp.total_marks * d.medium / 100.0, 2)},
            {"level": "Hard", "percentage": d.hard,
             "marks": round(bp.total_marks * d.hard / 100.0, 2)},
        ],
        "bloom": [
            {"level": lvl, "percentage": val,
             "marks": round(bp.total_marks * val / 100.0, 2)}
            for lvl, val in zip(BLOOM_LEVELS, bloom_vals)
        ],
        "types": [{"type": t.type, "marks": t.marks} for t in bp.types],
    }
    return {"ok": True, "errors": [], "expanded": expanded}
