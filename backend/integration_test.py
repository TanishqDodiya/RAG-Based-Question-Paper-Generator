import os
import sys
import unittest
from fastapi import HTTPException
from starlette.testclient import TestClient

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app, chroma_client, notes_collection

client = TestClient(app)

class RAGIntegrationTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.session_a = "session_test_a_1001"
        cls.session_b = "session_test_b_2002"
        
        # Clean up any leftover vectors for test sessions
        try:
            notes_collection.delete(where={"session_id": cls.session_a})
            notes_collection.delete(where={"session_id": cls.session_b})
        except Exception:
            pass

    def test_01_health_and_status(self):
        """Test status endpoint anti-caching & Ollama status."""
        response = client.get("/api/status", headers={"X-Session-ID": self.session_a})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(response.headers.get("cache-control"), "no-cache, no-store, must-revalidate, max-age=0")
        self.assertIn("ollama_connected", data)
        self.assertIn("chromadb", data)
        print("\n[TEST 1 PASSED] /api/status returns live status with anti-caching headers.")

    def test_02_session_b_no_documents_rejection(self):
        """Test 4 & 8: Session B has no documents -> Must refuse generation with HTTP 400."""
        payload = {
            "subject": "Operating Systems",
            "total_marks": 20,
            "difficulty": "Medium",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}]
        }
        response = client.post("/generate-paper", json=payload, headers={"X-Session-ID": self.session_b})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No study material is available", response.json()["detail"])
        print("\n[TEST 4 & 8 PASSED] Session B (0 docs) generation correctly rejected with HTTP 400!")

    def test_03_empty_file_upload(self):
        """Test 9: Empty file ingestion -> Must reject with HTTP 400."""
        files = [('files', ('empty.txt', b'', 'text/plain'))]
        response = client.post("/upload-notes", files=files, headers={"X-Session-ID": self.session_a})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not extract sufficient readable text", response.json()["detail"])
        print("\n[TEST 9 PASSED] Empty document ingestion correctly rejected with HTTP 400!")

    def test_04_valid_document_ingestion(self):
        """Test 6: Ingest valid study material for Session A."""
        os_sample_text = (
            "Operating Systems Lecture Notes.\n"
            "Chapter 1: Process Management and CPU Scheduling.\n"
            "A process is a program in execution. The Operating System manages processes using Process Control Blocks (PCB).\n"
            "CPU Scheduling algorithms include First-Come-First-Served (FCFS), Shortest Job First (SJF), and Round Robin (RR).\n"
            "Virtual memory uses paging and segmentation to map logical address space into physical memory RAM.\n"
            "Deadlock occurs when processes are blocked waiting for resources held by each other. Conditions for deadlock are Mutual Exclusion, Hold and Wait, No Preemption, and Circular Wait."
        )
        files = [('files', ('os_lecture_notes.txt', os_sample_text.encode('utf-8'), 'text/plain'))]
        upload_res = client.post("/upload-notes", files=files, headers={"X-Session-ID": self.session_a})
        self.assertEqual(upload_res.status_code, 200)
        print("\n[INGESTION PASSED] Ingested Operating Systems notes for Session A successfully.")

    def test_05_random_input_rejection_after_upload(self):
        """Test 5: Meaningless random input 'hfhdf6512' when docs exist -> Gate 2 catches & rejects HTTP 400."""
        payload = {
            "subject": "hfhdf6512",
            "total_marks": 20,
            "difficulty": "Medium",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}]
        }
        response = client.post("/generate-paper", json=payload, headers={"X-Session-ID": self.session_a})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid educational subject input detected", response.json()["detail"])
        print("\n[TEST 5 PASSED] Meaningless input 'hfhdf6512' caught by Input Gate and rejected with HTTP 400!")

    def test_06_irrelevant_query_rejection(self):
        """Test 7: Query irrelevant topic 'Advanced Astrophysics' when OS notes exist -> Gate 3 distance check rejects HTTP 422."""
        payload_astro = {
            "subject": "Advanced Astrophysics",
            "total_marks": 20,
            "difficulty": "Hard",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}]
        }
        res_astro = client.post("/generate-paper", json=payload_astro, headers={"X-Session-ID": self.session_a})
        self.assertEqual(res_astro.status_code, 422)
        self.assertIn("No relevant content found in your uploaded study material", res_astro.json()["detail"])
        print("\n[TEST 7 PASSED] Irrelevant topic 'Advanced Astrophysics' rejected with HTTP 422 relevance error!")

    def test_07_valid_paper_generation(self):
        """Test 6: Query relevant topic 'Operating Systems' -> Must succeed and return structured paper."""
        payload_os = {
            "subject": "Operating Systems",
            "total_marks": 10,
            "difficulty": "Medium",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}, {"type": "Short", "count": 1, "marks_per_q": 5}]
        }
        res_os = client.post("/generate-paper", json=payload_os, headers={"X-Session-ID": self.session_a})
        self.assertEqual(res_os.status_code, 200)
        paper_data = res_os.json()
        self.assertIn("title", paper_data)
        self.assertIn("sections", paper_data)
        print(f"\n[TEST 6 PASSED] Successfully generated grounded paper for 'Operating Systems' using Ollama llama3.2!")

if __name__ == "__main__":
    unittest.main()
