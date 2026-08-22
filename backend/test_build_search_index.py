import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_search_index


class StableSearchIndexTests(unittest.TestCase):
    def test_preserves_timestamp_when_only_generation_time_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.js"
            previous = {
                "meta": {"generatedAt": "anterior", "confirmedClaims": 2},
                "claims": [{"id": "claim-1"}],
                "documents": [],
            }
            path.write_text(
                "window.SAFE_KNOWLEDGE_INDEX = "
                + json.dumps(previous, separators=(",", ":"))
                + ";\n",
                encoding="utf-8",
            )
            current = {
                "meta": {"generatedAt": "novo", "confirmedClaims": 2},
                "claims": [{"id": "claim-1"}],
                "documents": [],
            }

            stabilized = build_search_index.stabilize_generated_at(path, current)

            self.assertEqual(stabilized["meta"]["generatedAt"], "anterior")

    def test_keeps_new_timestamp_when_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.js"
            previous = {
                "meta": {"generatedAt": "anterior", "confirmedClaims": 1},
                "claims": [{"id": "claim-1"}],
                "documents": [],
            }
            path.write_text(
                "window.SAFE_KNOWLEDGE_INDEX = "
                + json.dumps(previous, separators=(",", ":"))
                + ";\n",
                encoding="utf-8",
            )
            current = {
                "meta": {"generatedAt": "novo", "confirmedClaims": 2},
                "claims": [{"id": "claim-1"}, {"id": "claim-2"}],
                "documents": [],
            }

            stabilized = build_search_index.stabilize_generated_at(path, current)

            self.assertEqual(stabilized["meta"]["generatedAt"], "novo")


if __name__ == "__main__":
    unittest.main()
