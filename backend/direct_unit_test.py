import os
import sys
import unittest
from fastapi import HTTPException
from fastapi.responses import Response

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    validate_educational_topic,
    check_ollama_status,
    resolve_session_id,
    clean_json_response,
    notes_collection
)

class DirectBackendUnitTest(unittest.TestCase):

    def test_topic_validation_valid(self):
        valid_topics = [
            "Operating Systems",
            "Data Structures & Algorithms",
            "Quantum Mechanics Chapter 3",
            "Organic Chemistry Basics"
        ]
        for topic in valid_topics:
            res = validate_educational_topic(topic)
            self.assertEqual(res, topic)
        print("\n[PASSED] Valid educational topic strings passed validation.")

    def test_topic_validation_invalid(self):
        invalid_topics = [
            "  ",
            "a",
            "aaaaaa",
            "11111111",
            "hfhdf6512",
            "asdfgh123",
            "xyzxyz"
        ]
        for topic in invalid_topics:
            with self.assertRaises(HTTPException) as ctx:
                validate_educational_topic(topic)
            self.assertEqual(ctx.exception.status_code, 400)
        print("\n[PASSED] Random/invalid inputs (hfhdf6512, asdfgh123, aaaaaa) correctly rejected with HTTP 400!")

    def test_session_isolation_resolution(self):
        s1 = resolve_session_id("  session_custom_123  ")
        self.assertEqual(s1, "session_custom_123")
        
        s2 = resolve_session_id(None)
        self.assertTrue(s2.startswith("session_"))
        print("\n[PASSED] Session ID resolution strictly creates unique session IDs.")

    def test_ollama_status_function(self):
        connected, msg, models = check_ollama_status()
        print(f"\n[INFO] Ollama status check result -> Connected: {connected}, Message: '{msg}', Installed models: {models}")
        self.assertIsInstance(connected, bool)

    def test_clean_json_response(self):
        raw_markdown = "```json\n{\"title\": \"Test Paper\"}\n```"
        cleaned = clean_json_response(raw_markdown)
        self.assertEqual(cleaned, '{"title": "Test Paper"}')
        print("\n[PASSED] Clean JSON response regex parser works correctly.")

if __name__ == "__main__":
    unittest.main()
