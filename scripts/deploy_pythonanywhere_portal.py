"""Publica o código do Portal CCO no PythonAnywhere usando somente a API oficial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


PORTAL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "app.js",
    "assets/images/logo.png",
    "auth.css",
    "backend/knowledge_bundle.py",
    "backend/server.py",
    "backend/wsgi.py",
    "data/public-knowledge-index.js",
    "index.html",
    "instrutores.css",
    "styles.css",
    "topbar.css",
)


def api_request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    headers = {"Authorization": f"Token {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"PythonAnywhere retornou HTTP {error.code}: {detail[:500]}"
        ) from error


def files_url(host: str, username: str, remote_path: str) -> str:
    encoded_path = urllib.parse.quote(remote_path, safe="/")
    return f"https://{host}/api/v0/user/{username}/files/path{encoded_path}"


def upload_bytes(
    payload: bytes,
    remote_path: str,
    token: str,
    host: str,
    username: str,
) -> None:
    boundary = f"----PortalCCO{uuid.uuid4().hex}"
    filename = Path(remote_path).name or "portalcco-file"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="content"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    status, _ = api_request(
        files_url(host, username, remote_path),
        token,
        method="POST",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Upload de {remote_path} retornou HTTP {status}.")


def download_bytes(remote_path: str, token: str, host: str, username: str) -> bytes:
    status, payload = api_request(files_url(host, username, remote_path), token)
    if status != 200:
        raise RuntimeError(f"Leitura de {remote_path} retornou HTTP {status}.")
    return payload


def reload_webapp(token: str, host: str, username: str, domain: str) -> None:
    encoded_domain = urllib.parse.quote(domain, safe="")
    url = f"https://{host}/api/v0/user/{username}/webapps/{encoded_domain}/reload/"
    status, _ = api_request(url, token, method="POST", data=b"")
    if status not in {200, 201}:
        raise RuntimeError(f"Recarga do Portal retornou HTTP {status}.")


def local_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PORTAL_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    sha = result.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Não foi possível identificar o commit do PortalCCO.")
    return sha


def expected_release_id() -> str:
    source = (PORTAL_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    match = re.search(
        r'RELEASE_ID\s*=\s*os\.environ\.get\("SAFE_CCO_RELEASE",\s*"([^"]+)"\)',
        source,
    )
    if not match:
        raise RuntimeError("RELEASE_ID padrão não encontrado em backend/server.py.")
    return match.group(1)


def render_wsgi_config(username: str, release_root: str) -> bytes:
    template = (PORTAL_ROOT / "pythonanywhere_wsgi.py.example").read_text(encoding="utf-8")
    rendered = template.replace(
        '/home/CCOFields/safe-central-cco', release_root
    ).replace('/home/CCOFields', f"/home/{username}")
    compile(rendered, "pythonanywhere_wsgi.py", "exec")
    return rendered.encode("utf-8")


def runtime_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for relative in RUNTIME_FILES:
        path = PORTAL_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"Arquivo obrigatório do Portal ausente: {relative}")
        payloads[relative] = path.read_bytes()
    return payloads


def wait_for_release(domain: str, release_id: str, attempts: int = 12) -> dict:
    url = f"https://{domain}/api/health"
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok") and payload.get("release") == release_id:
                return payload
            errors.append(f"release={payload.get('release', '')}")
        except (OSError, ValueError, urllib.error.URLError) as error:
            errors.append(type(error).__name__)
        if attempt + 1 < attempts:
            time.sleep(2)
    raise RuntimeError(
        f"Portal não confirmou a versão {release_id}: {', '.join(errors[-3:])}"
    )


def deploy_portal(
    token: str,
    host: str,
    username: str,
    domain: str,
) -> dict:
    sha = local_git_sha()
    release_id = expected_release_id()
    release_root = f"/home/{username}/portalcco-releases/{sha}"
    payloads = runtime_payloads()
    manifest = {
        "schema_version": 1,
        "commit": sha,
        "release": release_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            path: hashlib.sha256(payload).hexdigest()
            for path, payload in payloads.items()
        },
    }

    for relative, payload in payloads.items():
        upload_bytes(payload, f"{release_root}/{relative}", token, host, username)
    upload_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        f"{release_root}/deployment-manifest.json",
        token,
        host,
        username,
    )

    wsgi_path = f"/var/www/{domain.replace('.', '_')}_wsgi.py"
    previous_wsgi = download_bytes(wsgi_path, token, host, username)
    managed_wsgi = render_wsgi_config(username, release_root)
    previous_hash = hashlib.sha256(previous_wsgi).hexdigest()
    if previous_wsgi != managed_wsgi:
        upload_bytes(
            previous_wsgi,
            f"/home/{username}/portalcco-data/deploy-backups/wsgi-{previous_hash}.py",
            token,
            host,
            username,
        )
        upload_bytes(managed_wsgi, wsgi_path, token, host, username)

    try:
        reload_webapp(token, host, username, domain)
        health = wait_for_release(domain, release_id)
    except Exception:
        if previous_wsgi != managed_wsgi:
            upload_bytes(previous_wsgi, wsgi_path, token, host, username)
            reload_webapp(token, host, username, domain)
        raise

    return {
        "status": "deployed",
        "commit": sha,
        "release": release_id,
        "files": len(payloads),
        "domain": domain,
        "knowledge": health.get("knowledge", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publica o código validado do Portal CCO sem usar navegador."
    )
    parser.add_argument("--host", default=os.environ.get("PYTHONANYWHERE_HOST", "www.pythonanywhere.com"))
    parser.add_argument("--username", default=os.environ.get("PYTHONANYWHERE_USERNAME", "CCOFields"))
    parser.add_argument("--domain", default=os.environ.get("PYTHONANYWHERE_DOMAIN", "ccofields.pythonanywhere.com"))
    args = parser.parse_args()
    token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina PYTHONANYWHERE_API_TOKEN somente no ambiente local.")
    print(json.dumps(
        deploy_portal(token, args.host, args.username, args.domain),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
