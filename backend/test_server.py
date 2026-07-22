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

    def test_passing_out_expands_to_health_exception_terms(self):
        expanded = server.tokens("O aluno passou mal e precisa cancelar o slot")
        self.assertIn("saude", expanded)
        self.assertIn("comprov", expanded)
        self.assertIn("cancel", expanded)

    def test_health_cancellation_recovers_no_show_exception(self):
        evidence = server.retrieve("O aluno passou mal e precisa cancelar o slot. Qual o procedimento?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_b013_2026_saude_pode_ser_excecao_no_show", evidence_ids)

    def test_extraordinary_traffic_recovers_rg003_exception(self):
        evidence = server.retrieve("O aluno ficou preso em uma interdição por acidente e não chegará ao voo. É NO SHOW?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_rg003_evento_viario_pode_ser_excecao", evidence_ids)

    def test_third_exception_in_90_days_recovers_coordination_rule(self):
        evidence = server.retrieve("Esta é a terceira solicitação de exceção do aluno em 90 dias. Quem deve analisar?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_rg003_terceira_excecao_90_dias", evidence_ids)


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
