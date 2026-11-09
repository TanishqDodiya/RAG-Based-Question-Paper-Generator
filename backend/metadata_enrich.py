"""Metadata enrichment for RAG chunks (M3).

Deterministic heuristics only — no LLM calls. Every helper degrades
gracefully to "General" / "" so old or odd documents never break ingest.
"""

import re

UNIT_PATTERNS = [
    re.compile(r"\b(unit|chapter|module|section)\s*[-:]?\s*(\d+[a-z]?)", re.IGNORECASE),
    re.compile(r"\b(unit|chapter|module)\s*[-:]?\s*([ivxlcdm]+)\b", re.IGNORECASE),
]

MAX_SECTION_LEN = 80


def detect_unit(text: str, fallback: str = "General") -> str:
    """Return e.g. 'Unit 3' from the first unit/chapter/module header found."""
    if not text:
        return fallback
    # Only scan the head of the segment to avoid picking up cross-references.
    head = text[:2000]
    for pat in UNIT_PATTERNS:
        m = pat.search(head)
        if m:
            kind = m.group(1).strip().capitalize()
            num = m.group(2).strip().upper()
            return f"{kind} {num}"
    return fallback


def detect_section(text: str) -> str:
    """Return a short heading-like first line as the section label ('' if none)."""
    if not text:
        return ""
    for line in text.splitlines():
        s = line.strip().strip("-–—*#").strip()
        if not s or len(s) > MAX_SECTION_LEN:
            continue
        # Skip pure numbers / page footers.
        if re.fullmatch(r"[\d\s\-–—\.ivxlcdm]+", s, re.IGNORECASE):
            continue
        # Heading-like: starts with capital / digit, mostly words.
        if re.match(r"[A-Z0-9]", s) and len(re.findall(r"[A-Za-z]{2,}", s)) >= 2:
            return s[:MAX_SECTION_LEN]
    return ""


def enrich_segment(segment_text: str, filename: str = "", override_unit: str = "") -> dict:
    """Build {unit, section} for one document segment."""
    if override_unit and override_unit.strip():
        unit = override_unit.strip()[:60]
    else:
        unit = detect_unit(segment_text or "")
        # Filename hint as last resort, e.g. "OS_Unit2_notes.pdf".
        if unit == "General" and filename:
            unit = detect_unit(filename.replace("_", " ").replace("-", " "), fallback="General")
    return {"unit": unit, "section": detect_section(segment_text or "")}
