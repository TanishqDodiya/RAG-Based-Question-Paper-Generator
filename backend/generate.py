"""Structured question generation (M4).

Expands (sections × blueprint) into per-question slots, retrieves targeted
context per unit, prompts the LLM once with a slot table + strict JSON
schema, then post-fills source_documents deterministically from retrieval
results (never trusting the LLM for provenance).

Legacy /generate-paper is untouched; this module powers /api/generate-structured.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import requests

logger = logging.getLogger("paper_generator")

BLOOM_LEVELS = ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"]

# Short verb hints per Bloom level, embedded in the prompt so the model
# pitches each question at the requested cognitive level.
BLOOM_HINTS = {
    "Remember": "recall facts, definitions, lists",
    "Understand": "explain ideas, describe, summarize in own words",
    "Apply": "solve a new problem, apply a procedure, compute",
    "Analyze": "compare, differentiate, examine relationships",
    "Evaluate": "justify, assess, critique with criteria",
    "Create": "design, construct, propose something new",
}

DIFFICULTY_HINTS = {
    "Easy": "direct recall or single-step, answer found almost verbatim in the material",
    "Medium": "requires connecting 2+ facts or a short derivation from the material",
    "Hard": "multi-step reasoning, edge cases, or justification from the material",
}

TYPE_HINTS = {
    "MCQ": "4 options (A–D), exactly one correct, plausible distractors from the material",
    "Short": "2–5 sentence answer, no options",
    "Long": "structured multi-part answer with explanation, no options",
    "True/False": "a single statement plus answer True/False with justification, no options",
    "Fill-in-blanks": "a sentence with ___ blank(s) plus the exact missing term(s) as answer, no options",
}


def _largest_remainder(total: int, weights: List[float]) -> List[int]:
    """Allocate integer counts summing to `total` proportional to weights."""
    if total <= 0 or not weights:
        return [0] * len(weights)
    wsum = sum(weights)
    if wsum <= 0:
        base = total // len(weights)
        out = [base] * len(weights)
        for i in range(total - base * len(weights)):
            out[i % len(weights)] += 1
        return out
    raw = [total * w / wsum for w in weights]
    out = [int(x) for x in raw]
    remainder = total - sum(out)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in range(remainder):
        out[order[i % len(order)]] += 1
    return out


def expand_slots(
    sections: List[Dict[str, Any]],
    topics: Optional[List[Dict[str, Any]]] = None,
    difficulty: Optional[Dict[str, float]] = None,
    bloom: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """One slot per question: {slot_id, unit, difficulty, bloom_level, type, marks}.

    Distributions come from the blueprint when provided, else uniform.
    Deterministic (largest-remainder + round-robin) so teachers can reproduce.

    FIX 4 contract: question counts, types and marks-per-question come ONLY from
    `sections` (GeneratorForm). The blueprint's type-marks distribution is NOT
    consumed here — it is validated for total-marks equality at the API boundary
    and used as the target in analytics. Topics/difficulty/bloom DO steer slots.
    """
    flat: List[Dict[str, Any]] = []
    for s in sections:
        for _ in range(int(s["count"])):
            flat.append({"type": s["type"], "marks": int(s["marks_per_q"])})
    n = len(flat)
    if n == 0:
        return []

    topic_names = [t["name"] for t in topics] if topics else ["General"]
    topic_w = [float(t.get("percentage", 0)) for t in topics] if topics else [100.0]
    d = difficulty or {"easy": 34, "medium": 33, "hard": 33}
    diff_names = ["Easy", "Medium", "Hard"]
    diff_w = [float(d.get("easy", 0)), float(d.get("medium", 0)), float(d.get("hard", 0))]
    b = bloom or {k.lower(): 100.0 / 6 for k in BLOOM_LEVELS}
    bloom_w = [float(b.get(k.lower(), 0)) for k in BLOOM_LEVELS]

    unit_counts = _largest_remainder(n, topic_w)
    diff_counts = _largest_remainder(n, diff_w)
    bloom_counts = _largest_remainder(n, bloom_w)

    def cycle(names: List[str], counts: List[int]) -> List[str]:
        seq: List[str] = []
        for name, c in zip(names, counts):
            seq.extend([name] * c)
        return seq

    units = cycle(topic_names, unit_counts)
    diffs = cycle(diff_names, diff_counts)
    blooms = cycle(BLOOM_LEVELS, bloom_counts)

    slots = []
    for i, q in enumerate(flat):
        slots.append({
            "slot_id": f"Q{i + 1}",
            "unit": units[i],
            "difficulty": diffs[i],
            "bloom_level": blooms[i],
            "type": q["type"],
            "marks": q["marks"],
        })
    return slots


def build_structured_prompt(
    subject: str,
    difficulty_overall: str,
    total_marks: int,
    slots: List[Dict[str, Any]],
    context_by_unit: Dict[str, str],
    validation_feedback: Optional[str] = None,
) -> tuple:
    """Returns (system_instruction, user_prompt) for the structured call.

    ``validation_feedback`` is used on the bounded retry: it repeats the
    deterministic validation errors while keeping the original slot plan and
    blueprint constraints unchanged.
    """
    slot_lines = []
    for s in slots:
        slot_lines.append(
            f"{s['slot_id']}: type={s['type']}, marks={s['marks']}, "
            f"difficulty={s['difficulty']}, bloom={s['bloom_level']}, unit/topic={s['unit']}"
        )
    context_parts = []
    for unit, ctx in context_by_unit.items():
        context_parts.append(f"--- SOURCE UNIT: {unit} ---\n{ctx}")
    combined = "\n\n".join(context_parts)

    bloom_guide = "\n".join(f"- {lvl}: {BLOOM_HINTS[lvl]}" for lvl in BLOOM_LEVELS)
    diff_guide = "\n".join(f"- {lvl}: {DIFFICULTY_HINTS[lvl]}" for lvl in ["Easy", "Medium", "Hard"])
    type_guide = "\n".join(f"- {t}: {TYPE_HINTS[t]}" for t in sorted(TYPE_HINTS))

    system_instruction = (
        "You are an expert academic examiner creating a professional question paper.\n"
        "STRICT GROUNDING: use ONLY the facts in REFERENCE STUDY MATERIAL. "
        "No external knowledge, no invented chapters or definitions.\n"
        "Every question must exactly match its assigned slot's type, marks, difficulty, "
        "bloom_level, and unit. Never add extra questions or alter slot metadata.\n"
        "If the material lacks information for a slot, emit for that slot "
        "{\"question\": \"INSUFFICIENT_CONTEXT\", ...} with its metadata intact.\n"
        "Respond ONLY with valid JSON matching the required schema."
    )
    prompt = f"""=== REFERENCE STUDY MATERIAL (STRICT SOURCE) ===
{combined}

=== EXAMINATION SPECIFICATIONS ===
Subject / Topic: {subject}
Overall difficulty: {difficulty_overall}
Total marks: {total_marks}

=== HARD OUTPUT CONSTRAINTS ===
- Produce EXACTLY {len(slots)} questions in total: one question per slot, in the same order.
- Do NOT add extra questions. Do NOT duplicate, merge, split, or omit any slot.
- For every question, copy type, marks, difficulty, bloom_level, and unit from its slot EXACTLY.
- The overall difficulty "{difficulty_overall}" is only a paper-level label. It never overrides
  an individual slot's difficulty.
- Every question id must equal its slot id.

=== PER-QUESTION SLOTS (generate EXACTLY these, in order) ===
{chr(10).join(slot_lines)}

=== COGNITIVE GUIDES ===
Bloom levels:
{bloom_guide}
Difficulty:
{diff_guide}
Question types:
{type_guide}

=== REQUIRED JSON OUTPUT ===
A single JSON object:
{{
  "title": "Examination Paper: {subject}",
  "subject": "{subject}",
  "total_marks": {total_marks},
  "difficulty": "{difficulty_overall}",
  "instructions": ["..."],
  "sections": [
    {{
      "section_title": "Section A: ...",
      "type": "MCQ",
      "marks_per_question": 1,
      "questions": [
        {{
          "id": "Q1",
          "question": "...",
          "type": "MCQ",
          "marks": 1,
          "difficulty": "Easy",
          "bloom_level": "Remember",
          "unit": "Unit 1",
          "topic": "CPU Scheduling",
          "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
          "answer": "A. ...",
          "explanation": "..."
        }}
      ]
    }}
  ]
}}
Rules: every question carries type/marks/difficulty/bloom_level/unit/topic copied from its slot
(topic = finest-grained sub-topic you choose within the slot's unit). Output sections in the
same order as the slot list, grouping consecutive slots of the same type into one section.
Every question id must equal its slot id. MCQ has 4 options; all other types have
"options": []. Respond ONLY with the JSON object."""

    if validation_feedback:
        prompt += f"""

=== CORRECTION REQUIRED ON RETRY ===
The previous output was rejected by deterministic validation:
{validation_feedback}

Regenerate the COMPLETE paper from the original slot list above. Fix every listed violation
exactly. Do NOT add, remove, merge, split, or reorder questions, and do NOT change any slot's
type, marks, difficulty, bloom_level, or unit."""

    return system_instruction, prompt


def _extract_json_object(raw: str) -> str:
    """Repair-parse: strip fences, grab outermost {...}, drop trailing commas."""
    t = raw.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    m = re.search(r"(\{[\s\S]*\})", t)
    if m:
        t = m.group(1)
    # Tolerate trailing commas before } or ].
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return t.strip()


def parse_structured_output(raw_text: str) -> dict:
    """Parse + shape-check. Raises ValueError with a clear message.

    The endpoint relies on ``sections`` being a list of objects whose
    ``questions`` is a list. A model that returns e.g.
    ``{"sections": {"type": "MCQ"}}`` used to reach ``.get(...)`` on a string
    and crash with HTTP 500; validating here turns it into the endpoint's
    normal bounded retry / HTTP 502 path.
    """
    cleaned = _extract_json_object(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model output was not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object.")
    if "sections" not in data:
        raise ValueError("Model output missing required 'sections' key.")
    if "error" in data:
        raise ValueError(str(data.get("message", "Model reported insufficient context.")))
    sections = data["sections"]
    if not isinstance(sections, list):
        raise ValueError("Model output 'sections' must be a list.")
    for s_idx, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            raise ValueError(f"Model output section {s_idx} must be an object.")
        questions = section.get("questions")
        if not isinstance(questions, list):
            raise ValueError(f"Model output section {s_idx} must contain a 'questions' list.")
        for q_idx, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                raise ValueError(f"Model output section {s_idx}, question {q_idx} must be an object.")
    return data


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _coerce_int(value: Any) -> int:
    """Strict integer coercion (no truncation of 1.5, no bools)."""
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("non-integral float")
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    raise ValueError("not an integer")


def _map_questions_to_slots(
    questions: List[Dict[str, Any]], slots: List[Dict[str, Any]]
) -> List[Optional[Dict[str, Any]]]:
    """Map output questions to slots by id when reliable, else by position.

    Models sometimes renumber questions even when they keep the requested order.
    Positional mapping remains the fallback so a correct paper is not rejected
    merely because ids were rewritten.
    """
    slot_ids = [str(s.get("slot_id", "")).strip() for s in slots]
    qids = [str(q.get("id", "")).strip() for q in questions]
    if (
        len(qids) == len(slot_ids)
        and all(qids)
        and len(set(qids)) == len(qids)
        and set(qids) == set(slot_ids)
    ):
        by_id = {str(s.get("slot_id", "")).strip(): s for s in slots}
        return [by_id[qid] for qid in qids]
    return [slots[i] if i < len(slots) else None for i in range(len(questions))]


def trim_unmatched_questions(
    paper: dict, slots: List[Dict[str, Any]]
) -> tuple:
    """Remove only unambiguous extra questions before strict validation.

    This is deliberately conservative. An extra question is removed only when:
      - every output question has a non-empty, unique id;
      - every requested slot id is present exactly once; and
      - the surplus questions have ids that are not in the slot plan.

    Any missing slot, duplicate/missing id, or malformed shape is left untouched
    so the normal strict validator rejects it and the endpoint retries. Questions
    that match a slot are never dropped or renumbered, so ordering and marks are
    preserved. Returns ``(paper_or_original, removed_count)``.
    """
    if not isinstance(paper, dict) or not isinstance(paper.get("sections"), list):
        return paper, 0

    slot_ids = {
        str(s.get("slot_id", "")).strip()
        for s in slots
        if str(s.get("slot_id", "")).strip()
    }
    if not slot_ids:
        return paper, 0

    entries: List[tuple] = []
    for section in paper["sections"]:
        if not isinstance(section, dict):
            return paper, 0
        questions = section.get("questions")
        if not isinstance(questions, list):
            return paper, 0
        for question in questions:
            if not isinstance(question, dict):
                return paper, 0
            entries.append((question, str(question.get("id", "")).strip()))

    if len(entries) <= len(slots):
        return paper, 0

    qids = [qid for _, qid in entries]
    if not all(qids) or len(set(qids)) != len(qids):
        return paper, 0
    if not slot_ids.issubset(set(qids)):
        return paper, 0

    extra_ids = {qid for qid in qids if qid not in slot_ids}
    if not extra_ids:
        return paper, 0

    new_sections = []
    kept_questions = []
    removed = 0
    for section in paper["sections"]:
        kept = []
        for question in section.get("questions", []):
            qid = str(question.get("id", "")).strip()
            if qid in extra_ids:
                removed += 1
            else:
                kept.append(question)
        kept_questions.extend(kept)
        if kept:
            new_section = dict(section)
            new_section["questions"] = kept
            new_sections.append(new_section)

    normalized = dict(paper)
    normalized["sections"] = new_sections

    # If the paper total was internally consistent with all questions
    # (including the extra one), reconcile it to the kept questions. Any other
    # total mismatch is left for the strict validator to reject.
    def _mark_sum(questions: List[Dict[str, Any]]) -> Optional[int]:
        try:
            return sum(_coerce_int(q.get("marks")) for q in questions)
        except (TypeError, ValueError):
            return None

    original_sum = _mark_sum([q for q, _ in entries])
    kept_sum = _mark_sum(kept_questions)
    if original_sum is not None and kept_sum is not None:
        try:
            current_total = _coerce_int(paper.get("total_marks"))
        except (TypeError, ValueError):
            current_total = None
        if current_total == original_sum:
            normalized["total_marks"] = kept_sum

    return normalized, removed


def validate_structured_paper(paper: dict, slots: List[Dict[str, Any]]) -> dict:
    """Validate every generated question against its authoritative slot.

    Missing metadata (type/marks/difficulty/bloom_level/unit and the paper-level
    total_marks) is safely repaired from the slot. A *present* value that
    disagrees with the slot is never rewritten: it is reported as an error so
    the endpoint can retry and, if needed, fail instead of returning a paper
    whose marks/types were silently altered to make the totals match.

    Returns {"ok": bool, "errors": List[str], "paper": dict}.
    """
    errors: List[str] = []
    if not isinstance(paper, dict):
        return {"ok": False, "errors": ["Paper output must be a JSON object."], "paper": paper}

    sections = paper.get("sections")
    if not isinstance(sections, list):
        return {"ok": False, "errors": ["Paper output must contain a 'sections' list."], "paper": paper}

    questions: List[Dict[str, Any]] = []
    for s_idx, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            errors.append(f"Section {s_idx} must be an object.")
            continue
        qs = section.get("questions")
        if not isinstance(qs, list):
            errors.append(f"Section {s_idx} must contain a 'questions' list.")
            continue
        for q_idx, q in enumerate(qs, start=1):
            if not isinstance(q, dict):
                errors.append(f"Section {s_idx}, question {q_idx} must be an object.")
                continue
            questions.append(q)

    if len(questions) != len(slots):
        errors.append(f"Expected {len(slots)} questions, got {len(questions)}.")

    mapped = _map_questions_to_slots(questions, slots)
    for pos, (q, slot) in enumerate(zip(questions, mapped), start=1):
        if slot is None:
            errors.append(f"Question {pos} has no matching slot.")
            continue
        label = f"Question {pos} ({slot.get('slot_id', '?')})"

        expected_type = str(slot.get("type", ""))
        actual_type = q.get("type")
        if _is_missing(actual_type):
            q["type"] = expected_type
        elif str(actual_type).strip().casefold() != expected_type.casefold():
            errors.append(
                f"{label} type '{actual_type}' does not match slot type '{expected_type}'."
            )
        else:
            q["type"] = expected_type

        expected_marks = int(slot.get("marks", 0))
        actual_marks = q.get("marks")
        if _is_missing(actual_marks):
            q["marks"] = expected_marks
        else:
            try:
                marks_val = _coerce_int(actual_marks)
            except (TypeError, ValueError):
                errors.append(f"{label} marks '{actual_marks}' is not a valid integer.")
            else:
                if marks_val != expected_marks:
                    errors.append(
                        f"{label} marks {marks_val} do not match slot marks {expected_marks}."
                    )
                else:
                    q["marks"] = expected_marks

        for field, expected in (
            ("difficulty", str(slot.get("difficulty", ""))),
            ("bloom_level", str(slot.get("bloom_level", ""))),
            ("unit", str(slot.get("unit", ""))),
        ):
            actual = q.get(field)
            if _is_missing(actual):
                q[field] = expected
            elif str(actual).strip().casefold() != expected.casefold():
                errors.append(
                    f"{label} {field} '{actual}' does not match slot {field} '{expected}'."
                )
            else:
                q[field] = expected

    expected_total = sum(int(s.get("marks", 0)) for s in slots)
    paper_total = paper.get("total_marks")
    if _is_missing(paper_total):
        paper["total_marks"] = expected_total
    else:
        try:
            total_val = _coerce_int(paper_total)
        except (TypeError, ValueError):
            errors.append(f"Paper total_marks '{paper_total}' is not a valid integer.")
        else:
            if total_val != expected_total:
                errors.append(
                    f"Paper total_marks ({total_val}) do not match requested total ({expected_total})."
                )
            else:
                paper["total_marks"] = expected_total

    if len(questions) == len(slots):
        try:
            question_total = sum(_coerce_int(q.get("marks")) for q in questions)
        except (TypeError, ValueError):
            question_total = None
        if question_total is not None and question_total != expected_total:
            errors.append(
                f"Question marks total ({question_total}) do not match requested total ({expected_total})."
            )

    return {"ok": not errors, "errors": errors, "paper": paper}


def post_fill_sources(paper: dict, sources_by_unit: Dict[str, List[str]]) -> dict:
    """Deterministically set each question's source_documents from retrieval.

    Maps question.unit → filenames retrieved for that unit (max 3). Unknown
    units receive an empty list: another unit's files are never attributed to
    them. Never trusts LLM provenance.
    """
    for section in paper.get("sections", []):
        for q in section.get("questions", []):
            unit = (q.get("unit") or "").strip()
            q["source_documents"] = sources_by_unit.get(unit, [])[:3]
    return paper


def call_ollama_structured(
    base_url: str,
    model: str,
    system_instruction: str,
    prompt: str,
    timeout: int = 300,
) -> str:
    """Single Ollama call with one retry on transport/HTTP failure.

    Returns the raw response string. Raises RuntimeError with safe messages.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_instruction,
        "stream": False,
        "format": "json",
        "options": {"num_gpu": 99, "temperature": 0.1, "num_ctx": 4096},
    }
    last_err: Optional[str] = None
    for attempt in (1, 2):
        try:
            resp = requests.post(
                f"{base_url.rstrip('/')}/api/generate",
                json=payload,
                headers={"Connection": "close"},
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.error(f"[OLLAMA-STRUCT] HTTP {resp.status_code}: {resp.text[:500]}")
                last_err = f"HTTP {resp.status_code}"
                continue
            return resp.json().get("response", "")
        except requests.exceptions.Timeout:
            logger.warning(f"[OLLAMA-STRUCT] Timeout on attempt {attempt}")
            last_err = "timeout"
        except Exception as e:
            logger.warning(f"[OLLAMA-STRUCT] Attempt {attempt} failed: {e}")
            last_err = "transport error"
    raise RuntimeError(f"Ollama generation failed ({last_err}). Please retry.")
