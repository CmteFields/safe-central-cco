import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from backend import server
from backend import wsgi


class RetrievalTests(unittest.TestCase):
    def test_ppa_sequence_recovers_canonical_complete_answer_from_public_index(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve(
                "De acordo com o PI da SAFE, qual a sequência de missões de PPA?"
            )
        self.assertEqual(evidence[0]["id"], "claim_ppap001k_sequencia_completa_missoes")
        self.assertIn("PS01", evidence[0]["operator_answer"])
        self.assertIn("NOT02", evidence[0]["operator_answer"])

    def test_noncanonical_confirmed_evidence_is_not_a_deterministic_answer(self):
        evidence = [{
            "kind": "confirmed_claim",
            "label": "Regra relacionada, mas não conclusiva",
        }]
        self.assertIsNone(server.deterministic_local_result(evidence))

    def test_public_index_is_used_when_private_knowledge_is_not_deployed(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve("Quantas horas por dia o aluno PP pode voar?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_ppap001k_limite_diario_instrucao", evidence_ids)
        # O catálogo de regras aprovadas (Regras/catalogo_regras.json) é uma camada
        # independente do pacote privado de conhecimento; continua disponível mesmo
        # quando CLAIMS_PATH/GRAPH_PATH simulam o pacote privado ausente.
        self.assertTrue(all(
            item["source"] == "Índice público de regras confirmadas"
            for item in evidence
            if not str(item["id"]).startswith("approved_rule_")
        ))

    def test_public_canonical_answer_overlays_older_private_claim(self):
        claims = {"claims": [{
            "id": "claim_rbac61_cma_vencido_impede_prerrogativas",
            "label": "CMA vencido impede o exercício das prerrogativas",
            "status": "confirmed",
            "document_code": "RBAC 61",
            "source_path": "Regulamentacao_ANAC/RBAC 61.md",
            "source_location": "61.17",
            "applies_to": ["alunos_piloto", "cma_vencido"],
        }]}
        graph = {"nodes": []}
        with patch.object(
            server, "load_json", side_effect=[claims, graph]
        ), patch.object(
            server, "load_public_operator_answers",
            return_value={
                "claim_rbac61_cma_vencido_impede_prerrogativas":
                    "Não. O aluno não pode voar sem CMA válido."
            },
        ), patch.object(
            server, "source_excerpt", return_value=""
        ), patch.object(
            server, "content_score", return_value=0
        ), patch.object(
            server, "CLAIMS_PATH", Path(__file__)
        ), patch.object(
            server, "GRAPH_PATH", Path(__file__)
        ):
            evidence = server.retrieve(
                "O aluno independente do voo solo pode voar sem CMA valido?"
            )

        self.assertEqual(
            evidence[0]["operator_answer"],
            "Não. O aluno não pode voar sem CMA válido.",
        )

    def test_cma_intent_excludes_unrelated_solo_rules(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve("Um aluno pode voar independente do voo solo sem CMA?")
        self.assertTrue(evidence)
        self.assertEqual(evidence[0]["id"], "claim_rbac61_cma_vencido_impede_prerrogativas")
        self.assertTrue(all("cma" in f"{item['label']} {item['id']}".casefold() for item in evidence))
        self.assertNotIn("claim_bops054_sem_solo_30_dias_novo_endosso", {item["id"] for item in evidence})

    def test_cma_has_no_automatic_thirty_day_extension(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve("O CMA vencido tem extensão de 30 dias para continuar voando?")
        evidence_ids = [item["id"] for item in evidence]
        self.assertEqual(evidence_ids, [
            "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma",
            "claim_rbac61_cma_vencido_impede_prerrogativas",
        ])

    def test_habilitation_tolerance_does_not_override_expired_cma(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve(
                "A habilitação venceu há 10 dias e o CMA também venceu. O piloto pode operar?"
            )
        evidence_ids = {item["id"] for item in evidence[:2]}
        self.assertEqual(evidence_ids, {
            "claim_rbac61_cma_vencido_impede_prerrogativas",
            "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma",
        })

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

    def test_instructor_choice_variants_recover_canonical_cco_answer(self):
        variants = [
            "Aluno pode escolher instrutor?",
            "Posso escolher o INVA para voar?",
            "Posso pedir para voar com um instrutor específico?",
            "Combinei o voo diretamente com o INVA. Já está confirmado?",
            "Não gostei do meu instrutor. Posso trocar?",
            "Quem define o instrutor da minha missão?",
            "Posso solicitar ao CCO preferência por outro INVA?",
        ]
        for question in variants:
            with self.subTest(question=question):
                evidence = server.retrieve(question)
                self.assertEqual(evidence[0]["id"], server.INSTRUCTOR_ALLOCATION_RULE_ID)
                with patch.object(server, "call_gemini_with_retry") as gemini, patch.object(
                    server, "record_learning", return_value="query_instructor_allocation"
                ):
                    result = server.answer_question(
                        question, capture_candidate=False, save_history=False
                    )
                gemini.assert_not_called()
                self.assertIn(
                    "não deve haver indicação, solicitação ou combinação direta",
                    result["answer"],
                )
                self.assertIn("operacoes@voesafe.com.br", result["answer"])
                self.assertIn(
                    "O CCO não está autorizado a atender esse tipo de solicitação",
                    result["answer"],
                )
                self.assertEqual(result["knowledge_status"], "approved")
                self.assertEqual(result["model_used"], "local-deterministic")

    def test_deterministic_answer_uses_only_highest_ranked_canonical_rule(self):
        result = server.deterministic_local_result([
            {
                "kind": "confirmed_claim",
                "operator_answer": "Resposta canônica principal.",
            },
            {
                "kind": "confirmed_claim",
                "operator_answer": "Resposta canônica de outro assunto.",
            },
        ])
        self.assertEqual(result["answer"], "Resposta canônica principal.")
        self.assertEqual(result["used_evidence"], [1])

    def test_base_transfer_variants_use_approved_rg006_without_gemini_or_new_gap(self):
        variants = [
            "aluno pode trocar de base?",
            "É permitido mudar a base do aluno?",
            "Posso transferir meu curso para outra base?",
            "Aluno PP pode mudar de SJK para CPQ?",
            "Aluno de INVA pode realizar missões em diferentes bases?",
            "Durante o curso de INVA posso alternar entre SBSJ e SDAM?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as gemini, patch.object(
                server, "record_learning", return_value="query_base_transfer"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            gemini.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertEqual(result["model_used"], "local-deterministic")
            self.assertEqual(result["candidate_id"], None)
            self.assertEqual(result["sources"][0]["code"], "RG-006")
            self.assertIn("não podem trocar de base", result["answer"])

    def test_every_approved_dynamic_rule_title_exposes_its_canonical_answer(self):
        rules = server.approved_dynamic_rules()
        self.assertGreaterEqual(len(rules), 9)
        for rule in rules:
            question = f"Qual é a regra sobre {rule['question']}?"
            with self.subTest(rule=rule["rule_code"], question=question):
                evidence = server.retrieve_dynamic_rules(question)
                self.assertTrue(evidence)
                self.assertEqual(evidence[0]["code"], rule["rule_code"])
                self.assertEqual(
                    evidence[0]["operator_answer"], rule["approved_rule_text"]
                )

    def test_every_curated_question_alias_recovers_its_claim_first(self):
        curated = server.load_json(server.CLAIMS_PATH)
        aliases = [
            (claim["id"], claim.get("document_code"), question)
            for claim in curated.get("claims", [])
            if claim.get("status") in {"confirmed", "confirmed_temporary_override"}
            for question in claim.get("question_aliases", [])
        ]
        self.assertGreater(len(aliases), 0)
        for claim_id, document_code, question in aliases:
            with self.subTest(claim_id=claim_id, question=question):
                evidence = server.retrieve(question)
                self.assertTrue(evidence)
                self.assertTrue(evidence[0].get("operator_answer"))
                if evidence[0]["id"] != claim_id:
                    self.assertEqual(evidence[0].get("code"), document_code)

    def test_nav03_can_precede_nav02_without_gemini(self):
        question = "Aluno pode fazer NAV03 antes da NAV02?"
        with patch.object(server, "call_gemini_with_retry") as gemini, patch.object(
            server, "semantic_retrieve_with_retry"
        ) as semantic_selector, patch.object(
            server, "record_learning", return_value="query_mission_order"
        ), patch.object(server, "upsert_rule_candidate") as create_gap:
            result = server.answer_question(
                question, capture_candidate=True, save_history=False
            )
        gemini.assert_not_called()
        semantic_selector.assert_not_called()
        create_gap.assert_not_called()
        self.assertEqual(result["knowledge_status"], "approved")
        self.assertEqual(result["sources"][0]["id"], "claim_ppap001k_nav03_pode_anteceder_nav02")
        self.assertIn("Sim.", result["answer"])
        self.assertIn("requisitos e liberações para voo solo", result["answer"])

    def test_other_mission_order_questions_use_complete_ppa_sequence(self):
        variants = [
            "Pode realizar AP05 antes da AP04 no PPA?",
            "O NOT02 pode acontecer antes do NOT01?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_mission_order"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertEqual(result["sources"][0]["id"], "claim_ppap001k_sequencia_completa_missoes")
            self.assertIn("NAV01 → NAV02 → NAV03", result["answer"])

    def test_cavok_access_variants_use_confirmed_answer_without_gemini_or_new_gap(self):
        variants = [
            "Como faço para acessar o CAVOK?",
            "Onde entro no sistema CAVOK?",
            "Não recebi meu acesso ao CAVOK, o que faço?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_cavok_access"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertEqual(result["response_mode"], "local_contingency")
            self.assertEqual(result["sources"][0]["id"], "claim_cavok_acesso_pessoal_aluno")
            self.assertIn("https://portaldoaluno.voesafe.com.br/", result["answer"])
            self.assertIn("https://voesafe.cavok.in/", result["answer"])

    def test_pp_solo_passenger_variants_use_confirmed_answer_without_new_gap(self):
        variants = [
            "O aluno de PP pode voar com a mãe no voo solo?",
            "Posso levar um familiar no voo solo de PPA?",
            "Aluno PP pode levar passageiro no solo?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_pp_passenger"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertEqual(result["response_mode"], "local_contingency")
            self.assertEqual(result["sources"][0]["id"], "claim_mip_acompanhante_proibido_solo_pp")
            self.assertIn("não pode levar a mãe", result["answer"].casefold())

    def test_rg013_requires_prior_instructor_flight_for_planned_solo_aerodrome(self):
        variants = [
            "Aluno de PP pode ir para qualquer destino no solo?",
            "Aluno de PC pode voar solo para um aeródromo que ainda não conhece?",
            "Precisa ter ido com instrutor antes de navegar solo para SBGW?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_rg013"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )

            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(
                result["sources"][0]["id"],
                "claim_rg013_familiarizacao_aerodromo_antes_voo_solo",
            )
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertIn("mesmo aeródromo com instrutor a bordo", result["answer"])

    def test_rg014_routes_aircraft_transfer_return_costs_without_new_gap(self):
        variants = [
            "Aluno que fizer translado entre as bases, a escola arca com algum custo?",
            "Quem paga o ônibus depois do translado da aeronave entre bases?",
            "Se houver problema técnico no translado, quem paga o retorno do aluno e do INVA?",
            "Se o retorno for impedido por meteorologia, quem paga as despesas do instrutor?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_rg014"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )

            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["sources"][0]["code"], "RG-014")
            self.assertEqual(result["knowledge_status"], "approved")
            self.assertEqual(result["model_used"], "local-deterministic")
            self.assertIn("ônibus", result["answer"])
            self.assertIn("meteorologia ou navegação", result["answer"])

    def test_family_may_watch_first_solo_from_ground_without_boarding(self):
        variants = [
            "Minha família pode acompanhar o primeiro voo solo?",
            "Minha mãe pode assistir ao meu primeiro voo solo?",
            "Familiares podem presenciar o evento do solo no pátio?",
        ]
        for question in variants:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_solo_family"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["sources"][0]["id"], "claim_mip_familia_pode_acompanhar_evento_solo_em_terra")
            self.assertIn("em terra", result["answer"])
            self.assertIn("não pode embarcar", result["answer"])

    def test_reviewed_operational_topics_route_to_their_approved_answers(self):
        cases = [
            (
                "A primeira barra tem prioridade sobre os cheques da segunda barra?",
                "claim_rg010_prioridade_barras_missoes_criticas",
                "alunos com restrição de INVA",
            ),
            (
                "Aluno de PP pode fazer a monitoria de NAV durante a fase AP?",
                "claim_mgop_monitoria_nav_durante_fase_ap",
                "antes do primeiro voo da fase de navegação",
            ),
            (
                "Faz 31 dias desde meu último solo na AP05. Posso solar?",
                "claim_bops054_sem_solo_30_dias_novo_endosso",
                "duplo comando",
            ),
        ]
        for question, rule_id, excerpt in cases:
            with self.subTest(question=question), patch.object(
                server, "call_gemini_with_retry"
            ) as answer_gemini, patch.object(
                server, "semantic_retrieve_with_retry"
            ) as semantic_selector, patch.object(
                server, "record_learning", return_value="query_reviewed_topic"
            ), patch.object(server, "upsert_rule_candidate") as create_gap:
                result = server.answer_question(
                    question, capture_candidate=True, save_history=False
                )
            answer_gemini.assert_not_called()
            semantic_selector.assert_not_called()
            create_gap.assert_not_called()
            self.assertEqual(result["sources"][0]["id"], rule_id)
            self.assertIn(excerpt, result["answer"])

    def test_unrelated_canonical_match_is_not_used_as_final_answer(self):
        evidence = [{
            "id": server.INSTRUCTOR_ALLOCATION_RULE_ID,
            "kind": "confirmed_claim",
            "label": "Aluno pode solicitar substituição de INVA ao CCO",
            "operator_answer": "Resposta de outro assunto.",
            "score": 40,
        }]
        self.assertIsNone(
            server.deterministic_local_result(
                evidence, "Qual é a prioridade da primeira barra?"
            )
        )

    def test_semantic_selector_can_recover_confirmed_rule_before_answer_generation(self):
        semantic_evidence = [{
            "id": "claim_semantic", "kind": "confirmed_claim",
            "label": "Regra semanticamente relacionada",
            "operator_answer": "Resposta canônica localizada semanticamente.",
            "code": "RG-100", "source": "Fonte", "location": "Seção",
            "url": "", "excerpt": "Regra", "score": 240,
        }]
        with patch.object(server, "retrieve", return_value=[]), patch.object(
            server, "gemini_key", return_value="configured"
        ), patch.object(
            server, "semantic_retrieve_with_retry", return_value=semantic_evidence
        ) as semantic_selector, patch.object(
            server, "call_gemini_with_retry"
        ) as answer_gemini, patch.object(
            server, "record_learning", return_value="query_semantic"
        ), patch.object(server, "upsert_rule_candidate") as create_gap:
            result = server.answer_question(
                "Pergunta formulada com sinônimos", capture_candidate=True, save_history=False
            )
        semantic_selector.assert_called_once()
        answer_gemini.assert_not_called()
        create_gap.assert_not_called()
        self.assertEqual(result["answer"], "Resposta canônica localizada semanticamente.")
        self.assertEqual(result["knowledge_status"], "approved")

    def test_semantic_selector_infers_intent_and_accepts_only_catalog_ids(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({
                    "selected_ids": ["approved_rule_9", "invented_rule"],
                })}]}}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["prompt"] = captured["body"]["contents"][0]["parts"][0]["text"]
            return FakeResponse()

        catalog = [{
            "id": "approved_rule_9", "label": "Uso do alojamento",
            "operator_answer": "Solicitar disponibilidade à área Comercial.",
            "code": "RG-007", "scope": "alojamento SAFE",
        }]
        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            selected = server.call_gemini_claim_selector(
                "Existe lugar para pernoite?", catalog
            )

        self.assertEqual(selected, ["approved_rule_9"])
        self.assertIn("linguagem coloquial", captured["prompt"])
        self.assertIn("CONFIRA NOVAMENTE A INTENÇÃO", captured["prompt"])
        self.assertIn("NO_CONFIRMED_MATCH", captured["prompt"])
        self.assertEqual(
            captured["body"]["generationConfig"]["responseSchema"]["properties"]
            ["selected_ids"]["minItems"], 1
        )
        self.assertGreaterEqual(
            captured["body"]["generationConfig"]["maxOutputTokens"], 1200
        )

    def test_semantic_selector_no_match_marker_does_not_become_evidence(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({
                    "selected_ids": ["NO_CONFIRMED_MATCH"],
                })}]}}]}).encode("utf-8")

        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", return_value=FakeResponse()
        ):
            selected = server.call_gemini_claim_selector(
                "Assunto inexistente", [{"id": "known", "label": "Outra regra"}]
            )

        self.assertEqual(selected, [])

    def test_semantic_query_expansion_reduces_catalog_before_selection(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({
                    "search_terms": ["pernoite", "hospedagem", "alojamento", "reserva"],
                })}]}}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            terms = server.call_gemini_query_expander("Existe lugar para dormir na escola?")

        catalog = [
            {"id": "irrelevant", "label": "Limite diário de instrução", "operator_answer": "", "scope": "voo"},
            {"id": "approved_rule_9", "label": "Uso do alojamento", "operator_answer": "Solicitar hospedagem ao Comercial", "scope": "alojamento SAFE"},
        ]
        shortlist = server.semantic_catalog_shortlist(
            "Existe lugar para dormir na escola?", terms, catalog
        )

        self.assertEqual(terms, ["pernoite", "hospedagem", "alojamento", "reserva"])
        self.assertEqual(shortlist[0]["id"], "approved_rule_9")
        self.assertGreaterEqual(
            captured["body"]["generationConfig"]["maxOutputTokens"], 1200
        )

    def test_recognizes_all_supported_course_tokens(self):
        self.assertEqual(server.requested_course("curso PP"), "pp")
        self.assertEqual(server.requested_course("curso PC"), "pc")
        self.assertEqual(server.requested_course("curso PCIFR"), "pcifr")
        self.assertEqual(server.requested_course("curso IFR"), "ifr")
        self.assertEqual(server.requested_course("curso INVA"), "inva")


class LearningGraphTests(unittest.TestCase):
    def test_records_question_evidence_and_pending_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portalcco.db"
            legacy_path = Path(directory) / "query_graph.json"
            evidence = [{"id": "claim_1"}]
            result = {"used_evidence": [1], "candidate_relations": [{
                "source_concept": "PPA", "target_concept": "Banca ANAC",
                "relation": "requires", "reason": "Evidência recuperada",
            }]}
            with patch.object(server, "LEARNING_DB_PATH", path), patch.object(
                server, "LEARNING_GRAPH_PATH", legacy_path
            ):
                query_id = server.record_learning("Pergunta de teste", evidence, result)
            connection = sqlite3.connect(path)
            try:
                question = connection.execute(
                    "SELECT question FROM learning_queries WHERE id=?", (query_id,)
                ).fetchone()
                evidence_row = connection.execute(
                    "SELECT relation FROM learning_query_evidence WHERE query_id=?", (query_id,)
                ).fetchone()
                candidate = connection.execute(
                    "SELECT status FROM learning_candidate_relations WHERE query_id=?", (query_id,)
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(question[0], "Pergunta de teste")
            self.assertEqual(evidence_row[0], "answered_using")
            self.assertEqual(candidate[0], "pending_review")
            self.assertFalse(legacy_path.exists())


class AuthenticationTests(unittest.TestCase):
    def test_initial_setup_requires_deployment_secret_in_production(self):
        with patch.object(server, "REQUIRE_SETUP_TOKEN", True), patch.object(
            server, "SETUP_TOKEN", "codigo-secreto"
        ):
            with self.assertRaises(PermissionError):
                server.authorize_initial_setup({"setup_token": "incorreto"})
            server.authorize_initial_setup({"setup_token": "codigo-secreto"})

    def test_initial_setup_fails_closed_without_configured_secret(self):
        with patch.object(server, "REQUIRE_SETUP_TOKEN", True), patch.object(server, "SETUP_TOKEN", ""):
            with self.assertRaises(RuntimeError):
                server.authorize_initial_setup({"setup_token": ""})

    def test_secure_session_cookie_in_production(self):
        with patch.object(server, "SECURE_COOKIES", True):
            cookie = server.Handler.session_cookie("token", 60)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Secure", cookie)

    def test_setup_login_and_session_cookie(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ):
            self.assertTrue(server.auth_setup_required())
            admin = server.create_user({
                "username": "admin.cco", "display_name": "Administrador CCO", "password": "senha",
            }, force_admin=True)
            user, token, csrf = server.authenticate("admin.cco", "senha")
            session, stored_csrf, token_hash = server.session_user(f"cco_session={token}")
            self.assertEqual(user["id"], admin["id"])
            self.assertEqual(session["id"], admin["id"])
            self.assertEqual(csrf, stored_csrf)
            self.assertTrue(token_hash)

    def test_portal_activity_exposes_online_users_without_sensitive_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ):
            server.create_user({
                "username": "admin.cco", "display_name": "Administrador CCO", "password": "senha",
            }, force_admin=True)
            user, token, _ = server.authenticate("admin.cco", "senha")
            _, _, token_hash = server.session_user(f"cco_session={token}")
            server.record_portal_activity(user["id"], token_hash, "Aeronaves")
            activity = server.list_portal_activity()
            self.assertEqual(activity["online_count"], 1)
            self.assertEqual(activity["items"][0]["display_name"], "Administrador CCO")
            self.assertEqual(activity["items"][0]["last_activity_area"], "Aeronaves")
            self.assertNotIn("password_hash", activity["items"][0])
            self.assertNotIn("csrf_token", activity["items"][0])

    def test_temporary_password_requires_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ):
            server.create_user({
                "username": "admin", "display_name": "Admin", "password": "admin",
            }, force_admin=True)
            operator = server.create_user({
                "username": "operador", "display_name": "Operador", "password": "temporaria",
                "role": "operator",
            })
            self.assertTrue(operator["must_change_password"])
            server.change_own_password(operator["id"], "temporaria", "nova")
            updated = next(item for item in server.list_users() if item["id"] == operator["id"])
            self.assertFalse(updated["must_change_password"])

    def test_admin_edit_requires_target_password_and_one_time_grant(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ):
            first = server.create_user({
                "username": "admin1", "display_name": "Admin 1", "password": "senha1",
            }, force_admin=True)
            second = server.create_user({
                "username": "admin2", "display_name": "Admin 2", "password": "senha2", "role": "admin",
            })
            with self.assertRaises(PermissionError):
                server.authorize_admin_edit(second["id"], first["id"], "incorreta")
            grant = server.authorize_admin_edit(second["id"], first["id"], "senha1")
            changed = server.update_user(first["id"], {
                "display_name": "Administrador 1", "role": "admin", "active": True,
                "admin_edit_token": grant,
            }, second["id"])
            self.assertEqual(changed["display_name"], "Administrador 1")
            with self.assertRaises(PermissionError):
                server.update_user(first["id"], {
                    "display_name": "Outro nome", "role": "admin", "active": True,
                    "admin_edit_token": grant,
                }, second["id"])

    def test_last_active_admin_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ):
            admin = server.create_user({
                "username": "admin", "display_name": "Admin", "password": "senha",
            }, force_admin=True)
            grant = server.authorize_admin_edit(admin["id"], admin["id"], "senha")
            with self.assertRaises(ValueError):
                server.update_user(admin["id"], {
                    "display_name": "Admin", "role": "viewer", "active": True,
                    "admin_edit_token": grant,
                }, admin["id"])


class WSGITests(unittest.TestCase):
    @staticmethod
    def request(
        path: str,
        method: str = "GET",
        payload: dict | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str], bytes]:
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else b""
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "SERVER_NAME": "portalcco.example",
            "SERVER_PORT": "443",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.url_scheme": "https",
            "wsgi.input": BytesIO(body),
            "CONTENT_LENGTH": str(len(body)),
        }
        if body:
            environ["CONTENT_TYPE"] = "application/json"
        for name, value in (request_headers or {}).items():
            environ[f"HTTP_{name.upper().replace('-', '_')}"] = value
        response_body = b"".join(wsgi.application(environ, start_response))
        headers = {name: value for name, value in captured["headers"]}
        return str(captured["status"]), headers, response_body

    def test_health_endpoint_through_wsgi(self):
        status, headers, body = self.request("/api/health")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["release"], server.RELEASE_ID)
        self.assertEqual(payload["updated_at"], server.PORTAL_UPDATED_AT)
        self.assertIn(payload["knowledge"], {"private_bundle", "configured_root", "public_index"})
        self.assertIn(payload["gemini"], {"configured", "missing"})
        self.assertEqual(payload["gemini_model"], server.LOCAL_MODEL)
        self.assertEqual(payload["gemini_fallback_model"], server.FALLBACK_MODEL)

    def test_static_portal_through_wsgi(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"CCO - Central de conhecimento", body)
        self.assertIn(b'id="portalUpdatedAt"', body)
        self.assertIn(b'<option selected>Aberto</option>', body)
        self.assertIn(b'styles.css?v=20260828-2', body)
        self.assertIn(b"public-knowledge-index.js?v=20260731-6", body)
        self.assertIn(b"instrutores.css?v=20260828-2", body)
        self.assertIn(b"app.js?v=20260828-3", body)
        self.assertIn(b'id="newSearchButton"', body)
        self.assertIn(b'id="toggleRecentSearch"', body)
        self.assertIn(b'id="recentSearch"', body)
        self.assertIn(b'aria-autocomplete="list"', body)

    def test_browser_uses_same_origin_ai_endpoint(self):
        status, _, body = self.request("/app.js")
        self.assertEqual(status, "200 OK")
        self.assertIn(b"`${window.location.origin}/api/ask`", body)
        self.assertIn(b"`${window.location.origin}/api/reports", body)
        self.assertNotIn(b"http://127.0.0.1:8765/api/ask", body)
        self.assertIn("Busca local inconclusiva".encode(), body)
        self.assertIn(b'item.fleet_status === "Ativa" && item.status !== "Operacional"', body)
        self.assertIn(b"edit-aircraft-button", body)
        self.assertIn("Somente leitura".encode(), body)
        self.assertIn(b"knowledge-gaps?status=open", body)
        self.assertIn(b"rule-candidates/${id}/reprocess", body)
        self.assertIn(b"operatorAnswer", body)
        self.assertIn(b"Resposta confirmada pela base SAFE", body)
        self.assertIn(b"function startNewSearch()", body)
        self.assertIn(b'input.value = ""', body)
        self.assertIn(b'$("#newSearchButton").addEventListener("click", startNewSearch)', body)
        self.assertIn("Histórico de passagens".encode(), body)
        self.assertIn("Concluídas neste ciclo".encode(), body)
        self.assertIn(b"data.active_cycle_id", body)
        self.assertIn(b"function handoverBaseWarning(payload)", body)
        self.assertIn("A mensagem menciona SDAM/Campinas".encode(), body)
        self.assertIn(b"function initializeFormDialogGuards()", body)
        self.assertIn(b"function formDialogHasChanges(dialog)", body)
        self.assertIn(b"requestFormDialogClose(dialog)", body)
        self.assertIn("Existem alterações não salvas".encode(), body)
        self.assertIn(b"function findQuestionSuggestions(query)", body)
        self.assertIn(b"questionSuggestionScore", body)
        self.assertIn(b"api/searches?limit=100", body)
        self.assertIn(b'item.action === "stored"', body)
        self.assertIn(b"const ASK_TIMEOUT_MS = 125000", body)
        self.assertIn(b"void saveLocalSearchRecord(query, localResult).then(loadSearchHistory)", body)
        self.assertNotIn(b"await saveLocalSearchRecord(query, localResult)", body)

    def test_static_portal_contains_reports_section(self):
        status, _, body = self.request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn(b'data-view="reports"', body)
        self.assertIn(b'id="reportsView"', body)
        self.assertIn(b'id="reportAnswerIssue"', body)
        self.assertIn(b'data-view="gestao-regras"', body)
        self.assertIn(b'id="ruleManagementView"', body)
        self.assertIn(b'id="accountFormError"', body)
        self.assertIn(b'id="handoverFormError"', body)
        self.assertIn(b'id="handoverBase"', body)
        self.assertIn(b'id="handoverType"', body)
        self.assertIn(b'id="handoverAssignee"', body)
        self.assertIn(b'id="handoverTicketShift"', body)
        self.assertIn(b'id="handoverAssignee" maxlength="100" readonly', body)
        self.assertNotIn(b'id="handoverOrigin"', body)
        self.assertNotIn(b'id="handoverTarget"', body)
        self.assertIn("Uma única passagem para as duas bases".encode(), body)
        self.assertIn("INFORMAÇÕES NO CICLO".encode(), body)
        self.assertIn("CONCLUÍDAS NO CICLO".encode(), body)
        self.assertIn("Onde a ação deve acontecer?".encode(), body)
        self.assertIn("SBSJ · São José dos Campos".encode(), body)
        self.assertIn("SDAM · Campo dos Amarais — Campinas".encode(), body)
        self.assertIn("Geral · Duas bases ou CCO".encode(), body)
        self.assertIn(b'id="aircraftFleetFilter"', body)
        self.assertIn(b'id="aircraftFleetStatus"', body)
        self.assertIn("<th>Ações</th>".encode(), body)
        self.assertIn(b'id="unreviewedRulesTab"', body)
        self.assertIn(b'id="pendingApprovalRulesTab"', body)
        self.assertNotIn(b'data-view="instrutores"', body)
        self.assertNotIn(b'id="instructorsView"', body)
        self.assertNotIn(b'id="instructorDialog"', body)
        self.assertNotIn(b'data-help-target="instrutores"', body)
        self.assertIn(b'data-view="atividade"', body)
        self.assertIn(b'id="activityView"', body)
        self.assertIn(b'id="activityRows"', body)
        self.assertIn("Acessos e atividade de uso monitorados".encode(), body)

    def test_static_portal_contains_standard_messages_section(self):
        status, _, body = self.request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn(b'data-view="mensagens-padrao"', body)
        self.assertIn(b'id="standardMessagesView"', body)
        self.assertIn(b'id="addStandardMessage"', body)
        self.assertIn(b'id="standardMessageSearch"', body)
        self.assertIn(b'id="standardMessageCategoryFilter"', body)
        self.assertIn(b'id="standardMessageDialog"', body)
        self.assertIn(b'id="standardMessageCategory"', body)
        self.assertIn(b'id="deleteStandardMessage"', body)
        self.assertIn("Mensagens padrão de gerência".encode(), body)

    def test_handover_timeline_route_returns_full_history_and_404s_on_unknown_id(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            central = root / "portalcco.db"
            for name in (
                "PORTAL_DB_PATH", "AUTH_DB_PATH", "BASES_DB_PATH",
                "INSTRUCTORS_DB_PATH", "AIRCRAFT_DB_PATH", "HANDOVERS_DB_PATH",
                "REPORTS_DB_PATH", "SEARCH_HISTORY_DB_PATH", "RULES_DB_PATH",
                "LEARNING_DB_PATH", "STANDARD_MESSAGES_DB_PATH",
            ):
                stack.enter_context(patch.object(server, name, central))
            stack.enter_context(patch.object(
                server,
                "LEGACY_DB_PATHS",
                {name: root / f"legacy-{name}.db" for name in server.LEGACY_DB_PATHS},
            ))
            stack.enter_context(patch.object(server, "LEARNING_GRAPH_PATH", root / "missing.json"))

            server.initialize_portal_storage()
            server.create_user({
                "username": "admin", "display_name": "Admin", "password": "admin",
            }, force_admin=True)

            status, headers, body = self.request("/api/auth/login", "POST", {
                "username": "admin", "password": "admin",
            })
            self.assertEqual(status, "200 OK")
            login = json.loads(body)
            authenticated_headers = {
                "Cookie": headers["Set-Cookie"].split(";", 1)[0],
                "X-CSRF-Token": login["csrf_token"],
            }

            status, _, body = self.request("/api/handovers", "POST", {
                "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                "item_type": "Pendência", "message": "Checar combustível", "priority": "Normal",
            }, authenticated_headers)
            self.assertEqual(status, "201 Created", body.decode("utf-8"))
            item_id = json.loads(body)["id"]

            status, _, body = self.request(
                f"/api/handovers/{item_id}/timeline", request_headers=authenticated_headers,
            )
            self.assertEqual(status, "200 OK", body.decode("utf-8"))
            timeline = json.loads(body)
            self.assertEqual(timeline["root_item_id"], item_id)
            self.assertEqual(len(timeline["occurrences"]), 1)
            self.assertTrue(any(event["action"] == "Item criado" for event in timeline["events"]))

            status, _, body = self.request(
                "/api/handovers/999999/timeline", request_headers=authenticated_headers,
            )
            self.assertEqual(status, "404 Not Found", body.decode("utf-8"))

    def test_temporary_password_and_first_writes_through_wsgi(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            central = root / "portalcco.db"
            for name in (
                "PORTAL_DB_PATH", "AUTH_DB_PATH", "BASES_DB_PATH",
                "INSTRUCTORS_DB_PATH", "AIRCRAFT_DB_PATH", "HANDOVERS_DB_PATH",
                "REPORTS_DB_PATH", "SEARCH_HISTORY_DB_PATH", "RULES_DB_PATH",
                "LEARNING_DB_PATH",
            ):
                stack.enter_context(patch.object(server, name, central))
            stack.enter_context(patch.object(
                server,
                "LEGACY_DB_PATHS",
                {name: root / f"legacy-{name}.db" for name in server.LEGACY_DB_PATHS},
            ))
            stack.enter_context(patch.object(server, "LEARNING_GRAPH_PATH", root / "missing.json"))

            server.initialize_portal_storage()
            server.create_user({
                "username": "admin", "display_name": "Admin", "password": "admin",
            }, force_admin=True)
            server.create_user({
                "username": "supervisor", "display_name": "Supervisor", "password": "temporaria",
                "role": "supervisor",
            })

            status, headers, body = self.request("/api/auth/login", "POST", {
                "username": "supervisor", "password": "temporaria",
            })
            self.assertEqual(status, "200 OK")
            login = json.loads(body)
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            authenticated_headers = {
                "Cookie": cookie,
                "X-CSRF-Token": login["csrf_token"],
            }
            self.assertTrue(login["user"]["must_change_password"])

            status, _, body = self.request(
                "/api/auth/change-password",
                "POST",
                {"current_password": "temporaria", "new_password": "nova"},
                authenticated_headers,
            )
            self.assertEqual(status, "200 OK", json.loads(body))

            status, _, body = self.request(
                "/api/activity/ping", "POST", {"area": "Passagem de turno"}, authenticated_headers
            )
            self.assertEqual(status, "200 OK", json.loads(body))
            status, _, body = self.request("/api/activity", request_headers=authenticated_headers)
            self.assertEqual(status, "200 OK", body.decode("utf-8"))
            activity = json.loads(body)
            self.assertEqual(activity["online_count"], 1)
            self.assertEqual(activity["items"][0]["display_name"], "Supervisor")

            first_records = (
                ("/api/handovers", {
                    "origin_shift": "T1", "target_shift": "T2",
                    "base_scope": "Geral", "item_type": "Pendência",
                    "message": "Primeira passagem", "priority": "Normal",
                    "status": "Pendente", "author": "Supervisor",
                }),
                ("/api/reports", {
                    "report_type": "discrepancy", "title": "Primeiro report",
                    "description": "Descrição da primeira discrepância.",
                    "reference": "", "priority": "Normal",
                }),
                ("/api/reports", {
                    "report_type": "question", "title": "Primeira indicação",
                    "description": "Pergunta sugerida para a base de conhecimento.",
                    "reference": "Qual regra se aplica neste cenário?", "priority": "Normal",
                }),
                ("/api/instructors", {
                    "name": "Instrutor Teste", "base": "SJK",
                    "group": "INVA", "releases": [],
                }),
                ("/api/aircraft", {
                    "model": "Aeronave Teste", "registration": "PT-TST", "base": "SJK",
                    "fleet_status": "Inativa",
                    "status": "Operacional", "operation_type": "VFR",
                    "active_restrictions": "Nenhuma",
                    "temporary_restrictions": "Nenhuma", "restriction_date": "",
                }),
            )
            for path, payload in first_records:
                status, _, body = self.request(path, "POST", payload, authenticated_headers)
                self.assertEqual(status, "201 Created", f"{path}: {body.decode('utf-8')}")
                if path == "/api/aircraft":
                    self.assertEqual(json.loads(body)["fleet_status"], "Inativa")

    def test_secure_initial_setup_through_wsgi(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "auth.db"
        ), patch.object(server, "REQUIRE_SETUP_TOKEN", True), patch.object(
            server, "SETUP_TOKEN", "codigo-de-implantacao"
        ):
            status, _, body = self.request("/api/auth/setup", "POST", {
                "username": "admin.cco",
                "display_name": "Administrador CCO",
                "password": "senha",
                "setup_token": "incorreto",
            })
            self.assertEqual(status, "401 Unauthorized")
            self.assertIn("inválido", json.loads(body)["error"])

            status, _, body = self.request("/api/auth/setup", "POST", {
                "username": "admin.cco",
                "display_name": "Administrador CCO",
                "password": "senha",
                "setup_token": "codigo-de-implantacao",
            })
            self.assertEqual(status, "201 Created")
            self.assertEqual(json.loads(body)["user"]["role"], "admin")


class OperationalStorageTests(unittest.TestCase):
    def test_existing_aircraft_table_adds_fleet_status_without_losing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aircraft.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("""CREATE TABLE aircraft (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    registration TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    base TEXT NOT NULL,
                    operational_status TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    active_restrictions TEXT NOT NULL,
                    temporary_restrictions TEXT NOT NULL,
                    restriction_date TEXT,
                    updated_at TEXT NOT NULL
                )""")
                connection.execute(
                    """INSERT INTO aircraft(
                       model, registration, base, operational_status, operation_type,
                       active_restrictions, temporary_restrictions, restriction_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "Aeronave legada", "PT-OLD", "SJK", "Inativa", "VFR",
                        "Nenhuma", "Nenhuma", None, "2026-01-01T00:00:00+00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            with patch.object(server, "AIRCRAFT_DB_PATH", path):
                items = server.list_aircraft()

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["fleet_status"], "Inativa")
            self.assertEqual(items[0]["status"], "Fora de Operação")

    def test_search_history_reopens_saved_presentation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "SEARCH_HISTORY_DB_PATH", Path(directory) / "history.db"
        ):
            record_id = server.save_search_history(
                "Pergunta", "local", "low",
                presentation={"question": "Pergunta", "answer": "Resposta salva"},
            )
            detail = server.get_search_history(record_id)
            self.assertEqual(detail["presentation"]["answer"], "Resposta salva")
            self.assertEqual(server.list_search_history()[0]["id"], record_id)


class StandardMessagesStorageTests(unittest.TestCase):
    def test_seeds_default_messages_on_first_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "STANDARD_MESSAGES_DB_PATH", Path(directory) / "standard_messages.db"
        ):
            items = server.list_standard_messages()
            self.assertEqual(len(items), len(server.STANDARD_MESSAGE_SEED))
            categories = {item["category"] for item in items}
            self.assertTrue(categories.issubset(set(server.STANDARD_MESSAGE_CATEGORIES)))
            self.assertTrue(any("operacoes@voesafe.com.br" in item["body"] for item in items))

    def test_save_update_and_delete_round_trip(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "STANDARD_MESSAGES_DB_PATH", Path(directory) / "standard_messages.db"
        ):
            created = server.save_standard_message({
                "category": "Escala/Slots", "title": "Teste", "body": "Corpo de teste",
            })
            self.assertEqual(created["category"], "Escala/Slots")
            self.assertTrue(created["active"])

            updated = server.save_standard_message({
                "category": "Escala/Slots", "title": "Teste editado", "body": "Corpo editado",
            }, created["id"])
            self.assertEqual(updated["title"], "Teste editado")

            server.delete_standard_message(created["id"])
            remaining_ids = {item["id"] for item in server.list_standard_messages()}
            self.assertNotIn(created["id"], remaining_ids)

    def test_rejects_invalid_category(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "STANDARD_MESSAGES_DB_PATH", Path(directory) / "standard_messages.db"
        ):
            with self.assertRaises(ValueError):
                server.save_standard_message({
                    "category": "Categoria inexistente", "title": "Teste", "body": "Corpo",
                })

    def test_update_of_missing_message_raises_lookup_error(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "STANDARD_MESSAGES_DB_PATH", Path(directory) / "standard_messages.db"
        ):
            with self.assertRaises(LookupError):
                server.save_standard_message({
                    "category": "Escala/Slots", "title": "Teste", "body": "Corpo",
                }, 999999)


class ConsolidatedStorageTests(unittest.TestCase):
    def test_central_database_uses_network_filesystem_safe_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portalcco.db"
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold(),
                    "wal",
                )
            finally:
                connection.close()

            server.configure_database(path)

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0].casefold(),
                    "delete",
                )
            finally:
                connection.close()

    def test_all_default_operational_paths_use_single_database(self):
        self.assertEqual({
            server.AUTH_DB_PATH,
            server.BASES_DB_PATH,
            server.INSTRUCTORS_DB_PATH,
            server.AIRCRAFT_DB_PATH,
            server.HANDOVERS_DB_PATH,
            server.REPORTS_DB_PATH,
            server.SEARCH_HISTORY_DB_PATH,
            server.RULES_DB_PATH,
            server.LEARNING_DB_PATH,
            server.STANDARD_MESSAGES_DB_PATH,
        }, {server.PORTAL_DB_PATH})

    def test_initialization_migrates_all_legacy_stores_without_deleting_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = {
                name: root / f"{name}.db"
                for name in (
                    "auth", "search_history", "rules", "bases", "handovers",
                    "reports", "instructors", "aircraft",
                )
            }
            with patch.object(server, "AUTH_DB_PATH", legacy["auth"]):
                server.create_user({
                    "username": "admin.legado",
                    "display_name": "Administrador Legado",
                    "password": "senha",
                }, force_admin=True)
            with patch.object(server, "BASES_DB_PATH", legacy["bases"]):
                server.initialize_bases_db()
            with patch.object(server, "INSTRUCTORS_DB_PATH", legacy["instructors"]):
                server.initialize_instructors_db()
            with patch.object(server, "AIRCRAFT_DB_PATH", legacy["aircraft"]):
                server.initialize_aircraft_db()
            with patch.object(server, "HANDOVERS_DB_PATH", legacy["handovers"]):
                server.initialize_handovers_db()
                server.save_handover({
                    "origin_shift": "T1",
                    "target_shift": "T2",
                    "base_scope": "Geral",
                    "item_type": "Pendência",
                    "message": "Pendência legada",
                    "priority": "Alta",
                    "status": "Pendente",
                    "author": "Operador Legado",
                })
            with patch.object(server, "REPORTS_DB_PATH", legacy["reports"]):
                server.initialize_reports_db()
                server.create_report({
                    "report_type": "discrepancy",
                    "title": "Report legado",
                    "description": "Descrição do report legado.",
                    "priority": "Normal",
                }, {
                    "id": 1,
                    "username": "admin.legado",
                    "display_name": "Administrador Legado",
                    "role": "admin",
                })
            with patch.object(server, "SEARCH_HISTORY_DB_PATH", legacy["search_history"]):
                server.save_search_history(
                    "Pesquisa legada", "local", "medium",
                    presentation={"answer": "Resposta legada"},
                )
            with patch.object(server, "RULES_DB_PATH", legacy["rules"]):
                server.upsert_rule_candidate(
                    "Pergunta legada", "Proposta legada", "low", "unanswered",
                    [], [], {"username": "admin.legado", "display_name": "Administrador Legado"},
                )

            legacy_graph = root / "query_graph.json"
            legacy_graph.write_text(json.dumps({
                "schema_version": 1,
                "nodes": [{
                    "id": "query_legacy",
                    "type": "operator_question",
                    "label": "Pergunta aprendida legada",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }],
                "edges": [{
                    "source": "query_legacy",
                    "target": "claim_legacy",
                    "relation": "answered_using",
                    "status": "observed",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }],
                "candidate_relations": [],
            }), encoding="utf-8")

            central = root / "portalcco.db"
            path_patches = [
                patch.object(server, name, central)
                for name in (
                    "PORTAL_DB_PATH", "AUTH_DB_PATH", "BASES_DB_PATH",
                    "INSTRUCTORS_DB_PATH", "AIRCRAFT_DB_PATH", "HANDOVERS_DB_PATH",
                    "REPORTS_DB_PATH", "SEARCH_HISTORY_DB_PATH", "RULES_DB_PATH",
                    "LEARNING_DB_PATH",
                )
            ]
            for item in path_patches:
                item.start()
            try:
                with patch.object(server, "LEGACY_DB_PATHS", legacy), patch.object(
                    server, "LEARNING_GRAPH_PATH", legacy_graph
                ), patch.object(
                    server, "RULES_CATALOG_PATH", root / "catalogo-inexistente.json"
                ):
                    server.initialize_portal_storage()
                    server.initialize_portal_storage()
            finally:
                for item in reversed(path_patches):
                    item.stop()

            connection = sqlite3.connect(central)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT display_name FROM users WHERE username='admin.legado'"
                    ).fetchone()[0],
                    "Administrador Legado",
                )
                self.assertGreater(connection.execute("SELECT COUNT(*) FROM instructors").fetchone()[0], 0)
                self.assertGreater(connection.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM bases").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM handovers").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM search_history").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM rule_candidates").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM learning_queries").fetchone()[0], 1)
                self.assertGreaterEqual(
                    connection.execute("SELECT COUNT(*) FROM storage_migrations").fetchone()[0], 11
                )
            finally:
                connection.close()
            self.assertTrue(all(path.exists() for path in legacy.values()))
            self.assertTrue(legacy_graph.exists())


class HandoverWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.original_scheduled_handover_shift = server.scheduled_handover_shift
        self.scheduled_shift_patch = patch.object(
            server, "scheduled_handover_shift", lambda moment=None: "T1"
        )
        self.scheduled_shift_patch.start()
        self.addCleanup(self.scheduled_shift_patch.stop)
        self.operator = {
            "id": 11,
            "username": "operador.teste",
            "display_name": "Operador Teste",
            "role": "operator",
        }

    def test_new_item_requires_explicit_base_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                with self.assertRaisesRegex(ValueError, "Selecione Geral, SDAM ou SBSJ"):
                    server.save_handover({
                        "origin_shift": "T1", "target_shift": "T2",
                        "item_type": "Pendência", "message": "Confirmar a ação operacional",
                        "priority": "Normal",
                    }, actor=self.operator)

    def test_legacy_rows_are_preserved_and_classified_as_general(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            connection = sqlite3.connect(database)
            connection.execute("""CREATE TABLE handovers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin_shift TEXT NOT NULL, target_shift TEXT NOT NULL,
                message TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL,
                author TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                completed_at TEXT
            )""")
            connection.executemany(
                """INSERT INTO handovers(
                   origin_shift,target_shift,message,priority,status,author,
                   created_at,updated_at,completed_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    ("T1", "T2", "Registro antigo A", "Normal", "Pendente", "Ana", "2026-08-17T12:00:00+00:00", "2026-08-17T12:00:00+00:00", None),
                    ("T1", "T2", "Registro antigo B", "Alta", "Concluída", "Bruno", "2026-08-17T12:10:00+00:00", "2026-08-17T13:00:00+00:00", "2026-08-17T13:00:00+00:00"),
                ],
            )
            connection.commit()
            connection.close()
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                server.initialize_handovers_db()
                result = server.list_handover_cycles()
            self.assertEqual(sum(len(cycle["items"]) for cycle in result["cycles"]), 2)
            self.assertTrue(all(item["base_scope"] == "Geral" for item in result["cycles"][0]["items"]))
            self.assertEqual({item["message"] for item in result["cycles"][0]["items"]}, {"Registro antigo A", "Registro antigo B"})

    def test_pending_carries_forward_but_information_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                pending = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "SDAM",
                    "item_type": "Pendência", "message": "Resolver slot", "priority": "Alta",
                }, actor=self.operator)
                information = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "SBSJ",
                    "item_type": "Informação", "message": "Escala já fechada", "priority": "Normal",
                }, actor=self.operator)
                cycle_id = pending["cycle_id"]
                server.publish_handover_cycle(cycle_id, self.operator)
                with self.assertRaises(ValueError):
                    server.save_handover({
                        **pending, "message": "Tentativa de alterar conteúdo publicado",
                    }, pending["id"], actor=self.operator)
                server.receive_handover_cycle(cycle_id, self.operator)
                server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Novo turno iniciado", "priority": "Normal",
                }, actor=self.operator)
                result = server.list_handover_cycles()
                draft = next(cycle for cycle in result["cycles"] if cycle["state"] == "draft")
                carried = [item for item in draft["items"] if item["carried_from_id"]]
                self.assertEqual(len(carried), 1)
                self.assertEqual(carried[0]["message"], "Resolver slot")
                self.assertEqual(carried[0]["base_scope"], "SDAM")
                self.assertNotIn(information["id"], [item["carried_from_id"] for item in draft["items"]])
                active_messages = [item["message"] for item in result["active_tickets"]]
                self.assertEqual(active_messages.count("Resolver slot"), 1)
                self.assertIn("Escala já fechada", active_messages)
                self.assertIn("Novo turno iniciado", active_messages)
                self.assertEqual(result["active_ticket_summary"], {
                    "pending": 1, "in_progress": 0, "information": 2, "total": 3,
                })
                server.transition_handover_item(carried[0]["id"], {
                    "action": "complete", "note": "Slot confirmado com o aluno.",
                }, self.operator)
                final = server.list_handover_cycles()
                self.assertEqual(final["summary"]["pending"], 0)
                self.assertEqual(final["summary"]["completed"], 1)
                self.assertEqual(
                    {item["message"] for item in final["active_tickets"]},
                    {"Escala já fechada", "Novo turno iniciado"},
                )

    def test_assume_is_rejected_once_item_is_no_longer_pendente(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                item = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Verificar combustível", "priority": "Normal",
                }, actor=self.operator)
                server.transition_handover_item(item["id"], {"action": "assume"}, self.operator)
                with self.assertRaisesRegex(ValueError, "não está mais pendente"):
                    server.transition_handover_item(item["id"], {"action": "assume"}, self.operator)
                current = server.list_handover_cycles()
                saved_item = next(
                    i for cycle in current["cycles"] for i in cycle["items"] if i["id"] == item["id"]
                )
                self.assertEqual(saved_item["status"], "Em andamento")
                self.assertEqual(saved_item["assignee"], self.operator["display_name"])

    def test_ticket_id_and_carry_count_survive_carry_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                original = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Revisar checklist", "priority": "Alta",
                }, actor=self.operator)
                server.publish_handover_cycle(original["cycle_id"], self.operator)
                server.receive_handover_cycle(original["cycle_id"], self.operator)
                server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Início do turno", "priority": "Normal",
                }, actor=self.operator)
                result = server.list_handover_cycles()
                all_items = [i for cycle in result["cycles"] for i in cycle["items"]]
                carried = next(i for i in all_items if i.get("carried_from_id") == original["id"])
                historical = next(i for i in all_items if i["id"] == original["id"])
                self.assertEqual(carried["ticket_id"], original["id"])
                self.assertEqual(historical["ticket_id"], original["id"])
                self.assertEqual(carried["carry_count"], 1)
                self.assertEqual(historical["carry_count"], 1)
                self.assertEqual(carried["first_created_at"], original["created_at"])
                projected = [
                    item for item in result["active_tickets"]
                    if item["ticket_id"] == original["id"]
                ]
                self.assertEqual(len(projected), 1)
                self.assertEqual(projected[0]["id"], carried["id"])
                self.assertEqual(projected[0]["cycle_state"], "draft")

    def test_shift_mismatch_flag_reflects_clock_vs_last_received(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                item = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Turno iniciado", "priority": "Normal",
                }, actor=self.operator)
                server.publish_handover_cycle(item["cycle_id"], self.operator)
                server.receive_handover_cycle(item["cycle_id"], self.operator)

                with patch.object(server, "scheduled_handover_shift", lambda moment=None: "T2"), \
                     patch.object(server, "is_within_cco_operational_hours", lambda moment=None: True):
                    result = server.list_handover_cycles()
                self.assertFalse(result["operational_shift_mismatch"])

                with patch.object(server, "scheduled_handover_shift", lambda moment=None: "T3"), \
                     patch.object(server, "is_within_cco_operational_hours", lambda moment=None: True):
                    result = server.list_handover_cycles()
                self.assertTrue(result["operational_shift_mismatch"])
                self.assertEqual(result["operational_shift_scheduled"], "T3")
                self.assertEqual(result["operational_shift"], "T2")

                # Outside CCO operating hours, the same disagreement is not an error.
                with patch.object(server, "scheduled_handover_shift", lambda moment=None: "T3"), \
                     patch.object(server, "is_within_cco_operational_hours", lambda moment=None: False):
                    result = server.list_handover_cycles()
                self.assertFalse(result["operational_shift_mismatch"])

                server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Nova passagem em elaboração", "priority": "Normal",
                }, actor=self.operator)
                with patch.object(server, "scheduled_handover_shift", lambda moment=None: "T1"), \
                     patch.object(server, "is_within_cco_operational_hours", lambda moment=None: True):
                    result = server.list_handover_cycles()
                self.assertFalse(result["operational_shift_mismatch"])

    def test_scheduled_handover_shift_matches_its_own_displayed_window(self):
        base = datetime(2026, 8, 28, tzinfo=timezone.utc)
        brasilia = timezone(timedelta(hours=-3))
        cases = [
            (8, 0, "T1"), (13, 59, "T1"),
            (14, 0, "T2"), (17, 59, "T2"),
            (18, 0, "T3"), (19, 59, "T3"),
            (20, 0, "T1"), (23, 30, "T1"), (2, 0, "T1"), (7, 59, "T1"),
        ]
        with patch.object(server, "scheduled_handover_shift", self.original_scheduled_handover_shift):
            for hour, minute, expected in cases:
                moment = base.replace(hour=hour, minute=minute, tzinfo=brasilia).astimezone(timezone.utc)
                self.assertEqual(
                    server.scheduled_handover_shift(moment), expected,
                    f"esperado {expected} às {hour:02d}:{minute:02d}",
                )

    def test_operational_hours_window_excludes_overnight(self):
        brasilia = timezone(timedelta(hours=-3))
        within = datetime(2026, 8, 28, 12, 0, tzinfo=brasilia).astimezone(timezone.utc)
        outside = datetime(2026, 8, 28, 22, 0, tzinfo=brasilia).astimezone(timezone.utc)
        self.assertTrue(server.is_within_cco_operational_hours(within))
        self.assertFalse(server.is_within_cco_operational_hours(outside))

    def test_item_timeline_aggregates_occurrences_and_events(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                original = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Checar pneu", "priority": "Normal",
                }, actor=self.operator)
                server.transition_handover_item(original["id"], {"action": "assume"}, self.operator)
                server.transition_handover_item(original["id"], {
                    "action": "complete", "note": "Pneu verificado.",
                }, self.operator)
                server.publish_handover_cycle(original["cycle_id"], self.operator)
                server.receive_handover_cycle(original["cycle_id"], self.operator)
                server.transition_handover_item(original["id"], {
                    "action": "reopen", "note": "Voltou a apresentar desgaste.",
                    "origin_shift": "T2", "target_shift": "T3",
                }, self.operator)

                timeline = server.handover_item_timeline(original["id"])
                self.assertEqual(timeline["root_item_id"], original["id"])
                self.assertEqual(len(timeline["occurrences"]), 2)
                self.assertEqual(timeline["carry_count"], 1)
                actions = {event["action"] for event in timeline["events"]}
                self.assertIn("Pendência assumida", actions)
                self.assertIn("Pendência concluída", actions)
                self.assertIn("Pendência reaberta no ciclo atual", actions)

                with self.assertRaises(LookupError):
                    server.handover_item_timeline(999999)

    def test_summary_pending_counts_items_stuck_in_cancelled_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                stuck = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Item preso em rascunho cancelado",
                    "priority": "Normal",
                }, actor=self.operator)
                server.cancel_handover_cycle(stuck["cycle_id"], self.operator)

                other = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Item novo e independente",
                    "priority": "Normal",
                }, actor=self.operator)

                result = server.list_handover_cycles()
                self.assertEqual(result["summary"]["pending"], 2)
                ticket_ids = {item["ticket_id"] for item in result["active_tickets"]}
                self.assertIn(stuck["id"], ticket_ids)
                self.assertIn(other["id"], ticket_ids)

    def test_active_cycle_flagged_stale_after_long_inactivity(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                item = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Turno iniciado", "priority": "Normal",
                }, actor=self.operator)
                result = server.list_handover_cycles()
                self.assertFalse(result["operational_shift_mismatch"])
                self.assertFalse(result["operational_shift_stale"])

                stale_timestamp = (
                    datetime.now(timezone.utc) - timedelta(hours=server.STALE_ACTIVE_CYCLE_HOURS + 1)
                ).isoformat()
                with server.handovers_connection() as connection:
                    connection.execute(
                        "UPDATE handover_cycles SET updated_at=? WHERE id=?",
                        (stale_timestamp, item["cycle_id"]),
                    )
                    connection.commit()

                result = server.list_handover_cycles()
                self.assertTrue(result["operational_shift_mismatch"])
                self.assertTrue(result["operational_shift_stale"])

    def test_information_items_can_be_resolved_and_reopened_but_not_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                info = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Verificar disponibilidade de instrutores",
                    "priority": "Normal",
                }, actor=self.operator)
                initial = server.list_handover_cycles()
                self.assertEqual([item["id"] for item in initial["active_tickets"]], [info["id"]])

                with self.assertRaisesRegex(ValueError, "só podem ser comentadas ou marcadas como resolvidas"):
                    server.transition_handover_item(info["id"], {"action": "assume"}, self.operator)

                with self.assertRaisesRegex(ValueError, "Registre uma observação"):
                    server.transition_handover_item(info["id"], {"action": "resolve"}, self.operator)

                resolved = server.transition_handover_item(info["id"], {
                    "action": "resolve", "note": "Confirmado com os dois instrutores.",
                }, self.operator)
                self.assertEqual(resolved["completed_by"], self.operator["display_name"])
                self.assertEqual(resolved["completion_note"], "Confirmado com os dois instrutores.")
                self.assertIsNotNone(resolved["completed_at"])
                self.assertEqual(server.list_handover_cycles()["active_tickets"], [])

                with self.assertRaisesRegex(ValueError, "já foi marcada como resolvida"):
                    server.transition_handover_item(info["id"], {
                        "action": "resolve", "note": "De novo.",
                    }, self.operator)

                reopened = server.transition_handover_item(info["id"], {
                    "action": "unresolve", "note": "Precisa reconfirmar após mudança de escala.",
                }, self.operator)
                self.assertEqual(reopened["completion_note"], "")
                self.assertIsNone(reopened["completed_at"])
                reopened_projection = server.list_handover_cycles()["active_tickets"]
                self.assertEqual([item["id"] for item in reopened_projection], [info["id"]])

                pending = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Trocar pneu", "priority": "Normal",
                }, actor=self.operator)
                with self.assertRaisesRegex(ValueError, "Use concluir ou reabrir"):
                    server.transition_handover_item(pending["id"], {
                        "action": "resolve", "note": "Tentativa indevida.",
                    }, self.operator)

    def test_open_information_remains_projected_after_its_cycle_leaves_history_window(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                original = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "SBSJ",
                    "item_type": "Informação", "message": "Acompanhar manutenção prolongada",
                    "priority": "Alta",
                }, actor=self.operator)
                server.publish_handover_cycle(original["cycle_id"], self.operator)
                server.receive_handover_cycle(original["cycle_id"], self.operator)
                origin = "T2"
                for index in range(server.HANDOVER_HISTORY_LIMIT + 2):
                    target = server.next_handover_shift(origin)
                    helper = server.save_handover({
                        "origin_shift": origin, "target_shift": target, "base_scope": "Geral",
                        "item_type": "Informação", "message": f"Ciclo auxiliar {index}",
                        "priority": "Baixa",
                    }, actor=self.operator)
                    server.transition_handover_item(helper["id"], {
                        "action": "resolve", "note": "Ciclo encerrado para o teste.",
                    }, self.operator)
                    server.publish_handover_cycle(helper["cycle_id"], self.operator)
                    server.receive_handover_cycle(helper["cycle_id"], self.operator)
                    origin = target

                result = server.list_handover_cycles()
                returned_cycle_ids = {cycle["id"] for cycle in result["cycles"]}
                self.assertNotIn(original["cycle_id"], returned_cycle_ids)
                self.assertEqual(len(result["active_tickets"]), 1)
                self.assertEqual(result["active_tickets"][0]["id"], original["id"])
                self.assertEqual(result["active_ticket_summary"]["total"], 1)

    def test_new_ticket_uses_operational_shift_and_authenticated_operator(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                ticket = server.save_handover({
                    "origin_shift": "T3", "target_shift": "T1", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Conferir escala",
                    "priority": "Normal", "assignee": "Nome informado pelo navegador",
                }, actor=self.operator)

                self.assertEqual(ticket["origin_shift"], "T1")
                self.assertEqual(ticket["target_shift"], "T2")
                self.assertEqual(ticket["assignee"], self.operator["display_name"])

                updated_cycle = server.update_handover_cycle_target(
                    ticket["cycle_id"], "T3", self.operator
                )
                self.assertEqual(updated_cycle["target_shift"], "T3")
                self.assertEqual(updated_cycle["route_kind"], "skip")
                self.assertEqual(updated_cycle["skipped_shifts"], ["T2"])
                self.assertTrue(all(
                    item["target_shift"] == "T3" for item in updated_cycle["items"]
                ))

                second = server.save_handover({
                    "base_scope": "SBSJ", "item_type": "Informação",
                    "message": "Ticket adicional", "priority": "Baixa",
                }, actor=self.operator)
                self.assertEqual(second["cycle_id"], ticket["cycle_id"])
                self.assertEqual(second["origin_shift"], "T1")
                self.assertEqual(second["target_shift"], "T3")
                self.assertEqual(second["assignee"], self.operator["display_name"])

    def test_summary_is_scoped_to_the_active_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                completed = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "SDAM",
                    "item_type": "Pendência", "message": "Finalizar coordenação", "priority": "Alta",
                }, actor=self.operator)
                server.transition_handover_item(completed["id"], {
                    "action": "complete", "note": "Coordenação finalizada.",
                }, self.operator)
                server.publish_handover_cycle(completed["cycle_id"], self.operator)
                server.receive_handover_cycle(completed["cycle_id"], self.operator)
                current = server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Operação normal", "priority": "Normal",
                }, actor=self.operator)

                result = server.list_handover_cycles()

                self.assertEqual(result["active_cycle_id"], current["cycle_id"])
                self.assertEqual(result["history_total"], 1)
                self.assertEqual(result["summary"], {
                    "pending": 0, "in_progress": 0, "completed": 0, "information": 1,
                })
                self.assertTrue(next(
                    cycle for cycle in result["cycles"] if cycle["id"] == current["cycle_id"]
                )["is_active"])

    def test_reopening_historical_item_creates_an_occurrence_in_active_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                original = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "SBSJ",
                    "item_type": "Pendência", "message": "Confirmar abastecimento", "priority": "Crítica",
                }, actor=self.operator)
                server.transition_handover_item(original["id"], {
                    "action": "complete", "note": "Abastecimento confirmado.",
                }, self.operator)
                server.publish_handover_cycle(original["cycle_id"], self.operator)
                server.receive_handover_cycle(original["cycle_id"], self.operator)
                current = server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Novo ciclo", "priority": "Normal",
                }, actor=self.operator)

                reopened = server.transition_handover_item(original["id"], {
                    "action": "reopen", "note": "Foi identificada uma nova divergência.",
                    "origin_shift": "T2", "target_shift": "T3",
                }, self.operator)

                self.assertNotEqual(reopened["id"], original["id"])
                self.assertEqual(reopened["cycle_id"], current["cycle_id"])
                self.assertEqual(reopened["status"], "Pendente")
                self.assertEqual(reopened["carried_from_id"], original["id"])
                self.assertEqual(reopened["root_item_id"], original["root_item_id"])
                with server.handovers_connection() as connection:
                    stored_original = connection.execute(
                        "SELECT status, completion_note FROM handovers WHERE id=?", (original["id"],)
                    ).fetchone()
                    event = connection.execute(
                        "SELECT action FROM handover_events WHERE item_id=? ORDER BY id DESC LIMIT 1",
                        (reopened["id"],),
                    ).fetchone()
                self.assertEqual(stored_original["status"], "Concluída")
                self.assertEqual(stored_original["completion_note"], "Abastecimento confirmado.")
                self.assertEqual(event["action"], "Pendência reaberta no ciclo atual")
                current_state = server.list_handover_cycles()
                self.assertEqual(current_state["summary"]["pending"], 1)
                projected = [
                    item for item in current_state["active_tickets"]
                    if item["ticket_id"] == original["id"]
                ]
                self.assertEqual(len(projected), 1)
                self.assertEqual(projected[0]["id"], reopened["id"])

    def test_operational_shift_follows_received_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                first = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Operação do T1 concluída",
                    "priority": "Normal",
                }, actor=self.operator)
                server.publish_handover_cycle(first["cycle_id"], self.operator)
                server.receive_handover_cycle(first["cycle_id"], self.operator)

                state = server.list_handover_cycles()

                self.assertEqual(state["operational_shift"], "T2")
                self.assertEqual(state["operational_shift_source"], "last_received_cycle")
                self.assertEqual(state["suggested_route"], {
                    "origin_shift": "T2", "target_shift": "T3",
                })
                current = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T1", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Ticket do turno atual",
                    "priority": "Normal",
                }, actor=self.operator)
                self.assertEqual(current["origin_shift"], "T2")
                self.assertEqual(current["target_shift"], "T3")

    def test_skipping_a_shift_is_allowed_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                first = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Primeiro ciclo",
                    "priority": "Normal",
                }, actor=self.operator)
                server.publish_handover_cycle(first["cycle_id"], self.operator)
                server.receive_handover_cycle(first["cycle_id"], self.operator)
                skipped = server.save_handover({
                    "origin_shift": "T2", "target_shift": "T1", "base_scope": "SBSJ",
                    "item_type": "Pendência", "message": "Passagem direta para o T1",
                    "priority": "Alta",
                }, actor=self.operator)
                server.update_handover_cycle_target(skipped["cycle_id"], "T1", self.operator)

                state = server.list_handover_cycles()
                cycle = next(item for item in state["cycles"] if item["id"] == skipped["cycle_id"])
                self.assertEqual(cycle["route_kind"], "skip")
                self.assertEqual(cycle["expected_target_shift"], "T3")
                self.assertEqual(cycle["skipped_shifts"], ["T3"])
                with server.handovers_connection() as connection:
                    event = connection.execute(
                        """SELECT details FROM handover_events
                           WHERE cycle_id=? AND action='Salto de turno registrado'""",
                        (skipped["cycle_id"],),
                    ).fetchone()
                self.assertEqual(json.loads(event["details"])["skipped_shifts"], ["T3"])

    def test_cancelled_draft_is_preserved_without_advancing_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "handovers.db"
            legacy = {**server.LEGACY_DB_PATHS, "handovers": Path(directory) / "missing.db"}
            with patch.object(server, "HANDOVERS_DB_PATH", database), patch.object(server, "LEGACY_DB_PATHS", legacy):
                first = server.save_handover({
                    "origin_shift": "T1", "target_shift": "T2", "base_scope": "Geral",
                    "item_type": "Pendência", "message": "Pendência original",
                    "priority": "Normal",
                }, actor=self.operator)
                server.publish_handover_cycle(first["cycle_id"], self.operator)
                server.receive_handover_cycle(first["cycle_id"], self.operator)
                draft = server.save_handover({
                    "origin_shift": "T2", "target_shift": "T3", "base_scope": "SDAM",
                    "item_type": "Pendência", "message": "Rascunho preservado",
                    "priority": "Normal",
                }, actor=self.operator)

                cancelled = server.cancel_handover_cycle(draft["cycle_id"], self.operator)
                state = server.list_handover_cycles()

                self.assertEqual(cancelled["state"], "cancelled")
                self.assertIsNone(state["draft_cycle_id"])
                self.assertEqual(state["operational_shift"], "T2")
                replacement = server.save_handover({
                    "origin_shift": "T2", "target_shift": "T1", "base_scope": "Geral",
                    "item_type": "Informação", "message": "Novo ciclo após encerrar rascunho",
                    "priority": "Normal",
                }, actor=self.operator)
                self.assertNotEqual(replacement["cycle_id"], draft["cycle_id"])
                with server.handovers_connection() as connection:
                    preserved = connection.execute(
                        "SELECT message FROM handovers WHERE id=?", (draft["id"],)
                    ).fetchone()
                    carried = connection.execute(
                        """SELECT message, carried_from_id FROM handovers
                           WHERE cycle_id=? AND message='Pendência original'""",
                        (replacement["cycle_id"],),
                    ).fetchall()
                self.assertEqual(preserved["message"], "Rascunho preservado")
                self.assertEqual(len(carried), 1)
                self.assertEqual(carried[0]["carried_from_id"], first["id"])

    def test_schedule_fallback_uses_operational_utc_minus_three(self):
        with patch.object(
            server, "scheduled_handover_shift", self.original_scheduled_handover_shift
        ):
            self.assertEqual(
                server.scheduled_handover_shift(datetime(2026, 8, 22, 13, tzinfo=timezone.utc)),
                "T1",
            )
            self.assertEqual(
                server.scheduled_handover_shift(datetime(2026, 8, 22, 18, tzinfo=timezone.utc)),
                "T2",
            )
            self.assertEqual(
                server.scheduled_handover_shift(datetime(2026, 8, 22, 22, tzinfo=timezone.utc)),
                "T3",
            )


class ReportStorageTests(unittest.TestCase):
    def test_operator_creates_report_with_authenticated_identity_and_audit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "REPORTS_DB_PATH", Path(directory) / "reports.db"
        ), patch.object(server, "RULES_DB_PATH", Path(directory) / "rules.db"):
            operator = {
                "id": 17,
                "username": "operador.cco",
                "display_name": "Operador CCO",
                "role": "operator",
            }
            created = server.create_report({
                "report_type": "discrepancy",
                "title": "Fonte divergente",
                "description": "A resposta não corresponde ao procedimento vigente.",
                "reference": "Pergunta: exemplo operacional",
                "priority": "Alta",
                "reporter_name": "Nome forjado",
            }, operator)

            self.assertEqual(created["status"], "Aberto")
            self.assertEqual(created["reporter_name"], "Operador CCO")
            self.assertEqual(created["reporter_username"], "operador.cco")
            self.assertEqual(server.list_reports()[0]["id"], created["id"])
            with server.reports_connection() as connection:
                event = connection.execute(
                    "SELECT action, actor_username FROM report_events WHERE report_id=?",
                    (created["id"],),
                ).fetchone()
            self.assertEqual(event["action"], "Criado")
            self.assertEqual(event["actor_username"], "operador.cco")

    def test_closed_report_requires_resolution_and_records_management(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "REPORTS_DB_PATH", Path(directory) / "reports.db"
        ), patch.object(server, "RULES_DB_PATH", Path(directory) / "rules.db"):
            operator = {
                "id": 5,
                "username": "operador",
                "display_name": "Operador",
                "role": "operator",
            }
            supervisor = {
                "id": 8,
                "username": "supervisor",
                "display_name": "Supervisor",
                "role": "supervisor",
            }
            created = server.create_report({
                "report_type": "question",
                "title": "Nova pergunta recorrente",
                "description": "A equipe precisa desta orientação na base.",
                "priority": "Normal",
            }, operator)

            with self.assertRaises(ValueError):
                server.update_report(created["id"], {
                    "status": "Resolvido",
                    "priority": "Normal",
                    "resolution": "",
                }, supervisor)

            resolved = server.update_report(created["id"], {
                "status": "Resolvido",
                "priority": "Alta",
                "resolution": "Pergunta validada e encaminhada para publicação.",
            }, supervisor)
            self.assertEqual(resolved["status"], "Resolvido")
            self.assertEqual(resolved["priority"], "Alta")
            self.assertTrue(resolved["resolved_at"])
            with server.reports_connection() as connection:
                events = connection.execute(
                    "SELECT action, actor_username FROM report_events WHERE report_id=? ORDER BY id",
                    (created["id"],),
                ).fetchall()
            self.assertEqual([row["action"] for row in events], ["Criado", "Atualizado"])
            self.assertEqual(events[-1]["actor_username"], "supervisor")

            candidates = server.list_rule_candidates("pending_approval")
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["source_kind"], "operator_report")
            self.assertEqual(candidates[0]["proposed_answer"], "Pergunta validada e encaminhada para publicação.")

    def test_discarded_question_report_rejects_linked_candidate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "REPORTS_DB_PATH", Path(directory) / "portal.db"
        ), patch.object(server, "RULES_DB_PATH", Path(directory) / "portal.db"), patch.object(
            server, "AUTH_DB_PATH", Path(directory) / "portal.db"
        ):
            actor = {
                "id": 1, "username": "supervisor", "display_name": "Supervisor", "role": "supervisor",
            }
            created = server.create_report({
                "report_type": "question",
                "title": "Entrada digitada por engano",
                "description": "Conteúdo inválido.",
                "priority": "Normal",
            }, actor)
            self.assertIsNotNone(created["rule_candidate_id"])

            discarded = server.update_report(created["id"], {
                "status": "Descartado",
                "priority": "Normal",
                "resolution": "Registro criado por engano.",
                "rule_action": "no_rule",
            }, actor)

            self.assertEqual(discarded["rule_candidate"]["status"], "rejected")
            self.assertEqual(server.list_rule_candidates("unreviewed"), [])

    def test_report_supports_assignment_comments_attachments_and_author_edit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "PORTAL_DB_PATH", Path(directory) / "portal.db"
        ), patch.object(server, "REPORTS_DB_PATH", Path(directory) / "portal.db"), patch.object(
            server, "RULES_DB_PATH", Path(directory) / "portal.db"
        ), patch.object(server, "AUTH_DB_PATH", Path(directory) / "portal.db"):
            server.configure_database(Path(directory) / "portal.db")
            operator = {
                "id": 10, "username": "operador", "display_name": "Operador", "role": "operator",
            }
            supervisor = {
                "id": 20, "username": "supervisor", "display_name": "Supervisor", "role": "supervisor",
            }
            server.initialize_auth_db()
            with server.auth_connection() as connection:
                timestamp = server.now_iso()
                connection.execute(
                    """INSERT INTO users(id, username, display_name, password_hash, password_salt,
                       role, active, must_change_password, created_at, updated_at)
                       VALUES (20, 'supervisor', 'Supervisor', 'x', '00', 'supervisor', 1, 0, ?, ?)""",
                    (timestamp, timestamp),
                )
            created = server.create_report({
                "report_type": "discrepancy",
                "title": "Resposta incompleta",
                "description": "Falta uma condição operacional.",
                "priority": "Alta",
            }, operator)
            edited = server.update_own_report(created["id"], {
                "report_type": "discrepancy",
                "title": "Resposta incompleta revisada",
                "description": "Falta uma condição operacional importante.",
                "reference": "Consulta query_123",
                "priority": "Crítica",
            }, operator)
            self.assertEqual(edited["title"], "Resposta incompleta revisada")

            comment = server.add_report_comment(created["id"], "Complemento do operador.", operator)
            self.assertEqual(comment["author_username"], "operador")
            attachment = server.add_report_attachment(created["id"], {
                "filename": 'evidencia"teste.txt',
                "content_type": "text/plain",
                "content_base64": server.base64.b64encode(b"evidencia").decode(),
            }, operator)
            content, content_type, filename = server.get_report_attachment(attachment["id"])
            self.assertEqual((content, content_type, filename), (b"evidencia", "text/plain", "evidencia_teste.txt"))

            assigned = server.update_report(created["id"], {
                "status": "Em análise",
                "priority": "Crítica",
                "resolution": "Em verificação.",
                "assignee_user_id": 20,
                "rule_action": "keep",
            }, supervisor)
            self.assertEqual(assigned["assignee_name"], "Supervisor")
            self.assertEqual(len(assigned["comments"]), 1)
            self.assertEqual(len(assigned["attachments"]), 1)
            self.assertGreaterEqual(len(assigned["events"]), 5)


class RuleCandidateStorageTests(unittest.TestCase):
    operator = {
        "id": 5,
        "username": "operador",
        "display_name": "Operador",
        "role": "operator",
    }
    supervisor = {
        "id": 8,
        "username": "supervisor",
        "display_name": "Supervisor",
        "role": "supervisor",
    }

    def test_local_catalog_is_imported_idempotently_and_preserves_portal_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "rules.db"
            catalog = root / "catalogo_regras.json"
            payload = {
                "schema_version": 1,
                "updated_at": "2026-07-29T12:00:00-03:00",
                "items": [
                    {
                        "document_id": "PR-001",
                        "title": "Proposta documental",
                        "status": "aguardando_aprovacao",
                        "summary": "Texto recebido do documento local.",
                        "document_path": "Regras/Propostas/PR-001.md",
                        "authority": "Diretoria",
                        "source_reference": "Proposta PR-001",
                        "scope": "Operação",
                        "review_note": "Aguardando decisão.",
                    },
                    {
                        "document_id": "PR-099",
                        "title": "Regra documental",
                        "status": "aprovada",
                        "published_rule_id": "RG-001",
                        "summary": "Resumo da regra.",
                        "approved_rule_text": "Texto oficial aprovado.",
                        "document_path": "Regras/regras_aprovadas.md",
                        "authority": "Escola SAFE",
                        "source_reference": "RG-001",
                        "scope": "Operação",
                    },
                ],
            }
            catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(server, "RULES_DB_PATH", database), patch.object(
                server, "RULES_CATALOG_PATH", catalog
            ):
                server.initialize_rules_db()
                with server.rules_connection() as connection:
                    self.assertEqual(server.synchronize_rules_catalog(connection), 2)
                    self.assertEqual(server.synchronize_rules_catalog(connection), 0)

                pending = server.list_rule_candidates("pending_approval")
                self.assertEqual(pending[0]["document_id"], "PR-001")
                approved = server.list_rule_candidates("approved")
                self.assertEqual(approved[0]["rule_code"], "RG-001")

                reviewed = server.review_rule_candidate(pending[0]["id"], {
                    "status": "pending_approval",
                    "review_note": "Revisão humana preservada.",
                    "approved_rule_text": "Texto ajustado no Portal.",
                }, self.supervisor)
                self.assertFalse(reviewed["catalog_managed"])

                payload["items"][0]["summary"] = "Texto alterado no catálogo."
                catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                with server.rules_connection() as connection:
                    self.assertEqual(server.synchronize_rules_catalog(connection), 0)
                preserved = server.list_rule_candidates("pending_approval")[0]
                self.assertEqual(preserved["proposed_answer"], "Texto recebido do documento local.")
                self.assertEqual(preserved["review_note"], "Revisão humana preservada.")

    def test_catalog_approval_claims_matching_open_question_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "rules.db"
            catalog = root / "catalogo_regras.json"
            with patch.object(server, "RULES_DB_PATH", database), patch.object(
                server, "RULES_CATALOG_PATH", catalog
            ):
                candidate = server.upsert_rule_candidate(
                    "Quantos mockups são necessários para o SIRA?", "Sem resposta", "low",
                    "unanswered", [], [], self.operator,
                )
                payload = {
                    "schema_version": 1,
                    "updated_at": "2026-08-17T11:05:28-03:00",
                    "items": [{
                        "document_id": "RG-011",
                        "title": "Mockups obrigatórios para SIRA/P-Mentor",
                        "status": "aprovada",
                        "summary": "Três sessões de duas horas.",
                        "approved_rule_text": "SIRA/P-Mentor exige três mockups de duas horas.",
                        "document_path": "Regras/regras_aprovadas.md",
                        "authority": "Escola SAFE",
                        "source_reference": "RG-011; MGOP",
                        "scope": "SIRA/P-Mentor",
                        "question_aliases": ["Quantos mockups são necessários para o SIRA?"],
                    }],
                }
                catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

                with server.rules_connection() as connection:
                    self.assertEqual(server.synchronize_rules_catalog(connection), 1)
                    self.assertEqual(server.synchronize_rules_catalog(connection), 0)

                approved = server.list_rule_candidates("approved")
                self.assertEqual(len(approved), 1)
                self.assertEqual(approved[0]["id"], candidate["id"])
                self.assertEqual(approved[0]["question"], candidate["question"])
                self.assertEqual(approved[0]["document_id"], "RG-011")
                self.assertEqual(approved[0]["rule_code"], "RG-011")
                self.assertTrue(approved[0]["catalog_managed"])

    def test_existing_catalog_rule_closes_later_matching_open_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "rules.db"
            catalog = root / "catalogo_regras.json"
            with patch.object(server, "RULES_DB_PATH", database), patch.object(
                server, "RULES_CATALOG_PATH", catalog
            ):
                payload = {
                    "schema_version": 1,
                    "updated_at": "2026-08-21T17:00:13-03:00",
                    "items": [{
                        "document_id": "PR-009",
                        "published_rule_id": "RG-013",
                        "title": "Familiarização em aeródromo antes de voo solo",
                        "status": "aprovada",
                        "summary": "É necessário voo anterior com instrutor.",
                        "approved_rule_text": "O aluno precisa conhecer o aeródromo com instrutor.",
                        "document_path": "Regras/regras_aprovadas.md",
                        "authority": "Escola SAFE",
                        "source_reference": "RG-013; MIP Rev. 12",
                        "scope": "Alunos PP e PC",
                        "question_aliases": ["Aluno de PP pode ir para qualquer destino no solo?"],
                    }],
                }
                catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

                server.initialize_rules_db()
                with server.rules_connection() as connection:
                    self.assertEqual(server.synchronize_rules_catalog(connection), 1)

                gap = server.upsert_rule_candidate(
                    "Aluno de PP pode ir para qualquer destino no solo?",
                    "Sem resposta", "low", "unanswered", [], [], self.operator,
                )

                with server.rules_connection() as connection:
                    self.assertEqual(server.synchronize_rules_catalog(connection), 0)
                    closed = connection.execute(
                        "SELECT * FROM rule_candidates WHERE id=?", (gap["id"],)
                    ).fetchone()
                    events = connection.execute(
                        "SELECT * FROM rule_events WHERE candidate_id=? AND action=?",
                        (gap["id"], "Revisão automática: rejected"),
                    ).fetchall()
                    self.assertEqual(server.synchronize_rules_catalog(connection), 0)

                self.assertEqual(closed["status"], "rejected")
                self.assertEqual(closed["reviewed_by_username"], "catalogo_local")
                self.assertIn("RG-013", closed["review_note"])
                self.assertEqual(len(events), 1)
                approved = server.list_rule_candidates("approved")
                self.assertEqual(len(approved), 1)
                self.assertEqual(approved[0]["rule_code"], "RG-013")

    def test_repeated_question_is_deduplicated_and_prioritized(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            first = server.upsert_rule_candidate(
                "Qual é a regra ainda não documentada?", "", "low", "unanswered", [], [], self.operator
            )
            repeated = server.upsert_rule_candidate(
                "  QUAL É A REGRA AINDA NÃO DOCUMENTADA?  ", "Proposta", "medium",
                "external_grounded", [{"label": "ANAC", "url": "https://www.gov.br/anac"}], [],
                self.operator,
            )
            self.assertEqual(first["id"], repeated["id"])
            self.assertEqual(repeated["occurrence_count"], 2)
            self.assertEqual(repeated["status"], "unreviewed")
            self.assertEqual(repeated["status_label"], "Não revisada")
            self.assertEqual(len(server.list_rule_candidates()), 1)

    def test_review_separates_unreviewed_from_pending_approval(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            candidate = server.upsert_rule_candidate(
                "Qual regra precisa de validação?", "Resposta proposta", "medium",
                "external_grounded", [], [], self.operator,
            )
            self.assertEqual(candidate["status"], "unreviewed")

            pending = server.review_rule_candidate(candidate["id"], {
                "status": "pending_approval",
                "review_note": "Primeira análise concluída; aguarda validação final.",
                "approved_rule_text": "Texto preparado para aprovação.",
            }, self.supervisor)

            self.assertEqual(pending["status"], "pending_approval")
            self.assertEqual(pending["status_label"], "Pendente de aprovação")
            self.assertEqual(server.list_rule_candidates("unreviewed"), [])
            self.assertEqual(
                server.list_rule_candidates("pending_approval")[0]["id"],
                candidate["id"],
            )
            self.assertEqual(server.retrieve_dynamic_rules(candidate["question"]), [])

    def test_legacy_pending_review_is_migrated_by_review_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            never_reviewed = server.upsert_rule_candidate(
                "Pergunta nunca revisada", "", "low", "unanswered", [], [], self.operator
            )
            already_reviewed = server.upsert_rule_candidate(
                "Pergunta já revisada", "Proposta", "medium", "operator_report", [], [],
                self.operator,
            )
            with server.rules_connection() as connection:
                connection.execute(
                    "UPDATE rule_candidates SET status='pending_review' WHERE id=?",
                    (never_reviewed["id"],),
                )
                connection.execute(
                    """UPDATE rule_candidates SET status='pending_review',
                       reviewed_at=?, reviewed_by_name=? WHERE id=?""",
                    ("2026-01-10T10:00:00+00:00", "Supervisor", already_reviewed["id"]),
                )

            server.initialize_rules_db()

            self.assertEqual(
                server.list_rule_candidates("unreviewed")[0]["id"],
                never_reviewed["id"],
            )
            self.assertEqual(
                server.list_rule_candidates("pending_approval")[0]["id"],
                already_reviewed["id"],
            )

    def test_rejected_candidate_reopens_as_unreviewed_after_new_question(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            candidate = server.upsert_rule_candidate(
                "Pergunta que pode retornar", "Proposta antiga", "low", "unanswered",
                [], [], self.operator,
            )
            server.review_rule_candidate(candidate["id"], {
                "status": "rejected",
                "review_note": "Proposta rejeitada na primeira análise.",
            }, self.supervisor)

            reopened = server.upsert_rule_candidate(
                "Pergunta que pode retornar", "Nova proposta", "medium", "operator_report",
                [], [], self.operator,
            )

            self.assertEqual(reopened["status"], "unreviewed")
            self.assertIsNone(reopened["reviewed_at"])
            self.assertEqual(reopened["review_note"], "")

    def test_approved_candidate_becomes_retrievable_rule(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            candidate = server.upsert_rule_candidate(
                "Qual é o limite especial do teste?", "Limite proposto", "medium",
                "external_grounded", [], [], self.operator,
            )
            approved = server.review_rule_candidate(candidate["id"], {
                "status": "approved",
                "review_note": "Validado pela Coordenação.",
                "approved_rule_text": "O limite especial do teste é de duas operações.",
                "rule_code": "RG-099",
                "authority": "Coordenação Operacional",
                "source_reference": "Documento oficial, seção 3",
                "scope": "Operações de teste",
            }, self.supervisor)
            self.assertEqual(approved["status"], "approved")
            evidence = server.retrieve_dynamic_rules("Qual é o limite especial do teste?")
            self.assertEqual(evidence[0]["code"], "RG-099")
            self.assertIn("duas operações", evidence[0]["label"])

    def test_knowledge_gap_report_groups_similar_questions_and_exports_csv(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            server.upsert_rule_candidate(
                "Aluno pode voar sem CMA válido?", "Sem resposta", "low", "unanswered",
                [], [], self.operator,
            )
            server.upsert_rule_candidate(
                "O aluno pode realizar voo com CMA vencido?", "Sem resposta", "low",
                "unanswered", [], [], self.operator,
            )
            report = server.knowledge_gap_report({"status": ["open"]})

            self.assertEqual(report["summary"]["items"], 2)
            self.assertEqual(report["summary"]["total_occurrences"], 2)
            self.assertGreaterEqual(report["summary"]["recurring_groups"], 1)
            self.assertEqual(report["items"][0]["similar_group_size"], 2)
            exported = server.knowledge_gap_csv(report).decode("utf-8-sig")
            self.assertIn("Pergunta;Ocorrências", exported)
            self.assertIn("CMA", exported)

    def test_reprocess_does_not_increase_occurrence_count(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ), patch.object(server, "answer_question", return_value={
            "answer": "Nova resposta provisória.", "confidence": "medium", "sources": [],
            "response_mode": "unanswered", "knowledge_status": "unreviewed",
        }), patch.object(server, "retrieve", return_value=[]):
            candidate = server.upsert_rule_candidate(
                "Pergunta para reprocessar", "Resposta anterior", "low", "unanswered",
                [], [], self.operator,
            )
            result = server.reprocess_rule_candidate(candidate["id"], self.supervisor)

            self.assertEqual(result["item"]["occurrence_count"], 1)
            self.assertEqual(result["item"]["proposed_answer"], "Nova resposta provisória.")

    def test_approval_writes_auditable_export(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ), patch.object(
            server, "APPROVED_RULES_EXPORT_PATH", Path(directory) / "approved-export.json"
        ):
            candidate = server.upsert_rule_candidate(
                "Pergunta aprovada", "Proposta", "medium", "operator_report", [], [],
                self.operator,
            )
            server.review_rule_candidate(candidate["id"], {
                "status": "approved", "review_note": "Aprovação formal registrada.",
                "approved_rule_text": "Esta é a regra aprovada.", "rule_code": "RG-099",
                "authority": "Coordenação Operacional", "source_reference": "Ata 10",
            }, self.supervisor)

            payload = json.loads(server.APPROVED_RULES_EXPORT_PATH.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["rules"][0]["rule_code"], "RG-099")

    def test_approval_requires_rule_authority_source_and_note(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ):
            candidate = server.upsert_rule_candidate(
                "Pergunta", "Resposta", "low", "unanswered", [], [], self.operator
            )
            with self.assertRaises(ValueError):
                server.review_rule_candidate(candidate["id"], {
                    "status": "approved",
                    "review_note": "",
                    "approved_rule_text": "Regra",
                }, self.supervisor)

    def test_low_local_answer_uses_grounding_and_queues_provisional_rule(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "RULES_DB_PATH", Path(directory) / "rules.db"
        ), patch.object(
            server, "SEARCH_HISTORY_DB_PATH", Path(directory) / "history.db"
        ), patch.object(
            server, "LEARNING_DB_PATH", Path(directory) / "learning.db"
        ), patch.object(
            server, "LEARNING_GRAPH_PATH", Path(directory) / "learning.json"
        ), patch.object(server, "retrieve", return_value=[{
            "id": "claim_local", "kind": "confirmed_claim", "label": "Regra insuficiente",
            "code": "MGOP", "source": "MGOP", "location": "Seção 1", "score": 1, "excerpt": "",
        }]), patch.object(server, "WEB_GROUNDING_ENABLED", True):
            def fake_gemini(question, evidence, grounded=False, model=None, deadline=None):
                if not grounded:
                    return {
                        "answer": "A base não é conclusiva.", "confidence": "low",
                        "used_evidence": [], "candidate_relations": [],
                    }
                return {
                    "answer": "A fonte oficial indica a regra proposta.",
                    "confidence": "high",
                    "used_evidence": [],
                    "candidate_relations": [],
                    "_web_sources": [{
                        "id": "web_1", "kind": "external_source", "label": "ANAC",
                        "code": "Fonte externa", "source": "https://www.gov.br/anac",
                        "location": "https://www.gov.br/anac", "url": "https://www.gov.br/anac",
                        "excerpt": "",
                    }],
                }

            with patch.object(server, "call_gemini", side_effect=fake_gemini):
                result = server.answer_question("Pergunta sem regra local", self.operator)

            self.assertTrue(result["provisional"])
            self.assertEqual(result["response_mode"], "external_grounded")
            self.assertEqual(result["sources"][0]["label"], "ANAC")
            candidate = server.list_rule_candidates()[0]
            self.assertEqual(candidate["source_kind"], "external_grounded")
            self.assertEqual(candidate["occurrence_count"], 1)

    def test_grounded_gemini_request_enables_google_search_and_reads_citations(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {"parts": [{"text": json.dumps({
                            "answer": "Resposta oficial provisória.",
                            "confidence": "medium",
                            "used_evidence": [],
                            "candidate_relations": [],
                        })}]},
                        "groundingMetadata": {
                            "webSearchQueries": ["consulta oficial"],
                            "groundingChunks": [{"web": {
                                "title": "ANAC",
                                "uri": "https://www.gov.br/anac",
                            }}],
                        },
                    }],
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", side_effect=fake_urlopen
        ), patch.object(server, "EXTERNAL_MODEL", "gemini-3.1-pro-preview"):
            result = server.call_gemini("Pergunta regulatória", [], grounded=True)

        self.assertEqual(captured["body"]["tools"], [{"google_search": {}}])
        self.assertIn("gemini-3.1-pro-preview:generateContent", captured["url"])
        self.assertEqual(result["_web_sources"][0]["label"], "ANAC")
        self.assertEqual(result["_search_queries"], ["consulta oficial"])
        self.assertEqual(result["_model"], "gemini-3.1-pro-preview")

    def test_local_gemini_uses_primary_flash_model(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({
                    "answer": "Resposta local.",
                    "confidence": "high",
                    "used_evidence": [],
                    "candidate_relations": [],
                })}]}}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse()

        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", side_effect=fake_urlopen
        ), patch.object(server, "LOCAL_MODEL", "gemini-3.6-flash"):
            result = server.call_gemini("Pergunta local", [])

        self.assertIn("gemini-3.6-flash:generateContent", captured["url"])
        self.assertEqual(result["_model"], "gemini-3.6-flash")

    def test_grounded_gemini_rejects_non_anac_citations(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {"parts": [{"text": json.dumps({
                            "answer": "Resposta sem fonte ANAC.",
                            "confidence": "high",
                            "used_evidence": [],
                            "candidate_relations": [],
                        })}]},
                        "groundingMetadata": {
                            "groundingChunks": [
                                {"web": {"title": "Blog aeronáutico", "uri": "https://example.com/regra"}},
                                {"web": {"title": "ANAC", "uri": "https://www.gov.br/anac/pt-br/assuntos"}},
                            ],
                        },
                    }],
                }).encode("utf-8")

        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", return_value=FakeResponse()
        ):
            result = server.call_gemini("Pergunta regulatória", [], grounded=True)

        self.assertEqual(len(result["_web_sources"]), 1)
        self.assertEqual(result["_web_sources"][0]["label"], "ANAC")
        self.assertIn("gov.br/anac", result["_web_sources"][0]["url"])

    def test_confirmed_canonical_answer_survives_gemini_outage(self):
        evidence = [{
            "id": "claim_rbac61_cma_vencido_impede_prerrogativas",
            "kind": "confirmed_claim",
            "label": "CMA vencido impede o exercício das prerrogativas",
            "operator_answer": "Não. O aluno não pode voar sem CMA válido.",
            "code": "RBAC 61",
            "source": "RBAC 61",
            "location": "61.17",
            "score": 50,
            "excerpt": "",
        }]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "SEARCH_HISTORY_DB_PATH", Path(directory) / "history.db"
        ), patch.object(
            server, "LEARNING_DB_PATH", Path(directory) / "learning.db"
        ), patch.object(
            server, "LEARNING_GRAPH_PATH", Path(directory) / "learning.json"
        ), patch.object(
            server, "retrieve", return_value=evidence
        ), patch.object(server, "call_gemini_with_retry") as mocked_gemini:
            result = server.answer_question(
                "O aluno independente do voo solo pode voar sem CMA valido?", self.operator
            )

        mocked_gemini.assert_not_called()
        self.assertFalse(result["provisional"])
        self.assertEqual(result["response_mode"], "local_contingency")
        self.assertEqual(result["answer"], "Não. O aluno não pode voar sem CMA válido.")
        self.assertEqual(result["sources"][0]["id"], evidence[0]["id"])

    def test_transient_gemini_error_is_retried(self):
        expected = {
            "answer": "Resposta após repetição.",
            "confidence": "high",
            "used_evidence": [],
            "candidate_relations": [],
        }
        with patch.object(
            server, "GEMINI_TRANSIENT_RETRIES", 2
        ), patch.object(
            server, "call_gemini",
            side_effect=[server.GeminiTemporaryError("503"), expected],
        ) as mocked_call, patch.object(
            server.random, "uniform", return_value=0.0
        ), patch.object(server.time, "sleep") as mocked_sleep:
            result = server.call_gemini_with_retry("Pergunta", [])

        self.assertEqual(result, expected)
        self.assertEqual(mocked_call.call_count, 2)
        mocked_sleep.assert_called_once_with(1.0)

    def test_gemini_timeout_respects_per_call_limit_and_total_deadline(self):
        with patch.object(server, "GEMINI_HTTP_TIMEOUT_SECONDS", 30.0), patch.object(
            server.time, "monotonic", return_value=100.0
        ):
            self.assertEqual(server.gemini_timeout(), 30.0)
            self.assertEqual(server.gemini_timeout(112.5), 12.5)
            with self.assertRaises(server.GeminiDeadlineExceededError):
                server.gemini_timeout(100.0)

    def test_answer_question_uses_one_budget_for_all_gemini_stages(self):
        with patch.object(server.time, "monotonic", return_value=100.0), patch.object(
            server, "GEMINI_ANSWER_BUDGET_SECONDS", 110.0
        ), patch.object(server, "retrieve", return_value=[]), patch.object(
            server, "gemini_key", return_value="configured"
        ), patch.object(
            server, "semantic_retrieve_with_retry", return_value=[]
        ) as semantic, patch.object(
            server, "call_gemini_with_retry", side_effect=RuntimeError("indisponível")
        ) as local, patch.object(
            server, "call_grounded_gemini_with_fallback", side_effect=RuntimeError("indisponível")
        ) as grounded, patch.object(
            server, "record_learning", return_value="query_budget"
        ), patch.object(
            server, "upsert_rule_candidate", return_value={"id": 25}
        ):
            result = server.answer_question(
                "Pergunta ainda sem resposta", self.supervisor, save_history=False
            )

        self.assertEqual(semantic.call_args.kwargs["deadline"], 210.0)
        self.assertTrue(all(call.kwargs["deadline"] == 210.0 for call in local.call_args_list))
        self.assertEqual(grounded.call_args.kwargs["deadline"], 210.0)
        self.assertTrue(result["provisional"])
        self.assertEqual(result["candidate_id"], 25)

    def test_zero_model_quota_skips_retry_and_grounding_uses_flash_fallback(self):
        quota_error = server.urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com", 429, "Too Many Requests", {},
            BytesIO(b'{"error":{"message":"Quota exceeded, limit: 0"}}'),
        )
        with patch.object(server, "gemini_key", return_value="test-key"), patch(
            "backend.server.urllib.request.urlopen", side_effect=quota_error
        ):
            with self.assertRaises(server.GeminiModelQuotaUnavailableError):
                server.call_gemini("Pergunta", [], grounded=True, model="gemini-3.1-pro")

        fallback_result = {
            "answer": "Resposta oficial de contingência.",
            "confidence": "medium",
            "used_evidence": [],
            "candidate_relations": [],
            "_model": "gemini-3.6-flash",
        }
        with patch.object(
            server, "EXTERNAL_MODEL", "gemini-3.1-pro"
        ), patch.object(
            server, "LOCAL_MODEL", "gemini-3.6-flash"
        ), patch.object(
            server, "FALLBACK_MODEL", "gemini-3.5-flash-lite"
        ), patch.object(
            server, "call_gemini_with_retry",
            side_effect=[server.GeminiModelQuotaUnavailableError("sem cota"), fallback_result],
        ) as mocked_call:
            result = server.call_grounded_gemini_with_fallback("Pergunta", [])

        self.assertEqual(result, fallback_result)
        self.assertEqual(mocked_call.call_count, 2)
        self.assertEqual(mocked_call.call_args_list[0].kwargs["model"], "gemini-3.1-pro")
        self.assertEqual(mocked_call.call_args_list[1].kwargs["model"], "gemini-3.6-flash")

    def test_primary_outage_uses_fallback_and_reports_error_only_to_supervision(self):
        evidence = [{
            "id": "claim_1",
            "kind": "confirmed_claim",
            "label": "Regra confirmada",
            "operator_answer": "",
            "code": "SAFE",
            "source": "Documento SAFE",
            "location": "Linha 1",
            "score": 10,
            "excerpt": "Trecho confirmado.",
        }]
        fallback_result = {
            "answer": "Resposta interpretada pelo modelo de contingência.",
            "confidence": "high",
            "used_evidence": [1],
            "candidate_relations": [],
            "_model": "gemini-3.5-flash-lite",
        }

        def run(actor):
            with patch.object(
                server, "retrieve", return_value=evidence
            ), patch.object(
                server, "call_gemini_with_retry",
                side_effect=[server.GeminiTemporaryError("HTTP 503"), fallback_result],
            ) as mocked_gemini, patch.object(
                server, "record_learning", return_value="query_test"
            ), patch.object(server, "save_search_history"):
                result = server.answer_question("Pergunta operacional", actor)
            self.assertEqual(
                mocked_gemini.call_args_list[1].kwargs["model"],
                server.FALLBACK_MODEL,
            )
            return result

        supervisor_result = run(self.supervisor)
        operator_result = run(self.operator)

        self.assertEqual(supervisor_result["model_used"], "gemini-3.5-flash-lite")
        self.assertIn("HTTP 503", supervisor_result["local_error"])
        self.assertEqual(operator_result["local_error"], "")


if __name__ == "__main__":
    unittest.main()
