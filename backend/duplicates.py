"""Semantic duplicate detection (M6).

Deterministic and offline: combines token-set cosine with difflib sequence
ratio and takes the max (high recall for paraphrases like
"Explain process scheduling" vs "Describe how process scheduling works").
Flags pairs with similarity >= 0.80.
"""

import difflib
import math
import re
from typing import List, Dict, Any

SIMILARITY_THRESHOLD = 0.75

# Verb-level synonym normalization so rewordings ("Explain X" vs
# "Describe how X works") score as the paraphrases they are.
SYNONYMS = {
    "explain": "EXPLAIN", "describe": "EXPLAIN", "discuss": "EXPLAIN",
    "elaborate": "EXPLAIN", "illustrate": "EXPLAIN",
    "list": "LIST", "name": "LIST", "state": "LIST", "enumerate": "LIST",
    "compare": "COMPARE", "contrast": "COMPARE", "differentiate": "COMPARE",
    "what": "WHAT", "which": "WHAT",
    "how": "HOW", "method": "HOW",
    "why": "WHY", "reason": "WHY",
}


def _content_tokens(text: str) -> List[str]:
    raw = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return [SYNONYMS.get(w, w) for w in raw]


def token_cosine(a: str, b: str) -> float:
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    fa: Dict[str, int] = {}
    fb: Dict[str, int] = {}
    for w in ta:
        fa[w] = fa.get(w, 0) + 1
    for w in tb:
        fb[w] = fb.get(w, 0) + 1
    dot = sum(fa[w] * fb.get(w, 0) for w in fa)
    na = math.sqrt(sum(v * v for v in fa.values()))
    nb = math.sqrt(sum(v * v for v in fb.values()))
    return dot / (na * nb) if na and nb else 0.0


def similarity(a: str, b: str) -> float:
    """Max of token-cosine and sequence ratio (0..1)."""
    if not a or not b:
        return 0.0
    if a.strip() == b.strip():
        return 1.0
    seq = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return max(token_cosine(a, b), seq)


def find_duplicates(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """questions: [{id, question}]. Returns [{q1, q2, similarity}] sorted desc."""
    pairs = []
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            sim = similarity(questions[i].get("question", ""), questions[j].get("question", ""))
            if sim >= SIMILARITY_THRESHOLD:
                pairs.append({
                    "q1": questions[i].get("id", f"Q{i + 1}"),
                    "q2": questions[j].get("id", f"Q{j + 1}"),
                    "similarity": round(sim, 4),
                    "similarity_pct": round(sim * 100, 1),
                })
    return sorted(pairs, key=lambda p: p["similarity"], reverse=True)
