"""Regression tests for Phase 1 fixes: C-01, H-01, H-02, H-07.

Deterministic: no live Ollama or ChromaDB access. The LLM/vector boundary is
stubbed exactly where the endpoints would otherwise call it.

Run:  python test_phase1_fixes.py
"""

import gc
import json
import os
import sys
import tempfile
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import history
import main
from fastapi.testclient import TestClient

client = TestClient(main.app, raise_server_exceptions=False)

SESSION = "phase1_regression_session"

LEGACY_PAYLOAD = {
    "subject": "Operating Systems",
    "total_marks": 1,
    "difficulty": "Medium",
    "sections": [{"type": "MCQ", "count": 1, "marks_per_q": 1}],
}

STRUCTURED_PAYLOAD = dict(LEGACY_PAYLOAD)


class FakeCollection:
    """Minimal Chroma collection double used by the RAG gates."""

    def __init__(self, text="Operating Systems: Round Robin uses a time quantum."):
        self.text = text

    def get(self, where=None, include=None, **kwargs):
        return {
            "ids": ["chunk-1"],
            "documents": [self.text],
            "metadatas": [{"filename": "os.pdf", "unit": "Unit 1"}],
        }

    def query(self, **kwargs):
        return {
            "documents": [[self.text]],
            "distances": [[0.2]],
            "metadatas": [[{"filename": "os.pdf", "unit": "Unit 1"}]],
        }


class FakeOllamaResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return {"response": json.dumps(self._payload)}


def _stub_rag():
    return (
        patch.object(main, "notes_collection", FakeCollection()),
        patch.object(main, "check_ollama_status", return_value=(True, "ok", [])),
    )


class TestLegacyPaperSchema(unittest.TestCase):
    """H-01: malformed legacy LLM output must not be returned as HTTP 200."""

    def test_missing_sections_returns_502(self):
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main.requests, "post",
            return_value=FakeOllamaResponse({"title": "x", "total_marks": 1}),
        ):
            res = client.post(
                "/generate-paper",
                headers={"X-Session-ID": SESSION},
                json=LEGACY_PAYLOAD,
            )
        self.assertEqual(res.status_code, 502)
        self.assertIn("invalid paper structure", res.json()["detail"])

    def test_sections_not_a_list_returns_502(self):
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main.requests, "post",
            return_value=FakeOllamaResponse({"sections": {"type": "MCQ"}}),
        ):
            res = client.post(
                "/generate-paper",
                headers={"X-Session-ID": SESSION},
                json=LEGACY_PAYLOAD,
            )
        self.assertEqual(res.status_code, 502)

    def test_non_object_output_returns_502(self):
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main.requests, "post", return_value=FakeOllamaResponse(None),
        ):
            res = client.post(
                "/generate-paper",
                headers={"X-Session-ID": SESSION},
                json=LEGACY_PAYLOAD,
            )
        self.assertEqual(res.status_code, 502)

    def test_valid_paper_still_returns_200(self):
        valid = {
            "title": "Examination Paper",
            "subject": "Operating Systems",
            "total_marks": 1,
            "sections": [{
                "section_title": "Section A",
                "type": "MCQ",
                "marks_per_question": 1,
                "questions": [{
                    "id": "Q1",
                    "question": "Which scheduling algorithm uses a time quantum?",
                    "options": ["A. FCFS", "B. Round Robin"],
                    "answer": "B. Round Robin",
                    "explanation": "Round Robin uses a time quantum.",
                }],
            }],
        }
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main.requests, "post", return_value=FakeOllamaResponse(valid),
        ):
            res = client.post(
                "/generate-paper",
                headers={"X-Session-ID": SESSION},
                json=LEGACY_PAYLOAD,
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body["sections"]), 1)
        self.assertEqual(body["sections"][0]["questions"][0]["id"], "Q1")


class TestStructuredShape(unittest.TestCase):
    """H-02: non-list ``sections`` must be a controlled 502, not a 500."""

    def test_sections_dict_returns_502(self):
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main, "_call_ollama_structured",
            return_value=json.dumps({"sections": {"type": "MCQ"}}),
        ):
            res = client.post(
                "/api/generate-structured",
                headers={"X-Session-ID": SESSION},
                json=STRUCTURED_PAYLOAD,
            )
        self.assertEqual(res.status_code, 502)

    def test_section_questions_not_a_list_returns_502(self):
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main, "_call_ollama_structured",
            return_value=json.dumps({"sections": [{"questions": "Q1"}]}),
        ):
            res = client.post(
                "/api/generate-structured",
                headers={"X-Session-ID": SESSION},
                json=STRUCTURED_PAYLOAD,
            )
        self.assertEqual(res.status_code, 502)

    def test_valid_structured_paper_still_returns_200(self):
        valid = {
            "title": "Examination Paper",
            "sections": [{
                "section_title": "Section A",
                "type": "MCQ",
                "marks_per_question": 1,
                "questions": [{
                    "id": "Q1",
                    "question": "Which scheduling algorithm uses a time quantum?",
                    "options": ["A. FCFS", "B. Round Robin"],
                    "answer": "B. Round Robin",
                    "explanation": "Round Robin uses a time quantum.",
                    "unit": "General",
                }],
            }],
        }
        p1, p2 = _stub_rag()
        with p1, p2, patch.object(
            main, "_call_ollama_structured", return_value=json.dumps(valid),
        ):
            res = client.post(
                "/api/generate-structured",
                headers={"X-Session-ID": SESSION},
                json=STRUCTURED_PAYLOAD,
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["generation_info"]["engine"], "structured-v1")
        self.assertEqual(body["sections"][0]["questions"][0]["source_documents"], ["os.pdf"])


class TestHistoryConnections(unittest.TestCase):
    """H-07: every history operation must close its SQLite connection."""

    def test_no_unclosed_database_warnings(self):
        original_path = history._db_path
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                history.init_db(db_path)
                pid = history.save_paper(
                    "Test paper", "Operating Systems", 1, 1,
                    {"sections": [{"questions": [{"id": "Q1"}]}]}, None, None,
                )
                self.assertEqual(len(history.list_papers()), 1)
                self.assertIsNotNone(history.get_paper(pid))
                self.assertTrue(history.delete_paper(pid))
                self.assertEqual(history.list_papers(), [])
                gc.collect()

            unclosed = [
                w for w in caught
                if issubclass(w.category, ResourceWarning) and "unclosed database" in str(w.message)
            ]
            self.assertEqual(unclosed, [], f"leaked SQLite connections: {unclosed}")
        finally:
            history._db_path = original_path
            try:
                os.remove(db_path)
            except OSError:
                pass


class TestAuthGate(unittest.TestCase):
    """C-01: optional shared-secret gate; disabled keeps local flow unchanged."""

    def setUp(self):
        self._original_token = main.APP_AUTH_TOKEN
        self._p1 = patch.object(main, "notes_collection", FakeCollection())
        self._p2 = patch.object(main, "check_ollama_status", return_value=(False, "offline", []))
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        main.APP_AUTH_TOKEN = self._original_token

    def test_missing_token_returns_401(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        res = client.get("/api/status", headers={"X-Session-ID": SESSION})
        self.assertEqual(res.status_code, 401)

    def test_wrong_token_returns_401(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        res = client.get(
            "/api/status",
            headers={"X-Session-ID": SESSION, "X-API-Key": "wrong"},
        )
        self.assertEqual(res.status_code, 401)

    def test_x_api_key_token_returns_200(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        res = client.get(
            "/api/status",
            headers={"X-Session-ID": SESSION, "X-API-Key": "phase1-test-token"},
        )
        self.assertEqual(res.status_code, 200)

    def test_bearer_token_returns_200(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        res = client.get(
            "/api/status",
            headers={"X-Session-ID": SESSION, "Authorization": "Bearer phase1-test-token"},
        )
        self.assertEqual(res.status_code, 200)

    def test_cors_preflight_is_not_blocked(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        res = client.options(
            "/api/status",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotEqual(res.status_code, 401)

    def test_disabled_auth_keeps_existing_local_flow(self):
        main.APP_AUTH_TOKEN = ""
        res = client.get("/api/status", headers={"X-Session-ID": SESSION})
        self.assertEqual(res.status_code, 200)

    def test_remote_client_without_token_is_blocked(self):
        main.APP_AUTH_TOKEN = ""
        remote = TestClient(
            main.app, raise_server_exceptions=False, client=("192.168.1.50", 12345))
        res = remote.get("/api/status", headers={"X-Session-ID": SESSION})
        self.assertEqual(res.status_code, 403)

    def test_remote_client_with_token_is_allowed(self):
        main.APP_AUTH_TOKEN = "phase1-test-token"
        remote = TestClient(
            main.app, raise_server_exceptions=False, client=("192.168.1.50", 12345))
        res = remote.get(
            "/api/status",
            headers={"X-Session-ID": SESSION, "X-API-Key": "phase1-test-token"},
        )
        self.assertEqual(res.status_code, 200)


class TestServerDefaults(unittest.TestCase):
    """C-01: ``python main.py`` must default to loopback with reload off."""

    def test_defaults_are_loopback(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("APP_HOST", "APP_PORT", "APP_RELOAD"):
                os.environ.pop(key, None)
            self.assertEqual(main.get_server_settings(), ("127.0.0.1", 8000, False))

    def test_explicit_overrides_are_honoured(self):
        with patch.dict(os.environ, {
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "9001",
            "APP_RELOAD": "true",
        }):
            self.assertEqual(main.get_server_settings(), ("0.0.0.0", 9001, True))

    def test_invalid_port_falls_back(self):
        with patch.dict(os.environ, {"APP_PORT": "not-a-port"}):
            self.assertEqual(main.get_server_settings()[1], 8000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
