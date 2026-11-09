"""Committed regression suite for M4-M10 + audit FIX 1-4 (stabilization freeze).

Design: fully deterministic, no live Ollama required. The LLM/embedding
boundary is stubbed (monkeypatched) wherever a test would otherwise need it;
everything else runs against the real modules (and the real ChromaDB in
read-only fashion via TestClient where needed).

Run:  python test_milestones.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
from fastapi.testclient import TestClient

client = TestClient(main.app, raise_server_exceptions=False)

CHUNKS = [
    {"text": "A process is a program in execution. The OS manages processes using Process Control Blocks (PCB).",
     "filename": "os.pdf", "unit": "Unit 1", "page": "p.2"},
    {"text": "CPU scheduling algorithms include FCFS, SJF and Round Robin. Round Robin uses a time quantum.",
     "filename": "os.pdf", "unit": "Unit 2", "page": "p.5"},
]

GOOD_MCQ = {"id": "Q1", "question": "Which CPU scheduling algorithm uses a time quantum?",
            "type": "MCQ", "marks": 1, "difficulty": "Easy", "bloom_level": "Remember",
            "unit": "Unit 2", "topic": "Scheduling",
            "options": ["A. FCFS", "B. Round Robin", "C. SJF", "D. Priority"],
            "answer": "B. Round Robin", "explanation": "Uses a time quantum."}

PAPER_TWO_Q = {"subject": "OS", "total_marks": 6, "difficulty": "Medium",
               "sections": [{"section_title": "Sec A", "type": "MCQ",
                             "marks_per_question": 1, "questions": [
                   dict(GOOD_MCQ),
                   {"id": "Q2", "question": "Describe how process scheduling works.",
                    "type": "Short", "marks": 5, "difficulty": "Medium",
                    "bloom_level": "Understand", "unit": "Unit 2", "topic": "Scheduling",
                    "options": [], "answer": "Round robin with a time quantum.",
                    "explanation": "Model answer."},
               ]}]}


# ---------------------------------------------------------------- FIX 1
class TestFix1StructuredValidation(unittest.TestCase):
    def test_valid_types_accepted_both_models(self):
        for t in ["MCQ", "Short", "Long", "True/False", "Fill-in-blanks"]:
            sec = {"type": t, "count": 1, "marks_per_q": 1}
            main.GeneratePaperRequest(subject="Operating Systems", total_marks=1,
                                      difficulty="Easy", sections=[sec])
            main.StructuredGenerateRequest(subject="Operating Systems", total_marks=1,
                                           difficulty="Easy", sections=[sec])
        print("\n[FIX1] valid types accepted on both paths.")

    def test_invalid_type_rejected_422_offline(self):
        # Pydantic-level (no Ollama involved).
        with self.assertRaises(Exception):
            main.StructuredGenerateRequest(subject="Operating Systems", total_marks=5,
                                           difficulty="Medium",
                                           sections=[{"type": "BOGUS", "count": 1, "marks_per_q": 5}])
        # HTTP-level: 422 even while Ollama is offline (validation precedes gates).
        r = client.post("/api/generate-structured",
                        json={"subject": "Operating Systems", "total_marks": 5,
                              "difficulty": "Medium",
                              "sections": [{"type": "BOGUS", "count": 1, "marks_per_q": 5}]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("Invalid section type", r.text)
        print("\n[FIX1] invalid type -> 422 with clear message (offline).")

    def test_difficulty_values(self):
        for d in ["Easy", "Medium", "Hard"]:
            main.StructuredGenerateRequest(subject="Operating Systems", total_marks=1,
                                           difficulty=d,
                                           sections=[{"type": "MCQ", "count": 1, "marks_per_q": 1}])
        with self.assertRaises(Exception):
            main.StructuredGenerateRequest(subject="Operating Systems", total_marks=1,
                                           difficulty="Extreme",
                                           sections=[{"type": "MCQ", "count": 1, "marks_per_q": 1}])
        print("\n[FIX1] difficulty allowlist enforced.")


# ---------------------------------------------------------------- M4
class TestM4StructuredGeneration(unittest.TestCase):
    def test_slot_distribution(self):
        from generate import expand_slots
        slots = expand_slots(
            [{"type": "MCQ", "count": 5, "marks_per_q": 1},
             {"type": "Short", "count": 3, "marks_per_q": 5}],
            topics=[{"name": "Unit 1", "percentage": 50}, {"name": "Unit 2", "percentage": 50}],
            difficulty={"easy": 50, "medium": 50, "hard": 0},
            bloom={"remember": 50, "understand": 50, "apply": 0, "analyze": 0,
                   "evaluate": 0, "create": 0})
        self.assertEqual(len(slots), 8)
        units = [s["unit"] for s in slots]
        self.assertEqual(units.count("Unit 1"), 4)
        self.assertEqual(units.count("Unit 2"), 4)
        print("\n[M4] slot distribution exact (4/4).")

    def test_slots_reflect_sections_not_blueprint_types(self):
        # FIX 4 contract: counts/types/marks come from sections; blueprint types
        # only constrain the total at the API boundary + feed analytics targets.
        from generate import expand_slots
        slots = expand_slots([{"type": "Long", "count": 2, "marks_per_q": 10}])
        self.assertTrue(all(s["type"] == "Long" and s["marks"] == 10 for s in slots))
        self.assertEqual(len(slots), 2)
        print("\n[M4/FIX4] slots follow sections; blueprint types do not rewrite them.")

    def test_post_fill_sources(self):
        from generate import post_fill_sources
        paper = {"sections": [{"type": "MCQ", "marks_per_question": 1, "questions": [
            {"id": "Q1", "unit": "Unit 1"}, {"id": "Q2", "unit": "Unknown"}]}]}
        out = post_fill_sources(paper, {"Unit 1": ["a.pdf", "b.pdf"], "Unit 2": ["c.pdf"]})
        q1, q2 = out["sections"][0]["questions"]
        self.assertEqual(q1["source_documents"], ["a.pdf", "b.pdf"])
        # H-15: unknown units never inherit another unit's files.
        self.assertEqual(q2["source_documents"], [])
        print("\n[M4/H15] source post-fill deterministic (known unit; no cross-unit fallback).")

    def test_repair_parse(self):
        from generate import parse_structured_output
        d = parse_structured_output('```json\n{"sections": [], "title": "t",}\n```')
        self.assertEqual(d, {"sections": [], "title": "t"})
        with self.assertRaises(ValueError):
            parse_structured_output('{"title": "no sections"}')
        print("\n[M4] repair-parse tolerates fences/trailing commas; rejects bad shape.")


# ---------------------------------------------------------------- M5
class TestM5Validator(unittest.TestCase):
    def test_grounding_and_overall_ladder(self):
        from validator import validate_question
        r = validate_question(dict(GOOD_MCQ), CHUNKS)
        self.assertEqual(r["checks"]["grounding"]["status"], "PASS")
        self.assertIn(r["overall"], ("APPROVED", "NEEDS_REVIEW"))

        bad = dict(GOOD_MCQ, id="QX", question="Explain photosynthesis stages in plants?",
                   answer="Light reactions.", unit="Unit 9", options=[])
        r2 = validate_question(bad, CHUNKS)
        self.assertEqual(r2["checks"]["grounding"]["status"], "FAIL")
        self.assertEqual(r2["overall"], "NEEDS_REGENERATION")
        print("\n[M5] grounding PASS vs FAIL; overall ladder correct.")

    def test_answer_empty_fails(self):
        from validator import validate_question
        r = validate_question(dict(GOOD_MCQ, answer=""), CHUNKS)
        self.assertEqual(r["checks"]["answer_support"]["status"], "FAIL")
        print("\n[M5] empty answer FAILS answer_support.")

    def test_difficulty_bloom_mapping(self):
        from validator import validate_question
        ok = validate_question(dict(GOOD_MCQ), CHUNKS)  # Easy + Remember
        self.assertEqual(ok["checks"]["difficulty"]["status"], "PASS")
        mismatch = validate_question(dict(GOOD_MCQ, difficulty="Hard"), CHUNKS)
        self.assertEqual(mismatch["checks"]["difficulty"]["status"], "NEEDS_REVIEW")
        print("\n[M5] difficulty/Bloom consistency graded (never hard-fails).")

    def test_marks_suitability(self):
        from validator import validate_question
        thin = dict(GOOD_MCQ, id="QM", type="Long", marks=10,
                    question="Design a scheduler for multicore systems with justification.",
                    bloom_level="Create", difficulty="Hard",
                    answer="Use Round Robin.", options=[])
        r = validate_question(thin, CHUNKS)
        self.assertEqual(r["checks"]["marks"]["status"], "FAIL")
        print("\n[M5] thin 10-mark answer FAILS marks suitability.")

    def test_bloom_verbs(self):
        from validator import validate_question
        with_verb = validate_question(dict(GOOD_MCQ, question="Define a time quantum and list its uses.",
                                           bloom_level="Remember"), CHUNKS)
        self.assertEqual(with_verb["checks"]["bloom"]["status"], "PASS")
        without = validate_question(dict(GOOD_MCQ), CHUNKS)  # "Which..." has no Remember verb
        self.assertEqual(without["checks"]["bloom"]["status"], "NEEDS_REVIEW")
        print("\n[M5] Bloom verbs PASS when present, REVIEW (not FAIL) when absent.")

    def test_type_shapes(self):
        from validator import validate_question
        mcq2 = validate_question(dict(GOOD_MCQ, options=["A. x", "B. y"]), CHUNKS)
        self.assertEqual(mcq2["checks"]["qtype"]["status"], "FAIL")
        tf = validate_question({"id": "T", "question": "Round Robin is preemptive. True or false?",
                                "type": "True/False", "marks": 1, "answer": "True, it uses quanta.",
                                "options": []}, CHUNKS)
        self.assertEqual(tf["checks"]["qtype"]["status"], "PASS")
        fill = validate_question({"id": "F", "question": "The ___ uses a time quantum.",
                                  "type": "Fill-in-blanks", "marks": 1,
                                  "answer": "Round Robin algorithm uses quanta.", "options": []}, CHUNKS)
        self.assertEqual(fill["checks"]["qtype"]["status"], "PASS")
        print("\n[M5] MCQ/T-F/Fill shapes enforced.")

    def test_quality_and_paper_summary(self):
        from validator import validate_paper
        out = validate_paper({"sections": [{"type": "MCQ", "marks_per_question": 1,
                                            "questions": [dict(GOOD_MCQ),
                                                          dict(GOOD_MCQ, id="Q2",
                                                               question="which algorithm uses a time quantum?")]}]},
                             CHUNKS)
        self.assertEqual(out["summary"]["total"], 2)
        self.assertEqual(out["summary"]["approved"] + out["summary"]["needs_review"]
                         + out["summary"]["needs_regeneration"], 2)
        print("\n[M5] paper summary counts consistent:", out["summary"])


# ---------------------------------------------------------------- M6
class TestM6Duplicates(unittest.TestCase):
    def test_five_case_matrix(self):
        from duplicates import similarity, SIMILARITY_THRESHOLD
        self.assertEqual(similarity("Explain process scheduling.",
                                    "Explain process scheduling."), 1.0)  # exact
        self.assertGreaterEqual(similarity("Explain process scheduling.",
                                           "Describe how process scheduling works."),
                                SIMILARITY_THRESHOLD)  # reworded
        self.assertGreaterEqual(similarity("List the CPU scheduling algorithms.",
                                           "Name the CPU scheduling algorithms."),
                                SIMILARITY_THRESHOLD)  # synonym
        self.assertLess(similarity("Explain FCFS scheduling with an example.",
                                   "Explain Round Robin scheduling with a time quantum."),
                        SIMILARITY_THRESHOLD)  # same-topic distinct
        self.assertLess(similarity("Explain process scheduling.",
                                   "What is virtual memory paging?"),
                        SIMILARITY_THRESHOLD)  # unrelated
        print("\n[M6] 5-case matrix behaves (flag only true duplicates).")

    def test_find_duplicates_shape(self):
        from duplicates import find_duplicates
        pairs = find_duplicates([{"id": "Q4", "question": "Explain process scheduling."},
                                 {"id": "Q17", "question": "Describe how process scheduling works."},
                                 {"id": "Q9", "question": "What is virtual memory paging?"}])
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0]["q1"], pairs[0]["q2"]), ("Q4", "Q17"))
        print("\n[M6] pair shape + sorting:", pairs)

    def test_regeneration_preserves_slot(self):
        # Stub the LLM/embedding boundary; assert slot constraints survive.
        orig_status, orig_retr, orig_call = (main.check_ollama_status,
                                            main.retrieve_relevant,
                                            main._call_ollama_structured)
        main.check_ollama_status = lambda: (True, "ok", [])
        main.retrieve_relevant = lambda *a, **k: {
            "documents": ["Round Robin uses a time quantum for fair scheduling."],
            "distances": [0.2],
            "metadatas": [{"filename": "os.pdf", "unit": "Unit 2"}]}
        main._call_ollama_structured = lambda *a, **k: json.dumps({
            "question": "Which fair-share algorithm relies on a time quantum?",
            "options": ["A. FCFS", "B. Round Robin", "C. SJF", "D. Priority"],
            "answer": "B. Round Robin", "explanation": "Quantum-based."})
        try:
            r = client.post("/api/questions/regenerate",
                            json={"subject": "Operating Systems",
                                  "question": {"id": "Q7", "type": "MCQ", "marks": 2,
                                               "difficulty": "Hard", "bloom_level": "Analyze",
                                               "unit": "Unit 2", "topic": "Scheduling"},
                                  "avoid": ["Explain process scheduling."]},
                            headers={"X-Session-ID": "regen_test"})
            self.assertEqual(r.status_code, 200, r.text[:200])
            q = r.json()["question"]
            for key, val in [("id", "Q7"), ("type", "MCQ"), ("marks", 2),
                             ("difficulty", "Hard"), ("bloom_level", "Analyze"),
                             ("unit", "Unit 2")]:
                self.assertEqual(q[key], val)
            self.assertTrue(q["question"] and q["answer"] and q["source_documents"])
        finally:
            (main.check_ollama_status, main.retrieve_relevant,
             main._call_ollama_structured) = (orig_status, orig_retr, orig_call)
        print("\n[M6] regen preserves slot (id/type/marks/difficulty/bloom/unit) + sources.")


# ---------------------------------------------------------------- M7
class TestM7Analytics(unittest.TestCase):
    def test_target_actual_and_flags(self):
        from analytics import compute_analytics
        paper = {"sections": [{"type": "MCQ", "marks_per_question": 1, "questions": [
            {"id": "Q1", "unit": "Unit 1", "difficulty": "Easy",
             "bloom_level": "Remember", "type": "MCQ", "marks": 1},
            {"id": "Q2", "unit": "Unit 1", "difficulty": "Easy",
             "bloom_level": "Remember", "type": "MCQ", "marks": 1}]}]}
        bp = {"total_marks": 2,
              "topics": [{"name": "Unit 1", "percentage": 50}, {"name": "Unit 2", "percentage": 50}],
              "difficulty": {"easy": 100, "medium": 0, "hard": 0},
              "bloom": {"remember": 100, "understand": 0, "apply": 0, "analyze": 0,
                        "evaluate": 0, "create": 0},
              "types": [{"type": "MCQ", "marks": 2}]}
        out = compute_analytics(paper, bp, None, {"pairs": [], "count": 0})
        units = {r["label"]: r for r in out["comparison"]["units"]}
        self.assertTrue(units["Unit 2"]["flagged"])  # 50% target, 0% actual
        self.assertTrue(units["Unit 1"]["flagged"])  # 50% target, 100% actual
        self.assertEqual(units["Unit 2"]["delta"], -50.0)
        print("\n[M7] >10% delta flagged:", units["Unit 2"])

    def test_quality_heuristic_and_label(self):
        from analytics import compute_analytics
        val = {"results": [
            {"checks": {"syllabus": {"status": "PASS"}, "grounding": {"status": "PASS"},
                        "answer_support": {"status": "PASS"}, "bloom": {"status": "PASS"},
                        "difficulty": {"status": "PASS"}}},
            {"checks": {"syllabus": {"status": "PASS"}, "grounding": {"status": "NEEDS_REVIEW"},
                        "answer_support": {"status": "PASS"}, "bloom": {"status": "PASS"},
                        "difficulty": {"status": "PASS"}}}]}
        out = compute_analytics(PAPER_TWO_Q, None, val, {"pairs": [], "count": 0})
        self.assertIsNotNone(out["quality"]["overall"])
        self.assertIn("not a scientific accuracy", out["quality"]["label"])
        print("\n[M7] heuristic quality:", out["quality"]["overall"], "| risk:",
              out["quality"]["duplicate_risk"])

    def test_missing_inputs_degrade_to_null(self):
        from analytics import compute_analytics
        out = compute_analytics(PAPER_TWO_Q, None, None, None)
        self.assertIsNone(out["comparison"])
        self.assertIsNone(out["quality"]["overall"])
        self.assertEqual(out["n_questions"], 2)
        print("\n[M7] missing inputs -> nulls, never invented numbers.")


# ---------------------------------------------------------------- M8 (contracts the UI relies on)
class TestM8ReviewContracts(unittest.TestCase):
    def test_edit_revalidates(self):
        # Fixing MCQ options 2 -> 4 must flip qtype FAIL -> PASS on revalidation.
        from validator import validate_paper
        before = validate_paper({"sections": [{"type": "MCQ", "marks_per_question": 1,
                                               "questions": [dict(GOOD_MCQ, options=["A. x", "B. y"])]}]},
                                CHUNKS)
        after = validate_paper({"sections": [{"type": "MCQ", "marks_per_question": 1,
                                              "questions": [dict(GOOD_MCQ)]}]}, CHUNKS)
        self.assertEqual(before["results"][0]["checks"]["qtype"]["status"], "FAIL")
        self.assertEqual(after["results"][0]["checks"]["qtype"]["status"], "PASS")
        print("\n[M8] edit-then-revalidate flips verdict as the UI expects.")

    def test_delete_shrinks_summary(self):
        from validator import validate_paper
        full = validate_paper({"sections": [{"type": "MCQ", "marks_per_question": 1,
                                             "questions": [dict(GOOD_MCQ),
                                                           dict(GOOD_MCQ, id="Q2")]}]}, CHUNKS)
        pruned = validate_paper({"sections": [{"type": "MCQ", "marks_per_question": 1,
                                               "questions": [dict(GOOD_MCQ)]}]}, CHUNKS)
        self.assertEqual(full["summary"]["total"] - pruned["summary"]["total"], 1)
        print("\n[M8] delete reduces validated total by exactly one.")

    def test_frontend_resets_state_per_paper(self):
        # FIX 2 regression: panels must remount on a new paper identity.
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "frontend", "src", "App.jsx")
        with open(app_path, encoding="utf-8") as f:
            src = f.read()
        for token in ['key={`val-${paperGen}`}', 'key={`dup-${paperGen}`}',
                      'key={`ana-${paperGen}`}', 'key={`rev-${paperGen}`}',
                      "setPaperGen((g) => g + 1)"]:
            self.assertIn(token, src, f"missing FIX 2 token: {token}")
        print("\n[M8/FIX2] App keys all four panels by paperGen identity.")


# ---------------------------------------------------------------- M9
class TestM9PdfExport(unittest.TestCase):
    def test_pdf_and_key(self):
        from export_pdf import build_pdf
        a = build_pdf(PAPER_TWO_Q, include_answers=False)
        b = build_pdf(PAPER_TWO_Q, include_answers=True)
        self.assertTrue(a[:5] == b"%PDF-" and b[:5] == b"%PDF-")
        import io
        import pypdf
        ta = " ".join((p.extract_text() or "")
                       for p in pypdf.PdfReader(io.BytesIO(a)).pages)
        tb = " ".join((p.extract_text() or "")
                       for p in pypdf.PdfReader(io.BytesIO(b)).pages)
        self.assertNotIn("ANSWER KEY", ta)
        self.assertIn("ANSWER KEY", tb)
        self.assertIn("Model answer.", tb)  # explanations only in key
        self.assertNotIn("Model answer.", ta)
        print(f"\n[M9] PDFs valid (paper {len(a)}B, key {len(b)}B), key labelled.")

    def test_empty_rejected(self):
        from export_pdf import build_pdf
        with self.assertRaises(ValueError):
            build_pdf({"subject": "OS", "sections": []})
        r = client.post("/api/export/pdf", json={"paper": {"subject": "OS", "sections": []}})
        self.assertEqual(r.status_code, 400)
        print("\n[M9] empty paper rejected (lib + endpoint).")

    def test_symbiosis_header_and_blanks(self):
        # Header layout: provided metadata renders, missing fields stay blank.
        import io
        import pypdf
        from export_pdf import build_pdf
        paper = dict(PAPER_TWO_Q)
        paper["institution"] = "SYMBIOSIS INSTITUTE OF TECHNOLOGY, NAGPUR"
        paper["exam_meta"] = {"programme": "B.Tech CSE", "semester": "III",
                              "batch": "2023-27", "course_code": "0705210303",
                              "exam_date": "02/12/2025", "day": "Tuesday",
                              "time_slot": "10:00 - 11:30"}
        text = " ".join((p.extract_text() or "")
                         for p in pypdf.PdfReader(io.BytesIO(build_pdf(paper, False))).pages)
        # pypdf inserts line breaks mid-phrase; normalize before matching.
        flat = " ".join(text.replace("\n", " ").split())
        for needle in ["SYMBIOSIS INTERNATIONAL (DEEMED UNIVERSITY)", "Seat No.",
                       "STUDENT INFORMATION", "B.Tech CSE", "0705210303",
                       "DO NOT WRITE ANYTHING", "Signature of Student"]:
            self.assertIn(needle, flat, needle)
        key_text = " ".join((p.extract_text() or "")
                            for p in pypdf.PdfReader(io.BytesIO(build_pdf(paper, True))).pages)
        self.assertIn("ANSWER KEY", key_text)
        self.assertNotIn("STUDENT INFORMATION", key_text)
        bare = " ".join((p.extract_text() or "") for p in pypdf.PdfReader(
            io.BytesIO(build_pdf(PAPER_TWO_Q, False))).pages)
        self.assertIn("___", bare)  # blanks, nothing invented
        self.assertNotIn("B.Tech", bare)
        print("\n[M9] Symbiosis header renders metadata; blanks stay blank; key labelled.")


# ---------------------------------------------------------------- M10
class TestM10History(unittest.TestCase):
    def test_crud_cycle(self):
        import history
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        prev = history._db_path
        try:
            history.init_db(tmp.name)
            pid = history.save_paper("T", "OS", 6, 2, PAPER_TWO_Q,
                                     {"subject": "OS"}, {"summary": {"total": 2}})
            items = history.list_papers()
            self.assertTrue(any(p["id"] == pid for p in items))
            full = history.get_paper(pid)
            self.assertEqual(full["paper"]["subject"], "OS")
            self.assertEqual(full["blueprint"], {"subject": "OS"})
            # Duplicate = re-save fetched snapshot under a new title.
            pid2 = history.save_paper(full["title"] + " (copy)", full["subject"], 6, 2,
                                      full["paper"], full["blueprint"], full["validation"])
            self.assertNotEqual(pid2, pid)
            self.assertTrue(history.delete_paper(pid2))
            self.assertTrue(history.delete_paper(pid))
            self.assertIsNone(history.get_paper(pid))
        finally:
            history.init_db(prev)
            try:
                os.remove(tmp.name)
            except OSError:
                pass
        print("\n[M10] save/list/get/duplicate/delete/404-after-delete cycle passes.")


# ---------------------------------------------------------------- FIX 3
class TestFix3UploadOrder(unittest.TestCase):
    def test_invalid_file_rejected_offline(self):
        # .exe while Ollama is offline must name the file (400), not 503.
        r = client.post("/upload-notes",
                        files=[("files", ("evil.exe", b"hello world", "application/octet-stream"))],
                        headers={"X-Session-ID": "fix3_suite"})
        self.assertEqual(r.status_code, 400, r.text[:200])
        self.assertIn("evil.exe", r.text)
        print("\n[FIX3] invalid file identified without Ollama.")

    def test_empty_file_rejected_offline(self):
        r = client.post("/upload-notes",
                        files=[("files", ("empty.txt", b"", "text/plain"))],
                        headers={"X-Session-ID": "fix3_suite"})
        self.assertEqual(r.status_code, 400, r.text[:200])
        print("\n[FIX3] empty file rejected without Ollama.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
