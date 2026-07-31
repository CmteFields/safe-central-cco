"""Baixa regras aprovadas no Portal para a caixa de entrada documental local."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION = ROOT / "Regras" / "Entradas" / "portal_regras_aprovadas.json"


def download_export(token: str, host: str, username: str, remote_path: str) -> bytes:
    encoded_path = urllib.parse.quote(remote_path, safe="/")
    request = urllib.request.Request(
        f"https://{host}/api/v0/user/{username}/files/path{encoded_path}",
        headers={"Authorization": f"Token {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PythonAnywhere retornou HTTP {error.code}: {detail[:500]}") from error


def validate_export(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("O pacote não possui o schema_version 1 esperado.")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise ValueError("O pacote não contém uma lista de regras.")
    seen_codes: set[str] = set()
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("O pacote contém uma regra inválida.")
        code = str(item.get("rule_code", "")).strip().upper()
        required = (
            str(item.get("approved_rule_text", "")).strip(),
            str(item.get("authority", "")).strip(),
            str(item.get("source_reference", "")).strip(),
            str(item.get("reviewed_at", "")).strip(),
        )
        if not re.fullmatch(r"RG-\d{3}", code) or not all(required):
            raise ValueError(f"Regra aprovada incompleta ou com código inválido: {code or '(sem código)'}.")
        if code in seen_codes:
            raise ValueError(f"Código duplicado no pacote: {code}.")
        seen_codes.add(code)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa o pacote auditável de regras aprovadas do Portal CCO."
    )
    parser.add_argument("--host", default=os.environ.get("PYTHONANYWHERE_HOST", "www.pythonanywhere.com"))
    parser.add_argument("--username", default=os.environ.get("PYTHONANYWHERE_USERNAME", "CCOFields"))
    parser.add_argument("--remote-path", default="")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()

    token = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina PYTHONANYWHERE_API_TOKEN somente no ambiente local.")
    remote_path = args.remote_path or f"/home/{args.username}/portalcco-data/approved-rules-export.json"
    raw = download_export(token, args.host, args.username, remote_path)
    payload = validate_export(json.loads(raw.decode("utf-8")))
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.destination.with_suffix(".tmp")
    temporary.write_bytes(serialized)
    temporary.replace(args.destination)
    print(json.dumps({
        "status": "imported_for_review",
        "rules": len(payload["rules"]),
        "destination": str(args.destination),
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "next_step": "Publicar as regras válidas no catálogo e executar Knowledge/update_knowledge.py.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
