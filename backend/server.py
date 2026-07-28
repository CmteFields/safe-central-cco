"""Backend RAG do Portal CCO: grafo SAFE + Gemini + aprendizagem auditável."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PORTAL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_ROOT = PORTAL_ROOT.parent
KNOWLEDGE_ROOT = Path(os.environ.get("SAFE_KNOWLEDGE_ROOT", DEFAULT_KNOWLEDGE_ROOT)).resolve()
CLAIMS_PATH = KNOWLEDGE_ROOT / "Knowledge" / "claims_curated.json"
GRAPH_PATH = KNOWLEDGE_ROOT / "graphify-out" / "graph.json"
DATA_DIR = Path(os.environ.get("SAFE_CCO_DATA_DIR", PORTAL_ROOT / "data")).resolve()
PUBLIC_KNOWLEDGE_INDEX_PATH = PORTAL_ROOT / "data" / "public-knowledge-index.js"
LEARNING_GRAPH_PATH = Path(
    os.environ.get("SAFE_LEARNING_GRAPH_PATH", KNOWLEDGE_ROOT / "Knowledge" / "query_graph.json")
).resolve()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
HOST = os.environ.get("SAFE_CCO_HOST", "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
PORT = int(os.environ.get("SAFE_CCO_PORT") or os.environ.get("PORT") or "8765")
SECURE_COOKIES = os.environ.get("SAFE_CCO_SECURE_COOKIES", "").lower() in {"1", "true", "yes"} or bool(
    os.environ.get("RENDER")
)
SETUP_TOKEN = os.environ.get("SAFE_CCO_SETUP_TOKEN", "").strip()
REQUIRE_SETUP_TOKEN = os.environ.get("SAFE_CCO_REQUIRE_SETUP_TOKEN", "").lower() in {
    "1", "true", "yes"
} or bool(os.environ.get("RENDER"))
INSTRUCTORS_DB_PATH = Path(os.environ.get("SAFE_INSTRUCTORS_DB_PATH", DATA_DIR / "instructors.db")).resolve()
AIRCRAFT_DB_PATH = Path(os.environ.get("SAFE_AIRCRAFT_DB_PATH", DATA_DIR / "aircraft.db")).resolve()
BASES_DB_PATH = Path(os.environ.get("SAFE_BASES_DB_PATH", DATA_DIR / "bases.db")).resolve()
HANDOVERS_DB_PATH = Path(os.environ.get("SAFE_HANDOVERS_DB_PATH", DATA_DIR / "handovers.db")).resolve()
REPORTS_DB_PATH = Path(os.environ.get("SAFE_REPORTS_DB_PATH", DATA_DIR / "reports.db")).resolve()
SEARCH_HISTORY_DB_PATH = Path(os.environ.get("SAFE_SEARCH_HISTORY_DB_PATH", DATA_DIR / "search_history.db")).resolve()
AUTH_DB_PATH = Path(os.environ.get("SAFE_AUTH_DB_PATH", DATA_DIR / "auth.db")).resolve()
MAX_QUESTION_LENGTH = 1200
WRITE_LOCK = threading.Lock()
INSTRUCTORS_LOCK = threading.Lock()
AIRCRAFT_LOCK = threading.Lock()
BASES_LOCK = threading.Lock()
HANDOVERS_LOCK = threading.Lock()
REPORTS_LOCK = threading.Lock()
SEARCH_HISTORY_LOCK = threading.Lock()
AUTH_LOCK = threading.Lock()
STOPWORDS = {"a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em", "na", "no", "para", "por", "com", "um", "uma", "que", "pode", "como", "safe", "fazer", "concluir", "quantos"}

INSTRUCTOR_SEED = [
    ("KEVIN WAJIMA", "SJK", "INVA", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado IFR Avião"]),
    ("DALAQUA (Part Time)", "SJK", "INVA", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)"]),
    ("KLEBER (Eventual)", "SJK", "INVA", ["Liberado MC01", "Liberado IFR Avião"]),
    ("DIEGO SOARES (Part Time)", "SJK", "INVA", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)"]),
    ("VIVIAN (Eventual)", "SJK", "INVA", ["Liberado MC01", "Liberado C150", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)", "Instrutor Eventual"]),
    ("BERNARDO BANDEIRA (Eventual)", "SJK", "INVA", ["Liberado MC01", "Liberado C150", "Instrutor Eventual"]),
    ("DANIEL BRUM (Eventual)", "SJK", "INVA", ["Liberado MC01", "Instrutor Eventual"]),
    ("ISABELA GARCIA (Eventual)", "SJK", "INVA", ["Liberado MC01", "Instrutor Eventual"]),
    ("DANILO LIRA (Eventual)", "SJK", "INVA", ["Liberado MC01", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)", "Instrutor Eventual"]),
    ("LUAN SANTANA (Eventual)", "SJK", "INVA", ["Liberado MC01", "Instrutor Eventual"]),
    ("MAYSON VICENTE (Eventual)", "SJK", "INVA", ["Instrutor Eventual"]),
    ("PINHO", "SJK", "INVA Solo", ["Liberado MC01", "Liberado P-Mentor VFR/IFR SIC"]),
    ("CAÍQUE DUARTE", "SJK", "INVA Solo", ["Liberado MC01", "Liberado P-Mentor VFR/IFR SIC", "Liberado COLT"]),
    ("MILENA MADELA", "SJK", "INVA Solo", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado COLT"]),
    ("ERIK SUZUKI", "SJK", "INVA Solo", ["Liberado MC01", "Liberado P-Mentor VFR/IFR SIC"]),
    ("GUSTAVO ABBEGG (Part Time)", "CPQ", "INVA", ["Liberado MC01", "Liberado C150", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)"]),
    ("LUIZ QUAGLIA (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT"]),
    ("PEDRO SALES (Part Time)", "CPQ", "INVA", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)"]),
    ("EDUARDO GEVINSKI (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT", "Liberado IFR AATD", "Liberado IFR PCATD (Laboratório)", "Instrutor Eventual"]),
    ("LUCAS PAIVA (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT", "Instrutor Eventual"]),
    ("LANY AMORIM (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT", "Instrutor Eventual"]),
    ("JOSÉ FELIPE (Eventual)", "CPQ", "INVA", ["Instrutor Eventual", "Liberado COLT"]),
    ("IAN GAIECKI (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT", "Instrutor Eventual"]),
    ("WILLARD (Eventual)", "CPQ", "INVA", ["Liberado MC01", "Liberado COLT"]),
    ("THEO", "CPQ", "INVA Solo", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado COLT"]),
    ("JHONY", "CPQ", "INVA Solo", ["Liberado MC01", "Liberado C150", "Liberado P-Mentor VFR/IFR SIC", "Liberado COLT"]),
]

AIRCRAFT_SEED = [
    ("Tecnam P-Mentor", "PS-SFP", "Não informada", "Operacional", "IFR (RNAV/PBN)", "Nenhuma", "Nenhuma", None),
    ("Inpaer COLT 100", "PS-SFJ", "Não informada", "Operacional", "IFR Capota / VFR Noturno", "Nenhuma", "Nenhuma", None),
    ("Inpaer COLT 100", "PS-SFL", "Não informada", "Operacional", "IFR Capota / VFR Noturno", "Nenhuma", "Nenhuma", None),
    ("Montaer MC-01", "PS-LOM", "Não informada", "Operacional", "IFR Capota / VFR Noturno", "Nenhuma", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFI", "Não informada", "Operacional", "VFR Noturno", "Restrita a voos VFR (não homologada para IFR)", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFE", "Não informada", "Operacional", "IFR Capota, Diurno", "Restrita a IFR Capota Diurno (não homologada para voos noturnos)", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFH", "Não informada", "Operacional", "VFR Diurno", "Restrita a voos VFR Diurnos (não homologada para IFR ou voos noturnos)", "Nenhuma", None),
    ("Cessna 150", "PS-CRS", "Não informada", "Fora de Operação", "Não listada", "Fora de operação (não consta nas certificações ativas)", "Nenhuma", None),
]

BASE_SEED = [
    ("SJK", "São José dos Campos", "Ativa"),
    ("CPQ", "Campinas", "Ativa"),
]

SHIFTS = {
    "T1": "08:00–14:00",
    "T2": "12:00–18:00",
    "T3": "18:00–20:00",
}
HANDOVER_PRIORITIES = {"Baixa", "Normal", "Alta", "Crítica"}
HANDOVER_STATUSES = {"Pendente", "Em andamento", "Concluída"}
REPORT_TYPES = {"discrepancy": "Discrepância", "question": "Indicação de pergunta"}
REPORT_PRIORITIES = {"Baixa", "Normal", "Alta", "Crítica"}
REPORT_STATUSES = {"Aberto", "Em análise", "Resolvido", "Descartado"}
GENERAL_CMA_RULE_IDS = {
    "claim_rbac61_cma_vencido_impede_prerrogativas",
    "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma",
}
ROLES = {"admin", "supervisor", "operator", "viewer"}
ROLE_LABELS = {"admin": "Administrador", "supervisor": "Supervisor", "operator": "Operador", "viewer": "Consulta"}
SESSION_HOURS = 12
PASSWORD_ITERATIONS = 310_000


@contextmanager
def auth_connection():
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AUTH_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_auth_db() -> None:
    with AUTH_LOCK, auth_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS admin_edit_grants (
            token_hash TEXT PRIMARY KEY,
            acting_user_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt.hex(), digest.hex()


def validate_password(password: str) -> None:
    if not password or len(password) > 200:
        raise ValueError("Informe uma senha válida.")


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "username": row["username"], "display_name": row["display_name"],
        "role": row["role"], "role_label": ROLE_LABELS.get(row["role"], row["role"]),
        "active": bool(row["active"]), "must_change_password": bool(row["must_change_password"]),
    }


def auth_setup_required() -> bool:
    initialize_auth_db()
    with auth_connection() as connection:
        return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def authorize_initial_setup(data: dict[str, Any]) -> None:
    if not REQUIRE_SETUP_TOKEN:
        return
    if not SETUP_TOKEN:
        raise RuntimeError("Configuração segura incompleta: defina SAFE_CCO_SETUP_TOKEN no servidor.")
    supplied = str(data.get("setup_token", ""))
    if not secrets.compare_digest(supplied, SETUP_TOKEN):
        raise PermissionError("Código de implantação inválido.")


def create_user(data: dict[str, Any], force_admin: bool = False) -> dict[str, Any]:
    initialize_auth_db()
    username = str(data.get("username", "")).strip().lower()
    display_name = str(data.get("display_name", "")).strip()
    password = str(data.get("password", ""))
    role = "admin" if force_admin else str(data.get("role", "")).strip()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise ValueError("Usuário deve ter de 3 a 40 caracteres: letras, números, ponto, hífen ou sublinhado.")
    if not display_name or len(display_name) > 100 or role not in ROLES:
        raise ValueError("Nome ou perfil inválido.")
    validate_password(password)
    salt, digest = hash_password(password)
    timestamp = now_iso()
    with AUTH_LOCK, auth_connection() as connection:
        if force_admin and connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            raise ValueError("O administrador inicial já foi configurado.")
        try:
            cursor = connection.execute(
                """INSERT INTO users(username, display_name, password_hash, password_salt, role, active,
                   must_change_password, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (username, display_name, digest, salt, role, 0 if force_admin else 1, timestamp, timestamp),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Este nome de usuário já existe.") from error
        row = connection.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    return public_user(row)


def authenticate(username: str, password: str) -> tuple[dict[str, Any], str, str]:
    initialize_auth_db()
    with auth_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
        if not row or not row["active"]:
            raise PermissionError("Usuário ou senha inválidos.")
        _, digest = hash_password(password, bytes.fromhex(row["password_salt"]))
        if not secrets.compare_digest(digest, row["password_hash"]):
            raise PermissionError("Usuário ou senha inválidos.")
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        csrf = secrets.token_urlsafe(24)
        created = datetime.now(timezone.utc)
        expires = created.timestamp() + SESSION_HOURS * 3600
        expires_iso = datetime.fromtimestamp(expires, timezone.utc).isoformat()
        connection.execute("DELETE FROM sessions WHERE expires_at < ?", (created.isoformat(),))
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, row["id"], csrf, expires_iso, created.isoformat()),
        )
    return public_user(row), raw_token, csrf


def session_user(cookie_header: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    initialize_auth_db()
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header or "")
    except Exception:
        return None, None, None
    morsel = cookie.get("cco_session")
    if not morsel:
        return None, None, None
    raw_token = morsel.value
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with auth_connection() as connection:
        row = connection.execute(
            """SELECT u.*, s.csrf_token, s.expires_at FROM sessions s
               JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""", (token_hash,)
        ).fetchone()
        if not row or not row["active"] or row["expires_at"] <= now_iso():
            if row:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            return None, None, None
    return public_user(row), row["csrf_token"], token_hash


def list_users() -> list[dict[str, Any]]:
    initialize_auth_db()
    with auth_connection() as connection:
        rows = connection.execute("SELECT * FROM users ORDER BY display_name").fetchall()
    return [public_user(row) for row in rows]


def authorize_admin_edit(acting_user_id: int, target_user_id: int, password: str) -> str:
    initialize_auth_db()
    timestamp = datetime.now(timezone.utc)
    with AUTH_LOCK, auth_connection() as connection:
        target = connection.execute("SELECT * FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not target:
            raise LookupError("Usuário não encontrado.")
        if target["role"] != "admin":
            raise ValueError("Esta confirmação é exclusiva para contas de Administrador.")
        _, supplied_digest = hash_password(password, bytes.fromhex(target["password_salt"]))
        if not secrets.compare_digest(supplied_digest, target["password_hash"]):
            raise PermissionError("Senha do Administrador incorreta.")
        raw_token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.fromtimestamp(timestamp.timestamp() + 300, timezone.utc).isoformat()
        connection.execute("DELETE FROM admin_edit_grants WHERE expires_at < ?", (timestamp.isoformat(),))
        connection.execute(
            "INSERT INTO admin_edit_grants(token_hash, acting_user_id, target_user_id, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, acting_user_id, target_user_id, expires_at, timestamp.isoformat()),
        )
    return raw_token


def update_user(user_id: int, data: dict[str, Any], acting_user_id: int) -> dict[str, Any]:
    display_name = str(data.get("display_name", "")).strip()
    role = str(data.get("role", "")).strip()
    active = bool(data.get("active", True))
    if not display_name or len(display_name) > 100 or role not in ROLES:
        raise ValueError("Nome ou perfil inválido.")
    timestamp = now_iso()
    with AUTH_LOCK, auth_connection() as connection:
        current = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not current:
            raise LookupError("Usuário não encontrado.")
        if current["role"] == "admin":
            raw_grant = str(data.get("admin_edit_token", ""))
            grant_hash = hashlib.sha256(raw_grant.encode()).hexdigest()
            grant = connection.execute(
                """SELECT * FROM admin_edit_grants WHERE token_hash=? AND acting_user_id=?
                   AND target_user_id=? AND expires_at>?""",
                (grant_hash, acting_user_id, user_id, now_iso()),
            ).fetchone()
            if not grant:
                raise PermissionError("Confirme a senha do Administrador antes de editar esta conta.")
        removing_admin_access = current["role"] == "admin" and (not active or role != "admin")
        if removing_admin_access:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Não é possível remover o último Administrador ativo.")
        if current["role"] == "admin":
            connection.execute("DELETE FROM admin_edit_grants WHERE token_hash=?", (grant_hash,))
        cursor = connection.execute(
            "UPDATE users SET display_name=?, role=?, active=?, updated_at=? WHERE id=?",
            (display_name, role, int(active), timestamp, user_id),
        )
        if not active or role != current["role"]:
            connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return public_user(row)


def reset_user_password(user_id: int, password: str, acting_user_id: int, edit_token: str = "") -> None:
    validate_password(password)
    salt, digest = hash_password(password)
    with AUTH_LOCK, auth_connection() as connection:
        target = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise LookupError("Usuário não encontrado.")
        if target["role"] == "admin":
            token_hash = hashlib.sha256(edit_token.encode()).hexdigest()
            grant = connection.execute(
                """SELECT * FROM admin_edit_grants WHERE token_hash=? AND acting_user_id=?
                   AND target_user_id=? AND expires_at>?""",
                (token_hash, acting_user_id, user_id, now_iso()),
            ).fetchone()
            if not grant:
                raise PermissionError("Confirme a senha do Administrador antes de redefinir esta conta.")
            connection.execute("DELETE FROM admin_edit_grants WHERE token_hash=?", (token_hash,))
        cursor = connection.execute(
            "UPDATE users SET password_hash=?, password_salt=?, must_change_password=1, updated_at=? WHERE id=?",
            (digest, salt, now_iso(), user_id),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def change_own_password(user_id: int, current_password: str, new_password: str) -> None:
    validate_password(new_password)
    with AUTH_LOCK, auth_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise LookupError("Usuário não encontrado.")
        _, current_digest = hash_password(current_password, bytes.fromhex(row["password_salt"]))
        if not secrets.compare_digest(current_digest, row["password_hash"]):
            raise PermissionError("Senha atual inválida.")
        salt, digest = hash_password(new_password)
        connection.execute(
            "UPDATE users SET password_hash=?, password_salt=?, must_change_password=0, updated_at=? WHERE id=?",
            (digest, salt, now_iso(), user_id),
        )


@contextmanager
def search_history_connection():
    SEARCH_HISTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SEARCH_HISTORY_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_search_history_db() -> None:
    with SEARCH_HISTORY_LOCK, search_history_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS search_history (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            response_mode TEXT NOT NULL,
            confidence TEXT NOT NULL,
            result_json TEXT,
            presentation_json TEXT,
            knowledge_version TEXT,
            created_at TEXT NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_search_history_created ON search_history(created_at DESC)")


def save_search_history(
    question: str, response_mode: str, confidence: str,
    result: dict[str, Any] | None = None, presentation: dict[str, Any] | None = None,
    record_id: str | None = None,
) -> str:
    initialize_search_history_db()
    clean_question = question.strip()
    if not clean_question or len(clean_question) > MAX_QUESTION_LENGTH:
        raise ValueError("Pergunta inválida para o histórico.")
    if response_mode not in {"ai", "local"}:
        raise ValueError("Modo de resposta inválido.")
    timestamp = now_iso()
    record_id = record_id or "search_" + hashlib.sha256(f"{timestamp}:{clean_question}".encode("utf-8")).hexdigest()[:16]
    knowledge_version = (
        datetime.fromtimestamp(CLAIMS_PATH.stat().st_mtime, timezone.utc).isoformat()
        if CLAIMS_PATH.exists() else ""
    )
    with SEARCH_HISTORY_LOCK, search_history_connection() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO search_history
               (id, question, response_mode, confidence, result_json, presentation_json, knowledge_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id, clean_question, response_mode, confidence,
                json.dumps(result, ensure_ascii=False) if result else None,
                json.dumps(presentation, ensure_ascii=False) if presentation else None,
                knowledge_version, timestamp,
            ),
        )
    return record_id


def list_search_history(limit: int = 10) -> list[dict[str, Any]]:
    initialize_search_history_db()
    limit = max(1, min(limit, 100))
    with search_history_connection() as connection:
        rows = connection.execute(
            """SELECT id, question, response_mode, confidence, knowledge_version, created_at
               FROM search_history ORDER BY created_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_search_history(record_id: str) -> dict[str, Any]:
    initialize_search_history_db()
    with search_history_connection() as connection:
        row = connection.execute("SELECT * FROM search_history WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise LookupError("Pesquisa não encontrada.")
    item = dict(row)
    item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
    item["presentation"] = json.loads(item.pop("presentation_json")) if item["presentation_json"] else None
    return item


@contextmanager
def bases_connection():
    BASES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(BASES_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_bases_db() -> None:
    with BASES_LOCK, bases_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS bases (
            code TEXT PRIMARY KEY COLLATE NOCASE,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        if connection.execute("SELECT COUNT(*) FROM bases").fetchone()[0] == 0:
            timestamp = now_iso()
            connection.executemany(
                "INSERT INTO bases(code, name, status, updated_at) VALUES (?, ?, ?, ?)",
                [(*item, timestamp) for item in BASE_SEED],
            )


def list_bases(active_only: bool = False) -> list[dict[str, Any]]:
    initialize_bases_db()
    with bases_connection() as connection:
        query = "SELECT * FROM bases"
        if active_only:
            query += " WHERE status='Ativa'"
        rows = connection.execute(query + " ORDER BY code").fetchall()
    return [{"code": row["code"], "name": row["name"], "status": row["status"], "updated_at": row["updated_at"]} for row in rows]


def validate_base_code(code: str, allow_unassigned: bool = False) -> str:
    normalized = code.strip().upper()
    if allow_unassigned and normalized in {"", "NÃO INFORMADA", "NAO INFORMADA"}:
        return "Não informada"
    valid_codes = {item["code"].upper() for item in list_bases(active_only=True)}
    if normalized not in valid_codes:
        raise ValueError("Selecione uma base ativa cadastrada.")
    return normalized


@contextmanager
def handovers_connection():
    HANDOVERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(HANDOVERS_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_handovers_db() -> None:
    with HANDOVERS_LOCK, handovers_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS handovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_shift TEXT NOT NULL,
            target_shift TEXT NOT NULL,
            message TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handovers_status ON handovers(status, updated_at)")


def handover_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "origin_shift": row["origin_shift"], "target_shift": row["target_shift"],
        "message": row["message"], "priority": row["priority"], "status": row["status"],
        "author": row["author"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def validate_handover(data: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    origin = str(data.get("origin_shift", "")).strip().upper()
    target = str(data.get("target_shift", "")).strip().upper()
    message = str(data.get("message", "")).strip()
    priority = str(data.get("priority", "Normal")).strip()
    status = str(data.get("status", "Pendente")).strip()
    author = str(data.get("author", "")).strip()
    if origin not in SHIFTS or target not in SHIFTS:
        raise ValueError("Selecione turnos de origem e destino válidos.")
    if origin == target:
        raise ValueError("O turno de destino deve ser diferente do turno de origem.")
    if not message or len(message) > 2000:
        raise ValueError("Informe uma mensagem de até 2.000 caracteres.")
    if priority not in HANDOVER_PRIORITIES or status not in HANDOVER_STATUSES:
        raise ValueError("Prioridade ou situação inválida.")
    if not author or len(author) > 100:
        raise ValueError("Informe quem está deixando a passagem.")
    return origin, target, message, priority, status, author


def list_handovers() -> list[dict[str, Any]]:
    initialize_handovers_db()
    with handovers_connection() as connection:
        rows = connection.execute(
            """SELECT * FROM handovers ORDER BY
               CASE status WHEN 'Pendente' THEN 0 WHEN 'Em andamento' THEN 1 ELSE 2 END,
               CASE priority WHEN 'Crítica' THEN 0 WHEN 'Alta' THEN 1 WHEN 'Normal' THEN 2 ELSE 3 END,
               updated_at DESC"""
        ).fetchall()
    return [handover_dict(row) for row in rows]


def save_handover(data: dict[str, Any], handover_id: int | None = None) -> dict[str, Any]:
    values = validate_handover(data)
    timestamp = now_iso()
    completed_at = timestamp if values[4] == "Concluída" else None
    with HANDOVERS_LOCK, handovers_connection() as connection:
        if handover_id is None:
            cursor = connection.execute(
                """INSERT INTO handovers(origin_shift, target_shift, message, priority, status, author,
                   created_at, updated_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, timestamp, timestamp, completed_at),
            )
            handover_id = cursor.lastrowid
        else:
            cursor = connection.execute(
                """UPDATE handovers SET origin_shift=?, target_shift=?, message=?, priority=?, status=?,
                   author=?, updated_at=?, completed_at=? WHERE id=?""",
                (*values, timestamp, completed_at, handover_id),
            )
            if not cursor.rowcount:
                raise LookupError("Passagem de turno não encontrada.")
        row = connection.execute("SELECT * FROM handovers WHERE id=?", (handover_id,)).fetchone()
    return handover_dict(row)


def delete_handover(handover_id: int) -> None:
    with HANDOVERS_LOCK, handovers_connection() as connection:
        cursor = connection.execute("DELETE FROM handovers WHERE id=?", (handover_id,))
        if not cursor.rowcount:
            raise LookupError("Passagem de turno não encontrada.")


@contextmanager
def reports_connection():
    REPORTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(REPORTS_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_reports_db() -> None:
    with REPORTS_LOCK, reports_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            reference TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            reporter_user_id INTEGER NOT NULL,
            reporter_username TEXT NOT NULL,
            reporter_name TEXT NOT NULL,
            resolution TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS report_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, priority, updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_report_events_report ON report_events(report_id, created_at)")


def report_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "report_type": row["report_type"],
        "type_label": REPORT_TYPES.get(row["report_type"], row["report_type"]),
        "title": row["title"],
        "description": row["description"],
        "reference": row["reference"],
        "priority": row["priority"],
        "status": row["status"],
        "reporter_username": row["reporter_username"],
        "reporter_name": row["reporter_name"],
        "resolution": row["resolution"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
    }


def validate_new_report(data: dict[str, Any]) -> tuple[str, str, str, str, str]:
    report_type = str(data.get("report_type", "")).strip()
    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    reference = str(data.get("reference", "")).strip()
    priority = str(data.get("priority", "Normal")).strip()
    if report_type not in REPORT_TYPES:
        raise ValueError("Selecione um tipo de report válido.")
    if not title or len(title) > 160:
        raise ValueError("Informe um título de até 160 caracteres.")
    if not description or len(description) > 3000:
        raise ValueError("Descreva o report em até 3.000 caracteres.")
    if len(reference) > 500:
        raise ValueError("A referência deve ter até 500 caracteres.")
    if priority not in REPORT_PRIORITIES:
        raise ValueError("Selecione uma prioridade válida.")
    return report_type, title, description, reference, priority


def list_reports() -> list[dict[str, Any]]:
    initialize_reports_db()
    with reports_connection() as connection:
        rows = connection.execute(
            """SELECT * FROM reports ORDER BY
               CASE status WHEN 'Aberto' THEN 0 WHEN 'Em análise' THEN 1
                   WHEN 'Resolvido' THEN 2 ELSE 3 END,
               CASE priority WHEN 'Crítica' THEN 0 WHEN 'Alta' THEN 1
                   WHEN 'Normal' THEN 2 ELSE 3 END,
               updated_at DESC"""
        ).fetchall()
    return [report_dict(row) for row in rows]


def create_report(data: dict[str, Any], reporter: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    values = validate_new_report(data)
    timestamp = now_iso()
    with REPORTS_LOCK, reports_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO reports(report_type, title, description, reference, priority, status,
               reporter_user_id, reporter_username, reporter_name, resolution, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'Aberto', ?, ?, ?, '', ?, ?)""",
            (*values, reporter["id"], reporter["username"], reporter["display_name"], timestamp, timestamp),
        )
        report_id = int(cursor.lastrowid)
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Criado', ?, ?, ?, ?)""",
            (
                report_id,
                reporter["username"],
                reporter["display_name"],
                json.dumps({"report_type": values[0], "priority": values[4]}, ensure_ascii=False),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    return report_dict(row)


def update_report(report_id: int, data: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    priority = str(data.get("priority", "")).strip()
    status = str(data.get("status", "")).strip()
    resolution = str(data.get("resolution", "")).strip()
    if priority not in REPORT_PRIORITIES or status not in REPORT_STATUSES:
        raise ValueError("Prioridade ou situação do report inválida.")
    if len(resolution) > 2000:
        raise ValueError("A tratativa deve ter até 2.000 caracteres.")
    if status in {"Resolvido", "Descartado"} and not resolution:
        raise ValueError("Registre a tratativa antes de encerrar o report.")
    timestamp = now_iso()
    resolved_at = timestamp if status in {"Resolvido", "Descartado"} else None
    with REPORTS_LOCK, reports_connection() as connection:
        current = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not current:
            raise LookupError("Report não encontrado.")
        changes = {
            "status": {"from": current["status"], "to": status},
            "priority": {"from": current["priority"], "to": priority},
            "resolution_updated": resolution != current["resolution"],
        }
        connection.execute(
            """UPDATE reports SET priority=?, status=?, resolution=?, updated_at=?, resolved_at=?
               WHERE id=?""",
            (priority, status, resolution, timestamp, resolved_at, report_id),
        )
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Atualizado', ?, ?, ?, ?)""",
            (
                report_id,
                actor["username"],
                actor["display_name"],
                json.dumps(changes, ensure_ascii=False),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    return report_dict(row)


@contextmanager
def instructor_connection():
    INSTRUCTORS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(INSTRUCTORS_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_instructors_db() -> None:
    with INSTRUCTORS_LOCK, instructor_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS instructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE,
            base TEXT NOT NULL,
            group_name TEXT NOT NULL,
            releases TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_instructors_name ON instructors(name)")
        if connection.execute("SELECT COUNT(*) FROM instructors").fetchone()[0] == 0:
            timestamp = now_iso()
            connection.executemany(
                "INSERT INTO instructors(name, base, group_name, releases, updated_at) VALUES (?, ?, ?, ?, ?)",
                [(name, base, group, json.dumps(releases, ensure_ascii=False), timestamp) for name, base, group, releases in INSTRUCTOR_SEED],
            )


def instructor_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "base": row["base"],
        "group": row["group_name"], "releases": json.loads(row["releases"]),
        "updated_at": row["updated_at"],
    }


def validate_instructor(data: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    name = str(data.get("name", "")).strip()
    base = validate_base_code(str(data.get("base", "")))
    group = str(data.get("group", "")).strip()
    releases = data.get("releases", [])
    if not name or len(name) > 120 or not base or len(base) > 20 or not group or len(group) > 50:
        raise ValueError("Preencha instrutor, base e grupo com valores válidos.")
    if not isinstance(releases, list) or len(releases) > 30:
        raise ValueError("Liberações inválidas.")
    clean_releases = list(dict.fromkeys(str(value).strip() for value in releases if str(value).strip()))
    if any(len(value) > 100 for value in clean_releases):
        raise ValueError("Uma das liberações é muito longa.")
    return name, base, group, clean_releases


def list_instructors() -> list[dict[str, Any]]:
    initialize_instructors_db()
    with instructor_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM instructors ORDER BY CASE base WHEN 'SJK' THEN 0 WHEN 'CPQ' THEN 1 ELSE 2 END, name"
        ).fetchall()
    return [instructor_dict(row) for row in rows]


def save_instructor(data: dict[str, Any], instructor_id: int | None = None) -> dict[str, Any]:
    name, base, group, releases = validate_instructor(data)
    timestamp = now_iso()
    with INSTRUCTORS_LOCK, instructor_connection() as connection:
        if instructor_id is None:
            cursor = connection.execute(
                "INSERT INTO instructors(name, base, group_name, releases, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, base, group, json.dumps(releases, ensure_ascii=False), timestamp),
            )
            instructor_id = cursor.lastrowid
        else:
            cursor = connection.execute(
                "UPDATE instructors SET name=?, base=?, group_name=?, releases=?, updated_at=? WHERE id=?",
                (name, base, group, json.dumps(releases, ensure_ascii=False), timestamp, instructor_id),
            )
            if not cursor.rowcount:
                raise LookupError("Instrutor não encontrado.")
        row = connection.execute("SELECT * FROM instructors WHERE id=?", (instructor_id,)).fetchone()
    return instructor_dict(row)


def delete_instructor(instructor_id: int) -> None:
    with INSTRUCTORS_LOCK, instructor_connection() as connection:
        cursor = connection.execute("DELETE FROM instructors WHERE id=?", (instructor_id,))
        if not cursor.rowcount:
            raise LookupError("Instrutor não encontrado.")


@contextmanager
def aircraft_connection():
    AIRCRAFT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AIRCRAFT_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_aircraft_db() -> None:
    with AIRCRAFT_LOCK, aircraft_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS aircraft (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            registration TEXT NOT NULL COLLATE NOCASE UNIQUE,
            base TEXT NOT NULL,
            operational_status TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            active_restrictions TEXT NOT NULL,
            temporary_restrictions TEXT NOT NULL,
            restriction_date TEXT,
            updated_at TEXT NOT NULL
        )""")
        connection.execute("UPDATE aircraft SET operational_status='Operacional' WHERE operational_status='Ativa'")
        connection.execute("UPDATE aircraft SET operational_status='Fora de Operação' WHERE operational_status='Inativa'")
        connection.execute("UPDATE aircraft SET operational_status='Em Manutenção' WHERE operational_status='Manutenção'")
        if connection.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0] == 0:
            timestamp = now_iso()
            connection.executemany(
                """INSERT INTO aircraft(model, registration, base, operational_status, operation_type,
                   active_restrictions, temporary_restrictions, restriction_date, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(*item, timestamp) for item in AIRCRAFT_SEED],
            )


def aircraft_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "model": row["model"], "registration": row["registration"],
        "base": row["base"], "status": row["operational_status"],
        "operation_type": row["operation_type"], "active_restrictions": row["active_restrictions"],
        "temporary_restrictions": row["temporary_restrictions"],
        "restriction_date": row["restriction_date"], "updated_at": row["updated_at"],
    }


def validate_aircraft(data: dict[str, Any]) -> tuple[str, ...]:
    values = (
        str(data.get("model", "")).strip(),
        str(data.get("registration", "")).strip().upper(),
        validate_base_code(str(data.get("base", "")), allow_unassigned=True),
        str(data.get("status", "")).strip(),
        str(data.get("operation_type", "")).strip(),
        str(data.get("active_restrictions", "")).strip() or "Nenhuma",
        str(data.get("temporary_restrictions", "")).strip() or "Nenhuma",
        str(data.get("restriction_date") or "").strip(),
    )
    if any(not value for value in values[:5]) or any(len(value) > 500 for value in values):
        raise ValueError("Preencha modelo, matrícula, base, status e tipo de operação com valores válidos.")
    if values[7] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[7]):
        raise ValueError("Data da restrição inválida.")
    return values


def list_aircraft() -> list[dict[str, Any]]:
    initialize_aircraft_db()
    with aircraft_connection() as connection:
        rows = connection.execute("SELECT * FROM aircraft ORDER BY operational_status, model, registration").fetchall()
    return [aircraft_dict(row) for row in rows]


def save_aircraft(data: dict[str, Any], aircraft_id: int | None = None) -> dict[str, Any]:
    values = validate_aircraft(data)
    timestamp = now_iso()
    with AIRCRAFT_LOCK, aircraft_connection() as connection:
        try:
            if aircraft_id is None:
                cursor = connection.execute(
                    """INSERT INTO aircraft(model, registration, base, operational_status, operation_type,
                       active_restrictions, temporary_restrictions, restriction_date, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, NULLIF(?, ''), ?)""", (*values, timestamp),
                )
                aircraft_id = cursor.lastrowid
            else:
                cursor = connection.execute(
                    """UPDATE aircraft SET model=?, registration=?, base=?, operational_status=?, operation_type=?,
                       active_restrictions=?, temporary_restrictions=?, restriction_date=NULLIF(?, ''), updated_at=? WHERE id=?""",
                    (*values, timestamp, aircraft_id),
                )
                if not cursor.rowcount:
                    raise LookupError("Aeronave não encontrada.")
        except sqlite3.IntegrityError as error:
            raise ValueError("Já existe uma aeronave com esta matrícula.") from error
        row = connection.execute("SELECT * FROM aircraft WHERE id=?", (aircraft_id,)).fetchone()
    return aircraft_dict(row)


def delete_aircraft(aircraft_id: int) -> None:
    with AIRCRAFT_LOCK, aircraft_connection() as connection:
        cursor = connection.execute("DELETE FROM aircraft WHERE id=?", (aircraft_id,))
        if not cursor.rowcount:
            raise LookupError("Aeronave não encontrada.")


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


@lru_cache(maxsize=4)
def load_public_knowledge_index(path_value: str) -> dict[str, Any]:
    content = Path(path_value).read_text(encoding="utf-8")
    _, separator, payload = content.partition("=")
    if not separator:
        raise ValueError("Índice público de conhecimento inválido.")
    return json.loads(payload.strip().removesuffix(";"))


def retrieve_public_claims(question: str, limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = tokens(question)
    course = requested_course(question)
    question_norm = normalize(question)
    medical_intent = "cma" in query_tokens or "certificado medico" in question_norm
    medical_enrollment_intent = medical_intent and "matricul" in question_norm
    medical_validity_intent = medical_intent and any(
        term in question_norm for term in ("vencid", "validade", "extens", "prorrog", "tolerancia", "30 dias")
    )
    medical_operation_intent = medical_intent and any(
        term in question_norm for term in ("voar", "voo", "operar", "operacao", "prerrogativ")
    )
    daily_limit_intent = bool(course) and any(
        term in question_norm for term in ("slot", "slots", "hora", "horas", "dia", "diaria", "diarias")
    )
    results = []
    public_index = load_public_knowledge_index(str(PUBLIC_KNOWLEDGE_INDEX_PATH))
    for claim in public_index.get("claims", []):
        metadata = f"{claim.get('code', '')} {claim.get('appliesTo', '')} {claim.get('relation', '')}"
        medical_text = normalize(f"{claim.get('label', '')} {metadata}")
        if medical_intent and "cma" not in medical_text and "certificado medico" not in medical_text:
            continue
        if (
            (medical_validity_intent or medical_operation_intent)
            and claim["id"] not in GENERAL_CMA_RULE_IDS
            and any(term in medical_text for term in ("matricula", "endosso", "cheque"))
        ):
            continue
        if not course_compatible(course, claim.get("label", ""), metadata):
            continue
        score = score_text(query_tokens, claim.get("label", ""), metadata)
        if medical_enrollment_intent and "matricula" in medical_text:
            score += 20
        if medical_validity_intent or medical_operation_intent:
            if claim["id"] in GENERAL_CMA_RULE_IDS:
                score += 35
            elif "matricula" in medical_text:
                score -= 15
        if daily_limit_intent and "limite_diario_instrucao" in claim.get("id", ""):
            score += 20
        if score <= 0:
            continue
        results.append({
            "id": claim["id"],
            "kind": "confirmed_claim",
            "label": claim.get("label", ""),
            "code": claim.get("code", ""),
            "source": "Índice público de regras confirmadas",
            "location": claim.get("location", ""),
            "score": score,
            "excerpt": claim.get("label", ""),
        })
    results.sort(key=lambda item: (-item["score"], item["label"].casefold()))
    return results[:limit]


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
    if not CLAIMS_PATH.is_file() or not GRAPH_PATH.is_file():
        return retrieve_public_claims(question, limit)
    query_tokens = tokens(question)
    course = requested_course(question)
    question_norm = normalize(question)
    medical_intent = "cma" in query_tokens or "certificado medico" in question_norm
    medical_enrollment_intent = medical_intent and "matricul" in question_norm
    medical_validity_intent = medical_intent and any(
        term in question_norm for term in ("vencid", "validade", "extens", "prorrog", "tolerancia", "30 dias")
    )
    medical_operation_intent = medical_intent and any(
        term in question_norm for term in ("voar", "voo", "operar", "operacao", "prerrogativ")
    )
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
        medical_text = normalize(f"{claim.get('label', '')} {metadata}")
        if medical_intent and "cma" not in medical_text and "certificado medico" not in medical_text:
            continue
        if (
            (medical_validity_intent or medical_operation_intent)
            and claim["id"] not in GENERAL_CMA_RULE_IDS
            and any(term in medical_text for term in ("matricula", "endosso", "cheque"))
        ):
            continue
        if not course_compatible(course, claim.get("label", ""), metadata):
            continue
        score = score_text(query_tokens, claim.get("label", ""), metadata)
        if medical_enrollment_intent and "matricula" in medical_text:
            score += 20
        if medical_validity_intent or medical_operation_intent:
            if claim["id"] in GENERAL_CMA_RULE_IDS:
                score += 35
            elif "matricula" in medical_text:
                score -= 15
        if daily_limit_intent and (
            "limite_diario_instrucao" in claim["id"] or "limite_instrucao_local" in claim["id"]
        ):
            score += 20
        if score > 0:
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
        medical_text = normalize(f"{node.get('label', '')} {metadata}")
        if medical_intent and "cma" not in medical_text and "certificado medico" not in medical_text:
            continue
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
        "generationConfig": {"maxOutputTokens": 1000, "responseMimeType": "application/json", "responseSchema": schema},
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
    payload = {
        "query_id": query_id, "answer": result.get("answer", ""),
        "confidence": result.get("confidence", "low"), "sources": sources,
        "candidate_relations_count": len(result.get("candidate_relations", [])),
    }
    save_search_history(question, "ai", payload["confidence"], result=payload, record_id=query_id)
    return payload


class Handler(BaseHTTPRequestHandler):
    @staticmethod
    def session_cookie(value: str, max_age: int) -> str:
        secure = "; Secure" if SECURE_COOKIES else ""
        return f"cco_session={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def auth_context(self) -> tuple[dict[str, Any] | None, str | None, str | None]:
        return session_user(self.headers.get("Cookie", ""))

    def require_auth(self, roles: set[str] | None = None, require_csrf: bool = False) -> tuple[dict[str, Any], str] | None:
        user, csrf, _ = self.auth_context()
        if not user:
            self.send_json(401, {"error": "Autenticação necessária."})
            return None
        if roles and user["role"] not in roles:
            self.send_json(403, {"error": "Seu perfil não possui permissão para esta ação."})
            return None
        if user["must_change_password"] and self.path not in {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}:
            self.send_json(403, {"error": "Altere a senha temporária antes de continuar."})
            return None
        if require_csrf and not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf or ""):
            self.send_json(403, {"error": "Token de segurança inválido. Entre novamente."})
            return None
        return user, csrf or ""

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(200, {"ok": True})
            return
        if self.path == "/api/auth/status":
            setup_required = auth_setup_required()
            self.send_json(200, {
                "setup_required": setup_required,
                "setup_token_required": setup_required and REQUIRE_SETUP_TOKEN,
                "setup_configured": not REQUIRE_SETUP_TOKEN or bool(SETUP_TOKEN),
            })
            return
        if self.path == "/api/auth/me":
            context = self.require_auth()
            if context:
                user, csrf = context
                self.send_json(200, {"user": user, "csrf_token": csrf})
            return
        if urllib.parse.urlparse(self.path).path.startswith("/api/"):
            context = self.require_auth({"admin", "supervisor", "operator", "viewer"})
            if not context:
                return
            user, _ = context
            if urllib.parse.urlparse(self.path).path == "/api/users":
                if user["role"] != "admin":
                    self.send_json(403, {"error": "Apenas administradores podem gerenciar usuários."}); return
                self.send_json(200, {"items": list_users(), "roles": ROLE_LABELS}); return
        if urllib.parse.urlparse(self.path).path == "/api/instructors":
            self.send_json(200, {"items": list_instructors()})
            return
        if urllib.parse.urlparse(self.path).path == "/api/aircraft":
            self.send_json(200, {"items": list_aircraft()})
            return
        if urllib.parse.urlparse(self.path).path == "/api/bases":
            self.send_json(200, {"items": list_bases()})
            return
        if urllib.parse.urlparse(self.path).path == "/api/handovers":
            self.send_json(200, {"items": list_handovers(), "shifts": SHIFTS})
            return
        if urllib.parse.urlparse(self.path).path == "/api/reports":
            self.send_json(200, {
                "items": list_reports(),
                "types": REPORT_TYPES,
                "priorities": sorted(REPORT_PRIORITIES),
                "statuses": ["Aberto", "Em análise", "Resolvido", "Descartado"],
            })
            return
        if urllib.parse.urlparse(self.path).path == "/api/searches":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                limit = int(query.get("limit", ["10"])[0])
            except ValueError:
                limit = 10
            self.send_json(200, {"items": list_search_history(limit)})
            return
        search_match = re.fullmatch(r"/api/searches/([A-Za-z0-9_-]+)", urllib.parse.urlparse(self.path).path)
        if search_match:
            try:
                self.send_json(200, get_search_history(search_match.group(1)))
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
            if self.path == "/api/auth/setup":
                if not auth_setup_required():
                    self.send_json(409, {"error": "O administrador inicial já foi configurado."}); return
                authorize_initial_setup(data)
                user = create_user(data, force_admin=True)
                self.send_json(201, {"user": user}); return
            if self.path == "/api/auth/login":
                user, token, csrf = authenticate(str(data.get("username", "")), str(data.get("password", "")))
                cookie = self.session_cookie(token, SESSION_HOURS * 3600)
                self.send_json(200, {"user": user, "csrf_token": csrf}, {"Set-Cookie": cookie}); return
            context = self.require_auth({"admin", "supervisor", "operator", "viewer"}, require_csrf=True)
            if not context:
                return
            user, _ = context
            if self.path == "/api/auth/logout":
                _, _, token_hash = self.auth_context()
                if token_hash:
                    with AUTH_LOCK, auth_connection() as connection:
                        connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
                self.send_json(200, {"ok": True}, {"Set-Cookie": self.session_cookie("", 0)}); return
            if self.path == "/api/auth/change-password":
                change_own_password(user["id"], str(data.get("current_password", "")), str(data.get("new_password", "")))
                self.send_json(200, {"ok": True}); return
            if self.path == "/api/users":
                if user["role"] != "admin":
                    self.send_json(403, {"error": "Apenas administradores podem criar usuários."}); return
                self.send_json(201, create_user(data)); return
            authorize_match = re.fullmatch(r"/api/users/(\d+)/authorize-edit", self.path)
            if authorize_match:
                if user["role"] != "admin":
                    self.send_json(403, {"error": "Apenas administradores podem editar contas administrativas."}); return
                edit_token = authorize_admin_edit(
                    user["id"], int(authorize_match.group(1)), str(data.get("password", ""))
                )
                self.send_json(200, {"edit_token": edit_token, "expires_in": 300}); return
            reset_match = re.fullmatch(r"/api/users/(\d+)/reset-password", self.path)
            if reset_match:
                if user["role"] != "admin":
                    self.send_json(403, {"error": "Apenas administradores podem redefinir senhas."}); return
                reset_user_password(
                    int(reset_match.group(1)), str(data.get("password", "")), user["id"],
                    str(data.get("admin_edit_token", "")),
                )
                self.send_json(200, {"ok": True}); return
            if self.path == "/api/instructors":
                if user["role"] not in {"admin", "supervisor"}:
                    self.send_json(403, {"error": "Somente Supervisor ou Administrador pode alterar instrutores."}); return
                self.send_json(201, save_instructor(data))
                return
            if self.path == "/api/aircraft":
                if user["role"] not in {"admin", "supervisor"}:
                    self.send_json(403, {"error": "Somente Supervisor ou Administrador pode alterar aeronaves."}); return
                self.send_json(201, save_aircraft(data))
                return
            if self.path == "/api/handovers":
                if user["role"] not in {"admin", "supervisor", "operator"}:
                    self.send_json(403, {"error": "Perfil de consulta não pode registrar passagens."}); return
                self.send_json(201, save_handover(data))
                return
            if self.path == "/api/reports":
                if user["role"] not in {"admin", "supervisor", "operator"}:
                    self.send_json(403, {"error": "Perfil de consulta não pode registrar reports."}); return
                self.send_json(201, create_report(data, user))
                return
            if self.path == "/api/searches":
                record_id = save_search_history(
                    str(data.get("question", "")), "local", str(data.get("confidence", "low")),
                    presentation=data.get("presentation") if isinstance(data.get("presentation"), dict) else None,
                )
                self.send_json(201, {"id": record_id})
                return
            if self.path != "/api/ask":
                self.send_json(404, {"error": "Rota não encontrada."}); return
            question = str(data.get("question", "")).strip()
            if not question or len(question) > MAX_QUESTION_LENGTH:
                self.send_json(400, {"error": "Pergunta vazia ou muito longa."}); return
            self.send_json(200, answer_question(question))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except PermissionError as error:
            self.send_json(401, {"error": str(error)})
        except LookupError as error:
            self.send_json(404, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def do_PUT(self) -> None:
        context = self.require_auth({"admin", "supervisor", "operator", "viewer"}, require_csrf=True)
        if not context:
            return
        user, _ = context
        user_match = re.fullmatch(r"/api/users/(\d+)", urllib.parse.urlparse(self.path).path)
        if user_match:
            if user["role"] != "admin":
                self.send_json(403, {"error": "Apenas administradores podem alterar usuários."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                self.send_json(200, update_user(int(user_match.group(1)), data, user["id"]))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            except PermissionError as error:
                self.send_json(403, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            return
        report_match = re.fullmatch(r"/api/reports/(\d+)", urllib.parse.urlparse(self.path).path)
        if report_match:
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode tratar reports."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                self.send_json(200, update_report(int(report_match.group(1)), data, user))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
        handover_match = re.fullmatch(r"/api/handovers/(\d+)", urllib.parse.urlparse(self.path).path)
        if handover_match:
            if user["role"] not in {"admin", "supervisor", "operator"}:
                self.send_json(403, {"error": "Perfil de consulta não pode alterar passagens."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                self.send_json(200, save_handover(data, int(handover_match.group(1))))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
        aircraft_match = re.fullmatch(r"/api/aircraft/(\d+)", urllib.parse.urlparse(self.path).path)
        if aircraft_match:
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode alterar aeronaves."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                self.send_json(200, save_aircraft(data, int(aircraft_match.group(1))))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
        match = re.fullmatch(r"/api/instructors/(\d+)", urllib.parse.urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "Rota não encontrada."}); return
        if user["role"] not in {"admin", "supervisor"}:
            self.send_json(403, {"error": "Somente Supervisor ou Administrador pode alterar instrutores."}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
            self.send_json(200, save_instructor(data, int(match.group(1))))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except LookupError as error:
            self.send_json(404, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def do_DELETE(self) -> None:
        context = self.require_auth({"admin", "supervisor", "operator", "viewer"}, require_csrf=True)
        if not context:
            return
        user, _ = context
        handover_match = re.fullmatch(r"/api/handovers/(\d+)", urllib.parse.urlparse(self.path).path)
        if handover_match:
            if user["role"] not in {"admin", "supervisor", "operator"}:
                self.send_json(403, {"error": "Perfil de consulta não pode excluir passagens."}); return
            try:
                delete_handover(int(handover_match.group(1)))
                self.send_json(200, {"ok": True})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
        aircraft_match = re.fullmatch(r"/api/aircraft/(\d+)", urllib.parse.urlparse(self.path).path)
        if aircraft_match:
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode excluir aeronaves."}); return
            try:
                delete_aircraft(int(aircraft_match.group(1)))
                self.send_json(200, {"ok": True})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
        match = re.fullmatch(r"/api/instructors/(\d+)", urllib.parse.urlparse(self.path).path)
        if not match:
            self.send_json(404, {"error": "Rota não encontrada."}); return
        if user["role"] not in {"admin", "supervisor"}:
            self.send_json(403, {"error": "Somente Supervisor ou Administrador pode excluir instrutores."}); return
        try:
            delete_instructor(int(match.group(1)))
            self.send_json(200, {"ok": True})
        except LookupError as error:
            self.send_json(404, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    print(f"SAFE CCO API em http://{HOST}:{PORT} | modelo={MODEL} | conhecimento={KNOWLEDGE_ROOT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
