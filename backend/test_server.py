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

    def test_pc_slots_question_recovers_pc_daily_hours_limit(self):
        evidence = server.retrieve("Aluno PC pode fazer mais de três slots solo no mesmo dia?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_pcap001k_limite_diario_instrucao", evidence_ids)
        self.assertNotIn("claim_pcifrap001k_limite_diario_instrucao", evidence_ids)

    def test_pp_daily_hours_question_recovers_pp_limit_and_excludes_pcifr(self):
        evidence = server.retrieve("pp pode fazer mais do que 3 horas por dia de voo?")
        evidence_ids = [item["id"] for item in evidence]
        self.assertIn("claim_mip_pp_limite_instrucao_local", evidence_ids)
        self.assertIn("claim_ppap001k_limite_diario_instrucao", evidence_ids)
        self.assertNotIn("claim_pcifrap001k_limite_diario_instrucao", evidence_ids)

    def test_short_course_token_does_not_match_inside_another_course(self):
        self.assertEqual(server.score_text(["pp"], "Curso PCIFR"), 0)

    def test_mockup_question_recovers_ground_prerequisite(self):
        evidence = server.retrieve("Quais são os pré-requisitos para o aluno fazer o MOCKUP?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_mgop_ground_e_prova_antes_mockup", evidence_ids)

    def test_lodging_question_recovers_commercial_and_cavok_rule(self):
        evidence = server.retrieve("Como o aluno solicita e agenda o alojamento da SAFE?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_mgop_alojamento_comercial_cavok", evidence_ids)

    def test_pcifr_hood_check_recovers_conditional_rule(self):
        evidence = server.retrieve("Aluno PCIFR pode realizar o cheque ANAC sob capota?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_mgop_pcifr_cheque_sob_capota_condicionado", evidence_ids)

    def test_inva_daily_hours_recovers_inva_limit_and_excludes_pp(self):
        evidence = server.retrieve("Aluno INVA pode fazer mais de 3 horas de instrução por dia?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_invap001h_limite_diario_instrucao", evidence_ids)
        self.assertNotIn("claim_ppap001k_limite_diario_instrucao", evidence_ids)

    def test_ifr_aircraft_limit_excludes_pc_course_rules(self):
        evidence = server.retrieve("No curso IFR, posso usar aeronave não certificada IFR em toda a fase 3B?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_ifrap001d_aeronave_nao_ifr_maximo_75", evidence_ids)
        self.assertNotIn("claim_pcap001k_fase3b_tempo_decolagem_pouso", evidence_ids)

    def test_dgr_recovers_both_actions_from_same_document(self):
        evidence = server.retrieve("Ao identificar carga perigosa DGR na SAFE, qual é o procedimento?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_mgso_dgr_exige_relprev_imediato", evidence_ids)
        self.assertIn("claim_mgso_dgr_dso_contem_risco", evidence_ids)

    def test_recognizes_all_supported_course_tokens(self):
        self.assertEqual(server.requested_course("curso PP"), "pp")
        self.assertEqual(server.requested_course("curso PC"), "pc")
        self.assertEqual(server.requested_course("curso PCIFR"), "pcifr")
        self.assertEqual(server.requested_course("curso IFR"), "ifr")
        self.assertEqual(server.requested_course("curso INVA"), "inva")


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
