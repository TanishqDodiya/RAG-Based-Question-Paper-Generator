"""Paper analytics + heuristic quality score (M7).

Deterministic, offline. Compares Target (blueprint) vs Actual (paper metadata)
per axis and derives a system-generated quality score from validation +
duplicate outputs. The score is explicitly labelled heuristic — it is a
mean of check pass-rates, not a scientific accuracy percentage.
"""

from typing import List, Dict, Any, Optional

FLAG_DELTA_PCT = 10.0


def _marks_by(paper: Dict[str, Any], key: str, norm=None) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for section in paper.get("sections", []):
        for q in section.get("questions", []):
            label = str(q.get(key, "") or ("General" if key == "unit" else "Unknown"))
            if norm:
                label = norm(label)
            try:
                marks = float(q.get("marks", section.get("marks_per_question", 0)) or 0)
            except (TypeError, ValueError):
                marks = 0
            out[label] = out.get(label, 0.0) + marks
    return out


def _pct_dist(marks: Dict[str, float]) -> Dict[str, float]:
    total = sum(marks.values()) or 1.0
    return {k: round(v * 100.0 / total, 1) for k, v in marks.items()}


def _compare(target_pct: Dict[str, float], actual_pct: Dict[str, float]) -> List[Dict[str, Any]]:
    labels = sorted(set(target_pct) | set(actual_pct))
    rows = []
    for label in labels:
        t = float(target_pct.get(label, 0.0))
        a = float(actual_pct.get(label, 0.0))
        delta = round(a - t, 1)
        rows.append({
            "label": label, "target_pct": t, "actual_pct": a,
            "delta": delta, "flagged": abs(delta) > FLAG_DELTA_PCT,
        })
    return rows


def _pass_rate(validation: Optional[Dict[str, Any]], check: str) -> Optional[float]:
    if not validation or not validation.get("results"):
        return None
    res = validation["results"]
    ok = sum(1 for r in res if (r.get("checks", {}).get(check, {}).get("status")) == "PASS")
    return round(ok * 100.0 / len(res), 1)


def compute_analytics(
    paper: Dict[str, Any],
    blueprint: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
    duplicates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    bp = blueprint or {}
    total_marks = sum(
        float(q.get("marks", 0) or 0)
        for s in paper.get("sections", []) for q in s.get("questions", []))
    n_questions = sum(len(s.get("questions", [])) for s in paper.get("sections", []))

    actual_units = _marks_by(paper, "unit")
    actual_diff = _marks_by(paper, "difficulty", norm=lambda x: x.capitalize() or "Unknown")
    actual_bloom = _marks_by(paper, "bloom_level", norm=lambda x: (x or "").capitalize() or "Unknown")
    actual_types = _marks_by(paper, "type")

    # Targets from blueprint (marks space).
    t_marks = float(bp.get("total_marks", 0) or 0) or (total_marks or 1.0)
    target_units, target_diff, target_bloom, target_types = {}, {}, {}, {}
    for t in bp.get("topics", []):
        target_units[str(t.get("name", "?"))] = round(t_marks * float(t.get("percentage", 0)) / 100.0, 1)
    d = bp.get("difficulty", {}) or {}
    for lvl, key in (("Easy", "easy"), ("Medium", "medium"), ("Hard", "hard")):
        target_diff[lvl] = round(t_marks * float(d.get(key, 0)) / 100.0, 1)
    b = bp.get("bloom", {}) or {}
    for lvl in ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"):
        target_bloom[lvl] = round(t_marks * float(b.get(lvl.lower(), 0)) / 100.0, 1)
    for t in bp.get("types", []):
        target_types[str(t.get("type", "?"))] = float(t.get("marks", 0))

    comparison = {}
    if bp:
        comparison = {
            "units": _compare(_pct_dist(target_units), _pct_dist(actual_units)),
            "difficulty": _compare(_pct_dist(target_diff), _pct_dist(actual_diff)),
            "bloom": _compare(_pct_dist(target_bloom), _pct_dist(actual_bloom)),
            "types": _compare(_pct_dist(target_types), _pct_dist(actual_types)),
        }

    # Heuristic quality components (each 0-100 or None when inputs missing).
    syllabus = _pass_rate(validation, "syllabus")
    grounding = _pass_rate(validation, "grounding")
    answer = _pass_rate(validation, "answer_support")
    bloom_q = _pass_rate(validation, "bloom")
    diff_q = _pass_rate(validation, "difficulty")

    dup_pairs = (duplicates or {}).get("pairs", []) if duplicates else None
    dup_count = (duplicates or {}).get("count", 0) if duplicates else 0
    diversity = None
    if dup_pairs is not None and n_questions > 1:
        total_pairs = n_questions * (n_questions - 1) / 2
        diversity = round(max(0.0, 1.0 - len(dup_pairs) / total_pairs) * 100.0, 1)
    dup_risk = "Unknown" if dup_pairs is None else ("Low" if dup_count == 0 else ("Medium" if dup_count <= 2 else "High"))

    # Difficulty/Bloom balance vs blueprint (100 = perfect match).
    def _balance(axis: str) -> Optional[float]:
        rows = comparison.get(axis, [])
        if not rows:
            return None
        return round(max(0.0, 100.0 - sum(abs(r["delta"]) for r in rows) / 2.0), 1)

    components = {
        "syllabus_coverage": syllabus,
        "source_grounding": grounding,
        "answer_support": answer,
        "bloom_distribution": _balance("bloom") if bp else bloom_q,
        "difficulty_balance": _balance("difficulty") if bp else diff_q,
        "question_diversity": diversity,
    }
    available = [v for v in components.values() if v is not None]
    overall = round(sum(available) / len(available), 1) if available else None

    return {
        "total_marks": total_marks,
        "n_questions": n_questions,
        "actual": {
            "units": actual_units, "difficulty": actual_diff,
            "bloom": actual_bloom, "types": actual_types,
        },
        "targets": {"units": target_units, "difficulty": target_diff,
                    "bloom": target_bloom, "types": target_types} if bp else None,
        "comparison": comparison or None,
        "quality": {
            "components": components,
            "duplicate_risk": dup_risk,
            "duplicate_pairs": dup_count,
            "overall": overall,
            "label": "System-generated heuristic quality score (mean of validation pass-rates) — not a scientific accuracy percentage.",
        },
    }
