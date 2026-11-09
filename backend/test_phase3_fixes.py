"""Regression tests for Phase 3 fixes: H-04, H-05, M-01, M-02, M-03, M-04.

Deterministic: no live Ollama/ChromaDB. Backend regeneration is stubbed at the
retrieval/LLM boundary. Frontend state helpers are covered by
``frontend/tests/phase3.test.mjs`` (Node's built-in runner); this file checks
the React wiring in the same static style already used by the project's
regression suites.

Run:  python test_phase3_fixes.py
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from fastapi.testclient import TestClient

client = TestClient(main.app, raise_server_exceptions=False)

SESSION = "phase3_regression_session"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REGEN_QUESTION = {
    "id": "Q7",
    "type": "MCQ",
    "marks": 2,
    "difficulty": "Hard",
    "bloom_level": "Analyze",
    "unit": "Unit 2",
    "topic": "Scheduling",
}

REGEN_OUTPUT = {
    "question": "Which fair-share algorithm relies on a time quantum?",
    "options": ["A. FCFS", "B. Round Robin", "C. SJF", "D. Priority"],
    "answer": "B. Round Robin",
    "explanation": "Quantum-based.",
}


def _retrieval_for_unit():
    return {
        "documents": ["Round Robin uses a time quantum."],
        "distances": [0.2],
        "metadatas": [{"filename": "os.pdf", "unit": "Unit 2"}],
    }


class TestM01SafeRegenerationMarks(unittest.TestCase):
    def _post(self, question):
        return client.post(
            "/api/questions/regenerate",
            headers={"X-Session-ID": SESSION},
            json={"subject": "Operating Systems", "question": question},
        )

    def test_invalid_marks_return_422_without_retrieval(self):
        invalid_values = [None, "", "   ", "abc", -5, 0, 2.5, True]
        for marks in invalid_values:
            with self.subTest(marks=marks):
                question = dict(REGEN_QUESTION)
                question["marks"] = marks
                with patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                        patch.object(main, "retrieve_relevant",
                                     side_effect=AssertionError("retrieval must not run")):
                    response = self._post(question)
                self.assertEqual(response.status_code, 422, response.text[:300])
                self.assertIn("marks", response.text.lower())

    def test_missing_marks_return_422(self):
        question = {key: value for key, value in REGEN_QUESTION.items() if key != "marks"}
        with patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "retrieve_relevant",
                             side_effect=AssertionError("retrieval must not run")):
            response = self._post(question)
        self.assertEqual(response.status_code, 422, response.text[:300])
        self.assertIn("marks", response.text.lower())

    def test_valid_marks_still_regenerate(self):
        with patch.object(main, "check_ollama_status", return_value=(True, "ok", [])), \
                patch.object(main, "retrieve_relevant", return_value=_retrieval_for_unit()), \
                patch.object(main, "_call_ollama_structured",
                             return_value=json.dumps(REGEN_OUTPUT)):
            response = self._post(dict(REGEN_QUESTION))
        self.assertEqual(response.status_code, 200, response.text[:300])
        body = response.json()
        self.assertEqual(body["question"]["marks"], 2)
        self.assertEqual(body["question"]["id"], "Q7")


def _read(relative_path):
    with open(os.path.join(ROOT, relative_path), encoding="utf-8") as handle:
        return handle.read()


class TestPhase3FrontendWiring(unittest.TestCase):
    def test_h04_app_centralizes_edit_refresh(self):
        app = _read(os.path.join("frontend", "src", "App.jsx"))
        for token in [
            "const handlePaperEdited = async (nextPaper)",
            "await Promise.allSettled([",
            "validatePaper(nextPaper)",
            "checkDuplicates(nextPaper)",
            "setValidation(null);",
            "setDuplicates(null);",
            "setQualityToken((token) => token + 1);",
            "onPaperChange={handlePaperEdited}",
            "qualityToken={qualityToken}",
            "<PaperErrorBoundary>",
            "validateBlueprint(savedBlueprint)",
            "expanded: data.expanded",
            "setPaperGen((g) => g + 1);",
        ]:
            self.assertIn(token, app, f"missing H-04/H-05 wiring: {token}")

    def test_h05_history_restores_exam_meta_and_structured_blueprint(self):
        history = _read(os.path.join("frontend", "src", "components", "HistoryList.jsx"))
        self.assertIn("exam_meta: blueprint.exam_meta", history)
        self.assertIn("await onLoad(data)", history)

        generator = _read(os.path.join("frontend", "src", "components", "GeneratorForm.jsx"))
        self.assertIn("sectionsFromPaper(paper)", generator)
        self.assertIn("paperIdentity", generator)

    def test_m02_preview_uses_defensive_helpers(self):
        preview = _read(os.path.join("frontend", "src", "components", "PaperPreview.jsx"))
        for token in [
            "safeSections(paperData)",
            "safeQuestions(section)",
            "safeOptions(q)",
            "paperShapeIssues(paperData)",
            "shapeIssues.length > 0",
            "Array.isArray(extra)",
        ]:
            self.assertIn(token, preview, f"missing M-02 defensive rendering: {token}")

    def test_m03_reject_and_edit_are_functional(self):
        review = _read(os.path.join("frontend", "src", "components", "ReviewMode.jsx"))
        for token in [
            "removeQuestionFromPaper(paper, qid)",
            "updateQuestionInPaper(paper, qid, patch)",
            "validateQuestionDraft(draft)",
            "buildQuestionPatch(draft)",
            "draft.answer",
            "draft.options",
            "rejectQ(qid)",
        ]:
            self.assertIn(token, review, f"missing M-03 review behaviour: {token}")

        duplicate = _read(os.path.join("frontend", "src", "components", "DuplicatePanel.jsx"))
        for token in ["removeQuestionFromPaper(paper, qid)", "replaceQuestionInPaper(paper, qid, data.question)"]:
            self.assertIn(token, duplicate, f"missing M-03 duplicate-panel behaviour: {token}")

    def test_m04_blueprint_form_synchronizes_from_active_blueprint(self):
        form = _read(os.path.join("frontend", "src", "components", "BlueprintForm.jsx"))
        for token in [
            "useEffect",
            "blueprintFormState(",
            "activeBlueprint?.payload || null",
            "activeBlueprint?.exam_meta || null",
            "restoreToken",
            "lastHydratedToken",
        ]:
            self.assertIn(token, form, f"missing M-04 form synchronisation: {token}")

    def test_h04_analysis_refreshes_after_edit(self):
        analysis = _read(os.path.join("frontend", "src", "components", "PaperAnalysis.jsx"))
        for token in ["qualityToken", "useEffect", "hasAnalyzed.current", "runAnalysis()"]:
            self.assertIn(token, analysis, f"missing H-04 analytics refresh: {token}")

    def test_h04_stale_responses_cannot_overwrite_newer_paper(self):
        expectations = {
            "DuplicatePanel.jsx": ["paperRef.current !== sourcePaper", "checkId.current"],
            "ReviewMode.jsx": ["paperRef.current !== sourcePaper"],
            "PaperAnalysis.jsx": ["requestId.current"],
            "ValidationPanel.jsx": ["requestId.current"],
        }
        for filename, tokens in expectations.items():
            source = _read(os.path.join("frontend", "src", "components", filename))
            for token in tokens:
                self.assertIn(token, source, f"missing stale-response guard in {filename}: {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
