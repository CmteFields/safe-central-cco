"""Instala pacotes privados de conhecimento em uma raiz persistente."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path, PurePosixPath


MANIFEST_NAME = "knowledge-bundle-manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Caminho inválido no pacote de conhecimento: {value!r}")
    return path


def install_knowledge_bundle(bundle_path: Path, knowledge_root: Path, state_path: Path) -> bool:
    """Instala um pacote novo e retorna True; pacotes já aplicados retornam False."""
    if not bundle_path.is_file():
        return False
    bundle_hash = file_sha256(bundle_path)
    if state_path.is_file() and state_path.read_text(encoding="utf-8").strip() == bundle_hash:
        return False

    with zipfile.ZipFile(bundle_path) as archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Manifesto ausente ou inválido no pacote de conhecimento.") from error
        expected_files = manifest.get("files", {})
        if not isinstance(expected_files, dict) or not expected_files:
            raise ValueError("O pacote de conhecimento não contém arquivos declarados.")

        validated = []
        for member_name, expected_hash in expected_files.items():
            relative = safe_member_path(member_name)
            try:
                payload = archive.read(member_name)
            except KeyError as error:
                raise ValueError(f"Arquivo ausente no pacote: {member_name}") from error
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"Hash inválido no pacote: {member_name}")
            validated.append((relative, payload))

    knowledge_root.mkdir(parents=True, exist_ok=True)
    for relative, payload in validated:
        destination = knowledge_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, destination)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_state = state_path.with_name(f".{state_path.name}.tmp")
    temporary_state.write_text(bundle_hash + "\n", encoding="utf-8")
    os.replace(temporary_state, state_path)
    return True
