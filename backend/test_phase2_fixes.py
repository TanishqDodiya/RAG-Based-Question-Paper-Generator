"""Regression tests for Phase 2 fixes: H-03, H-11, H-12, H-15, H-16.

Deterministic: no live Ollama or ChromaDB access. The LLM/vector boundary is
stubbed exactly where the endpoints would otherwise call it.

Run:  python test_phase2_fixes.py
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from fastapi import HTTPException
from fastapi.testclient import TestClient

from generate import post_fill_sources, validate_structured_paper

client = TestClient(main.app, raise_server_exceptions=False)

SESSION = "phase2_regression_session"


class FakeCollection:
    """Minimal Chroma collection double used by the RAG gates."""

    def __init__(self, text="Operating Systems scheduling uses Round Robin.",
                 unit="Unit 1", distance=0.2):
        self.text = text
        self.unit = unit
        self.distance = distance

    def get(self, where=None, include=None, **kwargs):
        return {
            "ids": ["chunk-1"],
            "documents": [self.text],
            "metadatas": [{"filename": "os.pdf", "unit": self.unit}],
        }

    def query(self, **kwargs):
        return {
            "documents": [[self.text]],
            "distances": [[self.distance]],
            "metadatas": [[{"filename": "os.pdf", "unit": self.unit}]],
        }


class FakeOllamaResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return {"response": json.dumps(self._payload)}


LEGACY_PAYLOAD = {
    "subject": "Operating Systems",
    "total_marks": 1,
    "difficulty": "Medium",
    "sections": [{"type": "MCQ", "count": 1, "marks_per_q": 1}],
}

LEGACY_PAPER = {
    "title": "Examination Paper: Operating Systems",
    "subject": "Operating Systems",
    "total_marks": 1,
    "sections": [{
        "type": "MCQ",
        "marks_per_question": 1,
        "questions": [{"id": "Q1", "question": "Which algorithm uses a time quantum?"}],
    }],
}

STRUCTURED_PAYLOAD = dict(LEGACY_PAYLOAD)

STRUCTURED_PAPER = {
    "title": "Examination Paper: Operating Systems",
    "total_marks": 1,
    "sections": [{
        "type": "MCQ",
        "marks_per_question": 1,
        "questions": [{
            "id": "Q1",
            "question": "Which algorithm uses a time quantum?",
            "type": "MCQ",
            "marks": 1,
            "difficulty": "Easy",
            "bloom_level": "Remember",
            "unit": "General",
        }],
    }],
}

REGEN_QUESTION = {
    "id": "Q7", "type": "MCQ", "marks": 2, "difficulty": "Hard",
    "bloom_level": "Analyze", "unit": "Unit 2", "topic": "Scheduling",
}

REGEN_OUTPUT = {
    "question": "Which fair-share algorithm relies on a time quantum?",
    "options": ["A. FCFS", "B. Round Robin", "C. SJF", "D. Priority"],
    "answer": "B. Round Robin",
    "explanation": "Quantum-based.",
}


def _blueprint(total_marks=3, types=None, topics=None, subject="Operating Systems"):
    return {
        "subject": subject,
        "exam_name": "Mid-Semester Examination",
        "total_marks": total_marks,
        "duration_minutes": 120,
        "topics": topics or [
            {"name": "Unit 1", "percentage": 50},
            {"name": "Unit 2", "percentage": 50},
        ],
        "difficulty": {"easy": 100, "medium": 0, "hard": 0},
        "types": types or [{"type": "MCQ", "marks": 2}, {"type": "Short", "marks": 1}],
        "bloom": {"remember": 100, "understand": 0, "apply": 0,
                  "analyze": 0, "evaluate": 0, "create": 0},
    }


BLUEPRINT_PAYLOAD = {
    "subject": "Operating Systems",
    "total_marks": 3,
    "difficulty": "Medium",
    "sections": [
        {"type": "MCQ", "count": 2, "marks_per_q": 1},
        {"type": "Short", "count": 1, "marks_per_q": 1},
    ],
    "blueprint": _blueprint(),
}

BLUEPRINT_PAPER = {
    "title": "Examination Paper: Operating Systems",
    "total_marks": 3,
    "sections": [
        {
            "type": "MCQ",
            "marks_per_question": 1,
            "questions": [
                {"id": "Q1", "question": "Which scheduler uses a time quantum?",
                 "type": "MCQ", "marks": 1, "difficulty": "Easy",
                 "bloom_level": "Remember", "unit": "Unit 1"},
                {"id": "Q2", "question": "What is a process control block?",
                 "type": "MCQ", "marks": 1, "difficulty": "Easy",
                 "bloom_level": "Remember", "unit": "Unit 1"},
            ],
        },
        {
            "type": "Short",
            "marks_per_question": 1,
            "questions": [
                {"id": "Q3", "question": "Explain round-robin scheduling.",
                 "type": "Short", "marks": 1, "difficulty": "Easy",
                 "bloom_level": "Remember", "unit": "Unit 2"},
            ],
        },
    ],
}


def _retrieval_for_units(missing=(), wrong_unit=(), distance=0.2):
    def fake_retrieve(query, session_id, unit=None, n_results=8, allow_fallback=True):
        if unit in missing:
            return {"documents": [], "distances": [], "metadatas": []}
        returned_unit = "Unit 1" if unit in wrong_unit else (unit or "Unit 1")
        return {
            "documents": [f"Relevant notes for {unit or 'General'}."],
            "distances": [distance],
            "metadatas": [{"filename": f"{unit or 'general'}.pdf", "unit": returned_unit}],
        }
    return fake_retrieve


# ---------------------------------------------------------------- H-03
class TestH03SharedThreshold(unittest.TestCase):
    """Legacy, structured and regeneration must obey one threshold value."""

    def test_threshold_is_shared_by_all_workflows(self):
        for threshold, expected in ((0.30, 422), (0.50, 200)):
            with self.subTest(workflow="legacy", threshold=threshold):
                with patch.object(main, "RAG_RELEVANCE_THRESHOLD", threshold), \
                        patch.object(main, "notes_collection", FakeCollection(distance=0.40)), \
                        patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                        patch.object(main.requests, "post",
                                     return_value=FakeOllamaResponse(LEGACY_PAPER)):
                    r = client.post("/generate-paper", headers={"X-Session-ID": SESSION},
                                    json=LEGACY_PAYLOAD)
                self.assertEqual(r.status_code, expected, r.text[:300])

            with self.subTest(workflow="structured", threshold=threshold):
                with patch.object(main, "RAG_RELEVANCE_THRESHOLD", threshold), \
                        patch.object(main, "notes_collection", FakeCollection(distance=0.40)), \
                        patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                        patch.object(main, "_call_ollama_structured",
                                     return_value=json.dumps(STRUCTURED_PAPER)):
                    r = client.post("/api/generate-structured",
                                    headers={"X-Session-ID": SESSION},
                                    json=STRUCTURED_PAYLOAD)
                self.assertEqual(r.status_code, expected, r.text[:300])

            with self.subTest(workflow="regeneration", threshold=threshold):
                with patch.object(main, "RAG_RELEVANCE_THRESHOLD", threshold), \
                        patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                        patch.object(main, "retrieve_relevant",
                                     side_effect=_retrieval_for_units(distance=0.40)), \
                        patch.object(main, "_call_ollama_structured",
                                     return_value=json.dumps(REGEN_OUTPUT)):
                    r = client.post("/api/questions/regenerate",
                                    headers={"X-Session-ID": SESSION},
                                    json={"subject": "Operating Systems",
                                          "question": REGEN_QUESTION})
                self.assertEqual(r.status_code, expected, r.text[:300])


# ---------------------------------------------------------------- H-11
class TestH11TopicValidation(unittest.TestCase):
    def test_short_and_technical_subjects_accepted(self):
        for topic in ["AI", "OS", "C++", "R", "Rhythm", "Rhythms", "C#", "DBMS",
                      "Operating Systems", "Data Structures & Algorithms",
                      "COVID-19", "Machine Learning"]:
            with self.subTest(topic=topic):
                self.assertEqual(main.validate_educational_topic(topic), topic)

    def test_invalid_and_empty_subjects_rejected(self):
        for topic in ["", "   ", "12345", "!!!", "a", "aaaaaa", "xyzxyz",
                      "asdfgh", "qwerty", "hfhdf6512", "asdfgh123", "1111a"]:
            with self.subTest(topic=topic):
                with self.assertRaises(HTTPException) as ctx:
                    main.validate_educational_topic(topic)
                self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------- H-12
class TestH12BlueprintValidation(unittest.TestCase):
    def test_type_marks_must_equal_blueprint_total(self):
        bp = _blueprint(total_marks=4,
                        types=[{"type": "MCQ", "marks": 1}, {"type": "Short", "marks": 2}])
        r = client.post("/api/blueprint/validate", json=bp)
        self.assertEqual(r.status_code, 400)
        self.assertIn("must equal total marks", r.text)

    def test_duplicate_and_blank_structure_rejected(self):
        dup = _blueprint(types=[{"type": "MCQ", "marks": 2}, {"type": "MCQ", "marks": 1}])
        r = client.post("/api/blueprint/validate", json=dup)
        self.assertEqual(r.status_code, 400)
        self.assertIn("unique", r.text)

        blank = _blueprint(topics=[{"name": "   ", "percentage": 100}])
        r = client.post("/api/blueprint/validate", json=blank)
        self.assertEqual(r.status_code, 400)
        self.assertIn("non-empty", r.text)

        no_subject = _blueprint(subject="   ")
        r = client.post("/api/blueprint/validate", json=no_subject)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Subject is required", r.text)

    def test_blueprint_total_must_match_requested_total(self):
        payload = dict(BLUEPRINT_PAYLOAD)
        payload["total_marks"] = 1
        payload["sections"] = [{"type": "MCQ", "count": 1, "marks_per_q": 1}]
        payload["blueprint"] = _blueprint(
            total_marks=2,
            types=[{"type": "MCQ", "marks": 2}],
            topics=[{"name": "Unit 1", "percentage": 100}],
        )
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "_call_ollama_structured",
                             side_effect=AssertionError("LLM must not be called")):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=payload)
        self.assertEqual(r.status_code, 400, r.text[:300])
        self.assertIn("must match requested total marks", r.text)

    def test_failed_validation_cannot_reuse_previous_blueprint(self):
        # A previously valid blueprint is accepted...
        self.assertEqual(client.post("/api/blueprint/validate", json=_blueprint()).status_code, 200)
        # ...but a later invalid one fails and cannot silently become active.
        invalid = _blueprint(total_marks=4,
                             types=[{"type": "MCQ", "marks": 1}])
        self.assertEqual(client.post("/api/blueprint/validate", json=invalid).status_code, 400)

        payload = dict(BLUEPRINT_PAYLOAD)
        payload["blueprint"] = invalid
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "_call_ollama_structured",
                             side_effect=AssertionError("LLM must not be called")):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=payload)
        self.assertEqual(r.status_code, 400, r.text[:300])


class TestH12FrontendStaleBlueprint(unittest.TestCase):
    """Static wiring check: a failed re-validation must clear App's blueprint."""

    def test_blueprint_form_clears_active_blueprint_on_invalid(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        form_path = os.path.join(root, "frontend", "src", "components", "BlueprintForm.jsx")
        app_path = os.path.join(root, "frontend", "src", "App.jsx")
        generator_path = os.path.join(root, "frontend", "src", "components", "GeneratorForm.jsx")
        with open(form_path, encoding="utf-8") as f:
            form = f.read()
        with open(app_path, encoding="utf-8") as f:
            app = f.read()
        with open(generator_path, encoding="utf-8") as f:
            generator = f.read()

        self.assertIn("if (onInvalid) onInvalid();", form)
        self.assertIn("onInvalid={() => setBlueprint(null)}", app)
        # Structured generation is disabled when App clears the blueprint.
        self.assertIn("const useStructured = blueprint?.payload && blueprint?.expanded;", generator)


# ---------------------------------------------------------------- H-15
class TestH15UnitSpecificRetrieval(unittest.TestCase):
    def test_missing_unit_context_is_reported(self):
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "retrieve_relevant",
                             side_effect=_retrieval_for_units(missing={"Unit 2"})), \
                patch.object(main, "_call_ollama_structured",
                             side_effect=AssertionError("LLM must not be called")):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=BLUEPRINT_PAYLOAD)
        self.assertEqual(r.status_code, 422, r.text[:300])
        self.assertIn("Unit 2", r.text)

    def test_wrong_unit_metadata_is_not_used(self):
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "retrieve_relevant",
                             side_effect=_retrieval_for_units(wrong_unit={"Unit 2"})), \
                patch.object(main, "_call_ollama_structured",
                             side_effect=AssertionError("LLM must not be called")):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=BLUEPRINT_PAYLOAD)
        self.assertEqual(r.status_code, 422, r.text[:300])
        self.assertIn("Unit 2", r.text)

    def test_retrieve_relevant_no_fallback_drops_wrong_unit(self):
        class IgnoringCollection(FakeCollection):
            def query(self, **kwargs):
                return {
                    "documents": [["Wrong unit material"]],
                    "distances": [[0.1]],
                    "metadatas": [[{"filename": "wrong.pdf", "unit": "Unit 1"}]],
                }

        with patch.object(main, "notes_collection", IgnoringCollection()):
            res = main.retrieve_relevant("q", SESSION, unit="Unit 2", allow_fallback=False)
        self.assertEqual(res["documents"], [])

        with patch.object(main, "notes_collection", IgnoringCollection()):
            res = main.retrieve_relevant("q", SESSION, unit="Unit 2", allow_fallback=True)
        self.assertTrue(res.get("fallback"))
        self.assertEqual(res["documents"], ["Wrong unit material"])

    def test_post_fill_sources_never_cross_fills(self):
        paper = {"sections": [{"questions": [
            {"id": "Q1", "unit": "Unit 1"},
            {"id": "Q2", "unit": "Unknown"},
        ]}]}
        out = post_fill_sources(paper, {"Unit 1": ["a.pdf"], "Unit 2": ["b.pdf"]})
        self.assertEqual(out["sections"][0]["questions"][0]["source_documents"], ["a.pdf"])
        self.assertEqual(out["sections"][0]["questions"][1]["source_documents"], [])

    def test_valid_units_still_generate(self):
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "retrieve_relevant",
                             side_effect=_retrieval_for_units()), \
                patch.object(main, "_call_ollama_structured",
                             return_value=json.dumps(BLUEPRINT_PAPER)):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=BLUEPRINT_PAYLOAD)
        self.assertEqual(r.status_code, 200, r.text[:500])
        body = r.json()
        self.assertEqual(body["generation_info"]["retrieval_units"], ["Unit 1", "Unit 2"])
        self.assertEqual(body["sections"][0]["questions"][0]["source_documents"], ["Unit 1.pdf"])


# ---------------------------------------------------------------- H-16
SLOTS = [
    {"slot_id": "Q1", "type": "MCQ", "marks": 1, "difficulty": "Easy",
     "bloom_level": "Remember", "unit": "Unit 1"},
    {"slot_id": "Q2", "type": "Short", "marks": 2, "difficulty": "Medium",
     "bloom_level": "Understand", "unit": "Unit 2"},
]

VALID_Q1 = {"id": "Q1", "question": "Which algorithm uses a time quantum?",
            "type": "MCQ", "marks": 1, "difficulty": "Easy",
            "bloom_level": "Remember", "unit": "Unit 1"}
VALID_Q2 = {"id": "Q2", "question": "Explain round-robin scheduling.",
            "type": "Short", "marks": 2, "difficulty": "Medium",
            "bloom_level": "Understand", "unit": "Unit 2"}


def _paper(q1=None, q2=None, total_marks=3):
    questions = [q for q in (q1, q2) if q is not None]
    return {"total_marks": total_marks,
            "sections": [{"type": "MCQ", "marks_per_question": 1,
                          "questions": questions}]}


class TestH16StrictQuestionValidation(unittest.TestCase):
    def test_valid_paper_passes(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1), dict(VALID_Q2)), SLOTS)
        self.assertTrue(res["ok"], res["errors"])

    def test_wrong_type_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1, type="Short"), dict(VALID_Q2)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("type" in e for e in res["errors"]))

    def test_wrong_marks_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1, marks=2), dict(VALID_Q2)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("marks" in e for e in res["errors"]))

    def test_wrong_difficulty_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1, difficulty="Hard"), dict(VALID_Q2)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("difficulty" in e for e in res["errors"]))

    def test_wrong_bloom_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1, bloom_level="Apply"), dict(VALID_Q2)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("bloom_level" in e for e in res["errors"]))

    def test_wrong_unit_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1, unit="Unit 2"), dict(VALID_Q2)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("unit" in e for e in res["errors"]))

    def test_wrong_count_rejected(self):
        res = validate_structured_paper(_paper(dict(VALID_Q1)), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Expected 2 questions, got 1" in e for e in res["errors"]))

    def test_wrong_total_marks_rejected(self):
        res = validate_structured_paper(
            _paper(dict(VALID_Q1), dict(VALID_Q2), total_marks=99), SLOTS)
        self.assertFalse(res["ok"])
        self.assertTrue(any("total_marks" in e for e in res["errors"]))

    def test_missing_metadata_is_repaired_from_slot(self):
        paper = {"sections": [{"type": "MCQ", "questions": [
            {"id": "Q1", "question": "Q1?"},
            {"id": "Q2", "question": "Q2?"},
        ]}]}
        res = validate_structured_paper(paper, SLOTS)
        self.assertTrue(res["ok"], res["errors"])
        q1, q2 = res["paper"]["sections"][0]["questions"]
        self.assertEqual((q1["type"], q1["marks"], q1["difficulty"],
                          q1["bloom_level"], q1["unit"]),
                         ("MCQ", 1, "Easy", "Remember", "Unit 1"))
        self.assertEqual((q2["type"], q2["marks"], q2["difficulty"],
                          q2["bloom_level"], q2["unit"]),
                         ("Short", 2, "Medium", "Understand", "Unit 2"))
        self.assertEqual(res["paper"]["total_marks"], 3)

    def test_endpoint_retries_then_fails_with_clear_error(self):
        invalid = {"total_marks": 1, "sections": [{"type": "MCQ", "questions": [{
            "id": "Q1", "question": "Q?", "type": "Short", "marks": 1,
            "difficulty": "Easy", "bloom_level": "Remember", "unit": "General",
        }]}]}
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "_call_ollama_structured",
                             return_value=json.dumps(invalid)):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=STRUCTURED_PAYLOAD)
        self.assertEqual(r.status_code, 502)
        self.assertIn("type", r.text)

    def test_endpoint_accepts_valid_output_on_retry(self):
        invalid = {"total_marks": 1, "sections": [{"type": "MCQ", "questions": [{
            "id": "Q1", "question": "Q?", "type": "Short", "marks": 1,
            "difficulty": "Easy", "bloom_level": "Remember", "unit": "General",
        }]}]}
        with patch.object(main, "notes_collection", FakeCollection()), \
                patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "_call_ollama_structured",
                             side_effect=[json.dumps(invalid), json.dumps(STRUCTURED_PAPER)]):
            r = client.post("/api/generate-structured",
                            headers={"X-Session-ID": SESSION}, json=STRUCTURED_PAYLOAD)
        self.assertEqual(r.status_code, 200, r.text[:300])


if __name__ == "__main__":
    unittest.main()
