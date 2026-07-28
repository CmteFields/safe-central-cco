import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from backend import server
from backend import wsgi


class RetrievalTests(unittest.TestCase):
    def test_public_index_is_used_when_private_knowledge_is_not_deployed(self):
        missing_root = Path("diretorio-privado-ausente")
        with patch.object(server, "CLAIMS_PATH", missing_root / "claims.json"), patch.object(
            server, "GRAPH_PATH", missing_root / "graph.json"
        ):
            evidence = server.retrieve("Quantas horas por dia o aluno PP pode voar?")
        evidence_ids = {item["id"] for item in evidence}
        self.assertIn("claim_ppap001k_limite_diario_instrucao", evidence_ids)
        self.assertTrue(all(item["source"] == "Índice público de regras confirmadas" for item in evidence))

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
        response_body = b"".join(wsgi.application(environ, start_response))
        headers = {name: value for name, value in captured["headers"]}
        return str(captured["status"]), headers, response_body

    def test_health_endpoint_through_wsgi(self):
        status, headers, body = self.request("/api/health")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body), {"ok": True})

    def test_static_portal_through_wsgi(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"CCO - Central de conhecimento", body)

    def test_browser_uses_same_origin_ai_endpoint(self):
        status, _, body = self.request("/app.js")
        self.assertEqual(status, "200 OK")
        self.assertIn(b"`${window.location.origin}/api/ask`", body)
        self.assertIn(b"`${window.location.origin}/api/reports", body)
        self.assertNotIn(b"http://127.0.0.1:8765/api/ask", body)
        self.assertIn("Modo de contingência".encode(), body)

    def test_static_portal_contains_reports_section(self):
        status, _, body = self.request("/")
        self.assertEqual(status, "200 OK")
        self.assertIn(b'data-view="reports"', body)
        self.assertIn(b'id="reportsView"', body)
        self.assertIn(b'id="reportAnswerIssue"', body)

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


class ReportStorageTests(unittest.TestCase):
    def test_operator_creates_report_with_authenticated_identity_and_audit(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            server, "REPORTS_DB_PATH", Path(directory) / "reports.db"
        ):
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
        ):
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


if __name__ == "__main__":
    unittest.main()
