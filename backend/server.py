"""Backend RAG do Portal CCO: grafo SAFE + Gemini + aprendizagem auditável."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from functools import lru_cache
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PORTAL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_ROOT = PORTAL_ROOT.parent
KNOWLEDGE_ROOT = Path(os.environ.get("SAFE_KNOWLEDGE_ROOT", DEFAULT_KNOWLEDGE_ROOT)).resolve()
CLAIMS_PATH = KNOWLEDGE_ROOT / "Knowledge" / "claims_curated.json"
GRAPH_PATH = KNOWLEDGE_ROOT / "graphify-out" / "graph.json"
LEARNING_GRAPH_PATH = KNOWLEDGE_ROOT / "Knowledge" / "query_graph.json"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
HOST = os.environ.get("SAFE_CCO_HOST", "127.0.0.1")
PORT = int(os.environ.get("SAFE_CCO_PORT", "8765"))
MAX_QUESTION_LENGTH = 1200
WRITE_LOCK = threading.Lock()
STOPWORDS = {"a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em", "na", "no", "para", "por", "com", "um", "uma", "que", "pode", "como", "safe", "fazer", "concluir", "quantos"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").casefold()


def contains_normalized_token(normalized: str, token: str) -> bool:
    if len(token) <= 3:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", normalized))
    return token in normalized


def contains_token(value: str, token: str) -> bool:
    return contains_normalized_token(normalize(value), token)


def requested_course(value: str) -> str:
    normalized = normalize(value)
    if re.search(r"\bpcifr\b", normalized) or "piloto comercial e voo por instrumentos" in normalized:
        return "pcifr"
    if re.search(r"\binva\b", normalized) or "curso de instrutor de voo" in normalized:
        return "inva"
    if re.search(r"\bifr\b", normalized) or "curso de voo por instrumentos" in normalized:
        return "ifr"
    if re.search(r"\b(?:pc|pca)\b", normalized) or "piloto comercial" in normalized:
        return "pc"
    if re.search(r"\b(?:pp|ppa)\b", normalized) or "piloto privado" in normalized:
        return "pp"
    return ""


def content_course(label: str, metadata: str = "") -> str:
    metadata_norm = normalize(metadata)
    label_norm = normalize(label)
    if re.search(r"\bpcifrap[0-9a-z]*\b", metadata_norm):
        return "pcifr"
    if re.search(r"\binvap[0-9a-z]*\b", metadata_norm):
        return "inva"
    if re.search(r"\bifrap[0-9a-z]*\b", metadata_norm):
        return "ifr"
    if re.search(r"\bppap[0-9a-z]*\b", metadata_norm):
        return "pp"
    if re.search(r"\bpcap[0-9a-z]*\b", metadata_norm):
        return "pc"
    if re.search(r"\bpcifr\b", label_norm):
        return "pcifr"
    if re.search(r"\binva\b", label_norm):
        return "inva"
    if re.search(r"\b(?:pc|pca)\b", label_norm) or "piloto comercial" in label_norm:
        return "pc"
    if re.search(r"\b(?:pp|ppa)\b", label_norm) or "piloto privado" in label_norm:
        return "pp"
    if re.search(r"\bifr\b", label_norm) or "curso de voo por instrumentos" in label_norm:
        return "ifr"
    return ""


def course_compatible(course: str, label: str, metadata: str = "") -> bool:
    identified = content_course(label, metadata)
    return not course or not identified or course == identified


def tokens(value: str) -> list[str]:
    normalized = normalize(value)
    items = [item for item in re.split(r"[^a-z0-9-]+", normalized) if len(item) > 1 and item not in STOPWORDS]
    expansions = []
    if any(term in normalized for term in ("passou mal", "passar mal", "doente", "doenca", "problema de saude")):
        expansions.extend(["saude", "problema", "exce", "justific", "comprov"])
    if any(term in normalized for term in ("cancelar", "cancelado", "cancelamento")):
        expansions.extend(["cancel", "no", "show"])
    extraordinary_road_events = ("acidente", "interdicao", "alagamento", "bloqueio total", "pane no veiculo", "pneu furado")
    if any(term in normalized for term in extraordinary_road_events):
        expansions.extend(["evento", "viari", "extraordin", "evidenc", "exce", "no", "show"])
    if "banca" in normalized and any(term in normalized for term in ("ppa", "piloto privado")):
        expansions.extend(["requisit", "inicio", "curso", "privado", "065"])
    course = requested_course(normalized)
    if course and any(term in normalized for term in ("slot", "slots", "hora", "horas", "dia", "diaria", "diarias")):
        expansions.extend([course, "instrucao", "diari", "limite"])
    return list(dict.fromkeys(items + expansions))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_text(query_tokens: list[str], label: str, metadata: str = "") -> int:
    label_norm, metadata_norm = normalize(label), normalize(metadata)
    return sum(
        (5 if contains_normalized_token(label_norm, token) else 0)
        + (1 if contains_normalized_token(metadata_norm, token) else 0)
        for token in query_tokens
    )


def document_code(label: str) -> str:
    match = re.search(r"\b(?:B-OPS|AVOP|POP|INFO[- ]?SAFE|ALERTA[- ]?SAFE|MGOP|MIP)[-_ ]?\d+(?:[-/]\d+)?\b", label, re.IGNORECASE)
    return match.group(0).upper().replace("_", "-") if match else ""


@lru_cache(maxsize=512)
def source_search_text(source_path: str) -> str:
    if not source_path or source_path.startswith(("Knowledge/", "graphify-out/")):
        return ""
    path = (KNOWLEDGE_ROOT / source_path).resolve()
    try:
        path.relative_to(KNOWLEDGE_ROOT)
    except ValueError:
        return ""
    if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
        return ""
    return normalize(path.read_text(encoding="utf-8", errors="replace")[:250_000])


def content_score(query_tokens: list[str], source_path: str) -> int:
    content = source_search_text(source_path)
    matches = sum(1 for token in query_tokens if contains_normalized_token(content, token))
    coverage_bonus = 8 if query_tokens and matches >= max(2, len(query_tokens) // 2) else 0
    return matches * 4 + coverage_bonus


def source_excerpt(source_path: str, location: str, query_tokens: list[str] | None = None, limit: int = 3000) -> str:
    path = (KNOWLEDGE_ROOT / source_path).resolve()
    try:
        path.relative_to(KNOWLEDGE_ROOT)
    except ValueError:
        return ""
    if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    numbers = [int(value) for value in re.findall(r"\d+", location or "")]
    if numbers and "toda" not in normalize(location):
        start = max(0, numbers[0] - 4)
        end = min(len(lines), (numbers[-1] if len(numbers) > 1 else numbers[0]) + 3)
        excerpt = "\n".join(lines[start:end])
    elif query_tokens:
        ranked = sorted(
            ((sum(1 for token in query_tokens if token in normalize(line)), index) for index, line in enumerate(lines)),
            reverse=True,
        )
        chosen, windows = [], []
        for score, index in ranked:
            if not score or any(abs(index - previous) < 12 for previous in chosen):
                continue
            chosen.append(index)
            windows.append("\n".join(lines[max(0, index - 12):min(len(lines), index + 21)]))
            if len(windows) == 3:
                break
        excerpt = "\n\n[... outro trecho relevante ...]\n\n".join(windows) if windows else "\n".join(lines[:60])
    else:
        excerpt = "\n".join(lines[:40])
    return excerpt[:limit]


def retrieve(question: str, limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = tokens(question)
    course = requested_course(question)
    question_norm = normalize(question)
    daily_limit_intent = bool(course) and any(
        term in question_norm for term in ("slot", "slots", "hora", "horas", "dia", "diaria", "diarias")
    )
    claims_data = load_json(CLAIMS_PATH)
    graph_data = load_json(GRAPH_PATH)
    results: list[dict[str, Any]] = []
    claim_ids = set()
    for claim in claims_data.get("claims", []):
        if claim.get("status") not in {"confirmed", "confirmed_temporary_override"}:
            continue
        claim_ids.add(claim["id"])
        metadata = f"{claim.get('document_code', '')} {claim.get('source_path', '')} {' '.join(claim.get('applies_to', []))}"
        if not course_compatible(course, claim.get("label", ""), metadata):
            continue
        score = score_text(query_tokens, claim.get("label", ""), metadata)
        if daily_limit_intent and (
            "limite_diario_instrucao" in claim["id"] or "limite_instrucao_local" in claim["id"]
        ):
            score += 20
        if score:
            results.append({
                "id": claim["id"], "kind": "confirmed_claim", "label": claim["label"],
                "code": claim.get("document_code", ""), "source": claim.get("source_path", ""),
                "location": claim.get("source_location", ""), "score": score,
                "excerpt": "",
            })
    for node in graph_data.get("nodes", []):
        if node.get("id") in claim_ids or not node.get("source_file"):
            continue
        metadata = f"{node.get('source_file', '')} {node.get('source_location', '')}"
        if not course_compatible(course, node.get("label", ""), metadata):
            continue
        score = score_text(query_tokens, node.get("label", ""), metadata)
        if score:
            results.append({
                "id": node["id"], "kind": "graph_node", "label": node.get("label", node["id"]),
                "code": document_code(node.get("label", "")), "source": node.get("source_file", ""),
                "location": node.get("source_location", ""), "score": score,
                "excerpt": "",
            })
    results.sort(key=lambda item: (-item["score"], item["kind"] != "confirmed_claim", item["label"].casefold()))
    results = results[:120]
    for item in results:
        item["score"] += content_score(query_tokens, item.get("source", ""))
    results.sort(key=lambda item: (-item["score"], item["kind"] != "confirmed_claim", item["label"].casefold()))
    selected, source_counts = [], {}
    kind_limits = {"confirmed_claim": 4, "graph_node": 4}
    kind_counts = {"confirmed_claim": 0, "graph_node": 0}
    for item in results:
        source_key = item.get("source") or item["id"]
        per_source_limit = 2 if item["kind"] == "confirmed_claim" else 1
        if source_counts.get(source_key, 0) >= per_source_limit or kind_counts[item["kind"]] >= kind_limits[item["kind"]]:
            continue
        selected.append(item)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        kind_counts[item["kind"]] += 1
        if len(selected) >= limit:
            break
    selected.sort(key=lambda item: (-item["score"], item["kind"] != "confirmed_claim"))
    for item in selected:
        item["excerpt"] = source_excerpt(item.get("source", ""), item.get("location", ""), query_tokens)
    return selected


def gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


def call_gemini(question: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    key = gemini_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY não configurada no processo do backend.")
    evidence_text = "\n\n".join(
        f"EVIDÊNCIA {index}\nID: {item['id']}\nTIPO: {item['kind']}\nREGRA/TÍTULO: {item['label']}\n"
        f"CÓDIGO: {item['code']}\nLOCAL: {item['location']}\nTRECHO:\n{item['excerpt']}"
        for index, item in enumerate(evidence, 1)
    )
    prompt = f"""Você é o assistente operacional do CCO da Escola SAFE.
Responda somente com base nas evidências fornecidas. Não invente regras, prazos ou permissões.
Responda diretamente o que foi perguntado. Você pode fazer inferência aritmética ou sequencial simples quando sustentada pelas evidências, deixando claro que se trata de uma conclusão lógica.
Se as evidências forem insuficientes ou conflitantes, diga isso claramente e defina confidence como low.
Prefira regras confirmadas e documentos vigentes. Seja direto e use português do Brasil.
Uma exceção ao intervalo entre atividades não é uma exceção ao limite máximo diário, a menos que a evidência diga isso expressamente.
Indique em used_evidence apenas números das evidências realmente usadas.
candidate_relations são possíveis relações conceituais percebidas na pergunta; elas serão revisadas e nunca são regras oficiais.

PERGUNTA: {question}

{evidence_text or 'NENHUMA EVIDÊNCIA LOCALIZADA'}
"""
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "used_evidence": {"type": "array", "items": {"type": "integer"}},
            "candidate_relations": {"type": "array", "items": {"type": "object", "properties": {
                "source_concept": {"type": "string"}, "target_concept": {"type": "string"},
                "relation": {"type": "string"}, "reason": {"type": "string"},
            }, "required": ["source_concept", "target_concept", "relation", "reason"]}},
        },
        "required": ["answer", "confidence", "used_evidence", "candidate_relations"],
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1000, "responseMimeType": "application/json", "responseSchema": schema},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Gemini respondeu HTTP {error.code}: {detail}") from error
    except TimeoutError as error:
        raise RuntimeError("Gemini excedeu o tempo de resposta de 90 segundos.") from error
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def load_learning_graph() -> dict[str, Any]:
    if LEARNING_GRAPH_PATH.exists():
        return load_json(LEARNING_GRAPH_PATH)
    return {"schema_version": 1, "nodes": [], "edges": [], "candidate_relations": []}


def record_learning(question: str, evidence: list[dict[str, Any]], result: dict[str, Any]) -> str:
    timestamp = now_iso()
    query_id = "query_" + hashlib.sha256(f"{timestamp}:{question}".encode("utf-8")).hexdigest()[:16]
    with WRITE_LOCK:
        graph = load_learning_graph()
        graph["nodes"].append({"id": query_id, "type": "operator_question", "label": question, "created_at": timestamp})
        used = {int(value) for value in result.get("used_evidence", []) if str(value).isdigit()}
        for index, item in enumerate(evidence, 1):
            if index in used:
                graph["edges"].append({"source": query_id, "target": item["id"], "relation": "answered_using", "status": "observed", "created_at": timestamp})
        for relation in result.get("candidate_relations", []):
            graph["candidate_relations"].append({**relation, "origin_query": query_id, "status": "pending_review", "created_at": timestamp})
        LEARNING_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEARNING_GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return query_id


def answer_question(question: str) -> dict[str, Any]:
    evidence = retrieve(question)
    result = call_gemini(question, evidence)
    used_indices = [int(value) for value in result.get("used_evidence", []) if str(value).isdigit()]
    sources = [evidence[index - 1] for index in used_indices if 1 <= index <= len(evidence)]
    query_id = record_learning(question, evidence, result)
    return {
        "query_id": query_id, "answer": result.get("answer", ""),
        "confidence": result.get("confidence", "low"), "sources": sources,
        "candidate_relations_count": len(result.get("candidate_relations", [])),
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(200, {"ok": True, "model": MODEL, "key_configured": bool(gemini_key()), "knowledge_root": str(KNOWLEDGE_ROOT)})
            return
        requested = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).lstrip("/") or "index.html"
        path = (PORTAL_ROOT / requested).resolve()
        try:
            path.relative_to(PORTAL_ROOT)
        except ValueError:
            self.send_json(403, {"error": "Caminho inválido."}); return
        if not path.is_file() or path.parts[-2:-1] == ("backend",):
            self.send_json(404, {"error": "Arquivo não encontrado."}); return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/api/ask":
            self.send_json(404, {"error": "Rota não encontrada."}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
            question = str(data.get("question", "")).strip()
            if not question or len(question) > MAX_QUESTION_LENGTH:
                self.send_json(400, {"error": "Pergunta vazia ou muito longa."}); return
            self.send_json(200, answer_question(question))
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    print(f"SAFE CCO API em http://{HOST}:{PORT} | modelo={MODEL} | conhecimento={KNOWLEDGE_ROOT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
