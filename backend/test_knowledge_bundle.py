import hashlib
import json
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


if __name__ == "__main__":
    unittest.main()
