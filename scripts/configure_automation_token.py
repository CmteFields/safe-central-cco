"""Provisiona o token restrito do Portal sem revelar nem versionar o segredo."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def api_request(
    url: str,
    api_token: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
) -> bytes:
    headers = {"Authorization": f"Token {api_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"PythonAnywhere retornou HTTP {error.code}: {detail[:300]}"
        ) from error


def files_url(host: str, username: str, remote_path: str) -> str:
    encoded = urllib.parse.quote(remote_path, safe="/")
    return f"https://{host}/api/v0/user/{username}/files/path{encoded}"


def upload_json(
    payload: bytes,
    remote_path: str,
    api_token: str,
    host: str,
    username: str,
) -> None:
    boundary = f"----PortalCCO{uuid.uuid4().hex}"
    filename = Path(remote_path).name
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="content"; filename="{filename}"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    api_request(
        files_url(host, username, remote_path),
        api_token,
        method="POST",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def reload_webapp(api_token: str, host: str, username: str, domain: str) -> None:
    url = f"https://{host}/api/v0/user/{username}/webapps/{domain}/reload/"
    api_request(url, api_token, method="POST", data=b"")


def save_user_environment(name: str, value: str) -> None:
    if os.name != "nt":
        raise RuntimeError("A persistência segura automática está disponível somente no Windows.")
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configura o token restrito da Gestão de Regras sem exibi-lo."
    )
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument(
        "--host", default=os.environ.get("PYTHONANYWHERE_HOST", "www.pythonanywhere.com")
    )
    parser.add_argument(
        "--username", default=os.environ.get("PYTHONANYWHERE_USERNAME", "CCOFields")
    )
    parser.add_argument(
        "--domain", default=os.environ.get("PYTHONANYWHERE_DOMAIN", "ccofields.pythonanywhere.com")
    )
    args = parser.parse_args()

    api_token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if not api_token:
        raise SystemExit("Defina PYTHONANYWHERE_API_TOKEN somente no ambiente local.")

    remote_path = f"/home/{args.username}/.portalcco-secrets.json"
    secret_bytes = api_request(files_url(args.host, args.username, remote_path), api_token)
    settings = json.loads(secret_bytes.decode("utf-8"))
    portal_token = str(settings.get("SAFE_CCO_AUTOMATION_TOKEN", "")).strip()
    changed = args.rotate or len(portal_token) < 43
    if changed:
        portal_token = secrets.token_urlsafe(48)
        settings["SAFE_CCO_AUTOMATION_TOKEN"] = portal_token
        upload_json(
            (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            remote_path,
            api_token,
            args.host,
            args.username,
        )
        reload_webapp(api_token, args.host, args.username, args.domain)

    save_user_environment("PORTALCCO_AUTOMATION_TOKEN", portal_token)
    save_user_environment("PORTALCCO_BASE_URL", f"https://{args.domain}")
    print(
        "Token restrito da Gestão de Regras rotacionado e salvo com segurança."
        if changed
        else "Token restrito da Gestão de Regras recuperado e salvo com segurança."
    )


if __name__ == "__main__":
    main()
