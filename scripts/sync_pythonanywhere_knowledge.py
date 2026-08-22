"""Empacota a base privada, envia ao PythonAnywhere e recarrega o Portal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from deploy_pythonanywhere_portal import deploy_portal


ROOT = Path(__file__).resolve().parents[2]
MANDATORY_FILES = (
    "Knowledge/claims_curated.json",
    "Knowledge/query_graph.json",
    "Regras/catalogo_regras.json",
    "graphify-out/graph.json",
)
MANIFEST_NAME = "knowledge-bundle-manifest.json"


def normalized_relative_path(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(ROOT.resolve())
        except (OSError, ValueError):
            return None
    normalized = candidate.as_posix().lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        return None
    return normalized


def source_files() -> list[str]:
    paths = set(MANDATORY_FILES)
    claims = json.loads((ROOT / "Knowledge" / "claims_curated.json").read_text(encoding="utf-8"))
    for item in claims.get("claims", []) + claims.get("hypotheses", []):
        for value in [item.get("source_path"), *item.get("support_paths", [])]:
            relative = normalized_relative_path(value or "")
            if relative:
                paths.add(relative)
    graph = json.loads((ROOT / "graphify-out" / "graph.json").read_text(encoding="utf-8"))
    for node in graph.get("nodes", []):
        relative = normalized_relative_path(node.get("source_file", ""))
        if relative:
            paths.add(relative)
    return sorted(
        path for path in paths
        if (ROOT / path).is_file() and (ROOT / path).suffix.lower() in {".json", ".md", ".txt"}
    )


def build_bundle(destination: Path) -> dict:
    files = {}
    for relative in source_files():
        payload = (ROOT / relative).read_bytes()
        files[relative] = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            archive.write(ROOT / relative, relative)
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def api_request(url: str, token: str, data: bytes | None = None, content_type: str | None = None):
    headers = {"Authorization": f"Token {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PythonAnywhere retornou HTTP {error.code}: {detail[:500]}") from error


def upload_bundle(bundle: Path, token: str, host: str, username: str, remote_path: str) -> None:
    boundary = f"----PortalCCO{uuid.uuid4().hex}"
    payload = bundle.read_bytes()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="content"; filename="knowledge-bundle.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    encoded_path = urllib.parse.quote(remote_path, safe="/")
    url = f"https://{host}/api/v0/user/{username}/files/path{encoded_path}"
    status, _ = api_request(url, token, body, f"multipart/form-data; boundary={boundary}")
    if status not in {200, 201}:
        raise RuntimeError(f"Upload do pacote retornou HTTP {status}.")


def reload_webapp(token: str, host: str, username: str, domain: str) -> None:
    encoded_domain = urllib.parse.quote(domain, safe="")
    url = f"https://{host}/api/v0/user/{username}/webapps/{encoded_domain}/reload/"
    status, _ = api_request(url, token, b"")
    if status not in {200, 201}:
        raise RuntimeError(f"Recarga do Portal retornou HTTP {status}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza a base privada com o Portal CCO.")
    parser.add_argument("--build-only", type=Path, help="Gera o pacote local sem enviar.")
    parser.add_argument("--host", default=os.environ.get("PYTHONANYWHERE_HOST", "www.pythonanywhere.com"))
    parser.add_argument("--username", default=os.environ.get("PYTHONANYWHERE_USERNAME", "CCOFields"))
    parser.add_argument("--domain", default=os.environ.get("PYTHONANYWHERE_DOMAIN", "ccofields.pythonanywhere.com"))
    parser.add_argument(
        "--deploy-portal",
        action="store_true",
        help="Publica também o código do Portal por release atômico e valida /api/health.",
    )
    args = parser.parse_args()

    if args.build_only:
        manifest = build_bundle(args.build_only)
        print(json.dumps({"bundle": str(args.build_only), "files": len(manifest["files"])}, ensure_ascii=False))
        return

    token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina PYTHONANYWHERE_API_TOKEN somente no ambiente local.")
    remote_path = f"/home/{args.username}/portalcco-data/knowledge-bundle.zip"
    with tempfile.TemporaryDirectory() as temporary:
        bundle = Path(temporary) / "knowledge-bundle.zip"
        manifest = build_bundle(bundle)
        upload_bundle(bundle, token, args.host, args.username, remote_path)
    portal = None
    if args.deploy_portal:
        portal = deploy_portal(token, args.host, args.username, args.domain)
    else:
        reload_webapp(token, args.host, args.username, args.domain)
    result = {
        "status": "synchronized",
        "files": len(manifest["files"]),
        "domain": args.domain,
    }
    if portal:
        result["portal"] = portal
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
