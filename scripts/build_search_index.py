"""Gera o índice estático de consulta do Portal CCO a partir do conhecimento validado."""

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PORTAL = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "Knowledge" / "claims_curated.json"
GRAPH_PATH = ROOT / "graphify-out" / "graph.json"
OUTPUT_PATH = PORTAL / "data" / "knowledge-index.js"


def compact_claim(claim):
    return {
        "id": claim["id"],
        "label": claim["label"],
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


def main():
    claims_data = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    graph_data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    claims = [compact_claim(item) for item in claims_data.get("claims", []) if item.get("status") == "confirmed"]
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
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "confirmedClaims": len(claims),
            "documents": len(documents),
            "graphNodes": len(graph_data.get("nodes", [])),
            "graphLinks": len(graph_data.get("links", [])),
        },
        "claims": claims,
        "documents": documents,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = "window.SAFE_KNOWLEDGE_INDEX = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(json.dumps(payload["meta"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
