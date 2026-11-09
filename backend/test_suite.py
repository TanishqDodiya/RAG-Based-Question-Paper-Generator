import sys
import os
import unittest
import requests

BASE_URL = "http://localhost:8000"

class TestRAGGrounding(unittest.TestCase):
    def test_01_health_status(self):
        """Test status endpoint and anti-caching headers"""
        try:
            resp = requests.get(f"{BASE_URL}/api/status", headers={"X-Session-ID": "test_session_1"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("ollama_connected", data)
            self.assertIn("chromadb", data)
            print("\n[TEST 1 PASSED] /api/status endpoint responds correctly:", data.get("message"))
        except Exception as e:
            self.fail(f"Health status check failed: {e}")

    def test_04_no_documents(self):
        """Test 4: Request paper when 0 documents uploaded for session -> must reject HTTP 400"""
        unique_session = "empty_session_9999"
        payload = {
            "subject": "Operating Systems",
            "total_marks": 25,
            "difficulty": "Medium",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}]
        }
        resp = requests.post(f"{BASE_URL}/generate-paper", json=payload, headers={"X-Session-ID": unique_session})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No study material is available", resp.json().get("detail", ""))
        print("\n[TEST 4 PASSED] Refused generation when zero documents uploaded.")

    def test_05_random_input(self):
        """Test 5: Meaningless input like 'hfhdf6512' -> must reject HTTP 400"""
        unique_session = "empty_session_9999"
        payload = {
            "subject": "hfhdf6512",
            "total_marks": 25,
            "difficulty": "Medium",
            "sections": [{"type": "MCQ", "count": 5, "marks_per_q": 1}]
        }
        resp = requests.post(f"{BASE_URL}/generate-paper", json=payload, headers={"X-Session-ID": unique_session})
        self.assertEqual(resp.status_code, 400)
        print("\n[TEST 5 PASSED] Refused generation for random input 'hfhdf6512'.")

if __name__ == "__main__":
    unittest.main()
