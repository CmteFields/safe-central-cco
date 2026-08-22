"""Gera o índice estático de consulta do Portal CCO a partir do conhecimento validado."""

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PORTAL = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "Knowledge" / "claims_curated.json"
GRAPH_PATH = ROOT / "graphify-out" / "graph.json"
OUTPUT_PATH = PORTAL / "data" / "knowledge-index.js"
PUBLIC_OUTPUT_PATH = PORTAL / "data" / "public-knowledge-index.js"
CONFIRMED_STATUSES = {"confirmed", "confirmed_temporary_override"}


def load_index(path):
    if not path.is_file():
        return None
    try:
        _, separator, encoded = path.read_text(encoding="utf-8").partition("=")
        if not separator:
            return None
        return json.loads(encoded.strip().removesuffix(";"))
    except (OSError, json.JSONDecodeError):
        return None


def stabilize_generated_at(path, payload):
    previous = load_index(path)
    if not previous:
        return payload
    previous_compare = json.loads(json.dumps(previous))
    current_compare = json.loads(json.dumps(payload))
    previous_compare.get("meta", {}).pop("generatedAt", None)
    current_compare.get("meta", {}).pop("generatedAt", None)
    if previous_compare == current_compare:
        payload["meta"]["generatedAt"] = previous["meta"].get(
            "generatedAt", payload["meta"]["generatedAt"]
        )
    return payload


def write_if_changed(path, content):
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def compact_claim(claim):
    return {
        "id": claim["id"],
        "label": claim["label"],
        "operatorAnswer": claim.get("operator_answer", ""),
        "code": claim.get("document_code", ""),
        "source": claim.get("source_path", ""),
        "location": claim.get("source_location", ""),
        "relation": claim.get("relation", ""),
        "appliesTo": ", ".join(claim.get("applies_to", [])),
    }


def compact_document(node):
    return {
        "id": node["id"],
        "label": node.get("label", node["id"]),
        "source": node.get("source_file", ""),
        "location": node.get("source_location", ""),
        "type": node.get("file_type", ""),
    }


def compact_public_claim(claim):
    """Remove caminhos internos e publica apenas a regra rastreável."""
    return {
        "id": claim["id"],
        "label": claim["label"],
        "operatorAnswer": claim.get("operator_answer", ""),
        "code": claim.get("document_code", ""),
        "location": claim.get("source_location", ""),
        "relation": claim.get("relation", ""),
        "appliesTo": ", ".join(claim.get("applies_to", [])),
    }


def main():
    claims_data = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    graph_data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    generated_at = datetime.fromtimestamp(
        max(CLAIMS_PATH.stat().st_mtime, GRAPH_PATH.stat().st_mtime),
        timezone.utc,
    ).isoformat()
    claims = [compact_claim(item) for item in claims_data.get("claims", []) if item.get("status") in CONFIRMED_STATUSES]
    claim_ids = {item["id"] for item in claims}
    documents = [
        compact_document(node)
        for node in graph_data.get("nodes", [])
        if node.get("id") not in claim_ids and node.get("source_file")
    ]
    documents.sort(key=lambda item: item["label"].casefold())
    payload = {
        "meta": {
            "schemaVersion": 1,
            "generatedAt": generated_at,
            "confirmedClaims": len(claims),
            "documents": len(documents),
            "graphNodes": len(graph_data.get("nodes", [])),
            "graphLinks": len(graph_data.get("links", [])),
        },
        "claims": claims,
        "documents": documents,
    }
    payload = stabilize_generated_at(OUTPUT_PATH, payload)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = "window.SAFE_KNOWLEDGE_INDEX = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    write_if_changed(OUTPUT_PATH, content)
    public_claims = [compact_public_claim(item) for item in claims_data.get("claims", []) if item.get("status") in CONFIRMED_STATUSES]
    public_payload = {
        "meta": {
            "schemaVersion": 1,
            "generatedAt": payload["meta"]["generatedAt"],
            "confirmedClaims": len(public_claims),
            "documents": 0,
            "scope": "public_confirmed_claims",
        },
        "claims": public_claims,
        "documents": [],
    }
    public_payload = stabilize_generated_at(PUBLIC_OUTPUT_PATH, public_payload)
    public_content = "window.SAFE_KNOWLEDGE_INDEX = " + json.dumps(public_payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    write_if_changed(PUBLIC_OUTPUT_PATH, public_content)
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
