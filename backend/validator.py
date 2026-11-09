"""Question validation / critic engine (M5).

Fully deterministic, no LLM calls, works offline. Each question is checked
against the session's indexed chunks (fetched via collection.get, no
embeddings needed) plus structural rules for type / Bloom / marks / quality.

Verdicts per check: PASS | NEEDS_REVIEW | FAIL
Overall per question: APPROVED | NEEDS_REVIEW | NEEDS_REGENERATION
"""

import re
from typing import List, Dict, Any

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "by", "as", "at", "from", "that",
    "this", "it", "its", "which", "what", "how", "why", "when", "who",
    "explain", "describe", "define", "discuss", "write", "give", "state",
    "following", "briefly",
}

BLOOM_VERBS = {
    "Remember": ["define", "list", "recall", "identify", "name", "state", "label", "match"],
    "Understand": ["explain", "describe", "summarize", "interpret", "classify", "discuss", "illustrate"],
    "Apply": ["apply", "solve", "demonstrate", "compute", "implement", "schedule", "calculate", "use"],
    "Analyze": ["analyze", "compare", "differentiate", "examine", "distinguish", "contrast", "categorize"],
    "Evaluate": ["evaluate", "justify", "assess", "critique", "defend", "judge", "recommend"],
    "Create": ["design", "construct", "develop", "formulate", "propose", "create", "compose"],
}

# Expected difficulty per Bloom level (lenient mapping for the difficulty check).
BLOOM_TO_DIFFICULTY = {
    "Remember": "Easy", "Understand": "Easy", "Apply": "Medium",
    "Analyze": "Medium", "Evaluate": "Hard", "Create": "Hard",
}

GROUNDING_PASS = 0.35
GROUNDING_REVIEW = 0.20
ANSWER_PASS = 0.30
ANSWER_REVIEW = 0.15


def tokens(text: str) -> set:
    words = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def overlap_ratio(query_tokens: set, doc_tokens: set) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def _norm_bloom(level: str) -> str:
    lvl = (level or "").strip().capitalize()
    return lvl if lvl in BLOOM_VERBS else ""


def validate_question(q: Dict[str, Any], chunks: List[Dict[str, Any]]) -> dict:
    """Validate one question dict against session chunks.

    chunks: [{text, filename, unit, page}]. Returns {id, checks{...}, overall, reasons[]}.
    Each check value: {"status": PASS|NEEDS_REVIEW|FAIL, "detail": str}.
    """
    qid = q.get("id", "?")
    qtext = q.get("question", "") or ""
    answer = q.get("answer", "") or ""
    qtype = (q.get("type") or "").strip()
    unit = (q.get("unit") or "").strip()
    bloom = _norm_bloom(q.get("bloom_level", ""))
    diff = (q.get("difficulty") or "").strip().capitalize()
    try:
        marks = int(q.get("marks", 0) or 0)
    except (TypeError, ValueError):
        marks = 0
    options = q.get("options") or []

    checks: Dict[str, Dict[str, str]] = {}
    reasons: List[str] = []

    qtok = tokens(qtext)
    unit_chunks = [c for c in chunks if unit and c.get("unit", "") == unit] or chunks
    best_unit = max([overlap_ratio(qtok, tokens(c.get("text", ""))) for c in unit_chunks] or [0.0])
    best_all = max([overlap_ratio(qtok, tokens(c.get("text", ""))) for c in chunks] or [0.0])

    # 1. Syllabus relevance (whole material)
    if best_all >= GROUNDING_PASS:
        checks["syllabus"] = {"status": "PASS", "detail": f"Supported by material ({best_all:.0%} term overlap)."}
    elif best_all >= GROUNDING_REVIEW:
        checks["syllabus"] = {"status": "NEEDS_REVIEW", "detail": f"Weak material overlap ({best_all:.0%}). Teacher should confirm."}
        reasons.append("Question is weakly supported by uploaded material.")
    else:
        checks["syllabus"] = {"status": "FAIL", "detail": f"Almost no material overlap ({best_all:.0%})."}
        reasons.append("Question is insufficiently supported by uploaded material.")

    # 2. Grounding (unit-scoped when unit known)
    scope = f"unit '{unit}'" if unit and unit_chunks is not chunks else "material"
    if best_unit >= GROUNDING_PASS:
        checks["grounding"] = {"status": "PASS", "detail": f"Grounded in {scope} ({best_unit:.0%} overlap)."}
    elif best_unit >= GROUNDING_REVIEW:
        checks["grounding"] = {"status": "NEEDS_REVIEW", "detail": f"Weak grounding in {scope} ({best_unit:.0%})."}
        reasons.append(f"Question weakly grounded in {scope}.")
    else:
        checks["grounding"] = {"status": "FAIL", "detail": f"Not grounded in {scope} ({best_unit:.0%})."}
        reasons.append(f"Question not grounded in {scope}.")

    # 3. Answer support
    atok = tokens(answer)
    best_ans = max([overlap_ratio(atok, tokens(c.get("text", ""))) for c in chunks] or [0.0])
    if not answer.strip():
        checks["answer_support"] = {"status": "FAIL", "detail": "Answer is empty."}
        reasons.append("Answer is missing.")
    elif best_ans >= ANSWER_PASS:
        checks["answer_support"] = {"status": "PASS", "detail": f"Answer supported ({best_ans:.0%} overlap)."}
    elif best_ans >= ANSWER_REVIEW:
        checks["answer_support"] = {"status": "NEEDS_REVIEW", "detail": f"Answer weakly supported ({best_ans:.0%}). Review advised."}
        reasons.append("Answer requires teacher review (weak source support).")
    else:
        checks["answer_support"] = {"status": "FAIL", "detail": f"Answer unsupported ({best_ans:.0%} overlap)."}
        reasons.append("Answer is not supported by source material.")

    # 4. Difficulty vs Bloom mapping
    if bloom and diff:
        expected = BLOOM_TO_DIFFICULTY.get(bloom, "")
        if expected == diff:
            checks["difficulty"] = {"status": "PASS", "detail": f"{diff} matches {bloom} expectations."}
        else:
            checks["difficulty"] = {"status": "NEEDS_REVIEW", "detail": f"{diff} requested but {bloom} usually maps to {expected}."}
            reasons.append(f"Difficulty ({diff}) does not match Bloom level ({bloom}, usually {expected}).")
    else:
        checks["difficulty"] = {"status": "NEEDS_REVIEW", "detail": "Difficulty or Bloom metadata missing."}

    # 5. Marks suitability (answer substance heuristic)
    ans_words = len(re.findall(r"\w+", answer))
    q_words = len(re.findall(r"\w+", qtext))
    if q_words < 4:
        checks["marks"] = {"status": "FAIL", "detail": "Question text too short to be answerable."}
        reasons.append("Question wording is incomplete.")
    elif marks >= 5 and ans_words < marks * 4:
        checks["marks"] = {"status": "FAIL", "detail": f"{ans_words} answer words for {marks} marks (expected ≥{marks * 4})."}
        reasons.append(f"Answer too thin for {marks} marks.")
    elif marks >= 5 and ans_words < marks * 8:
        checks["marks"] = {"status": "NEEDS_REVIEW", "detail": f"{ans_words} answer words for {marks} marks — possibly thin."}
        reasons.append(f"Answer may be thin for {marks} marks.")
    else:
        checks["marks"] = {"status": "PASS", "detail": f"Answer length ({ans_words} words) suits {marks} marks."}

    # 6. Bloom verb check
    if bloom:
        text_l = qtext.lower()
        verbs = BLOOM_VERBS[bloom]
        if any(re.search(rf"\b{v}\w*\b", text_l) for v in verbs):
            checks["bloom"] = {"status": "PASS", "detail": f"Matches {bloom} phrasing."}
        else:
            checks["bloom"] = {"status": "NEEDS_REVIEW", "detail": f"No typical {bloom} verb found; verify cognitive level."}
            reasons.append(f"Question may not match Bloom level {bloom}.")
    else:
        checks["bloom"] = {"status": "NEEDS_REVIEW", "detail": "Bloom level missing."}

    # 7. Question-type shape
    t = qtype
    if t == "MCQ":
        if isinstance(options, list) and len(options) == 4:
            checks["qtype"] = {"status": "PASS", "detail": "MCQ with 4 options."}
        else:
            checks["qtype"] = {"status": "FAIL", "detail": f"MCQ must have 4 options (found {len(options) if isinstance(options, list) else 0})."}
            reasons.append("MCQ does not have 4 options.")
    elif t in ("Short", "Long"):
        if not options:
            checks["qtype"] = {"status": "PASS", "detail": f"{t or 'Question'} shape OK (no options)."}
        else:
            checks["qtype"] = {"status": "FAIL", "detail": f"{t} answer must not carry MCQ options."}
            reasons.append(f"{t} question wrongly carries options.")
    elif t == "True/False":
        if str(answer).strip().lower().startswith(("true", "false")):
            checks["qtype"] = {"status": "PASS", "detail": "True/False with boolean answer."}
        else:
            checks["qtype"] = {"status": "FAIL", "detail": "True/False answer must start with True/False."}
            reasons.append("True/False answer is not boolean.")
    elif t == "Fill-in-blanks":
        if "___" in qtext or "..." in qtext:
            checks["qtype"] = {"status": "PASS", "detail": "Fill-in-the-blanks markers present."}
        else:
            checks["qtype"] = {"status": "FAIL", "detail": "Fill-in-the-blanks question needs ___ markers."}
            reasons.append("Fill-in-the-blanks has no blank markers.")
    else:
        checks["qtype"] = {"status": "NEEDS_REVIEW", "detail": f"Unknown type '{t or '?'}'."}

    # 8. Quality (wording)
    issues = []
    s = qtext.strip()
    if s and not s[0].isupper():
        issues.append("should start with a capital letter")
    if "??" in s or "  " in s:
        issues.append("contains repeated punctuation/spacing")
    if len(s) > 500:
        issues.append("unusually long — consider splitting")
    if re.search(r"\b(xxx|asdf|todo|placeholder)\b", s, re.IGNORECASE):
        issues.append("contains placeholder text")
    if issues:
        status = "FAIL" if len(issues) >= 2 else "NEEDS_REVIEW"
        checks["quality"] = {"status": status, "detail": "Wording: " + "; ".join(issues) + "."}
        reasons.append("Quality: " + "; ".join(issues) + ".")
    else:
        checks["quality"] = {"status": "PASS", "detail": "Clear, complete wording."}

    statuses = [c["status"] for c in checks.values()]
    if "FAIL" in statuses:
        overall = "NEEDS_REGENERATION"
    elif "NEEDS_REVIEW" in statuses:
        overall = "NEEDS_REVIEW"
    else:
        overall = "APPROVED"

    return {"id": qid, "checks": checks, "overall": overall, "reasons": reasons}


def validate_paper(paper: Dict[str, Any], chunks: List[Dict[str, Any]]) -> dict:
    """Validate every question in a paper dict. Returns {results, summary}."""
    results = []
    for section in paper.get("sections", []):
        for q in section.get("questions", []):
            qq = dict(q)
            qq.setdefault("type", section.get("type", ""))
            qq.setdefault("marks", section.get("marks_per_question", 0))
            results.append(validate_question(qq, chunks))
    summary = {
        "total": len(results),
        "approved": sum(1 for r in results if r["overall"] == "APPROVED"),
        "needs_review": sum(1 for r in results if r["overall"] == "NEEDS_REVIEW"),
        "needs_regeneration": sum(1 for r in results if r["overall"] == "NEEDS_REGENERATION"),
    }
    return {"results": results, "summary": summary}
