import unittest
from unittest.mock import patch

from scripts import deploy_pythonanywhere_portal as deploy


class PythonAnywhereDeploymentTests(unittest.TestCase):
    def test_runtime_payload_is_public_and_complete(self):
        payloads = deploy.runtime_payloads()
        self.assertEqual(set(payloads), set(deploy.RUNTIME_FILES))
        self.assertIn("backend/server.py", payloads)
        self.assertIn("data/public-knowledge-index.js", payloads)
        self.assertNotIn("data/knowledge-index.js", payloads)
        self.assertTrue(all(payloads.values()))

    def test_wsgi_uses_atomic_release_and_persistent_data(self):
        rendered = deploy.render_wsgi_config(
            "OperadorTeste",
            "/home/OperadorTeste/portalcco-releases/abc123",
        ).decode("utf-8")
        self.assertIn("/home/OperadorTeste/portalcco-releases/abc123", rendered)
        self.assertIn("/home/OperadorTeste/portalcco-data", rendered)
        self.assertIn("/home/OperadorTeste/.portalcco-secrets.json", rendered)
        self.assertNotIn("/home/CCOFields", rendered)

    @patch.object(deploy, "wait_for_release", side_effect=RuntimeError("falhou"))
    @patch.object(deploy, "reload_webapp")
    @patch.object(deploy, "download_bytes", return_value=b"wsgi-anterior")
    @patch.object(deploy, "upload_bytes")
    @patch.object(deploy, "runtime_payloads", return_value={"index.html": b"portal"})
    @patch.object(deploy, "render_wsgi_config", return_value=b"wsgi-novo")
    @patch.object(deploy, "expected_release_id", return_value="release-teste")
    @patch.object(deploy, "local_git_sha", return_value="a" * 40)
    def test_failed_health_check_restores_previous_wsgi(
        self,
        _git_sha,
        _release_id,
        _render_wsgi,
        _payloads,
        upload,
        _download,
        reload_webapp,
        _wait,
    ):
        with self.assertRaisesRegex(RuntimeError, "falhou"):
            deploy.deploy_portal("token", "host", "usuario", "portal.exemplo")

        restored = [
            call for call in upload.call_args_list
            if call.args[0] == b"wsgi-anterior"
            and call.args[1] == "/var/www/portal_exemplo_wsgi.py"
        ]
        self.assertEqual(len(restored), 1)
        self.assertEqual(reload_webapp.call_count, 2)


if __name__ == "__main__":
    unittest.main()
