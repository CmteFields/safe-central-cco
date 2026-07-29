import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.knowledge_bundle import MANIFEST_NAME, install_knowledge_bundle


class KnowledgeBundleTests(unittest.TestCase):
    def make_bundle(self, root: Path, files: dict[str, bytes]) -> Path:
        bundle = root / "knowledge-bundle.zip"
        manifest = {"schema_version": 1, "files": {
            name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()
        }}
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
            archive.writestr(MANIFEST_NAME, json.dumps(manifest))
        return bundle

    def test_installs_once_and_preserves_declared_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self.make_bundle(root, {"Knowledge/claims_curated.json": b'{"claims":[]}'})
            target = root / "private"
            state = root / "state.txt"
            self.assertTrue(install_knowledge_bundle(bundle, target, state))
            self.assertEqual(
                (target / "Knowledge" / "claims_curated.json").read_bytes(),
                b'{"claims":[]}',
            )
            self.assertFalse(install_knowledge_bundle(bundle, target, state))

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self.make_bundle(root, {"../outside.json": b"{}"})
            with self.assertRaises(ValueError):
                install_knowledge_bundle(bundle, root / "private", root / "state.txt")

    def test_backend_automatically_uses_persistent_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "data"
            data_root.mkdir()
            self.make_bundle(data_root, {
                "Knowledge/claims_curated.json": b'{"claims":[]}',
                "graphify-out/graph.json": b'{"nodes":[],"links":[]}',
            })
            environment = os.environ.copy()
            environment["SAFE_CCO_DATA_DIR"] = str(data_root)
            environment.pop("SAFE_KNOWLEDGE_ROOT", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import backend.server as s; print(s.BUNDLED_KNOWLEDGE_ACTIVE); print(s.KNOWLEDGE_ROOT)",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
            )
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], "True")
            self.assertEqual(Path(lines[1]), data_root / "private-knowledge")


if __name__ == "__main__":
    unittest.main()
