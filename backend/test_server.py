import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import server


class RetrievalTests(unittest.TestCase):
    def test_banca_ppa_recovers_bops_065(self):
        evidence = server.retrieve("Quantos voos o aluno PPA pode fazer sem a banca da ANAC?")
        self.assertTrue(any("065" in f"{item['label']} {item['code']}" for item in evidence))

    def test_extracts_document_code(self):
        self.assertEqual(server.document_code("Boletim B-OPS-065 - Requisitos"), "B-OPS-065")


class LearningGraphTests(unittest.TestCase):
    def test_records_question_evidence_and_pending_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "query_graph.json"
            evidence = [{"id": "claim_1"}]
            result = {"used_evidence": [1], "candidate_relations": [{
                "source_concept": "PPA", "target_concept": "Banca ANAC",
                "relation": "requires", "reason": "Evidência recuperada",
            }]}
            with patch.object(server, "LEARNING_GRAPH_PATH", path):
                query_id = server.record_learning("Pergunta de teste", evidence, result)
            graph = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(graph["nodes"][0]["id"], query_id)
            self.assertEqual(graph["edges"][0]["relation"], "answered_using")
            self.assertEqual(graph["candidate_relations"][0]["status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
