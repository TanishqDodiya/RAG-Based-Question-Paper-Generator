"""Regression tests for structured generation slot/count validation.

Deterministic: the Ollama boundary and Chroma collection are stubbed. The real
slot expansion, JSON parsing, extra-question trimming, validation and endpoint
retry loop run unchanged.

Run:  python test_generation_fixes.py
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from fastapi.testclient import TestClient
from generate import (
    build_structured_prompt,
    expand_slots,
    trim_unmatched_questions,
    validate_structured_paper,
)

client = TestClient(main.app, raise_server_exceptions=False)
SESSION = "generation_slot_regression_session"


class FakeCollection:
    """Minimal Chroma collection double used by the structured RAG gates."""

    def get(self, where=None, include=None, **kwargs):
        return {
            "ids": ["chunk-1"],
            "documents": ["Operating systems use scheduling algorithms."],
            "metadatas": [{"filename": "os.pdf", "unit": "General"}],
        }

    def query(self, **kwargs):
        return {
            "documents": [["Operating systems use scheduling algorithms."]],
            "distances": [[0.2]],
            "metadatas": [[{"filename": "os.pdf", "unit": "General"}]],
        }


def _payload(count=9):
    """Valid structured request whose section count is the source of truth."""
    total_marks = count
    return {
        "subject": "Operating Systems",
        "total_marks": total_marks,
        "difficulty": "Medium",
        "sections": [{"type": "MCQ", "count": count, "marks_per_q": 1}],
        "blueprint": {
            "subject": "Operating Systems",
            "exam_name": "Mid-Semester Examination",
            "total_marks": total_marks,
            "duration_minutes": 120,
            "topics": [{"name": "General", "percentage": 100}],
            "difficulty": {"easy": 0, "medium": 100, "hard": 0},
            "types": [{"type": "MCQ", "marks": total_marks}],
            "bloom": {
                "remember": 0,
                "understand": 100,
                "apply": 0,
                "analyze": 0,
                "evaluate": 0,
                "create": 0,
            },
        },
    }


def _slots_for(payload):
    blueprint = payload["blueprint"]
    return expand_slots(
        payload["sections"],
        topics=blueprint["topics"],
        difficulty=blueprint["difficulty"],
        bloom=blueprint["bloom"],
    )


def _question_for(slot):
    return {
        "id": slot["slot_id"],
        "question": f"Which statement best explains {slot['slot_id']}?",
        "type": slot["type"],
        "marks": slot["marks"],
        "difficulty": slot["difficulty"],
        "bloom_level": slot["bloom_level"],
        "unit": slot["unit"],
        "topic": "Core concept",
        "options": ["A. One", "B. Two", "C. Three", "D. Four"],
        "answer": "A. One",
        "explanation": "Supported by the reference material.",
    }


def _paper_from_slots(slots, overrides=None, extras=None, total_marks=None):
    overrides = overrides or {}
    questions = []
    for slot in slots:
        question = _question_for(slot)
        question.update(overrides.get(slot["slot_id"], {}))
        questions.append(question)
    for index, extra in extras or []:
        questions.insert(index, extra)
    if total_marks is None:
        total_marks = sum(int(s["marks"]) for s in slots)
    return {
        "title": "Examination Paper: Operating Systems",
        "subject": "Operating Systems",
        "total_marks": total_marks,
        "difficulty": "Medium",
        "sections": [{
            "section_title": "Section A: MCQ",
            "type": "MCQ",
            "marks_per_question": 1,
            "questions": questions,
        }],
    }


def _extra_question(qid="QX", marks=1):
    return {
        "id": qid,
        "question": "This is an extra question that is not in the slot plan.",
        "type": "MCQ",
        "marks": marks,
        "difficulty": "Easy",
        "bloom_level": "Remember",
        "unit": "General",
        "topic": "Extra",
        "options": ["A. One", "B. Two", "C. Three", "D. Four"],
        "answer": "A. One",
        "explanation": "Extra.",
    }


def _post_structured(payload, outputs):
    """Post to the endpoint with a stubbed LLM returning ``outputs`` in order."""
    calls = []

    def fake_call(base_url, model, system_instruction, prompt, timeout=300):
        calls.append(prompt)
        index = len(calls) - 1
        output = outputs[index] if index < len(outputs) else outputs[-1]
        if isinstance(output, Exception):
            raise output
        return output if isinstance(output, str) else json.dumps(output)

    with patch.object(main, "notes_collection", FakeCollection()), \
            patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
            patch.object(main, "_call_ollama_structured", side_effect=fake_call):
        response = client.post(
            "/api/generate-structured",
            headers={"X-Session-ID": SESSION},
            json=payload,
        )
    return response, calls


def _all_questions(body):
    return [
        question
        for section in body.get("sections", [])
        for question in section.get("questions", [])
    ]


class TestBlueprintQuestionCount(unittest.TestCase):
    def test_blueprint_requesting_nine_returns_exactly_nine(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        self.assertEqual(len(slots), 9)
        response, calls = _post_structured(payload, [_paper_from_slots(slots)])
        self.assertEqual(response.status_code, 200, response.text[:500])
        body = response.json()
        questions = _all_questions(body)
        self.assertEqual(len(questions), 9)
        self.assertEqual([q["id"] for q in questions], [f"Q{i}" for i in range(1, 10)])
        self.assertEqual(len(body["generation_info"]["slots"]), 9)
        self.assertEqual(body["total_marks"], 9)
        self.assertEqual(len(calls), 1)

    def test_count_is_dynamic_not_hardcoded(self):
        payload = _payload(4)
        slots = _slots_for(payload)
        response, _ = _post_structured(payload, [_paper_from_slots(slots)])
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertEqual(len(_all_questions(response.json())), 4)


class TestExtraQuestionHandling(unittest.TestCase):
    def test_extra_question_is_trimmed_without_shifting_slots(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        expected = _paper_from_slots(slots)
        # Insert the extra question in the middle: positional truncation would
        # shift Q3..Q9 and corrupt their expected slots.
        paper = _paper_from_slots(
            slots,
            extras=[(2, _extra_question("QX", marks=1))],
            total_marks=10,
        )
        response, calls = _post_structured(payload, [paper])
        self.assertEqual(response.status_code, 200, response.text[:500])
        body = response.json()
        questions = _all_questions(body)
        self.assertEqual(len(questions), 9)
        self.assertEqual([q["id"] for q in questions], [f"Q{i}" for i in range(1, 10)])
        self.assertEqual(body["total_marks"], 9)
        self.assertEqual(len(calls), 1, "unambiguous extra should not need a retry")
        for question, slot, expected_q in zip(
                questions, slots, expected["sections"][0]["questions"]):
            self.assertEqual(question["marks"], slot["marks"])
            self.assertEqual(question["difficulty"], slot["difficulty"])
            self.assertEqual(question["bloom_level"], slot["bloom_level"])
            self.assertEqual(question["question"], expected_q["question"])
            self.assertEqual(question["source_documents"], ["os.pdf"])

    def test_trim_helper_never_drops_a_required_slot(self):
        slots = _slots_for(_payload(3))
        paper = _paper_from_slots(
            slots, extras=[(1, _extra_question("QX"))], total_marks=4)
        normalized, removed = trim_unmatched_questions(paper, slots)
        self.assertEqual(removed, 1)
        ids = [q["id"] for q in normalized["sections"][0]["questions"]]
        self.assertEqual(ids, ["Q1", "Q2", "Q3"])

        missing = _paper_from_slots(slots)
        missing["sections"][0]["questions"][1]["id"] = "QX"
        unchanged, removed = trim_unmatched_questions(missing, slots)
        self.assertEqual(removed, 0)
        self.assertEqual([q["id"] for q in unchanged["sections"][0]["questions"]],
                         ["Q1", "QX", "Q3"])


class TestSlotMismatchRetry(unittest.TestCase):
    def test_understand_slot_with_remember_output_is_rejected_and_retried(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        bad = _paper_from_slots(
            slots, overrides={"Q3": {"bloom_level": "Remember"}})
        good = _paper_from_slots(slots)
        response, calls = _post_structured(payload, [bad, good])
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertEqual(len(calls), 2)
        self.assertIn("CORRECTION REQUIRED ON RETRY", calls[1])
        self.assertIn("bloom_level", calls[1])
        self.assertIn("Understand", calls[1])
        q3 = _all_questions(response.json())[2]
        self.assertEqual(q3["bloom_level"], "Understand")

    def test_medium_slot_with_easy_output_is_rejected_and_retried(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        bad = _paper_from_slots(
            slots, overrides={"Q4": {"difficulty": "Easy"}})
        good = _paper_from_slots(slots)
        response, calls = _post_structured(payload, [bad, good])
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertEqual(len(calls), 2)
        self.assertIn("CORRECTION REQUIRED ON RETRY", calls[1])
        self.assertIn("difficulty", calls[1])
        self.assertIn("Medium", calls[1])
        q4 = _all_questions(response.json())[3]
        self.assertEqual(q4["difficulty"], "Medium")

    def test_retry_prompt_keeps_all_original_slots(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        bad = _paper_from_slots(
            slots, overrides={"Q2": {"difficulty": "Hard"}})
        good = _paper_from_slots(slots)
        _, calls = _post_structured(payload, [bad, good])
        self.assertEqual(len(calls), 2)
        for slot in slots:
            self.assertIn(f"{slot['slot_id']}: type={slot['type']}", calls[1])
        self.assertIn("EXACTLY 9 questions", calls[1])


class TestMixedAndFinalValidation(unittest.TestCase):
    def test_mixed_difficulty_and_bloom_slots_pass(self):
        slots = expand_slots(
            [{"type": "MCQ", "count": 6, "marks_per_q": 1}],
            topics=[{"name": "General", "percentage": 100}],
            difficulty={"easy": 34, "medium": 33, "hard": 33},
            bloom={"remember": 17, "understand": 17, "apply": 17,
                   "analyze": 17, "evaluate": 16, "create": 16},
        )
        self.assertGreater(len({s["difficulty"] for s in slots}), 1)
        self.assertGreater(len({s["bloom_level"] for s in slots}), 1)
        result = validate_structured_paper(_paper_from_slots(slots), slots)
        self.assertTrue(result["ok"], result["errors"])

    def test_correct_output_passes_all_validations(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        result = validate_structured_paper(_paper_from_slots(slots), slots)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["paper"]["total_marks"], 9)

    def test_wrong_type_and_unit_are_still_rejected(self):
        slots = _slots_for(_payload(3))
        bad = _paper_from_slots(slots, overrides={
            "Q1": {"type": "Short"},
            "Q2": {"unit": "Unit 9"},
        })
        result = validate_structured_paper(bad, slots)
        self.assertFalse(result["ok"])
        self.assertTrue(any("type" in error for error in result["errors"]))
        self.assertTrue(any("unit" in error for error in result["errors"]))

    def test_prompt_states_exact_count_and_each_slot_contract(self):
        slots = _slots_for(_payload(9))
        _, prompt = build_structured_prompt(
            "Operating Systems", "Medium", 9, slots, {"General": "context"})
        self.assertIn("EXACTLY 9 questions", prompt)
        self.assertIn("Do NOT add extra questions", prompt)
        for slot in slots:
            self.assertIn(
                f"{slot['slot_id']}: type={slot['type']}, marks={slot['marks']}, "
                f"difficulty={slot['difficulty']}, bloom={slot['bloom_level']}, "
                f"unit/topic={slot['unit']}",
                prompt,
            )


class TestRetryExhaustion(unittest.TestCase):
    def test_exhausted_retries_return_controlled_502_not_500(self):
        payload = _payload(9)
        slots = _slots_for(payload)
        bad = _paper_from_slots(
            slots, overrides={"Q1": {"bloom_level": "Remember"}})
        response, calls = _post_structured(payload, [bad, bad])
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.status_code, 502, response.text[:500])
        self.assertIn("Model output failed validation", response.text)
        self.assertIn("bloom_level", response.text)

    def test_parse_failure_on_both_attempts_returns_502(self):
        payload = _payload(3)
        response, calls = _post_structured(payload, ["not-json", "still-not-json"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.status_code, 502, response.text[:500])
        self.assertIn("Model output failed validation", response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
