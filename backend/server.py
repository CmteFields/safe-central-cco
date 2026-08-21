"""Backend RAG do Portal CCO: grafo SAFE + Gemini + aprendizagem auditável."""

from __future__ import annotations

import base64
import binascii
import hashlib
import csv
import io
import json
import mimetypes
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from backend.knowledge_bundle import install_knowledge_bundle
except ModuleNotFoundError:  # Execução direta de backend/server.py.
    from knowledge_bundle import install_knowledge_bundle


PORTAL_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("SAFE_CCO_DATA_DIR", PORTAL_ROOT / "data")).resolve()
DEFAULT_KNOWLEDGE_ROOT = PORTAL_ROOT.parent
CONFIGURED_KNOWLEDGE_ROOT = os.environ.get("SAFE_KNOWLEDGE_ROOT", "").strip()
PRIVATE_BUNDLE_PATH = DATA_DIR / "knowledge-bundle.zip"
PRIVATE_KNOWLEDGE_ROOT = DATA_DIR / "private-knowledge"
BUNDLED_KNOWLEDGE_ACTIVE = not CONFIGURED_KNOWLEDGE_ROOT and PRIVATE_BUNDLE_PATH.is_file()
if BUNDLED_KNOWLEDGE_ACTIVE:
    install_knowledge_bundle(
        PRIVATE_BUNDLE_PATH,
        PRIVATE_KNOWLEDGE_ROOT,
        DATA_DIR / ".knowledge-bundle.sha256",
    )
KNOWLEDGE_ROOT = Path(
    CONFIGURED_KNOWLEDGE_ROOT
    or (PRIVATE_KNOWLEDGE_ROOT if BUNDLED_KNOWLEDGE_ACTIVE else DEFAULT_KNOWLEDGE_ROOT)
).resolve()
CLAIMS_PATH = KNOWLEDGE_ROOT / "Knowledge" / "claims_curated.json"
GRAPH_PATH = KNOWLEDGE_ROOT / "graphify-out" / "graph.json"
PUBLIC_KNOWLEDGE_INDEX_PATH = PORTAL_ROOT / "data" / "public-knowledge-index.js"
# Arquivo legado: passa a ser importado para o banco central na primeira execução.
LEARNING_GRAPH_PATH = Path(
    KNOWLEDGE_ROOT / "Knowledge" / "query_graph.json"
    if BUNDLED_KNOWLEDGE_ACTIVE
    else os.environ.get("SAFE_LEARNING_GRAPH_PATH", KNOWLEDGE_ROOT / "Knowledge" / "query_graph.json")
).resolve()
RULES_CATALOG_PATH = Path(
    KNOWLEDGE_ROOT / "Regras" / "catalogo_regras.json"
    if BUNDLED_KNOWLEDGE_ACTIVE
    else os.environ.get("SAFE_RULES_CATALOG_PATH", KNOWLEDGE_ROOT / "Regras" / "catalogo_regras.json")
).resolve()
LOCAL_MODEL = (
    os.environ.get("GEMINI_LOCAL_MODEL")
    or os.environ.get("GEMINI_MODEL")
    or "gemini-3.6-flash"
)
FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
EXTERNAL_MODEL = os.environ.get("GEMINI_EXTERNAL_MODEL", "gemini-3.1-pro-preview")
RELEASE_ID = os.environ.get("SAFE_CCO_RELEASE", "2026-08-21-form-dialog-close-1")
PORTAL_UPDATED_AT = os.environ.get("SAFE_CCO_UPDATED_AT", "").strip() or datetime.fromtimestamp(
    max(
        path.stat().st_mtime
        for path in (
            PORTAL_ROOT / "index.html",
            PORTAL_ROOT / "app.js",
            PORTAL_ROOT / "styles.css",
            PORTAL_ROOT / "topbar.css",
            PORTAL_ROOT / "backend" / "server.py",
            PUBLIC_KNOWLEDGE_INDEX_PATH,
        )
        if path.is_file()
    ),
    timezone.utc,
).isoformat()
HOST = os.environ.get("SAFE_CCO_HOST", "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
PORT = int(os.environ.get("SAFE_CCO_PORT") or os.environ.get("PORT") or "8765")
SECURE_COOKIES = os.environ.get("SAFE_CCO_SECURE_COOKIES", "").lower() in {"1", "true", "yes"} or bool(
    os.environ.get("RENDER")
)
SETUP_TOKEN = os.environ.get("SAFE_CCO_SETUP_TOKEN", "").strip()
REQUIRE_SETUP_TOKEN = os.environ.get("SAFE_CCO_REQUIRE_SETUP_TOKEN", "").lower() in {
    "1", "true", "yes"
} or bool(os.environ.get("RENDER"))
PORTAL_DB_PATH = Path(os.environ.get("SAFE_PORTAL_DB_PATH", DATA_DIR / "portalcco.db")).resolve()
INSTRUCTORS_DB_PATH = Path(os.environ.get("SAFE_INSTRUCTORS_DB_PATH", PORTAL_DB_PATH)).resolve()
AIRCRAFT_DB_PATH = Path(os.environ.get("SAFE_AIRCRAFT_DB_PATH", PORTAL_DB_PATH)).resolve()
BASES_DB_PATH = Path(os.environ.get("SAFE_BASES_DB_PATH", PORTAL_DB_PATH)).resolve()
HANDOVERS_DB_PATH = Path(os.environ.get("SAFE_HANDOVERS_DB_PATH", PORTAL_DB_PATH)).resolve()
REPORTS_DB_PATH = Path(os.environ.get("SAFE_REPORTS_DB_PATH", PORTAL_DB_PATH)).resolve()
SEARCH_HISTORY_DB_PATH = Path(os.environ.get("SAFE_SEARCH_HISTORY_DB_PATH", PORTAL_DB_PATH)).resolve()
AUTH_DB_PATH = Path(os.environ.get("SAFE_AUTH_DB_PATH", PORTAL_DB_PATH)).resolve()
RULES_DB_PATH = Path(os.environ.get("SAFE_RULES_DB_PATH", PORTAL_DB_PATH)).resolve()
APPROVED_RULES_EXPORT_PATH = Path(
    os.environ.get("SAFE_APPROVED_RULES_EXPORT_PATH", DATA_DIR / "approved-rules-export.json")
).resolve()
LEARNING_DB_PATH = Path(os.environ.get("SAFE_LEARNING_DB_PATH", PORTAL_DB_PATH)).resolve()
LEGACY_DB_PATHS = {
    "auth": DATA_DIR / "auth.db",
    "search_history": DATA_DIR / "search_history.db",
    "rules": DATA_DIR / "rules.db",
    "bases": DATA_DIR / "bases.db",
    "handovers": DATA_DIR / "handovers.db",
    "reports": DATA_DIR / "reports.db",
    "instructors": DATA_DIR / "instructors.db",
    "aircraft": DATA_DIR / "aircraft.db",
}
WEB_GROUNDING_ENABLED = os.environ.get("SAFE_CCO_WEB_GROUNDING", "1").lower() in {"1", "true", "yes"}
GEMINI_TRANSIENT_RETRIES = max(0, int(os.environ.get("GEMINI_TRANSIENT_RETRIES", "3")))
MAX_QUESTION_LENGTH = 1200
PORTAL_STORAGE_LOCK = threading.RLock()
WRITE_LOCK = PORTAL_STORAGE_LOCK
INSTRUCTORS_LOCK = PORTAL_STORAGE_LOCK
AIRCRAFT_LOCK = PORTAL_STORAGE_LOCK
BASES_LOCK = PORTAL_STORAGE_LOCK
HANDOVERS_LOCK = PORTAL_STORAGE_LOCK
REPORTS_LOCK = PORTAL_STORAGE_LOCK
SEARCH_HISTORY_LOCK = PORTAL_STORAGE_LOCK
AUTH_LOCK = PORTAL_STORAGE_LOCK
RULES_LOCK = PORTAL_STORAGE_LOCK
DATABASE_CONFIGURATION_LOCK = threading.Lock()
CONFIGURED_DATABASES: set[Path] = set()
STOPWORDS = {"a", "as", "o", "os", "de", "da", "das", "do", "dos", "e", "em", "na", "no", "para", "por", "com", "um", "uma", "que", "pode", "como", "safe", "fazer", "concluir", "quantos"}
DYNAMIC_GENERIC_STEMS = {
    "aluno", "base", "curso", "instrucao", "operacao", "regra", "safe", "voa", "voo",
}

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
    ("Tecnam P-Mentor", "PS-SFP", "Não informada", "Ativa", "Operacional", "IFR (RNAV/PBN)", "Nenhuma", "Nenhuma", None),
    ("Inpaer COLT 100", "PS-SFJ", "Não informada", "Inativa", "Fora de Operação", "Não aplicável (vendida)", "Aeronave vendida; não pertence à frota SAFE desde 29/07/2006", "Nenhuma", "2006-07-29"),
    ("Inpaer COLT 100", "PS-SFL", "Não informada", "Ativa", "Operacional", "IFR Capota / VFR Noturno", "Nenhuma", "Nenhuma", None),
    ("Montaer MC-01", "PS-LOM", "Não informada", "Ativa", "Operacional", "IFR Capota / VFR Noturno", "Nenhuma", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFI", "Não informada", "Ativa", "Operacional", "VFR Noturno", "Restrita a voos VFR (não homologada para IFR)", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFE", "Não informada", "Ativa", "Operacional", "IFR Capota, Diurno", "Restrita a IFR Capota Diurno (não homologada para voos noturnos)", "Nenhuma", None),
    ("Montaer MC-01", "PS-SFH", "Não informada", "Ativa", "Operacional", "VFR Diurno", "Restrita a voos VFR Diurnos (não homologada para IFR ou voos noturnos)", "Nenhuma", None),
    ("Cessna 150", "PS-CRS", "Não informada", "Inativa", "Fora de Operação", "Não listada", "Fora de operação (não consta nas certificações ativas)", "Nenhuma", None),
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
HANDOVER_BASES = {"Geral", "SDAM", "SBSJ"}
HANDOVER_ITEM_TYPES = {"Pendência", "Informação"}
HANDOVER_CYCLE_STATES = {"draft", "awaiting_receipt", "received"}
HANDOVER_HISTORY_LIMIT = 25
REPORT_TYPES = {"discrepancy": "Discrepância", "question": "Indicação de pergunta"}
REPORT_PRIORITIES = {"Baixa", "Normal", "Alta", "Crítica"}
REPORT_STATUSES = {"Aberto", "Em análise", "Resolvido", "Descartado"}
REPORT_RULE_ACTIONS = {
    "keep": "Manter sem decisão",
    "pending_approval": "Encaminhar para aprovação",
    "covered": "Já coberta pela base",
    "no_rule": "Não gera regra",
}
REPORT_ATTACHMENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}
MAX_REPORT_ATTACHMENTS = 5
MAX_REPORT_ATTACHMENT_BYTES = 2 * 1024 * 1024
AIRCRAFT_FLEET_STATUSES = {"Ativa", "Inativa"}
AIRCRAFT_OPERATIONAL_STATUSES = {"Operacional", "Fora de Operação", "Em Manutenção"}
RULE_CANDIDATE_STATUS_LABELS = {
    "unreviewed": "Não revisada",
    "pending_approval": "Pendente de aprovação",
    "approved": "Aprovada",
    "rejected": "Rejeitada",
}
CATALOG_STATUS_MAP = {
    "rascunho": "unreviewed",
    "em_discussao": "unreviewed",
    "aguardando_aprovacao": "pending_approval",
    "aprovada": "approved",
    "rejeitada": "rejected",
}
GENERAL_CMA_RULE_IDS = {
    "claim_rbac61_cma_vencido_impede_prerrogativas",
    "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma",
}
INSTRUCTOR_ALLOCATION_RULE_ID = "claim_mip_substituicao_instrutor_solicitada_administracao"
CMA_INVALID_RULE_ID = "claim_rbac61_cma_vencido_impede_prerrogativas"
CMA_EXTENSION_RULE_ID = "claim_rbac61_tolerancia_habilitacao_nao_prorroga_cma"
CAVOK_ACCESS_RULE_ID = "claim_cavok_acesso_pessoal_aluno"
PP_SOLO_PASSENGER_RULE_ID = "claim_mip_acompanhante_proibido_solo_pp"
SOLO_FAMILY_VISIT_RULE_ID = "claim_mip_familia_pode_acompanhar_evento_solo_em_terra"
PPA_SEQUENCE_RULE_ID = "claim_ppap001k_sequencia_completa_missoes"
PPA_MISSION_ORDER_RULE_ID = "claim_ppap001k_nav03_pode_anteceder_nav02"
PP_NAV_MONITORING_RULE_ID = "claim_mgop_monitoria_nav_durante_fase_ap"
BASE_TRANSFER_RULE_ID = "claim_rg006_troca_base_aluno"
BARS_PRIORITY_RULE_ID = "claim_rg010_prioridade_barras_missoes_criticas"
SOLO_RECENCY_RULE_ID = "claim_bops054_sem_solo_30_dias_novo_endosso"
READAPTATION_RULE_ID = "claim_bops054_readaptacao_90_dias"
ROLES = {"admin", "supervisor", "operator", "viewer"}
ROLE_LABELS = {"admin": "Administrador", "supervisor": "Supervisor", "operator": "Operador", "viewer": "Consulta"}
SESSION_HOURS = 12
ACTIVITY_ONLINE_MINUTES = 5
PASSWORD_ITERATIONS = 310_000


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def configure_database(path: Path) -> None:
    """Use rollback journaling, which is compatible with hosted network filesystems."""
    resolved_path = path.resolve()
    with DATABASE_CONFIGURATION_LOCK:
        if resolved_path in CONFIGURED_DATABASES:
            return
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved_path, timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            journal_mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(journal_mode).casefold() != "delete":
                raise RuntimeError("Não foi possível preparar o banco central para gravação segura.")
        finally:
            connection.close()
        CONFIGURED_DATABASES.add(resolved_path)


def migration_enabled_for(target_path: Path) -> bool:
    return target_path == PORTAL_DB_PATH


def initialize_migration_log(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS storage_migrations (
        source TEXT NOT NULL,
        item TEXT NOT NULL,
        migrated_rows INTEGER NOT NULL DEFAULT 0,
        migrated_at TEXT NOT NULL,
        PRIMARY KEY(source, item)
    )""")


def migrate_legacy_tables(
    connection: sqlite3.Connection,
    target_path: Path,
    legacy_path: Path,
    tables: dict[str, tuple[str, ...]],
) -> None:
    if (
        not migration_enabled_for(target_path)
        or legacy_path.resolve() == target_path
        or not legacy_path.is_file()
    ):
        return
    initialize_migration_log(connection)
    source_name = f"sqlite:{legacy_path.name}"
    legacy = sqlite3.connect(legacy_path, timeout=10)
    try:
        legacy.row_factory = sqlite3.Row
        for table, columns in tables.items():
            already_migrated = connection.execute(
                "SELECT 1 FROM storage_migrations WHERE source=? AND item=?",
                (source_name, table),
            ).fetchone()
            if already_migrated:
                continue
            exists = legacy.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            rows = legacy.execute(
                f"SELECT {', '.join(columns)} FROM {table}"
            ).fetchall() if exists else []
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                connection.executemany(
                    f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
            connection.execute(
                """INSERT INTO storage_migrations(source, item, migrated_rows, migrated_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    source_name, table, len(rows),
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                ),
            )
    finally:
        legacy.close()


@contextmanager
def auth_connection():
    connection = open_database(AUTH_DB_PATH)
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
            last_login_at TEXT,
            last_activity_at TEXT,
            last_activity_area TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL DEFAULT '',
            last_activity_area TEXT NOT NULL DEFAULT '',
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
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        for column, declaration in {
            "last_login_at": "TEXT",
            "last_activity_at": "TEXT",
            "last_activity_area": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in user_columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} {declaration}")
        session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()}
        for column, declaration in {
            "last_seen_at": "TEXT NOT NULL DEFAULT ''",
            "last_activity_area": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in session_columns:
                connection.execute(f"ALTER TABLE sessions ADD COLUMN {column} {declaration}")
        connection.execute("UPDATE sessions SET last_seen_at=created_at WHERE last_seen_at='' OR last_seen_at IS NULL")
        migrate_legacy_tables(connection, AUTH_DB_PATH, LEGACY_DB_PATHS["auth"], {
            "users": (
                "id", "username", "display_name", "password_hash", "password_salt", "role",
                "active", "must_change_password", "created_at", "updated_at",
            ),
            "sessions": ("token_hash", "user_id", "csrf_token", "expires_at", "created_at"),
            "admin_edit_grants": (
                "token_hash", "acting_user_id", "target_user_id", "expires_at", "created_at",
            ),
        })


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
            """INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at,
               last_seen_at, last_activity_area, created_at) VALUES (?, ?, ?, ?, ?, 'Login', ?)""",
            (token_hash, row["id"], csrf, expires_iso, created.isoformat(), created.isoformat()),
        )
        connection.execute(
            "UPDATE users SET last_login_at=?, last_activity_at=?, last_activity_area='Login' WHERE id=?",
            (created.isoformat(), created.isoformat(), row["id"]),
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


ACTIVITY_AREAS = {
    "Regras e procedimentos", "Aeronaves", "Passagem de turno", "Reports",
    "Gestão de regras", "Usuários e permissões", "Atividade do portal",
    "Minha conta", "Login", "Saiu do portal",
}


def record_portal_activity(user_id: int, token_hash: str, area: str | None = None) -> None:
    timestamp = now_iso()
    with AUTH_LOCK, auth_connection() as connection:
        if area in ACTIVITY_AREAS:
            connection.execute(
                "UPDATE sessions SET last_seen_at=?, last_activity_area=? WHERE token_hash=?",
                (timestamp, area, token_hash),
            )
            connection.execute(
                "UPDATE users SET last_activity_at=?, last_activity_area=? WHERE id=?",
                (timestamp, area, user_id),
            )
        else:
            connection.execute(
                "UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (timestamp, token_hash)
            )
            connection.execute(
                "UPDATE users SET last_activity_at=? WHERE id=?", (timestamp, user_id)
            )


def list_portal_activity() -> dict[str, Any]:
    initialize_auth_db()
    now = datetime.now(timezone.utc)
    online_cutoff = (now - timedelta(minutes=ACTIVITY_ONLINE_MINUTES)).isoformat()
    recent_cutoff = (now - timedelta(minutes=30)).isoformat()
    day_cutoff = (now - timedelta(hours=24)).isoformat()
    with auth_connection() as connection:
        rows = connection.execute(
            """SELECT u.id, u.username, u.display_name, u.role, u.active,
                      u.last_login_at, u.last_activity_at, u.last_activity_area,
                      MAX(s.last_seen_at) AS session_last_seen,
                      COUNT(s.token_hash) AS session_count
               FROM users u
               LEFT JOIN sessions s ON s.user_id=u.id AND s.expires_at>?
               WHERE u.active=1
               GROUP BY u.id
               ORDER BY COALESCE(MAX(s.last_seen_at), u.last_activity_at, '') DESC,
                        u.display_name COLLATE NOCASE""",
            (now.isoformat(),),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["role_label"] = ROLE_LABELS.get(item["role"], item["role"])
        item["online"] = bool(item["session_last_seen"] and item["session_last_seen"] >= online_cutoff)
        item["active_recently"] = bool(item["last_activity_at"] and item["last_activity_at"] >= recent_cutoff)
        item["accessed_24h"] = bool(item["last_activity_at"] and item["last_activity_at"] >= day_cutoff)
        items.append(item)
    return {
        "items": items,
        "online_count": sum(item["online"] for item in items),
        "recent_count": sum(item["active_recently"] for item in items),
        "accessed_24h_count": sum(item["accessed_24h"] for item in items),
        "active_user_count": len(items),
        "online_window_minutes": ACTIVITY_ONLINE_MINUTES,
        "generated_at": now.isoformat(),
    }


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
    connection = open_database(SEARCH_HISTORY_DB_PATH)
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
        migrate_legacy_tables(
            connection, SEARCH_HISTORY_DB_PATH, LEGACY_DB_PATHS["search_history"], {
                "search_history": (
                    "id", "question", "response_mode", "confidence", "result_json",
                    "presentation_json", "knowledge_version", "created_at",
                ),
            },
        )


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
def rules_connection():
    connection = open_database(RULES_DB_PATH)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_rules_db() -> None:
    with RULES_LOCK, rules_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS rule_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_question TEXT NOT NULL UNIQUE,
            question TEXT NOT NULL,
            proposed_answer TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'low',
            source_kind TEXT NOT NULL,
            sources_json TEXT NOT NULL DEFAULT '[]',
            local_evidence_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'unreviewed',
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            first_asked_at TEXT NOT NULL,
            last_asked_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            created_by_username TEXT NOT NULL DEFAULT '',
            created_by_name TEXT NOT NULL DEFAULT '',
            reviewed_by_username TEXT NOT NULL DEFAULT '',
            reviewed_by_name TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            review_note TEXT NOT NULL DEFAULT '',
            approved_rule_text TEXT NOT NULL DEFAULT '',
            rule_code TEXT NOT NULL DEFAULT '',
            authority TEXT NOT NULL DEFAULT '',
            source_reference TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            effective_from TEXT,
            effective_until TEXT,
            supersedes TEXT NOT NULL DEFAULT '',
            document_id TEXT NOT NULL DEFAULT '',
            document_path TEXT NOT NULL DEFAULT '',
            catalog_status TEXT NOT NULL DEFAULT '',
            catalog_hash TEXT NOT NULL DEFAULT '',
            catalog_synced_at TEXT,
            catalog_managed INTEGER NOT NULL DEFAULT 0
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS rule_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor_username TEXT NOT NULL DEFAULT '',
            actor_name TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(candidate_id) REFERENCES rule_candidates(id) ON DELETE CASCADE
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_candidates_status ON rule_candidates(status, last_asked_at DESC)"
        )
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(rule_candidates)").fetchall()
        }
        catalog_columns = {
            "document_id": "TEXT NOT NULL DEFAULT ''",
            "document_path": "TEXT NOT NULL DEFAULT ''",
            "catalog_status": "TEXT NOT NULL DEFAULT ''",
            "catalog_hash": "TEXT NOT NULL DEFAULT ''",
            "catalog_synced_at": "TEXT",
            "catalog_managed": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, declaration in catalog_columns.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE rule_candidates ADD COLUMN {column} {declaration}")
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_candidates_document_id
               ON rule_candidates(document_id) WHERE document_id <> ''"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_events_candidate ON rule_events(candidate_id, created_at)"
        )
        migrate_legacy_tables(connection, RULES_DB_PATH, LEGACY_DB_PATHS["rules"], {
            "rule_candidates": (
                "id", "normalized_question", "question", "proposed_answer", "confidence",
                "source_kind", "sources_json", "local_evidence_json", "status",
                "occurrence_count", "first_asked_at", "last_asked_at", "updated_at",
                "created_by_username", "created_by_name", "reviewed_by_username",
                "reviewed_by_name", "reviewed_at", "review_note", "approved_rule_text",
                "rule_code", "authority", "source_reference", "source_url", "scope",
                "effective_from", "effective_until", "supersedes",
            ),
            "rule_events": (
                "id", "candidate_id", "action", "actor_username", "actor_name",
                "details", "created_at",
            ),
        })
        connection.execute(
            """UPDATE rule_candidates
               SET status=CASE
                   WHEN reviewed_at IS NULL THEN 'unreviewed'
                   ELSE 'pending_approval'
               END
               WHERE status='pending_review'"""
        )


def synchronize_rules_catalog(connection: sqlite3.Connection) -> int:
    """Importa o catálogo documental sem sobrescrever uma revisão feita no Portal."""
    if not RULES_CATALOG_PATH.is_file():
        return 0
    try:
        payload = json.loads(RULES_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Catálogo de regras inválido: {RULES_CATALOG_PATH}") from error
    if payload.get("schema_version") != 1 or not isinstance(payload.get("items"), list):
        raise RuntimeError("O catálogo de regras não possui o schema_version 1 esperado.")

    catalog_updated_at = str(payload.get("updated_at", "")).strip() or now_iso()
    synchronized = 0
    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise RuntimeError("O catálogo de regras contém um item inválido.")
        item = {str(key): value for key, value in raw_item.items()}
        document_id = str(item.get("document_id", "")).strip().upper()
        title = str(item.get("title", "")).strip()
        catalog_status = str(item.get("status", "")).strip()
        if not re.fullmatch(r"(?:PR|RG)-\d{3}", document_id) or not title:
            raise RuntimeError("Todo item do catálogo deve possuir document_id e title válidos.")
        if catalog_status not in CATALOG_STATUS_MAP:
            raise RuntimeError(f"Estado inválido no catálogo para {document_id}: {catalog_status}")

        portal_status = CATALOG_STATUS_MAP[catalog_status]
        published_rule_id = str(item.get("published_rule_id", "")).strip().upper()
        if portal_status == "approved":
            published_rule_id = published_rule_id or document_id
            if not re.fullmatch(r"RG-\d{3}", published_rule_id):
                raise RuntimeError(
                    f"A regra aprovada {document_id} deve possuir um published_rule_id RG-###."
                )
        summary = str(item.get("summary", "")).strip()
        document_path = str(item.get("document_path", "")).strip()
        authority = str(item.get("authority", "")).strip()
        source_reference = str(item.get("source_reference", "")).strip()
        scope = str(item.get("scope", "")).strip()
        review_note = str(item.get("review_note", "")).strip()
        approved_text = str(item.get("approved_rule_text", "")).strip()
        if portal_status == "approved" and (not approved_text or not authority or not source_reference):
            raise RuntimeError(f"A regra aprovada {document_id} está incompleta no catálogo.")
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        catalog_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        current = connection.execute(
            "SELECT * FROM rule_candidates WHERE document_id=?", (document_id,)
        ).fetchone()
        matched_question_alias = False
        aliases = [
            normalize(str(value))
            for value in item.get("question_aliases", [])
            if str(value).strip()
        ]
        if not current and aliases:
            placeholders = ",".join("?" for _ in aliases)
            current = connection.execute(
                f"""SELECT * FROM rule_candidates
                    WHERE document_id='' AND status IN ('unreviewed', 'pending_approval')
                      AND normalized_question IN ({placeholders})
                    ORDER BY occurrence_count DESC, id ASC LIMIT 1""",
                aliases,
            ).fetchone()
            matched_question_alias = current is not None
        if current and not matched_question_alias and (
            not current["catalog_managed"] or current["catalog_hash"] == catalog_hash
        ):
            continue

        evidence = [{
            "id": document_id,
            "kind": "local_rule_document",
            "label": source_reference or title,
            "code": document_id,
            "source": document_path,
            "location": document_path,
            "url": "",
        }]
        evidence_json = json.dumps(evidence, ensure_ascii=False)
        reviewed_at = catalog_updated_at if portal_status != "unreviewed" else None
        reviewed_by_username = "catalogo_local" if reviewed_at else ""
        reviewed_by_name = "Catálogo documental" if reviewed_at else ""
        confidence = "high" if portal_status == "approved" else (
            "medium" if portal_status == "pending_approval" else "low"
        )
        if current:
            question = current["question"] if matched_question_alias else title
            normalized_question = (
                current["normalized_question"]
                if matched_question_alias
                else normalize(f"{document_id} {title}")
            )
            connection.execute(
                """UPDATE rule_candidates
                   SET normalized_question=?, question=?, proposed_answer=?, confidence=?,
                       source_kind='local_document', sources_json=?, local_evidence_json=?,
                       status=?, last_asked_at=?, updated_at=?, reviewed_by_username=?,
                       reviewed_by_name=?, reviewed_at=?, review_note=?, approved_rule_text=?,
                       rule_code=?, authority=?, source_reference=?, scope=?, document_path=?,
                       document_id=?, catalog_status=?, catalog_hash=?, catalog_synced_at=?,
                       catalog_managed=1
                   WHERE id=?""",
                (
                    normalized_question, question, summary, confidence,
                    evidence_json, evidence_json, portal_status, catalog_updated_at,
                    catalog_updated_at, reviewed_by_username, reviewed_by_name, reviewed_at,
                    review_note, approved_text, published_rule_id if portal_status == "approved" else "",
                    authority, source_reference, scope, document_path, document_id,
                    catalog_status, catalog_hash, now_iso(), current["id"],
                ),
            )
            candidate_id = int(current["id"])
            action = "Sincronizada do catálogo"
        else:
            cursor = connection.execute(
                """INSERT INTO rule_candidates(
                   normalized_question, question, proposed_answer, confidence, source_kind,
                   sources_json, local_evidence_json, status, occurrence_count, first_asked_at,
                   last_asked_at, updated_at, created_by_username, created_by_name,
                   reviewed_by_username, reviewed_by_name, reviewed_at, review_note,
                   approved_rule_text, rule_code, authority, source_reference, scope,
                   document_id, document_path, catalog_status, catalog_hash,
                   catalog_synced_at, catalog_managed
                   ) VALUES (?, ?, ?, ?, 'local_document', ?, ?, ?, 1, ?, ?, ?, ?, ?,
                             ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    normalize(f"{document_id} {title}"), title, summary, confidence,
                    evidence_json, evidence_json, portal_status, catalog_updated_at,
                    catalog_updated_at, catalog_updated_at, "catalogo_local",
                    "Catálogo documental", reviewed_by_username, reviewed_by_name, reviewed_at,
                    review_note, approved_text,
                    published_rule_id if portal_status == "approved" else "", authority,
                    source_reference, scope, document_id, document_path, catalog_status,
                    catalog_hash, now_iso(),
                ),
            )
            candidate_id = int(cursor.lastrowid)
            action = "Importada do catálogo"
        connection.execute(
            """INSERT INTO rule_events(candidate_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, ?, 'catalogo_local', 'Catálogo documental', ?, ?)""",
            (
                candidate_id, action,
                json.dumps(
                    {
                        "document_id": document_id,
                        "catalog_status": catalog_status,
                        "matched_question_alias": matched_question_alias,
                    },
                    ensure_ascii=False,
                ),
                now_iso(),
            ),
        )
        synchronized += 1
    return synchronized


def rule_candidate_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["sources"] = json.loads(item.pop("sources_json") or "[]")
    item["local_evidence"] = json.loads(item.pop("local_evidence_json") or "[]")
    item["status_label"] = RULE_CANDIDATE_STATUS_LABELS.get(item["status"], item["status"])
    return item


def compact_rule_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "id": str(item.get("id", "")),
        "kind": str(item.get("kind", "")),
        "label": str(item.get("label", ""))[:600],
        "code": str(item.get("code", ""))[:100],
        "source": str(item.get("source", ""))[:500],
        "location": str(item.get("location", ""))[:500],
        "url": str(item.get("url", ""))[:1000],
    } for item in items[:12]]


def upsert_rule_candidate(
    question: str,
    proposed_answer: str,
    confidence: str,
    source_kind: str,
    sources: list[dict[str, Any]],
    local_evidence: list[dict[str, Any]],
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_rules_db()
    clean_question = question.strip()
    normalized_question = normalize(clean_question)
    if not normalized_question or len(clean_question) > MAX_QUESTION_LENGTH:
        raise ValueError("Pergunta inválida para regras em aprovação.")
    timestamp = now_iso()
    actor = actor or {}
    sources_json = json.dumps(compact_rule_evidence(sources), ensure_ascii=False)
    evidence_json = json.dumps(compact_rule_evidence(local_evidence), ensure_ascii=False)
    with RULES_LOCK, rules_connection() as connection:
        current = connection.execute(
            "SELECT * FROM rule_candidates WHERE normalized_question=?", (normalized_question,)
        ).fetchone()
        if current:
            candidate_id = int(current["id"])
            next_status = "unreviewed" if current["status"] == "rejected" else current["status"]
            connection.execute(
                """UPDATE rule_candidates
                   SET question=?, proposed_answer=?, confidence=?, source_kind=?, sources_json=?,
                       local_evidence_json=?, status=?, occurrence_count=occurrence_count+1,
                       last_asked_at=?, updated_at=?
                   WHERE id=?""",
                (
                    clean_question, proposed_answer.strip()[:8000], confidence, source_kind,
                    sources_json, evidence_json, next_status, timestamp, timestamp, candidate_id,
                ),
            )
            if current["status"] == "rejected":
                connection.execute(
                    """UPDATE rule_candidates SET reviewed_by_username='', reviewed_by_name='',
                       reviewed_at=NULL, review_note='', approved_rule_text='', rule_code='',
                       authority='', source_reference='', source_url='', scope='',
                       effective_from=NULL, effective_until=NULL, supersedes=''
                       WHERE id=?""",
                    (candidate_id,),
                )
            action = "Reaberta após nova consulta" if current["status"] == "rejected" else "Pergunta repetida"
        else:
            cursor = connection.execute(
                """INSERT INTO rule_candidates(
                   normalized_question, question, proposed_answer, confidence, source_kind,
                   sources_json, local_evidence_json, status, occurrence_count,
                   first_asked_at, last_asked_at, updated_at, created_by_username, created_by_name
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed', 1, ?, ?, ?, ?, ?)""",
                (
                    normalized_question, clean_question, proposed_answer.strip()[:8000], confidence,
                    source_kind, sources_json, evidence_json, timestamp, timestamp, timestamp,
                    str(actor.get("username", "")), str(actor.get("display_name", "")),
                ),
            )
            candidate_id = int(cursor.lastrowid)
            action = "Criada"
        connection.execute(
            """INSERT INTO rule_events(candidate_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                candidate_id, action, str(actor.get("username", "")), str(actor.get("display_name", "")),
                json.dumps({"source_kind": source_kind, "confidence": confidence}, ensure_ascii=False),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)).fetchone()
    return rule_candidate_dict(row)


def list_rule_candidates(status: str = "unreviewed") -> list[dict[str, Any]]:
    initialize_rules_db()
    allowed = {"unreviewed", "pending_approval", "approved", "rejected", "pending_review", "all"}
    if status not in allowed:
        raise ValueError("Situação de regra inválida.")
    with rules_connection() as connection:
        if status == "all":
            rows = connection.execute(
                "SELECT * FROM rule_candidates ORDER BY last_asked_at DESC"
            ).fetchall()
        elif status == "pending_review":
            rows = connection.execute(
                """SELECT * FROM rule_candidates
                   WHERE status IN ('unreviewed', 'pending_approval')
                   ORDER BY occurrence_count DESC, last_asked_at DESC"""
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT * FROM rule_candidates WHERE status=?
                   ORDER BY occurrence_count DESC, last_asked_at DESC""", (status,)
            ).fetchall()
    return [rule_candidate_dict(row) for row in rows]


def _question_terms(question: str) -> set[str]:
    return {
        term for term in normalize(question).split()
        if term not in STOPWORDS and len(term) >= 3
    }


def group_similar_rule_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa variações lexicais para triagem, sem fundir registros nem aprovar regras."""
    if not items:
        return []
    parents = list(range(len(items)))
    term_sets = [_question_terms(str(item.get("question", ""))) for item in items]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            shared = term_sets[left] & term_sets[right]
            union_terms = term_sets[left] | term_sets[right]
            smallest = min(len(term_sets[left]), len(term_sets[right]))
            if (
                len(shared) >= 2 and union_terms and smallest
                and (len(shared) / len(union_terms) >= 0.5 or len(shared) / smallest >= 0.4)
            ):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(index)
    enriched = []
    for index, item in enumerate(items):
        members = groups[find(index)]
        group_occurrences = sum(int(items[position].get("occurrence_count", 0)) for position in members)
        enriched.append({
            **item,
            "similar_group_id": f"gap-group-{min(int(items[position]['id']) for position in members)}",
            "similar_group_size": len(members),
            "group_occurrence_count": group_occurrences,
            "similar_questions": [
                {"id": items[position]["id"], "question": items[position]["question"]}
                for position in members if position != index
            ],
        })
    return enriched


def knowledge_gap_report(query: dict[str, list[str]] | None = None) -> dict[str, Any]:
    query = query or {}
    status = query.get("status", ["open"])[0]
    allowed_statuses = {"open", "unreviewed", "pending_approval", "approved", "rejected", "all"}
    if status not in allowed_statuses:
        raise ValueError("Situação de lacuna inválida.")
    search = normalize(query.get("search", [""])[0])
    date_from = query.get("from", [""])[0].strip()
    date_to = query.get("to", [""])[0].strip()
    for value in (date_from, date_to):
        if value:
            datetime.strptime(value, "%Y-%m-%d")
    try:
        min_occurrences = max(1, int(query.get("min_occurrences", ["1"])[0]))
    except ValueError as error:
        raise ValueError("Ocorrência mínima inválida.") from error

    source_status = "pending_review" if status == "open" else status
    items = list_rule_candidates(source_status)
    filtered = []
    for item in items:
        haystack = normalize(" ".join(str(item.get(field, "")) for field in (
            "question", "proposed_answer", "approved_rule_text", "source_reference",
            "authority", "created_by_name", "created_by_username",
        )))
        asked_date = str(item.get("last_asked_at", ""))[:10]
        if search and search not in haystack:
            continue
        if date_from and asked_date < date_from:
            continue
        if date_to and asked_date > date_to:
            continue
        if int(item.get("occurrence_count", 0)) < min_occurrences:
            continue
        filtered.append(item)
    grouped = group_similar_rule_candidates(filtered)
    recurring_groups = {
        item["similar_group_id"] for item in grouped
        if item["group_occurrence_count"] > 1
    }
    summary = {
        "items": len(grouped),
        "total_occurrences": sum(int(item.get("occurrence_count", 0)) for item in grouped),
        "unreviewed": sum(item.get("status") == "unreviewed" for item in grouped),
        "pending_approval": sum(item.get("status") == "pending_approval" for item in grouped),
        "recurring_groups": len(recurring_groups),
    }
    return {"summary": summary, "items": grouped, "filters": {
        "status": status, "search": query.get("search", [""])[0], "from": date_from,
        "to": date_to, "min_occurrences": min_occurrences,
    }}


def knowledge_gap_csv(report: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow([
        "ID", "Situação", "Pergunta", "Ocorrências", "Ocorrências do grupo",
        "Primeira pergunta", "Última pergunta", "Usuário de origem", "Nome de origem",
        "Origem", "Confiança", "Resposta provisória", "Quantidade de fontes",
    ])
    for item in report["items"]:
        writer.writerow([
            item["id"], item["status_label"], item["question"], item["occurrence_count"],
            item["group_occurrence_count"], item["first_asked_at"], item["last_asked_at"],
            item["created_by_username"], item["created_by_name"], item["source_kind"],
            item["confidence"], item["proposed_answer"], len(item["sources"]),
        ])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def write_approved_rules_export(connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    owns_connection = connection is None
    if owns_connection:
        initialize_rules_db()
        connection = open_database(RULES_DB_PATH)
    try:
        rows = connection.execute(
            "SELECT * FROM rule_candidates WHERE status='approved' ORDER BY rule_code, id"
        ).fetchall()
        rules = []
        for row in rows:
            item = rule_candidate_dict(row)
            rules.append({key: item.get(key) for key in (
                "id", "question", "approved_rule_text", "rule_code", "authority",
                "source_reference", "source_url", "scope", "effective_from",
                "effective_until", "supersedes", "review_note", "reviewed_by_username",
                "reviewed_by_name", "reviewed_at", "updated_at",
            )})
        payload = {"schema_version": 1, "exported_at": now_iso(), "rules": rules}
        APPROVED_RULES_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = APPROVED_RULES_EXPORT_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(APPROVED_RULES_EXPORT_PATH)
        return payload
    finally:
        if owns_connection and connection is not None:
            connection.close()


def review_rule_candidate(candidate_id: int, data: dict[str, Any], reviewer: dict[str, Any]) -> dict[str, Any]:
    initialize_rules_db()
    status = str(data.get("status", "")).strip()
    if status == "pending_review":
        status = "pending_approval"
    if status not in {"approved", "rejected", "pending_approval"}:
        raise ValueError("Selecione uma decisão válida.")
    review_note = str(data.get("review_note", "")).strip()
    approved_rule_text = str(data.get("approved_rule_text", "")).strip()
    rule_code = str(data.get("rule_code", "")).strip()
    authority = str(data.get("authority", "")).strip()
    source_reference = str(data.get("source_reference", "")).strip()
    source_url = str(data.get("source_url", "")).strip()
    scope = str(data.get("scope", "")).strip()
    effective_from = str(data.get("effective_from", "")).strip() or None
    effective_until = str(data.get("effective_until", "")).strip() or None
    supersedes = str(data.get("supersedes", "")).strip()
    if not review_note:
        raise ValueError("Registre a justificativa da decisão.")
    if status == "approved" and (not approved_rule_text or not source_reference or not authority):
        raise ValueError("Para aprovar, informe a regra, a autoridade e a referência da fonte.")
    if status == "approved" and not re.fullmatch(r"RG-\d{3}", rule_code.upper()):
        raise ValueError("Para aprovar, use um código oficial no formato RG-###.")
    rule_code = rule_code.upper()
    if source_url and not source_url.startswith(("https://", "http://")):
        raise ValueError("A URL da fonte deve começar com http:// ou https://.")
    if any(len(value or "") > limit for value, limit in (
        (review_note, 3000), (approved_rule_text, 8000), (rule_code, 100),
        (authority, 120), (source_reference, 1000), (source_url, 1000),
        (scope, 1000), (supersedes, 500),
    )):
        raise ValueError("Um dos campos excede o limite permitido.")
    timestamp = now_iso()
    with RULES_LOCK, rules_connection() as connection:
        current = connection.execute(
            "SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if not current:
            raise LookupError("Regra em aprovação não encontrada.")
        if status == "approved" and connection.execute(
            "SELECT 1 FROM rule_candidates WHERE UPPER(rule_code)=? AND id<>? LIMIT 1",
            (rule_code, candidate_id),
        ).fetchone():
            raise ValueError("Já existe uma regra aprovada com esse código.")
        connection.execute(
            """UPDATE rule_candidates SET status=?, review_note=?, approved_rule_text=?,
               rule_code=?, authority=?, source_reference=?, source_url=?, scope=?,
               effective_from=?, effective_until=?, supersedes=?, reviewed_by_username=?,
               reviewed_by_name=?, reviewed_at=?, updated_at=?, catalog_managed=0 WHERE id=?""",
            (
                status, review_note, approved_rule_text, rule_code, authority, source_reference,
                source_url, scope, effective_from, effective_until, supersedes,
                reviewer["username"], reviewer["display_name"], timestamp, timestamp, candidate_id,
            ),
        )
        connection.execute(
            """INSERT INTO rule_events(candidate_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                candidate_id, f"Revisão: {status}", reviewer["username"], reviewer["display_name"],
                json.dumps({"from": current["status"], "to": status, "note": review_note}, ensure_ascii=False),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)).fetchone()
        write_approved_rules_export(connection)
    return rule_candidate_dict(row)


def approved_dynamic_rules() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date().isoformat()
    return [
        item for item in list_rule_candidates("approved")
        if (not item["effective_from"] or item["effective_from"] <= today)
        and (not item["effective_until"] or item["effective_until"] >= today)
    ]


def list_approved_rules() -> list[dict[str, Any]]:
    public_index = load_public_knowledge_index(str(PUBLIC_KNOWLEDGE_INDEX_PATH))
    static_rules = [{
        "id": item.get("id", ""),
        "rule_code": item.get("code", ""),
        "approved_rule_text": item.get("label", ""),
        "authority": "Base SAFE aprovada",
        "source_reference": item.get("location", ""),
        "source_url": "",
        "scope": item.get("appliesTo", ""),
        "effective_from": None,
        "effective_until": None,
        "status": "approved",
        "origin": "base_curated",
    } for item in public_index.get("claims", [])]
    dynamic_rules = [{**item, "origin": "reviewed_candidate"} for item in approved_dynamic_rules()]
    return dynamic_rules + static_rules


@contextmanager
def bases_connection():
    connection = open_database(BASES_DB_PATH)
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
        migrate_legacy_tables(connection, BASES_DB_PATH, LEGACY_DB_PATHS["bases"], {
            "bases": ("code", "name", "status", "updated_at"),
        })
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
    connection = open_database(HANDOVERS_DB_PATH)
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
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(handovers)").fetchall()
        }
        added_columns = {
            "cycle_id": "INTEGER",
            "base_scope": "TEXT NOT NULL DEFAULT 'Geral'",
            "item_type": "TEXT NOT NULL DEFAULT 'Pendência'",
            "assignee": "TEXT NOT NULL DEFAULT ''",
            "author_username": "TEXT NOT NULL DEFAULT ''",
            "completed_by": "TEXT NOT NULL DEFAULT ''",
            "completion_note": "TEXT NOT NULL DEFAULT ''",
            "carried_from_id": "INTEGER",
            "root_item_id": "INTEGER",
            "reopened_at": "TEXT",
        }
        for column, declaration in added_columns.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE handovers ADD COLUMN {column} {declaration}")
        connection.execute("""CREATE TABLE IF NOT EXISTS handover_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_shift TEXT NOT NULL,
            target_shift TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'draft',
            operation_date TEXT NOT NULL,
            created_by_username TEXT NOT NULL DEFAULT '',
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_by_username TEXT NOT NULL DEFAULT '',
            published_by_name TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            received_by_username TEXT NOT NULL DEFAULT '',
            received_by_name TEXT NOT NULL DEFAULT '',
            received_at TEXT
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS handover_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL,
            item_id INTEGER,
            action TEXT NOT NULL,
            actor_username TEXT NOT NULL DEFAULT '',
            actor_name TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handovers_status ON handovers(status, updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handovers_cycle ON handovers(cycle_id, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handovers_root ON handovers(root_item_id, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handover_cycles_state ON handover_cycles(state, updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_handover_events_cycle ON handover_events(cycle_id, created_at)")
        migrate_legacy_tables(connection, HANDOVERS_DB_PATH, LEGACY_DB_PATHS["handovers"], {
            "handovers": (
                "id", "origin_shift", "target_shift", "message", "priority", "status",
                "author", "created_at", "updated_at", "completed_at",
            ),
        })
        migrate_legacy_handovers(connection)


def migrate_legacy_handovers(connection: sqlite3.Connection) -> int:
    """Agrupa registros antigos por rota/dia, sem alterar conteúdo ou autoria."""
    rows = connection.execute(
        """SELECT id, origin_shift, target_shift, author, created_at, updated_at
           FROM handovers WHERE cycle_id IS NULL ORDER BY id"""
    ).fetchall()
    if not rows:
        connection.execute("UPDATE handovers SET root_item_id=id WHERE root_item_id IS NULL")
        return 0
    grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        operation_date = str(row["created_at"] or "")[:10] or now_iso()[:10]
        grouped.setdefault(
            (row["origin_shift"], row["target_shift"], operation_date), []
        ).append(row)
    migrated = 0
    for (origin, target, operation_date), items in grouped.items():
        created_at = min(str(item["created_at"]) for item in items)
        updated_at = max(str(item["updated_at"]) for item in items)
        publisher = str(items[0]["author"] or "Registro legado")
        cursor = connection.execute(
            """INSERT INTO handover_cycles(
               origin_shift, target_shift, state, operation_date,
               created_by_name, created_at, updated_at,
               published_by_name, published_at, received_by_name, received_at
               ) VALUES (?, ?, 'received', ?, ?, ?, ?, ?, ?, 'Migração segura', ?)""",
            (
                origin, target, operation_date, publisher, created_at, updated_at,
                publisher, created_at, updated_at,
            ),
        )
        cycle_id = int(cursor.lastrowid)
        item_ids = [int(item["id"]) for item in items]
        placeholders = ",".join("?" for _ in item_ids)
        connection.execute(
            f"""UPDATE handovers SET cycle_id=?, base_scope='Geral', item_type='Pendência',
                root_item_id=id WHERE id IN ({placeholders})""",
            (cycle_id, *item_ids),
        )
        connection.execute(
            """INSERT INTO handover_events(
               cycle_id, action, actor_name, details, created_at
               ) VALUES (?, 'Migração de passagem anterior', 'Sistema', ?, ?)""",
            (
                cycle_id,
                json.dumps({"legacy_item_ids": item_ids, "base_scope": "Geral"}, ensure_ascii=False),
                now_iso(),
            ),
        )
        migrated += len(items)
    return migrated


def handover_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "origin_shift": row["origin_shift"], "target_shift": row["target_shift"],
        "message": row["message"], "priority": row["priority"], "status": row["status"],
        "author": row["author"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "completed_at": row["completed_at"], "cycle_id": row["cycle_id"],
        "base_scope": row["base_scope"], "item_type": row["item_type"],
        "assignee": row["assignee"], "author_username": row["author_username"],
        "completed_by": row["completed_by"], "completion_note": row["completion_note"],
        "carried_from_id": row["carried_from_id"], "root_item_id": row["root_item_id"],
        "reopened_at": row["reopened_at"],
    }


def validate_handover(data: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    origin = str(data.get("origin_shift", "")).strip().upper()
    target = str(data.get("target_shift", "")).strip().upper()
    message = str(data.get("message", "")).strip()
    priority = str(data.get("priority", "Normal")).strip()
    base_scope = str(data.get("base_scope", "")).strip()
    item_type = str(data.get("item_type", "Pendência")).strip()
    assignee = str(data.get("assignee", "")).strip()
    if origin not in SHIFTS or target not in SHIFTS:
        raise ValueError("Selecione turnos de origem e destino válidos.")
    if origin == target:
        raise ValueError("O turno de destino deve ser diferente do turno de origem.")
    if not message or len(message) > 2000:
        raise ValueError("Informe uma mensagem de até 2.000 caracteres.")
    if priority not in HANDOVER_PRIORITIES:
        raise ValueError("Prioridade inválida.")
    if base_scope not in HANDOVER_BASES:
        raise ValueError("Selecione Geral, SDAM ou SBSJ.")
    if item_type not in HANDOVER_ITEM_TYPES:
        raise ValueError("Selecione Pendência ou Informação.")
    if len(assignee) > 100:
        raise ValueError("O responsável deve possuir até 100 caracteres.")
    return origin, target, message, priority, base_scope, item_type, assignee


def handover_actor(actor: dict[str, Any] | None, data: dict[str, Any] | None = None) -> tuple[str, str]:
    data = data or {}
    if actor:
        return str(actor.get("username", "")), str(actor.get("display_name", ""))
    return "", str(data.get("author", "")).strip() or "Operador"


def record_handover_event(
    connection: sqlite3.Connection, cycle_id: int, action: str,
    actor: dict[str, Any] | None, *, item_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    username, name = handover_actor(actor)
    connection.execute(
        """INSERT INTO handover_events(
           cycle_id, item_id, action, actor_username, actor_name, details, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            cycle_id, item_id, action, username, name,
            json.dumps(details or {}, ensure_ascii=False), now_iso(),
        ),
    )


def carry_open_handover_items(connection: sqlite3.Connection, cycle_id: int) -> int:
    rows = connection.execute(
        """SELECT h.* FROM handovers h
           JOIN (
               SELECT COALESCE(root_item_id, id) AS root_id, MAX(id) AS latest_id
               FROM handovers GROUP BY COALESCE(root_item_id, id)
           ) latest ON latest.latest_id=h.id
           JOIN handover_cycles c ON c.id=h.cycle_id
           WHERE h.item_type='Pendência' AND h.status IN ('Pendente', 'Em andamento')
             AND c.state IN ('awaiting_receipt', 'received')
           ORDER BY CASE h.priority WHEN 'Crítica' THEN 0 WHEN 'Alta' THEN 1
                    WHEN 'Normal' THEN 2 ELSE 3 END, h.id"""
    ).fetchall()
    copied = 0
    timestamp = now_iso()
    for row in rows:
        cursor = connection.execute(
            """INSERT INTO handovers(
               cycle_id, origin_shift, target_shift, message, priority, status, author,
               created_at, updated_at, completed_at, base_scope, item_type, assignee,
               author_username, completed_by, completion_note, carried_from_id,
               root_item_id, reopened_at
               ) SELECT ?, c.origin_shift, c.target_shift, ?, ?, ?, ?, ?, ?, NULL, ?,
                        'Pendência', ?, ?, '', '', ?, COALESCE(source.root_item_id, source.id), NULL
                 FROM handovers source JOIN handover_cycles c ON c.id=?
                 WHERE source.id=?""",
            (
                cycle_id, row["message"], row["priority"], row["status"], row["author"],
                timestamp, timestamp, row["base_scope"], row["assignee"],
                row["author_username"], row["id"], cycle_id, row["id"],
            ),
        )
        new_id = int(cursor.lastrowid)
        record_handover_event(
            connection, cycle_id, "Pendência carregada automaticamente", None,
            item_id=new_id,
            details={"carried_from_id": row["id"], "root_item_id": row["root_item_id"] or row["id"]},
        )
        copied += 1
    return copied


def ensure_draft_handover_cycle(
    connection: sqlite3.Connection, origin: str, target: str,
    actor: dict[str, Any] | None,
) -> sqlite3.Row:
    draft = connection.execute(
        "SELECT * FROM handover_cycles WHERE state='draft' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if draft:
        if draft["origin_shift"] != origin or draft["target_shift"] != target:
            raise ValueError(
                f"Já existe uma passagem em elaboração: {draft['origin_shift']} → {draft['target_shift']}."
            )
        return draft
    awaiting = connection.execute(
        "SELECT * FROM handover_cycles WHERE state='awaiting_receipt' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if awaiting:
        raise ValueError(
            f"Confirme o recebimento da passagem {awaiting['origin_shift']} → {awaiting['target_shift']} antes de iniciar outra."
        )
    timestamp = now_iso()
    username, name = handover_actor(actor)
    cursor = connection.execute(
        """INSERT INTO handover_cycles(
           origin_shift, target_shift, state, operation_date,
           created_by_username, created_by_name, created_at, updated_at
           ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)""",
        (origin, target, timestamp[:10], username, name, timestamp, timestamp),
    )
    cycle_id = int(cursor.lastrowid)
    record_handover_event(connection, cycle_id, "Passagem iniciada", actor)
    carry_open_handover_items(connection, cycle_id)
    return connection.execute("SELECT * FROM handover_cycles WHERE id=?", (cycle_id,)).fetchone()


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


def list_handover_cycles() -> dict[str, Any]:
    initialize_handovers_db()
    with handovers_connection() as connection:
        cycle_rows = connection.execute(
            """SELECT * FROM handover_cycles ORDER BY
               CASE state WHEN 'draft' THEN 0 WHEN 'awaiting_receipt' THEN 1 ELSE 2 END,
               updated_at DESC, id DESC LIMIT ?""",
            (HANDOVER_HISTORY_LIMIT + 1,),
        ).fetchall()
        cycle_ids = [int(row["id"]) for row in cycle_rows]
        item_rows: list[sqlite3.Row] = []
        event_rows: list[sqlite3.Row] = []
        if cycle_ids:
            placeholders = ",".join("?" for _ in cycle_ids)
            item_rows = connection.execute(
                f"""SELECT * FROM handovers WHERE cycle_id IN ({placeholders}) ORDER BY
                   CASE base_scope WHEN 'Geral' THEN 0 WHEN 'SDAM' THEN 1 ELSE 2 END,
                   CASE priority WHEN 'Crítica' THEN 0 WHEN 'Alta' THEN 1
                        WHEN 'Normal' THEN 2 ELSE 3 END, id""",
                cycle_ids,
            ).fetchall()
            event_rows = connection.execute(
                f"""SELECT * FROM handover_events WHERE cycle_id IN ({placeholders})
                    ORDER BY created_at DESC, id DESC""",
                cycle_ids,
            ).fetchall()
        latest_rows = connection.execute(
            """SELECT h.* FROM handovers h JOIN (
               SELECT COALESCE(root_item_id, id) AS root_id, MAX(id) AS latest_id
               FROM handovers GROUP BY COALESCE(root_item_id, id)
               ) latest ON latest.latest_id=h.id"""
        ).fetchall()
        total_cycles = int(connection.execute(
            "SELECT COUNT(*) FROM handover_cycles"
        ).fetchone()[0])
    items_by_cycle: dict[int, list[dict[str, Any]]] = {}
    latest_item_ids = {int(row["id"]) for row in latest_rows}
    for row in item_rows:
        item = handover_dict(row)
        item["is_latest_root"] = int(row["id"]) in latest_item_ids
        items_by_cycle.setdefault(int(row["cycle_id"]), []).append(item)
    events_by_cycle: dict[int, list[dict[str, Any]]] = {}
    for row in event_rows:
        event = dict(row)
        try:
            event["details"] = json.loads(event.pop("details"))
        except (json.JSONDecodeError, TypeError):
            event["details"] = {}
        events_by_cycle.setdefault(int(row["cycle_id"]), []).append(event)
    state_labels = {
        "draft": "Em elaboração",
        "awaiting_receipt": "Aguardando recebimento",
        "received": "Recebida",
    }
    active_row = next(
        (row for row in cycle_rows if row["state"] in {"draft", "awaiting_receipt"}),
        cycle_rows[0] if cycle_rows else None,
    )
    active_cycle_id = int(active_row["id"]) if active_row else None
    cycles = []
    for row in cycle_rows:
        cycle = dict(row)
        cycle["state_label"] = state_labels.get(cycle["state"], cycle["state"])
        cycle["items"] = items_by_cycle.get(int(row["id"]), [])
        cycle["events"] = events_by_cycle.get(int(row["id"]), [])
        cycle["is_active"] = int(row["id"]) == active_cycle_id
        cycles.append(cycle)
    active_rows = [
        row for row in latest_rows
        if active_cycle_id is not None and int(row["cycle_id"]) == active_cycle_id
    ]
    summary = {
        "pending": sum(row["status"] == "Pendente" and row["item_type"] == "Pendência" for row in active_rows),
        "in_progress": sum(row["status"] == "Em andamento" and row["item_type"] == "Pendência" for row in active_rows),
        "completed": sum(row["status"] == "Concluída" and row["item_type"] == "Pendência" for row in active_rows),
        "information": sum(row["item_type"] == "Informação" for row in active_rows),
    }
    return {
        "cycles": cycles,
        "summary": summary,
        "shifts": SHIFTS,
        "active_cycle_id": active_cycle_id,
        "history_total": max(0, total_cycles - (1 if active_cycle_id is not None else 0)),
    }


def save_handover(
    data: dict[str, Any], handover_id: int | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_handovers_db()
    values = validate_handover(data)
    timestamp = now_iso()
    origin, target, message, priority, base_scope, item_type, assignee = values
    username, author = handover_actor(actor, data)
    with HANDOVERS_LOCK, handovers_connection() as connection:
        if handover_id is None:
            cycle = ensure_draft_handover_cycle(connection, origin, target, actor)
            status = "Pendente" if item_type == "Pendência" else "Informação"
            cursor = connection.execute(
                """INSERT INTO handovers(
                   cycle_id, origin_shift, target_shift, message, priority, status, author,
                   created_at, updated_at, completed_at, base_scope, item_type, assignee,
                   author_username
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    cycle["id"], origin, target, message, priority, status, author,
                    timestamp, timestamp, base_scope, item_type, assignee, username,
                ),
            )
            handover_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE handovers SET root_item_id=id WHERE id=?", (handover_id,)
            )
            connection.execute(
                "UPDATE handover_cycles SET updated_at=? WHERE id=?", (timestamp, cycle["id"])
            )
            record_handover_event(
                connection, int(cycle["id"]), "Item criado", actor,
                item_id=handover_id,
                details={"base_scope": base_scope, "item_type": item_type, "priority": priority},
            )
        else:
            current = connection.execute(
                """SELECT h.*, c.state AS cycle_state FROM handovers h
                   JOIN handover_cycles c ON c.id=h.cycle_id WHERE h.id=?""",
                (handover_id,),
            ).fetchone()
            if not current:
                raise LookupError("Item da passagem de turno não encontrado.")
            if current["cycle_state"] != "draft":
                raise ValueError("Após a publicação, o conteúdo original não pode ser alterado.")
            if int(current["carried_from_id"] or 0):
                raise ValueError("Pendências carregadas mantêm o texto original; use comentários para complementar.")
            if current["origin_shift"] != origin or current["target_shift"] != target:
                raise ValueError("Os turnos da passagem em elaboração não podem ser alterados por item.")
            status = "Pendente" if item_type == "Pendência" else "Informação"
            cursor = connection.execute(
                """UPDATE handovers SET message=?, priority=?, status=?, base_scope=?,
                   item_type=?, assignee=?, updated_at=? WHERE id=?""",
                (message, priority, status, base_scope, item_type, assignee, timestamp, handover_id),
            )
            if not cursor.rowcount:
                raise LookupError("Item da passagem de turno não encontrado.")
            record_handover_event(
                connection, int(current["cycle_id"]), "Item editado", actor,
                item_id=handover_id,
                details={"base_scope": base_scope, "item_type": item_type, "priority": priority},
            )
        row = connection.execute("SELECT * FROM handovers WHERE id=?", (handover_id,)).fetchone()
    return handover_dict(row)


def delete_handover(handover_id: int, actor: dict[str, Any] | None = None) -> None:
    initialize_handovers_db()
    with HANDOVERS_LOCK, handovers_connection() as connection:
        item = connection.execute(
            """SELECT h.*, c.state AS cycle_state FROM handovers h
               JOIN handover_cycles c ON c.id=h.cycle_id WHERE h.id=?""",
            (handover_id,),
        ).fetchone()
        if not item:
            raise LookupError("Item da passagem de turno não encontrado.")
        if item["cycle_state"] != "draft":
            raise ValueError("Itens publicados não podem ser excluídos; conclua ou comente a pendência.")
        cursor = connection.execute("DELETE FROM handovers WHERE id=?", (handover_id,))
        if not cursor.rowcount:
            raise LookupError("Item da passagem de turno não encontrado.")
        record_handover_event(
            connection, int(item["cycle_id"]), "Item excluído durante elaboração", actor,
            details={"item_id": handover_id, "message": item["message"][:300]},
        )


def publish_handover_cycle(cycle_id: int, actor: dict[str, Any]) -> dict[str, Any]:
    initialize_handovers_db()
    with HANDOVERS_LOCK, handovers_connection() as connection:
        cycle = connection.execute("SELECT * FROM handover_cycles WHERE id=?", (cycle_id,)).fetchone()
        if not cycle:
            raise LookupError("Passagem de turno não encontrada.")
        if cycle["state"] != "draft":
            raise ValueError("Somente uma passagem em elaboração pode ser publicada.")
        if not connection.execute("SELECT 1 FROM handovers WHERE cycle_id=? LIMIT 1", (cycle_id,)).fetchone():
            raise ValueError("Inclua ao menos uma anotação antes de publicar.")
        timestamp = now_iso()
        username, name = handover_actor(actor)
        connection.execute(
            """UPDATE handover_cycles SET state='awaiting_receipt', updated_at=?,
               published_by_username=?, published_by_name=?, published_at=? WHERE id=?""",
            (timestamp, username, name, timestamp, cycle_id),
        )
        record_handover_event(connection, cycle_id, "Passagem publicada", actor)
    return next(item for item in list_handover_cycles()["cycles"] if item["id"] == cycle_id)


def receive_handover_cycle(cycle_id: int, actor: dict[str, Any]) -> dict[str, Any]:
    initialize_handovers_db()
    with HANDOVERS_LOCK, handovers_connection() as connection:
        cycle = connection.execute("SELECT * FROM handover_cycles WHERE id=?", (cycle_id,)).fetchone()
        if not cycle:
            raise LookupError("Passagem de turno não encontrada.")
        if cycle["state"] != "awaiting_receipt":
            raise ValueError("Esta passagem não está aguardando recebimento.")
        timestamp = now_iso()
        username, name = handover_actor(actor)
        connection.execute(
            """UPDATE handover_cycles SET state='received', updated_at=?,
               received_by_username=?, received_by_name=?, received_at=? WHERE id=?""",
            (timestamp, username, name, timestamp, cycle_id),
        )
        record_handover_event(connection, cycle_id, "Recebimento confirmado", actor)
    return next(item for item in list_handover_cycles()["cycles"] if item["id"] == cycle_id)


def transition_handover_item(
    handover_id: int, data: dict[str, Any], actor: dict[str, Any]
) -> dict[str, Any]:
    initialize_handovers_db()
    action = str(data.get("action", "")).strip()
    note = str(data.get("note", "")).strip()
    assignee = str(data.get("assignee", "")).strip()
    if action not in {"assume", "complete", "reopen", "assign", "comment"}:
        raise ValueError("Ação de passagem de turno inválida.")
    if action in {"complete", "reopen", "comment"} and not note:
        raise ValueError("Registre uma observação para esta ação.")
    if len(note) > 2000 or len(assignee) > 100:
        raise ValueError("Observação ou responsável excede o limite permitido.")
    timestamp = now_iso()
    username, name = handover_actor(actor)
    with HANDOVERS_LOCK, handovers_connection() as connection:
        item = connection.execute("SELECT * FROM handovers WHERE id=?", (handover_id,)).fetchone()
        if not item:
            raise LookupError("Item da passagem de turno não encontrado.")
        newer = connection.execute(
            """SELECT 1 FROM handovers WHERE COALESCE(root_item_id, id)=?
               AND id>? LIMIT 1""",
            (item["root_item_id"] or item["id"], item["id"]),
        ).fetchone()
        if newer:
            raise ValueError("Use a ocorrência mais recente desta pendência para registrar a ação.")
        if item["item_type"] != "Pendência" and action != "comment":
            raise ValueError("Informações não possuem fluxo de conclusão.")
        details: dict[str, Any] = {"note": note} if note else {}
        event_cycle_id = int(item["cycle_id"])
        if action == "assume":
            connection.execute(
                "UPDATE handovers SET status='Em andamento', assignee=?, updated_at=? WHERE id=?",
                (name, timestamp, handover_id),
            )
            event_action = "Pendência assumida"
            details["assignee"] = name
        elif action == "complete":
            if item["status"] == "Concluída":
                raise ValueError("Esta pendência já está concluída.")
            connection.execute(
                """UPDATE handovers SET status='Concluída', completed_at=?, completed_by=?,
                   completion_note=?, updated_at=? WHERE id=?""",
                (timestamp, name, note, timestamp, handover_id),
            )
            event_action = "Pendência concluída"
        elif action == "reopen":
            if item["status"] != "Concluída":
                raise ValueError("Somente uma pendência concluída pode ser reaberta.")
            draft = connection.execute(
                "SELECT * FROM handover_cycles WHERE state='draft' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not draft:
                origin = str(data.get("origin_shift", "")).strip().upper()
                target = str(data.get("target_shift", "")).strip().upper()
                if origin not in SHIFTS or target not in SHIFTS or origin == target:
                    raise ValueError(
                        "Informe a rota do turno atual para reabrir esta pendência no ciclo ativo."
                    )
                draft = ensure_draft_handover_cycle(connection, origin, target, actor)
            if int(draft["id"]) != int(item["cycle_id"]):
                cursor = connection.execute(
                    """INSERT INTO handovers(
                       cycle_id, origin_shift, target_shift, message, priority, status, author,
                       created_at, updated_at, completed_at, base_scope, item_type, assignee,
                       author_username, completed_by, completion_note, carried_from_id,
                       root_item_id, reopened_at
                       ) VALUES (?, ?, ?, ?, ?, 'Pendente', ?, ?, ?, NULL, ?, 'Pendência', ?,
                                 ?, '', '', ?, ?, ?)""",
                    (
                        draft["id"], draft["origin_shift"], draft["target_shift"],
                        item["message"], item["priority"], item["author"], timestamp, timestamp,
                        item["base_scope"], item["assignee"], item["author_username"], item["id"],
                        item["root_item_id"] or item["id"], timestamp,
                    ),
                )
                handover_id = int(cursor.lastrowid)
                connection.execute(
                    "UPDATE handover_cycles SET updated_at=? WHERE id=?",
                    (timestamp, draft["id"]),
                )
                event_action = "Pendência reaberta no ciclo atual"
                details["carried_from_id"] = item["id"]
                event_cycle_id = int(draft["id"])
            else:
                connection.execute(
                    """UPDATE handovers SET status='Pendente', completed_at=NULL, completed_by='',
                       completion_note='', reopened_at=?, updated_at=? WHERE id=?""",
                    (timestamp, timestamp, handover_id),
                )
                event_action = "Pendência reaberta"
                event_cycle_id = int(item["cycle_id"])
        elif action == "assign":
            connection.execute(
                "UPDATE handovers SET assignee=?, updated_at=? WHERE id=?",
                (assignee, timestamp, handover_id),
            )
            event_action = "Responsável alterado"
            details["assignee"] = assignee
        else:
            event_action = "Comentário adicionado"
        record_handover_event(
            connection, event_cycle_id, event_action, actor,
            item_id=handover_id, details=details,
        )
        row = connection.execute("SELECT * FROM handovers WHERE id=?", (handover_id,)).fetchone()
    return handover_dict(row)


@contextmanager
def reports_connection():
    connection = open_database(REPORTS_DB_PATH)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_reports_db() -> None:
    initialize_rules_db()
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
            assignee_user_id INTEGER,
            assignee_username TEXT NOT NULL DEFAULT '',
            assignee_name TEXT NOT NULL DEFAULT '',
            rule_candidate_id INTEGER,
            rule_action TEXT NOT NULL DEFAULT 'keep',
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
        connection.execute("""CREATE TABLE IF NOT EXISTS report_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            author_user_id INTEGER NOT NULL,
            author_username TEXT NOT NULL,
            author_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS report_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            content BLOB NOT NULL,
            uploaded_by_user_id INTEGER NOT NULL,
            uploaded_by_username TEXT NOT NULL,
            uploaded_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
        )""")
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(reports)").fetchall()
        }
        report_columns = {
            "assignee_user_id": "INTEGER",
            "assignee_username": "TEXT NOT NULL DEFAULT ''",
            "assignee_name": "TEXT NOT NULL DEFAULT ''",
            "rule_candidate_id": "INTEGER",
            "rule_action": "TEXT NOT NULL DEFAULT 'keep'",
        }
        for column, declaration in report_columns.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE reports ADD COLUMN {column} {declaration}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, priority, updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_report_events_report ON report_events(report_id, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_report_comments_report ON report_comments(report_id, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_report_attachments_report ON report_attachments(report_id, created_at)")
        migrate_legacy_tables(connection, REPORTS_DB_PATH, LEGACY_DB_PATHS["reports"], {
            "reports": (
                "id", "report_type", "title", "description", "reference", "priority",
                "status", "reporter_user_id", "reporter_username", "reporter_name",
                "resolution", "created_at", "updated_at", "resolved_at",
            ),
            "report_events": (
                "id", "report_id", "action", "actor_username", "actor_name", "details",
                "created_at",
            ),
        })
    backfill_report_candidate_links()


def backfill_report_candidate_links() -> None:
    """Relaciona reports antigos à regra criada na mesma indicação, sem mudar decisões."""
    with reports_connection() as connection:
        rows = connection.execute(
            """SELECT id, title, reference FROM reports
               WHERE report_type='question' AND rule_candidate_id IS NULL"""
        ).fetchall()
    if not rows:
        return
    updates = []
    with rules_connection() as connection:
        for row in rows:
            question = row["reference"].strip() or row["title"].strip()
            candidate = connection.execute(
                "SELECT id FROM rule_candidates WHERE normalized_question=?",
                (normalize(question),),
            ).fetchone()
            if candidate:
                updates.append((int(candidate["id"]), int(row["id"])))
    if updates:
        with REPORTS_LOCK, reports_connection() as connection:
            connection.executemany(
                "UPDATE reports SET rule_candidate_id=? WHERE id=? AND rule_candidate_id IS NULL",
                updates,
            )


def report_rule_summary(candidate_id: int | None) -> dict[str, Any] | None:
    if not candidate_id:
        return None
    initialize_rules_db()
    with rules_connection() as connection:
        row = connection.execute(
            "SELECT id, question, status, rule_code, updated_at FROM rule_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["status_label"] = RULE_CANDIDATE_STATUS_LABELS.get(item["status"], item["status"])
    return item


def report_details(connection: sqlite3.Connection, report_id: int) -> dict[str, Any]:
    comments = [dict(row) for row in connection.execute(
        """SELECT id, body, author_username, author_name, created_at
           FROM report_comments WHERE report_id=? ORDER BY created_at""",
        (report_id,),
    ).fetchall()]
    attachments = [dict(row) for row in connection.execute(
        """SELECT id, filename, content_type, size_bytes, uploaded_by_username,
                  uploaded_by_name, created_at
           FROM report_attachments WHERE report_id=? ORDER BY created_at""",
        (report_id,),
    ).fetchall()]
    events = []
    for row in connection.execute(
        """SELECT id, action, actor_username, actor_name, details, created_at
           FROM report_events WHERE report_id=? ORDER BY created_at""",
        (report_id,),
    ).fetchall():
        item = dict(row)
        try:
            item["details"] = json.loads(item["details"] or "{}")
        except json.JSONDecodeError:
            item["details"] = {}
        events.append(item)
    return {"comments": comments, "attachments": attachments, "events": events}


def report_dict(row: sqlite3.Row, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    item = {
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
        "assignee_user_id": row["assignee_user_id"],
        "assignee_username": row["assignee_username"],
        "assignee_name": row["assignee_name"],
        "rule_candidate_id": row["rule_candidate_id"],
        "rule_action": row["rule_action"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
    }
    item["rule_candidate"] = None
    if connection is not None:
        item.update(report_details(connection, int(row["id"])))
    return item


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
        items = [report_dict(row, connection) for row in rows]
    for item in items:
        item["rule_candidate"] = report_rule_summary(item["rule_candidate_id"])
    return items


def list_report_assignees() -> list[dict[str, Any]]:
    initialize_auth_db()
    with auth_connection() as connection:
        rows = connection.execute(
            """SELECT id, username, display_name, role FROM users
               WHERE active=1 AND role IN ('admin', 'supervisor')
               ORDER BY display_name"""
        ).fetchall()
    return [dict(row) for row in rows]


def create_report(data: dict[str, Any], reporter: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    values = validate_new_report(data)
    timestamp = now_iso()
    candidate = None
    if values[0] == "question":
        candidate = upsert_rule_candidate(
            question=values[3] or values[1],
            proposed_answer=values[2],
            confidence="low",
            source_kind="operator_report",
            sources=[],
            local_evidence=[],
            actor=reporter,
        )
    with REPORTS_LOCK, reports_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO reports(report_type, title, description, reference, priority, status,
               reporter_user_id, reporter_username, reporter_name, resolution, rule_candidate_id,
               rule_action, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'Aberto', ?, ?, ?, '', ?, 'keep', ?, ?)""",
            (
                *values, reporter["id"], reporter["username"], reporter["display_name"],
                candidate["id"] if candidate else None, timestamp, timestamp,
            ),
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
    with reports_connection() as connection:
        row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        item = report_dict(row, connection)
    item["rule_candidate"] = report_rule_summary(item["rule_candidate_id"])
    return item


def resolve_report_assignee(user_id: Any) -> tuple[int | None, str, str]:
    if user_id in {None, "", 0, "0"}:
        return None, "", ""
    try:
        candidate_id = int(user_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Responsável inválido.") from error
    initialize_auth_db()
    with auth_connection() as connection:
        row = connection.execute(
            """SELECT id, username, display_name FROM users
               WHERE id=? AND active=1 AND role IN ('admin', 'supervisor')""",
            (candidate_id,),
        ).fetchone()
    if not row:
        raise ValueError("Selecione um Supervisor ou Administrador ativo como responsável.")
    return int(row["id"]), row["username"], row["display_name"]


def transition_report_rule(
    report: sqlite3.Row, rule_action: str, resolution: str, actor: dict[str, Any]
) -> int | None:
    candidate_id = report["rule_candidate_id"]
    if rule_action == "keep":
        return candidate_id
    if rule_action not in REPORT_RULE_ACTIONS:
        raise ValueError("Selecione uma tratativa válida para a regra relacionada.")
    if not candidate_id and rule_action == "pending_approval":
        candidate = upsert_rule_candidate(
            question=report["reference"].strip() or report["title"].strip(),
            proposed_answer=resolution,
            confidence="low",
            source_kind="operator_report",
            sources=[],
            local_evidence=[],
            actor=actor,
        )
        candidate_id = int(candidate["id"])
    if not candidate_id:
        return None
    with RULES_LOCK, rules_connection() as connection:
        candidate = connection.execute(
            "SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if not candidate:
            return None
        if candidate["status"] == "approved":
            if rule_action in {"covered", "pending_approval"}:
                return candidate_id
            raise ValueError("A regra relacionada já está aprovada e não pode ser descartada pelo report.")
        timestamp = now_iso()
        if rule_action == "pending_approval":
            connection.execute(
                """UPDATE rule_candidates SET proposed_answer=?, status='pending_approval',
                   reviewed_by_username=?, reviewed_by_name=?, reviewed_at=?, review_note=?,
                   updated_at=? WHERE id=?""",
                (
                    resolution, actor["username"], actor["display_name"], timestamp,
                    "Encaminhada para aprovação pela tratativa do report.", timestamp, candidate_id,
                ),
            )
            action = "Encaminhada pelo report"
        else:
            note = (
                "Pergunta já coberta pela base confirmada; report encerrado."
                if rule_action == "covered"
                else "O report foi encerrado sem gerar regra de conhecimento."
            )
            connection.execute(
                """UPDATE rule_candidates SET status='rejected', reviewed_by_username=?,
                   reviewed_by_name=?, reviewed_at=?, review_note=?, updated_at=? WHERE id=?""",
                (actor["username"], actor["display_name"], timestamp, note, timestamp, candidate_id),
            )
            action = "Rejeitada pelo report"
        connection.execute(
            """INSERT INTO rule_events(candidate_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                candidate_id, action, actor["username"], actor["display_name"],
                json.dumps({"report_id": report["id"], "rule_action": rule_action}, ensure_ascii=False),
                timestamp,
            ),
        )
    return candidate_id


def update_report(report_id: int, data: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    priority = str(data.get("priority", "")).strip()
    status = str(data.get("status", "")).strip()
    resolution = str(data.get("resolution", "")).strip()
    assignee = resolve_report_assignee(data.get("assignee_user_id"))
    rule_action = str(data.get("rule_action", "keep")).strip() or "keep"
    if priority not in REPORT_PRIORITIES or status not in REPORT_STATUSES:
        raise ValueError("Prioridade ou situação do report inválida.")
    if len(resolution) > 2000:
        raise ValueError("A tratativa deve ter até 2.000 caracteres.")
    if status in {"Resolvido", "Descartado"} and not resolution:
        raise ValueError("Registre a tratativa antes de encerrar o report.")
    if status not in {"Resolvido", "Descartado"}:
        rule_action = "keep"
    elif status == "Descartado" and rule_action == "keep":
        rule_action = "no_rule"
    elif status == "Resolvido" and rule_action == "keep":
        rule_action = "pending_approval"
    timestamp = now_iso()
    resolved_at = timestamp if status in {"Resolvido", "Descartado"} else None
    with REPORTS_LOCK:
        with reports_connection() as connection:
            current = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not current:
            raise LookupError("Report não encontrado.")
        candidate_id = transition_report_rule(current, rule_action, resolution, actor)
        changes = {
            "status": {"from": current["status"], "to": status},
            "priority": {"from": current["priority"], "to": priority},
            "resolution_updated": resolution != current["resolution"],
            "assignee": {"from": current["assignee_name"], "to": assignee[2]},
            "rule_action": rule_action,
        }
        with reports_connection() as connection:
            connection.execute(
                """UPDATE reports SET priority=?, status=?, resolution=?, assignee_user_id=?,
                   assignee_username=?, assignee_name=?, rule_candidate_id=?, rule_action=?,
                   updated_at=?, resolved_at=? WHERE id=?""",
                (
                    priority, status, resolution, *assignee, candidate_id, rule_action,
                    timestamp, resolved_at, report_id,
                ),
            )
            connection.execute(
                """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
                   VALUES (?, 'Atualizado', ?, ?, ?, ?)""",
                (
                    report_id, actor["username"], actor["display_name"],
                    json.dumps(changes, ensure_ascii=False), timestamp,
                ),
            )
    with reports_connection() as connection:
        row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        item = report_dict(row, connection)
    item["rule_candidate"] = report_rule_summary(item["rule_candidate_id"])
    return item


def update_own_report(report_id: int, data: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    values = validate_new_report(data)
    timestamp = now_iso()
    with REPORTS_LOCK, reports_connection() as connection:
        current = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not current:
            raise LookupError("Report não encontrado.")
        if current["reporter_user_id"] != actor["id"]:
            raise PermissionError("Você só pode editar reports criados por você.")
        if current["status"] != "Aberto":
            raise PermissionError("Somente reports abertos podem ser editados pelo autor.")
        if values[0] != current["report_type"]:
            raise ValueError("O tipo do report não pode ser alterado após o envio.")
        connection.execute(
            """UPDATE reports SET title=?, description=?, reference=?, priority=?, updated_at=?
               WHERE id=?""",
            (values[1], values[2], values[3], values[4], timestamp, report_id),
        )
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Conteúdo editado', ?, ?, '{}', ?)""",
            (report_id, actor["username"], actor["display_name"], timestamp),
        )
        candidate_id = current["rule_candidate_id"]
    if candidate_id:
        with RULES_LOCK, rules_connection() as connection:
            candidate = connection.execute(
                "SELECT status FROM rule_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if candidate and candidate["status"] == "unreviewed":
                try:
                    connection.execute(
                        """UPDATE rule_candidates SET question=?, normalized_question=?, proposed_answer=?,
                           updated_at=? WHERE id=?""",
                        (
                            values[3] or values[1], normalize(values[3] or values[1]),
                            values[2], timestamp, candidate_id,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("Já existe outra regra candidata para esta pergunta.") from error
    with reports_connection() as connection:
        row = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        item = report_dict(row, connection)
    item["rule_candidate"] = report_rule_summary(item["rule_candidate_id"])
    return item


def add_report_comment(report_id: int, body: str, actor: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    body = body.strip()
    if not body or len(body) > 2000:
        raise ValueError("Informe um comentário de até 2.000 caracteres.")
    timestamp = now_iso()
    with REPORTS_LOCK, reports_connection() as connection:
        report = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise LookupError("Report não encontrado.")
        if actor["role"] == "operator" and report["reporter_user_id"] != actor["id"]:
            raise PermissionError("Você só pode comentar em reports criados por você.")
        cursor = connection.execute(
            """INSERT INTO report_comments(report_id, body, author_user_id, author_username,
               author_name, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, body, actor["id"], actor["username"], actor["display_name"], timestamp),
        )
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Comentário adicionado', ?, ?, '{}', ?)""",
            (report_id, actor["username"], actor["display_name"], timestamp),
        )
        row = connection.execute("SELECT * FROM report_comments WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def add_report_attachment(report_id: int, data: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    initialize_reports_db()
    filename = Path(str(data.get("filename", "")).strip()).name[:180]
    filename = re.sub(r'[\x00-\x1f\x7f"\\]', "_", filename).strip()
    content_type = str(data.get("content_type", "")).strip().lower()
    encoded = str(data.get("content_base64", ""))
    if not filename or content_type not in REPORT_ATTACHMENT_TYPES:
        raise ValueError("Envie uma imagem JPG/PNG, PDF ou arquivo TXT válido.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("O anexo enviado é inválido.") from error
    if not content or len(content) > MAX_REPORT_ATTACHMENT_BYTES:
        raise ValueError("Cada anexo deve possuir no máximo 2 MB.")
    timestamp = now_iso()
    with REPORTS_LOCK, reports_connection() as connection:
        report = connection.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report:
            raise LookupError("Report não encontrado.")
        if actor["role"] == "operator" and report["reporter_user_id"] != actor["id"]:
            raise PermissionError("Você só pode anexar arquivos aos reports criados por você.")
        if actor["role"] == "operator" and report["status"] not in {"Aberto", "Em análise"}:
            raise PermissionError("Não é possível anexar arquivos a um report encerrado.")
        count = connection.execute(
            "SELECT COUNT(*) FROM report_attachments WHERE report_id=?", (report_id,)
        ).fetchone()[0]
        if count >= MAX_REPORT_ATTACHMENTS:
            raise ValueError(f"Cada report aceita no máximo {MAX_REPORT_ATTACHMENTS} anexos.")
        cursor = connection.execute(
            """INSERT INTO report_attachments(report_id, filename, content_type, size_bytes,
               content, uploaded_by_user_id, uploaded_by_username, uploaded_by_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id, filename, content_type, len(content), sqlite3.Binary(content), actor["id"],
                actor["username"], actor["display_name"], timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Anexo adicionado', ?, ?, ?, ?)""",
            (
                report_id, actor["username"], actor["display_name"],
                json.dumps({"filename": filename, "size_bytes": len(content)}, ensure_ascii=False), timestamp,
            ),
        )
        row = connection.execute(
            """SELECT id, filename, content_type, size_bytes, uploaded_by_username,
                      uploaded_by_name, created_at FROM report_attachments WHERE id=?""",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def get_report_attachment(attachment_id: int) -> tuple[bytes, str, str]:
    initialize_reports_db()
    with reports_connection() as connection:
        row = connection.execute(
            "SELECT filename, content_type, content FROM report_attachments WHERE id=?",
            (attachment_id,),
        ).fetchone()
    if not row:
        raise LookupError("Anexo não encontrado.")
    return bytes(row["content"]), row["content_type"], row["filename"]


def delete_report_attachment(attachment_id: int, actor: dict[str, Any]) -> None:
    initialize_reports_db()
    with REPORTS_LOCK, reports_connection() as connection:
        row = connection.execute(
            """SELECT a.*, r.status FROM report_attachments a
               JOIN reports r ON r.id=a.report_id WHERE a.id=?""",
            (attachment_id,),
        ).fetchone()
        if not row:
            raise LookupError("Anexo não encontrado.")
        if actor["role"] == "operator" and (
            row["uploaded_by_user_id"] != actor["id"]
            or row["status"] not in {"Aberto", "Em análise"}
        ):
            raise PermissionError("Você não pode excluir este anexo.")
        connection.execute("DELETE FROM report_attachments WHERE id=?", (attachment_id,))
        connection.execute(
            """INSERT INTO report_events(report_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Anexo removido', ?, ?, ?, ?)""",
            (
                row["report_id"], actor["username"], actor["display_name"],
                json.dumps({"filename": row["filename"]}, ensure_ascii=False), now_iso(),
            ),
        )


@contextmanager
def instructor_connection():
    connection = open_database(INSTRUCTORS_DB_PATH)
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
        migrate_legacy_tables(connection, INSTRUCTORS_DB_PATH, LEGACY_DB_PATHS["instructors"], {
            "instructors": ("id", "name", "base", "group_name", "releases", "updated_at"),
        })
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
    initialize_instructors_db()
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
    initialize_instructors_db()
    with INSTRUCTORS_LOCK, instructor_connection() as connection:
        cursor = connection.execute("DELETE FROM instructors WHERE id=?", (instructor_id,))
        if not cursor.rowcount:
            raise LookupError("Instrutor não encontrado.")


@contextmanager
def aircraft_connection():
    connection = open_database(AIRCRAFT_DB_PATH)
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
            fleet_status TEXT NOT NULL DEFAULT 'Ativa',
            operational_status TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            active_restrictions TEXT NOT NULL,
            temporary_restrictions TEXT NOT NULL,
            restriction_date TEXT,
            updated_at TEXT NOT NULL
        )""")
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aircraft)").fetchall()
        }
        if "fleet_status" not in columns:
            connection.execute(
                "ALTER TABLE aircraft ADD COLUMN fleet_status TEXT NOT NULL DEFAULT 'Ativa'"
            )
        migrate_legacy_tables(connection, AIRCRAFT_DB_PATH, LEGACY_DB_PATHS["aircraft"], {
            "aircraft": (
                "id", "model", "registration", "base", "operational_status",
                "operation_type", "active_restrictions", "temporary_restrictions",
                "restriction_date", "updated_at",
            ),
        })
        connection.execute(
            "UPDATE aircraft SET fleet_status='Ativa', operational_status='Operacional' "
            "WHERE operational_status='Ativa'"
        )
        connection.execute(
            "UPDATE aircraft SET fleet_status='Inativa', operational_status='Fora de Operação' "
            "WHERE operational_status='Inativa'"
        )
        connection.execute("UPDATE aircraft SET operational_status='Em Manutenção' WHERE operational_status='Manutenção'")
        if connection.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0] == 0:
            timestamp = now_iso()
            connection.executemany(
                """INSERT INTO aircraft(model, registration, base, fleet_status, operational_status, operation_type,
                   active_restrictions, temporary_restrictions, restriction_date, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(*item, timestamp) for item in AIRCRAFT_SEED],
            )
        sold_note = "Aeronave vendida; não pertence à frota SAFE desde 29/07/2006"
        connection.execute(
            """UPDATE aircraft
               SET fleet_status='Inativa', operational_status='Fora de Operação',
                   operation_type='Não aplicável (vendida)', active_restrictions=?,
                   temporary_restrictions='Nenhuma', restriction_date='2006-07-29',
                   updated_at=?
               WHERE registration='PS-SFJ'
                 AND (fleet_status<>'Inativa' OR operational_status<>'Fora de Operação'
                      OR operation_type<>'Não aplicável (vendida)'
                      OR active_restrictions<>? OR IFNULL(restriction_date, '')<>'2006-07-29')""",
            (sold_note, now_iso(), sold_note),
        )


def aircraft_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "model": row["model"], "registration": row["registration"],
        "base": row["base"], "fleet_status": row["fleet_status"],
        "status": row["operational_status"],
        "operation_type": row["operation_type"], "active_restrictions": row["active_restrictions"],
        "temporary_restrictions": row["temporary_restrictions"],
        "restriction_date": row["restriction_date"], "updated_at": row["updated_at"],
    }


def validate_aircraft(data: dict[str, Any]) -> tuple[str, ...]:
    values = (
        str(data.get("model", "")).strip(),
        str(data.get("registration", "")).strip().upper(),
        validate_base_code(str(data.get("base", "")), allow_unassigned=True),
        str(data.get("fleet_status", "Ativa")).strip(),
        str(data.get("status", "")).strip(),
        str(data.get("operation_type", "")).strip(),
        str(data.get("active_restrictions", "")).strip() or "Nenhuma",
        str(data.get("temporary_restrictions", "")).strip() or "Nenhuma",
        str(data.get("restriction_date") or "").strip(),
    )
    if any(not value for value in values[:6]) or any(len(value) > 500 for value in values):
        raise ValueError(
            "Preencha modelo, matrícula, base, situação da frota, situação operacional "
            "e tipo de operação com valores válidos."
        )
    if values[3] not in AIRCRAFT_FLEET_STATUSES:
        raise ValueError("Selecione uma situação da frota válida.")
    if values[4] not in AIRCRAFT_OPERATIONAL_STATUSES:
        raise ValueError("Selecione uma situação operacional válida.")
    if values[8] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[8]):
        raise ValueError("Data da restrição inválida.")
    return values


def list_aircraft() -> list[dict[str, Any]]:
    initialize_aircraft_db()
    with aircraft_connection() as connection:
        rows = connection.execute(
            """SELECT * FROM aircraft ORDER BY
               CASE fleet_status WHEN 'Ativa' THEN 0 ELSE 1 END,
               operational_status, model, registration"""
        ).fetchall()
    return [aircraft_dict(row) for row in rows]


def save_aircraft(data: dict[str, Any], aircraft_id: int | None = None) -> dict[str, Any]:
    initialize_aircraft_db()
    values = validate_aircraft(data)
    timestamp = now_iso()
    with AIRCRAFT_LOCK, aircraft_connection() as connection:
        try:
            if aircraft_id is None:
                cursor = connection.execute(
                    """INSERT INTO aircraft(model, registration, base, fleet_status, operational_status, operation_type,
                       active_restrictions, temporary_restrictions, restriction_date, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULLIF(?, ''), ?)""", (*values, timestamp),
                )
                aircraft_id = cursor.lastrowid
            else:
                cursor = connection.execute(
                    """UPDATE aircraft SET model=?, registration=?, base=?, fleet_status=?,
                       operational_status=?, operation_type=?,
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
    initialize_aircraft_db()
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


def light_portuguese_stem(token: str) -> str:
    """Normaliza flexões simples sem transformar a recuperação em busca aproximada ampla."""
    value = normalize(token)
    if len(value) > 5 and value.endswith("oes"):
        value = value[:-3] + "ao"
    elif len(value) > 4 and value.endswith("s") and not value.endswith(("ss", "us")):
        value = value[:-1]
    if len(value) > 4 and value.endswith("m"):
        value = value[:-1]
    if len(value) > 4 and value.endswith("r"):
        value = value[:-1]
    return value


def contains_semantic_token(normalized: str, token: str) -> bool:
    if contains_normalized_token(normalized, token):
        return True
    token_stem = light_portuguese_stem(token)
    if len(token_stem) < 4:
        return False
    words = re.split(r"[^a-z0-9-]+", normalized)
    return any(light_portuguese_stem(word) == token_stem for word in words if word)


def contains_token(value: str, token: str) -> bool:
    return contains_normalized_token(normalize(value), token)


def reference_codes(value: str) -> set[str]:
    """Extrai códigos operacionais citados literalmente, como NAV03, PS12 e RG-006."""
    return set(re.findall(r"\b[a-z]{2,10}[-]?\d{1,4}[a-z0-9-]*\b", normalize(value)))


def reference_code_boost(question: str, searchable: str) -> int:
    requested = reference_codes(question)
    if not requested:
        return 0
    available = reference_codes(searchable)
    matched = requested & available
    if not matched:
        return 0
    boost = 18 * len(matched)
    if len(requested) >= 2 and requested <= available:
        boost += 55
    return boost


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
    if instructor_allocation_intent(normalized):
        expansions.extend([
            "inva", "instrutor", "cco", "escolha", "preferencia", "substituicao",
            "escala", "agendamento",
        ])
    base_context = (
        "base" in normalized
        or bool(re.search(r"\b(?:sjk|cpq)\b", normalized))
        or "sao jose" in normalized
        or "campinas" in normalized
    )
    if base_context and any(term in normalized for term in ("troc", "mud", "transfer", "alter", "migr")):
        expansions.extend(["troca", "base", "aluno"])
    return list(dict.fromkeys(items + expansions))


def instructor_allocation_intent(value: str) -> bool:
    normalized = normalize(value)
    mentions_instructor = any(term in normalized for term in (
        "inva", "instrutor", "professor de voo", "quem vai voar comigo",
    ))
    asks_allocation = any(term in normalized for term in (
        "escolh", "prefer", "troc", "substitu", "especific", "combina", "confirm",
        "agend", "marc", "defin", "escal", "nao gostei", "outro instrutor",
        "mesmo instrutor", "voar com", "solicitar",
    ))
    return mentions_instructor and asks_allocation


def canonical_intent_rule_ids(value: str) -> list[str]:
    """Mapeia intenções operacionais conhecidas às respostas canônicas aprovadas.

    O roteamento é contextual: ele não substitui a busca, apenas impede que uma
    coincidência lexical de outro assunto seja tratada como resposta definitiva.
    """
    normalized = normalize(value)
    preferred: list[str] = []

    def prefer(*rule_ids: str) -> None:
        for rule_id in rule_ids:
            if rule_id and rule_id not in preferred:
                preferred.append(rule_id)

    medical_intent = "cma" in normalized or "certificado medico" in normalized
    if medical_intent and any(term in normalized for term in (
        "extens", "prorrog", "tolerancia", "30 dias", "validade",
    )):
        prefer(CMA_EXTENSION_RULE_ID, CMA_INVALID_RULE_ID)
    elif medical_intent and any(term in normalized for term in (
        "voar", "voo", "operar", "sem cma", "vencid", "valido",
    )):
        prefer(CMA_INVALID_RULE_ID, CMA_EXTENSION_RULE_ID)

    if "cavok" in normalized and any(term in normalized for term in (
        "acess", "entr", "login", "senha", "link", "portal", "cadastro",
    )):
        prefer(CAVOK_ACCESS_RULE_ID)

    if instructor_allocation_intent(normalized):
        prefer(INSTRUCTOR_ALLOCATION_RULE_ID)

    base_context = (
        "base" in normalized
        or bool(re.search(r"\b(?:sjk|cpq)\b", normalized))
        or "sao jose" in normalized
        or "campinas" in normalized
    )
    if base_context and any(term in normalized for term in (
        "troc", "mud", "transfer", "alter", "migr",
    )):
        prefer(BASE_TRANSFER_RULE_ID)

    if "barra" in normalized and any(term in normalized for term in (
        "prior", "primeira", "segunda", "cheque", "missao", "critica", "ordem",
    )):
        prefer(BARS_PRIORITY_RULE_ID)

    if "monitor" in normalized and "nav" in normalized and any(term in normalized for term in (
        "fase ap", "aperfeicoamento", "ap01", "ap02", "ap03", "ap04", "ap05",
    )):
        prefer(PP_NAV_MONITORING_RULE_ID)

    asks_nav_order = "nav03" in normalized and "nav02" in normalized and any(
        term in normalized for term in ("antes", "ordem", "sequencia", "adiant", "preced")
    )
    if asks_nav_order:
        prefer(PPA_MISSION_ORDER_RULE_ID)
    elif "sequencia" in normalized and any(term in normalized for term in (
        "ppa", "pp", "missoes", "missao",
    )):
        prefer(PPA_SEQUENCE_RULE_ID)

    day_values = [int(value) for value in re.findall(r"\b(\d{1,3})\s*dias?\b", normalized)]
    recency_days_intent = "trinta dias" in normalized or any(value >= 30 for value in day_values)
    if recency_days_intent and any(
        term in normalized for term in ("sem solo", "sem voar solo", "ap05", "ultimo solo", "ultima solo")
    ):
        prefer(SOLO_RECENCY_RULE_ID, READAPTATION_RULE_ID)

    family_terms = ("mae", "pai", "famil", "acompanhante", "passageiro", "esposa", "marido")
    if "solo" in normalized and any(term in normalized for term in family_terms):
        boarding_terms = ("levar", "embarcar", "a bordo", "voar com", "para voar", "passageiro")
        ground_terms = ("assistir", "acompanhar", "presenciar", "ver", "evento", "terra", "patio")
        if any(term in normalized for term in boarding_terms):
            prefer(PP_SOLO_PASSENGER_RULE_ID, SOLO_FAMILY_VISIT_RULE_ID)
        elif any(term in normalized for term in ground_terms):
            prefer(SOLO_FAMILY_VISIT_RULE_ID, PP_SOLO_PASSENGER_RULE_ID)
        else:
            prefer(PP_SOLO_PASSENGER_RULE_ID, SOLO_FAMILY_VISIT_RULE_ID)

    return preferred


def canonical_intent_boost(claim_id: str, preferred_ids: list[str]) -> int:
    try:
        position = preferred_ids.index(claim_id)
    except ValueError:
        return 0
    return max(520, 650 - (position * 40))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_public_knowledge_index(path_value: str) -> dict[str, Any]:
    content = Path(path_value).read_text(encoding="utf-8")
    _, separator, payload = content.partition("=")
    if not separator:
        raise ValueError("Índice público de conhecimento inválido.")
    return json.loads(payload.strip().removesuffix(";"))


@lru_cache(maxsize=4)
def load_public_operator_answers(path_value: str) -> dict[str, str]:
    public_index = load_public_knowledge_index(path_value)
    return {
        str(claim.get("id", "")): str(claim.get("operatorAnswer", "")).strip()
        for claim in public_index.get("claims", [])
        if claim.get("id") and claim.get("operatorAnswer")
    }


def retrieve_dynamic_rules(question: str) -> list[dict[str, Any]]:
    query_tokens = tokens(question)
    results = []
    for rule in approved_dynamic_rules():
        label = rule.get("approved_rule_text", "")
        metadata = " ".join(str(rule.get(field, "")) for field in (
            "question", "proposed_answer", "rule_code", "authority", "source_reference",
            "scope", "supersedes", "document_id",
        ))
        searchable = normalize(f"{label} {metadata}")
        matched_tokens = {
            token for token in query_tokens if contains_semantic_token(searchable, token)
        }
        informative_matches = {
            token for token in matched_tokens
            if light_portuguese_stem(token) not in DYNAMIC_GENERIC_STEMS
        }
        # Termos genéricos como "voo", "aluno" e "instrução" não bastam para
        # inserir uma regra interna aprovada em uma resposta de outro assunto.
        coverage = len(matched_tokens) / max(1, len(query_tokens))
        if len(matched_tokens) < 2 or coverage < 0.45 or not informative_matches:
            continue
        score = (
            score_text(query_tokens, label, metadata)
            + 6
            + round(30 * coverage)
            + min(20, 8 * len(informative_matches))
        )
        results.append({
            "id": f"approved_rule_{rule['id']}",
            "kind": "confirmed_claim",
            "label": label,
            "code": rule.get("rule_code", ""),
            "source": rule.get("source_reference", ""),
            "location": rule.get("scope", "") or rule.get("source_reference", ""),
            "url": rule.get("source_url", ""),
            "score": score,
            "excerpt": label,
            "operator_answer": label,
        })
    return results


def retrieve_public_claims(question: str, limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = tokens(question)
    preferred_rule_ids = canonical_intent_rule_ids(question)
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
    instructor_intent = instructor_allocation_intent(question_norm)
    results = retrieve_dynamic_rules(question)
    public_index = load_public_knowledge_index(str(PUBLIC_KNOWLEDGE_INDEX_PATH))
    for claim in public_index.get("claims", []):
        metadata = f"{claim.get('code', '')} {claim.get('appliesTo', '')} {claim.get('relation', '')}"
        operator_answer = str(claim.get("operatorAnswer", ""))
        searchable = f"{claim.get('label', '')} {operator_answer}"
        medical_text = normalize(f"{searchable} {metadata}")
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
        # O título continua sendo o sinal lexical principal. A resposta canônica
        # amplia a cobertura sem permitir que textos longos e genéricos dominem
        # uma regra cujo título corresponde diretamente à pergunta.
        score = score_text(query_tokens, claim.get("label", ""), metadata)
        score += reference_code_boost(question, searchable)
        if operator_answer:
            canonical_matches = sum(
                1 for token in query_tokens
                if contains_semantic_token(normalize(operator_answer), token)
            )
            score += min(18, canonical_matches * 3)
        if medical_enrollment_intent and "matricula" in medical_text:
            score += 20
        if medical_validity_intent or medical_operation_intent:
            if claim["id"] in GENERAL_CMA_RULE_IDS:
                score += 35
            elif "matricula" in medical_text:
                score -= 15
        if medical_validity_intent and any(
            term in normalize(claim.get("label", ""))
            for term in ("30 dias", "tolerancia", "nao prorroga")
        ):
            score += 10
        if daily_limit_intent and "limite_diario_instrucao" in claim.get("id", ""):
            score += 20
        if instructor_intent and claim.get("id") == INSTRUCTOR_ALLOCATION_RULE_ID:
            score += 60
        score += canonical_intent_boost(str(claim.get("id", "")), preferred_rule_ids)
        if score <= 0:
            continue
        results.append({
            "id": claim["id"],
            "kind": "confirmed_claim",
            "label": claim.get("label", ""),
            "operator_answer": operator_answer,
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
        (5 if contains_semantic_token(label_norm, token) else 0)
        + (1 if contains_semantic_token(metadata_norm, token) else 0)
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
    preferred_rule_ids = canonical_intent_rule_ids(question)
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
    instructor_intent = instructor_allocation_intent(question_norm)
    banca_ppa_intent = (
        requested_course(question_norm) == "pp"
        and "banca" in question_norm
        and any(term in question_norm for term in ("quantos voos", "sem a banca", "sem banca"))
    )
    claims_data = load_json(CLAIMS_PATH)
    graph_data = load_json(GRAPH_PATH)
    public_operator_answers = load_public_operator_answers(str(PUBLIC_KNOWLEDGE_INDEX_PATH))
    results: list[dict[str, Any]] = retrieve_dynamic_rules(question)
    claim_ids = set()
    for claim in claims_data.get("claims", []):
        if claim.get("status") not in {"confirmed", "confirmed_temporary_override"}:
            continue
        claim_ids.add(claim["id"])
        metadata = f"{claim.get('document_code', '')} {claim.get('source_path', '')} {' '.join(claim.get('applies_to', []))}"
        operator_answer = (
            claim.get("operator_answer", "")
            or public_operator_answers.get(claim["id"], "")
        )
        searchable = f"{claim.get('label', '')} {operator_answer}"
        medical_text = normalize(f"{searchable} {metadata}")
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
        # O título continua sendo o sinal lexical principal. A resposta canônica
        # amplia a cobertura sem permitir que textos longos e genéricos dominem
        # uma regra cujo título corresponde diretamente à pergunta.
        score = score_text(query_tokens, claim.get("label", ""), metadata)
        score += reference_code_boost(question, searchable)
        if operator_answer:
            canonical_matches = sum(
                1 for token in query_tokens
                if contains_semantic_token(normalize(operator_answer), token)
            )
            score += min(18, canonical_matches * 3)
        if medical_enrollment_intent and "matricula" in medical_text:
            score += 20
        if medical_validity_intent or medical_operation_intent:
            if claim["id"] in GENERAL_CMA_RULE_IDS:
                score += 35
            elif "matricula" in medical_text:
                score -= 15
        if medical_validity_intent and any(
            term in normalize(claim.get("label", ""))
            for term in ("30 dias", "tolerancia", "nao prorroga")
        ):
            score += 10
        if daily_limit_intent and (
            "limite_diario_instrucao" in claim["id"] or "limite_instrucao_local" in claim["id"]
        ):
            score += 20
        if instructor_intent and claim.get("id") == INSTRUCTOR_ALLOCATION_RULE_ID:
            score += 60
        score += canonical_intent_boost(str(claim.get("id", "")), preferred_rule_ids)
        if score > 0:
            results.append({
                "id": claim["id"], "kind": "confirmed_claim", "label": claim["label"],
                "operator_answer": operator_answer,
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
        if banca_ppa_intent and "b-ops-065" in normalize(f"{node.get('label', '')} {metadata}"):
            score += 120
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
    # Regras confirmadas têm precedência sobre nós documentais brutos. O limite
    # anterior de quatro podia excluir exatamente a regra canônica procurada.
    kind_limits = {"confirmed_claim": limit, "graph_node": 4}
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


class GeminiTemporaryError(RuntimeError):
    """Falha transitória da API que pode ser repetida sem alterar a consulta."""


class GeminiModelQuotaUnavailableError(RuntimeError):
    """O modelo não possui cota disponível e deve ser substituído imediatamente."""


def semantic_claim_catalog() -> list[dict[str, Any]]:
    """Catálogo compacto e confirmado usado somente para seleção semântica de evidências."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in approved_dynamic_rules():
        entry_id = f"approved_rule_{rule['id']}"
        seen.add(entry_id)
        label = str(rule.get("approved_rule_text", ""))
        entries.append({
            "id": entry_id, "kind": "confirmed_claim", "label": label,
            "operator_answer": label, "code": rule.get("rule_code", ""),
            "source": rule.get("source_reference", ""),
            "location": rule.get("scope", "") or rule.get("source_reference", ""),
            "url": rule.get("source_url", ""), "excerpt": label,
            "scope": f"{rule.get('question', '')} {rule.get('proposed_answer', '')} {rule.get('scope', '')}",
        })
    if CLAIMS_PATH.is_file():
        public_answers = load_public_operator_answers(str(PUBLIC_KNOWLEDGE_INDEX_PATH))
        for claim in load_json(CLAIMS_PATH).get("claims", []):
            if claim.get("status") not in {"confirmed", "confirmed_temporary_override"}:
                continue
            entry_id = str(claim.get("id", ""))
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            entries.append({
                "id": entry_id, "kind": "confirmed_claim", "label": claim.get("label", ""),
                "operator_answer": claim.get("operator_answer", "") or public_answers.get(entry_id, ""),
                "code": claim.get("document_code", ""), "source": claim.get("source_path", ""),
                "location": claim.get("source_location", ""), "url": "", "excerpt": claim.get("label", ""),
                "scope": " ".join(claim.get("applies_to", [])),
            })
    else:
        for claim in load_public_knowledge_index(str(PUBLIC_KNOWLEDGE_INDEX_PATH)).get("claims", []):
            entry_id = str(claim.get("id", ""))
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            entries.append({
                "id": entry_id, "kind": "confirmed_claim", "label": claim.get("label", ""),
                "operator_answer": claim.get("operatorAnswer", ""), "code": claim.get("code", ""),
                "source": "Índice público de regras confirmadas", "location": claim.get("location", ""),
                "url": "", "excerpt": claim.get("label", ""), "scope": claim.get("appliesTo", ""),
            })
    return entries


def call_gemini_claim_selector(question: str, catalog: list[dict[str, Any]]) -> list[str]:
    """Seleciona semanticamente regras existentes; nunca cria nem redige uma regra."""
    key = gemini_key()
    if not key:
        return []
    compact_catalog = "\n".join(
        f"{item['id']} | {item.get('code', '')} | {item.get('label', '')} | "
        f"{item.get('scope', '')} | {str(item.get('operator_answer', ''))[:1200]}"
        for item in catalog
    )
    prompt = f"""Você seleciona evidências confirmadas da Escola SAFE.
Não responda à pergunta e não invente regras. Interprete primeiro a intenção real da pergunta, fazendo
equivalência semântica entre linguagem coloquial e os termos técnicos ou administrativos do catálogo;
não exija repetição das mesmas palavras. Escolha de 1 a 8 IDs que cubram essa intenção, incluindo
sequências, exceções, proibições e pré-requisitos. Se houver uma regra plausivelmente aplicável, inclua
a melhor. É obrigatório retornar ao menos um item. Se nenhuma regra cobrir o assunto ou a ação
perguntada, retorne exclusivamente o marcador NO_CONFIRMED_MATCH.
Priorize regras que contenham todos os códigos operacionais citados.

PERGUNTA: {question}

CATÁLOGO CONFIRMADO:
{compact_catalog}

CONFIRA NOVAMENTE A INTENÇÃO DA PERGUNTA: {question}
"""
    schema = {
        "type": "object",
        "properties": {
            "selected_ids": {
                "type": "array", "items": {"type": "string"},
                "minItems": 1, "maxItems": 8,
            },
        },
        "required": ["selected_ids"],
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            # O Gemini 3.6 Flash contabiliza tokens de raciocínio interno neste
            # limite. Valores baixos podem encerrar em MAX_TOKENS antes do JSON.
            "maxOutputTokens": 1600,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{LOCAL_MODEL}:generateContent",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        error_type = GeminiTemporaryError if error.code in {429, 500, 502, 503, 504} else RuntimeError
        raise error_type(f"Gemini respondeu HTTP {error.code}: {detail}") from error
    candidate = payload["candidates"][0]
    text = next(str(part["text"]).strip() for part in candidate["content"]["parts"] if part.get("text"))
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        selected = json.loads(text).get("selected_ids", [])
    except json.JSONDecodeError as error:
        raise RuntimeError("A Gemini devolveu uma seleção semântica inválida.") from error
    valid_ids = {item["id"] for item in catalog}
    return [str(item_id) for item_id in selected if str(item_id) in valid_ids][:8]


def call_gemini_query_expander(question: str) -> list[str]:
    """Traduz linguagem natural em termos de busca, sem responder nem criar regras."""
    key = gemini_key()
    if not key:
        return []
    prompt = f"""Converta a pergunta abaixo em 5 a 15 termos curtos para pesquisar um catálogo
operacional e administrativo de uma escola de aviação. Inclua sinônimos técnicos, administrativos e
coloquiais, substantivos da intenção e a ação solicitada. Preserve siglas e códigos. Não responda à
pergunta, não conclua uma regra e não acrescente fatos; retorne somente termos equivalentes.

PERGUNTA: {question}
"""
    schema = {
        "type": "object",
        "properties": {
            "search_terms": {
                "type": "array", "items": {"type": "string"},
                "minItems": 5, "maxItems": 15,
            },
        },
        "required": ["search_terms"],
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            # O Gemini 3.6 Flash usa parte do limite para raciocínio interno.
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{LOCAL_MODEL}:generateContent",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        error_type = GeminiTemporaryError if error.code in {429, 500, 502, 503, 504} else RuntimeError
        raise error_type(f"Gemini respondeu HTTP {error.code}: {detail}") from error
    text = next(
        str(part["text"]).strip()
        for part in payload["candidates"][0]["content"]["parts"]
        if part.get("text")
    )
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        raw_terms = json.loads(text).get("search_terms", [])
    except json.JSONDecodeError as error:
        raise RuntimeError("A Gemini devolveu uma expansão de consulta inválida.") from error
    terms, seen = [], set()
    for value in raw_terms:
        term = str(value).strip()[:100]
        normalized = normalize(term)
        if not term or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    return terms[:15]


def semantic_catalog_shortlist(
    question: str, expanded_terms: list[str], catalog: list[dict[str, Any]], limit: int = 48
) -> list[dict[str, Any]]:
    """Reduz o catálogo por termos equivalentes antes da decisão semântica final."""
    query_tokens = tokens(f"{question} {' '.join(expanded_terms)}")

    def rank(item: dict[str, Any]) -> tuple[int, int, str]:
        searchable = (
            f"{item.get('label', '')} {item.get('operator_answer', '')} "
            f"{item.get('scope', '')}"
        )
        score = score_text(query_tokens, searchable, f"{item.get('code', '')} {item.get('source', '')}")
        score += reference_code_boost(question, searchable)
        approved_priority = 1 if str(item.get("id", "")).startswith("approved_rule_") else 0
        return score, approved_priority, str(item.get("id", ""))

    return sorted(catalog, key=rank, reverse=True)[:limit]


def semantic_retrieve_with_retry(question: str, limit: int = 8) -> list[dict[str, Any]]:
    catalog = semantic_claim_catalog()
    for attempt in range(GEMINI_TRANSIENT_RETRIES + 1):
        try:
            expanded_terms = call_gemini_query_expander(question)
            shortlist = semantic_catalog_shortlist(question, expanded_terms, catalog)
            selected_ids = call_gemini_claim_selector(question, shortlist)
            by_id = {item["id"]: item for item in catalog}
            return [
                {**by_id[item_id], "score": 240 - index}
                for index, item_id in enumerate(selected_ids)
                if item_id in by_id
            ][:limit]
        except GeminiTemporaryError:
            if attempt >= GEMINI_TRANSIENT_RETRIES:
                raise
            delay = min(8.0, 2.0 ** attempt) + random.uniform(0.0, 0.5)
            time.sleep(delay)
    return []


def is_official_anac_source(url: str, title: str = "") -> bool:
    """Aceita apenas páginas da ANAC, inclusive links de redirecionamento do grounding."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold().rstrip("/")
    if host == "anac.gov.br" or host.endswith(".anac.gov.br"):
        return True
    if (host == "gov.br" or host.endswith(".gov.br")) and (
        path == "/anac" or path.startswith("/anac/")
    ):
        return True
    # Grounding costuma devolver um redirect do Google e o domínio original no título.
    if host.endswith(".google.com") or host.endswith(".googleusercontent.com"):
        title_norm = normalize(title)
        return (
            "anac.gov.br" in title_norm
            or title_norm == "anac"
            or "agencia nacional de aviacao civil" in title_norm
        )
    return False


def call_gemini(
    question: str,
    evidence: list[dict[str, Any]],
    grounded: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    key = gemini_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY não configurada no processo do backend.")
    evidence_text = "\n\n".join(
        f"EVIDÊNCIA {index}\nID: {item['id']}\nTIPO: {item['kind']}\nREGRA/TÍTULO: {item['label']}\n"
        f"CÓDIGO: {item['code']}\nLOCAL: {item['location']}\nTRECHO:\n{item['excerpt']}"
        for index, item in enumerate(evidence, 1)
    )
    if grounded:
        prompt = f"""Você é o assistente de pesquisa regulatória do CCO da Escola SAFE.
A base aprovada não foi suficiente para responder à pergunta abaixo.
Pesquise na web exclusivamente em páginas oficiais da Agência Nacional de Aviação Civil:
- https://www.gov.br/anac/
- https://www.anac.gov.br/
Inclua site:gov.br/anac ou site:anac.gov.br em todas as consultas de busca.
Não use blogs, fóruns, escolas, notícias, resumos de terceiros, outros órgãos ou resultados sem fonte oficial da ANAC.
Responda de forma direta em português do Brasil e deixe claro quando a fonte não resolver integralmente a dúvida.
Esta resposta é apenas uma proposta para revisão humana e não é uma regra aprovada da SAFE.
Uma fonte externa da ANAC nunca substitui uma regra interna SAFE mais restritiva.
Defina confidence como low quando houver conflito, dúvida de vigência ou ausência de fonte oficial conclusiva.
used_evidence deve ser uma lista vazia. candidate_relations pode registrar relações conceituais percebidas.

PERGUNTA: {question}
"""
    else:
        prompt = f"""Você é o assistente operacional do CCO da Escola SAFE.
Responda somente com base nas evidências fornecidas. Não invente regras, prazos ou permissões.
Responda diretamente o que foi perguntado. Você pode fazer inferência aritmética ou sequencial simples quando sustentada pelas evidências, deixando claro que se trata de uma conclusão lógica.
Se as evidências forem insuficientes ou conflitantes, diga isso claramente e defina confidence como low.
Prefira regras confirmadas e documentos vigentes. Seja direto e use português do Brasil.
Hierarquia operacional: o MGOP vigente é a fonte consolidada. Uma AVOP ativa pode complementar ou alterar temporariamente apenas o tema específico quando isso estiver explícito e enquanto ainda não tiver sido incorporada ao MGOP. Depois da incorporação, prevalece o MGOP atualizado. Em conflito não resolvido, não escolha automaticamente: informe a divergência e use confidence low.
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
        "generationConfig": {"maxOutputTokens": 4000, "responseMimeType": "application/json", "responseSchema": schema},
    }
    if grounded:
        body["tools"] = [{"google_search": {}}]
    selected_model = model or (EXTERNAL_MODEL if grounded else LOCAL_MODEL)
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        error.close()
        if error.code == 429 and "limit: 0" in detail.casefold():
            raise GeminiModelQuotaUnavailableError(
                f"O modelo {selected_model} não possui cota disponível para esta chave."
            ) from error
        error_type = GeminiTemporaryError if error.code in {429, 500, 502, 503, 504} else RuntimeError
        raise error_type(f"Gemini respondeu HTTP {error.code}: {detail}") from error
    except TimeoutError as error:
        raise RuntimeError("Gemini excedeu o tempo de resposta de 90 segundos.") from error
    candidate = payload["candidates"][0]
    text = next(
        str(part["text"]).strip()
        for part in candidate["content"]["parts"]
        if part.get("text")
    )
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "A Gemini devolveu uma resposta estruturada inválida; "
            "a consulta foi encaminhada ao modo de contingência."
        ) from error
    if grounded:
        metadata = candidate.get("groundingMetadata", {})
        web_sources = []
        seen_urls = set()
        for chunk in metadata.get("groundingChunks", []):
            web = chunk.get("web") or {}
            url = str(web.get("uri", "")).strip()
            title = str(web.get("title", "")).strip()
            if not url or url in seen_urls or not is_official_anac_source(url, title):
                continue
            seen_urls.add(url)
            web_sources.append({
                "id": f"web_{len(web_sources) + 1}",
                "kind": "external_source",
                "label": title or "ANAC — fonte oficial consultada",
                "code": "ANAC · fonte externa",
                "source": url,
                "location": url,
                "url": url,
                "excerpt": "",
            })
        result["_web_sources"] = web_sources
        result["_search_queries"] = metadata.get("webSearchQueries", [])
    result["_model"] = selected_model
    return result


def call_gemini_with_retry(
    question: str,
    evidence: list[dict[str, Any]],
    grounded: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    for attempt in range(GEMINI_TRANSIENT_RETRIES + 1):
        try:
            if model is None:
                return call_gemini(question, evidence, grounded=grounded)
            return call_gemini(question, evidence, grounded=grounded, model=model)
        except GeminiTemporaryError:
            if attempt >= GEMINI_TRANSIENT_RETRIES:
                raise
            delay = min(8.0, 2.0 ** attempt) + random.uniform(0.0, 0.5)
            time.sleep(delay)
    raise RuntimeError("Falha inesperada ao repetir a consulta Gemini.")


def call_grounded_gemini_with_fallback(
    question: str, evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pesquisa fontes oficiais usando o Pro e, se indisponível, modelos Flash compatíveis."""
    errors = []
    models = list(dict.fromkeys((EXTERNAL_MODEL, LOCAL_MODEL, FALLBACK_MODEL)))
    for selected_model in models:
        try:
            return call_gemini_with_retry(
                question, evidence, grounded=True, model=selected_model
            )
        except Exception as error:
            errors.append(f"{selected_model}: {type(error).__name__}")
    raise RuntimeError(
        "A pesquisa oficial externa está temporariamente indisponível nos modelos configurados "
        f"({', '.join(errors)})."
    )


def canonical_evidence_relevant(question: str, item: dict[str, Any]) -> bool:
    if not question:
        return True
    preferred_ids = canonical_intent_rule_ids(question)
    item_id = str(item.get("id", ""))
    if preferred_ids:
        return item_id in preferred_ids
    if int(item.get("score", 0) or 0) >= 200:
        return True
    normalized_question = normalize(question)
    query_stems = {
        light_portuguese_stem(token)
        for token in re.split(r"[^a-z0-9-]+", normalized_question)
        if len(token) > 1
        and token not in STOPWORDS
        and light_portuguese_stem(token) not in DYNAMIC_GENERIC_STEMS
    }
    evidence_text = normalize(" ".join(str(item.get(field, "")) for field in (
        "label", "code", "source", "location",
    )))
    if reference_codes(question) & reference_codes(evidence_text):
        return True
    if not query_stems:
        return False
    evidence_stems = {
        light_portuguese_stem(token)
        for token in re.split(r"[^a-z0-9-]+", evidence_text)
        if len(token) > 1
    }
    matches = query_stems & evidence_stems
    coverage = len(matches) / len(query_stems)
    return coverage >= 0.45 and (len(matches) >= 2 or len(query_stems) <= 2)


def deterministic_local_result(
    evidence: list[dict[str, Any]], question: str = ""
) -> dict[str, Any] | None:
    confirmed = [
        (index, item)
        for index, item in enumerate(evidence, 1)
        if item.get("kind") == "confirmed_claim"
    ]
    if not confirmed:
        return None
    preferred_ids = canonical_intent_rule_ids(question) if question else []
    if preferred_ids:
        confirmed.sort(key=lambda pair: (
            preferred_ids.index(str(pair[1].get("id", "")))
            if str(pair[1].get("id", "")) in preferred_ids
            else len(preferred_ids),
            pair[0],
        ))
    for index, item in confirmed:
        answer = str(item.get("operator_answer", "")).strip()
        if answer and canonical_evidence_relevant(question, item):
            return {
                "answer": answer,
                "confidence": "medium",
                "used_evidence": [index],
                "candidate_relations": [],
                "_model": "local-deterministic",
                "_contingency": True,
            }
    return None


def load_learning_graph() -> dict[str, Any]:
    if LEARNING_GRAPH_PATH.exists():
        return load_json(LEARNING_GRAPH_PATH)
    return {"schema_version": 1, "nodes": [], "edges": [], "candidate_relations": []}


@contextmanager
def learning_connection():
    connection = open_database(LEARNING_DB_PATH)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_legacy_learning_graph(connection: sqlite3.Connection) -> None:
    if not migration_enabled_for(LEARNING_DB_PATH) or not LEARNING_GRAPH_PATH.is_file():
        return
    initialize_migration_log(connection)
    source_name = f"json:{LEARNING_GRAPH_PATH.name}"
    item_name = "learning_graph"
    if connection.execute(
        "SELECT 1 FROM storage_migrations WHERE source=? AND item=?",
        (source_name, item_name),
    ).fetchone():
        return
    graph = load_learning_graph()
    nodes = [
        (
            str(node.get("id", "")),
            str(node.get("label", "")),
            str(node.get("created_at", "")) or now_iso(),
        )
        for node in graph.get("nodes", [])
        if node.get("type") == "operator_question" and node.get("id")
    ]
    if nodes:
        connection.executemany(
            """INSERT OR IGNORE INTO learning_queries(id, question, created_at)
               VALUES (?, ?, ?)""",
            nodes,
        )
    edges = [
        (
            str(edge.get("source", "")),
            str(edge.get("target", "")),
            str(edge.get("relation", "answered_using")),
            str(edge.get("status", "observed")),
            str(edge.get("created_at", "")) or now_iso(),
        )
        for edge in graph.get("edges", [])
        if edge.get("source") and edge.get("target")
    ]
    if edges:
        connection.executemany(
            """INSERT OR IGNORE INTO learning_query_evidence
               (query_id, evidence_id, relation, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            edges,
        )
    relations = [
        (
            str(relation.get("origin_query", "")),
            str(relation.get("source_concept", "")),
            str(relation.get("target_concept", "")),
            str(relation.get("relation", "")),
            str(relation.get("reason", "")),
            str(relation.get("status", "pending_review")),
            str(relation.get("created_at", "")) or now_iso(),
        )
        for relation in graph.get("candidate_relations", [])
        if relation.get("origin_query")
    ]
    if relations:
        connection.executemany(
            """INSERT INTO learning_candidate_relations
               (query_id, source_concept, target_concept, relation, reason, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            relations,
        )
    connection.execute(
        """INSERT INTO storage_migrations(source, item, migrated_rows, migrated_at)
           VALUES (?, ?, ?, ?)""",
        (source_name, item_name, len(nodes) + len(edges) + len(relations), now_iso()),
    )


def synchronize_legacy_learning_reviews(connection: sqlite3.Connection) -> int:
    """Replica no banco as revisões humanas registradas no grafo local."""
    if not LEARNING_GRAPH_PATH.is_file():
        return 0
    graph = load_learning_graph()
    reviewed = [
        relation for relation in graph.get("candidate_relations", [])
        if relation.get("origin_query") and relation.get("status") != "pending_review"
    ]
    updated = 0
    for item in reviewed:
        cursor = connection.execute(
            """UPDATE learning_candidate_relations SET status=?
               WHERE query_id=? AND source_concept=? AND target_concept=? AND relation=?
                 AND status<>?""",
            (
                str(item.get("status", "rejected_superseded")),
                str(item.get("origin_query", "")),
                str(item.get("source_concept", "")),
                str(item.get("target_concept", "")),
                str(item.get("relation", "")),
                str(item.get("status", "rejected_superseded")),
            ),
        )
        updated += cursor.rowcount
    return updated


def initialize_learning_db() -> None:
    with WRITE_LOCK, learning_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS learning_queries (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS learning_query_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(query_id, evidence_id, relation),
            FOREIGN KEY(query_id) REFERENCES learning_queries(id) ON DELETE CASCADE
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS learning_candidate_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id TEXT NOT NULL,
            source_concept TEXT NOT NULL,
            target_concept TEXT NOT NULL,
            relation TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(query_id) REFERENCES learning_queries(id) ON DELETE CASCADE
        )""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_evidence_query ON learning_query_evidence(query_id)"
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_learning_relations_status
               ON learning_candidate_relations(status, created_at)"""
        )
        migrate_legacy_learning_graph(connection)
        synchronize_legacy_learning_reviews(connection)


def record_learning(question: str, evidence: list[dict[str, Any]], result: dict[str, Any]) -> str:
    initialize_learning_db()
    timestamp = now_iso()
    query_id = "query_" + hashlib.sha256(f"{timestamp}:{question}".encode("utf-8")).hexdigest()[:16]
    with WRITE_LOCK, learning_connection() as connection:
        connection.execute(
            "INSERT INTO learning_queries(id, question, created_at) VALUES (?, ?, ?)",
            (query_id, question, timestamp),
        )
        used = {int(value) for value in result.get("used_evidence", []) if str(value).isdigit()}
        for index, item in enumerate(evidence, 1):
            if index in used:
                connection.execute(
                    """INSERT OR IGNORE INTO learning_query_evidence
                       (query_id, evidence_id, relation, status, created_at)
                       VALUES (?, ?, 'answered_using', 'observed', ?)""",
                    (query_id, str(item["id"]), timestamp),
                )
        for relation in result.get("candidate_relations", []):
            connection.execute(
                """INSERT INTO learning_candidate_relations
                   (query_id, source_concept, target_concept, relation, reason, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending_review', ?)""",
                (
                    query_id,
                    str(relation.get("source_concept", "")),
                    str(relation.get("target_concept", "")),
                    str(relation.get("relation", "")),
                    str(relation.get("reason", "")),
                    timestamp,
                ),
            )
    return query_id


def answer_question(
    question: str,
    actor: dict[str, Any] | None = None,
    *,
    capture_candidate: bool = True,
    save_history: bool = True,
) -> dict[str, Any]:
    local_errors = []
    evidence = retrieve(question)
    canonical_result = deterministic_local_result(evidence, question)
    if not canonical_result and gemini_key():
        try:
            semantic_evidence = semantic_retrieve_with_retry(question)
            if semantic_evidence:
                semantic_ids = {item["id"] for item in semantic_evidence}
                evidence = (semantic_evidence + [
                    item for item in evidence if item["id"] not in semantic_ids
                ])[:8]
                canonical_result = deterministic_local_result(evidence, question)
        except Exception as error:
            local_errors.append(f"Seleção semântica: {error}")
    if canonical_result and any(item.get("operator_answer") for item in evidence):
        local_result = canonical_result
    else:
        try:
            local_result = call_gemini_with_retry(question, evidence)
        except Exception as error:
            local_errors.append(str(error))
            try:
                local_result = call_gemini_with_retry(question, evidence, model=FALLBACK_MODEL)
            except Exception as fallback_error:
                local_errors.append(str(fallback_error))
                local_result = canonical_result or {
                    "answer": "",
                    "confidence": "low",
                    "used_evidence": [],
                    "candidate_relations": [],
                }
    used_indices = [int(value) for value in local_result.get("used_evidence", []) if str(value).isdigit()]
    local_sources = [evidence[index - 1] for index in used_indices if 1 <= index <= len(evidence)]
    local_answer_norm = normalize(str(local_result.get("answer", "")))
    local_sufficient = (
        local_result.get("confidence") in {"high", "medium"}
        and any(item.get("kind") == "confirmed_claim" for item in local_sources)
        and not any(term in local_answer_norm for term in ("conflit", "diverg"))
    )
    if not local_sufficient:
        if canonical_result and any(item.get("operator_answer") for item in evidence):
            local_result = canonical_result
            used_indices = canonical_result["used_evidence"]
            local_sources = [evidence[index - 1] for index in used_indices]
            local_answer_norm = normalize(str(local_result["answer"]))
            local_sufficient = True
    result = local_result
    sources = local_sources
    response_mode = "local_contingency" if local_result.get("_contingency") else "local_approved"
    knowledge_status = "approved"
    model_used = str(local_result.get("_model", LOCAL_MODEL))
    candidate = None
    external_error = ""

    if not local_sufficient:
        response_mode = "unanswered"
        knowledge_status = "unreviewed"
        if WEB_GROUNDING_ENABLED:
            try:
                external_result = call_grounded_gemini_with_fallback(question, evidence)
                external_sources = external_result.get("_web_sources", [])
                if external_result.get("answer") and external_sources:
                    result = external_result
                    sources = external_sources
                    response_mode = "external_grounded"
                    model_used = str(external_result.get("_model", EXTERNAL_MODEL))
            except Exception as error:
                external_error = str(error)
        if response_mode == "unanswered":
            result = local_result
            sources = local_sources
            if not result.get("answer"):
                result["answer"] = (
                    "Não encontrei uma resposta sustentada pela base aprovada nem uma fonte oficial "
                    "externa conclusiva. A pergunta foi registrada para análise em Regras em aprovação."
                )
            result["confidence"] = "low"
        answer_norm = normalize(str(result.get("answer", "")))
        source_kind = (
            "conflict" if any(term in answer_norm for term in ("conflit", "diverg"))
            else "external_grounded" if response_mode == "external_grounded"
            else "unanswered"
        )
        if capture_candidate:
            candidate = upsert_rule_candidate(
                question=question,
                proposed_answer=str(result.get("answer", "")),
                confidence=str(result.get("confidence", "low")),
                source_kind=source_kind,
                sources=sources,
                local_evidence=evidence,
                actor=actor,
            )

    try:
        query_id = record_learning(question, evidence, result)
    except Exception:
        timestamp = now_iso()
        query_id = "query_" + hashlib.sha256(f"{timestamp}:{question}".encode("utf-8")).hexdigest()[:16]
    payload = {
        "query_id": query_id, "answer": result.get("answer", ""),
        "confidence": result.get("confidence", "low"), "sources": sources,
        "candidate_relations_count": len(result.get("candidate_relations", [])),
        "knowledge_status": knowledge_status,
        "response_mode": response_mode,
        "model_used": model_used,
        "provisional": knowledge_status != "approved",
        "candidate_id": candidate["id"] if candidate else None,
        "local_error": (
            " | ".join(local_errors)
            if actor and actor.get("role") in {"admin", "supervisor"}
            else ""
        ),
        "external_error": (
            external_error
            if actor and actor.get("role") in {"admin", "supervisor"} and WEB_GROUNDING_ENABLED
            else ""
        ),
    }
    if save_history:
        save_search_history(question, "ai", payload["confidence"], result=payload, record_id=query_id)
    return payload


def reprocess_rule_candidate(candidate_id: int, actor: dict[str, Any]) -> dict[str, Any]:
    initialize_rules_db()
    with rules_connection() as connection:
        current = connection.execute(
            "SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
    if not current:
        raise LookupError("Regra em aprovação não encontrada.")
    if current["status"] not in {"unreviewed", "pending_approval"}:
        raise ValueError("Somente lacunas abertas podem ser reprocessadas.")

    result = answer_question(
        str(current["question"]), actor, capture_candidate=False, save_history=False
    )
    source_kind = {
        "external_grounded": "external_grounded",
        "local_approved": "local_document",
        "local_contingency": "local_document",
    }.get(str(result.get("response_mode", "")), "unanswered")
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    evidence = retrieve(str(current["question"]))
    timestamp = now_iso()
    with RULES_LOCK, rules_connection() as connection:
        connection.execute(
            """UPDATE rule_candidates SET proposed_answer=?, confidence=?, source_kind=?,
               sources_json=?, local_evidence_json=?, updated_at=? WHERE id=?""",
            (
                str(result.get("answer", ""))[:8000], str(result.get("confidence", "low")),
                source_kind, json.dumps(compact_rule_evidence(sources), ensure_ascii=False),
                json.dumps(compact_rule_evidence(evidence), ensure_ascii=False), timestamp,
                candidate_id,
            ),
        )
        connection.execute(
            """INSERT INTO rule_events(candidate_id, action, actor_username, actor_name, details, created_at)
               VALUES (?, 'Reprocessada', ?, ?, ?, ?)""",
            (
                candidate_id, actor["username"], actor["display_name"],
                json.dumps({
                    "response_mode": result.get("response_mode"),
                    "confidence": result.get("confidence"),
                    "knowledge_status": result.get("knowledge_status"),
                }, ensure_ascii=False),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM rule_candidates WHERE id=?", (candidate_id,)).fetchone()
    return {"item": rule_candidate_dict(row), "result": result}


def initialize_portal_storage() -> None:
    configure_database(PORTAL_DB_PATH)
    initialize_auth_db()
    initialize_bases_db()
    initialize_instructors_db()
    initialize_aircraft_db()
    initialize_handovers_db()
    initialize_reports_db()
    initialize_search_history_db()
    initialize_rules_db()
    with RULES_LOCK, rules_connection() as connection:
        synchronize_rules_catalog(connection)
        write_approved_rules_export(connection)
    initialize_learning_db()


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

    def send_bytes(
        self, status: int, body: bytes, content_type: str, filename: str | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def auth_context(self) -> tuple[dict[str, Any] | None, str | None, str | None]:
        return session_user(self.headers.get("Cookie", ""))

    def require_auth(self, roles: set[str] | None = None, require_csrf: bool = False) -> tuple[dict[str, Any], str] | None:
        user, csrf, token_hash = self.auth_context()
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
        if token_hash:
            record_portal_activity(user["id"], token_hash)
        return user, csrf or ""

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(200, {
                "ok": True,
                "release": RELEASE_ID,
                "updated_at": PORTAL_UPDATED_AT,
                "knowledge": "private_bundle" if BUNDLED_KNOWLEDGE_ACTIVE else (
                    "configured_root" if CONFIGURED_KNOWLEDGE_ROOT else "public_index"
                ),
                "gemini": "configured" if gemini_key() else "missing",
                "gemini_model": LOCAL_MODEL,
                "gemini_fallback_model": FALLBACK_MODEL,
            })
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
            if urllib.parse.urlparse(self.path).path == "/api/activity":
                self.send_json(200, list_portal_activity()); return
        if urllib.parse.urlparse(self.path).path == "/api/approved-rules":
            self.send_json(200, {"items": list_approved_rules()})
            return
        if urllib.parse.urlparse(self.path).path == "/api/rule-candidates":
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode revisar regras."}); return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            status = query.get("status", ["unreviewed"])[0]
            self.send_json(200, {"items": list_rule_candidates(status)})
            return
        if urllib.parse.urlparse(self.path).path in {
            "/api/knowledge-gaps", "/api/knowledge-gaps/export.csv"
        }:
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode consultar lacunas."}); return
            try:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                report = knowledge_gap_report(query)
                if urllib.parse.urlparse(self.path).path.endswith("export.csv"):
                    self.send_bytes(
                        200, knowledge_gap_csv(report), "text/csv; charset=utf-8",
                        f"lacunas-conhecimento-{datetime.now().date().isoformat()}.csv",
                    )
                else:
                    self.send_json(200, report)
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            return
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
            self.send_json(200, list_handover_cycles())
            return
        if urllib.parse.urlparse(self.path).path == "/api/reports":
            if user["role"] == "viewer":
                self.send_json(403, {"error": "O perfil de consulta não possui acesso aos reports."}); return
            self.send_json(200, {
                "items": list_reports(),
                "types": REPORT_TYPES,
                "priorities": sorted(REPORT_PRIORITIES),
                "statuses": ["Aberto", "Em análise", "Resolvido", "Descartado"],
                "rule_actions": REPORT_RULE_ACTIONS,
                "assignees": list_report_assignees(),
            })
            return
        attachment_match = re.fullmatch(
            r"/api/report-attachments/(\d+)", urllib.parse.urlparse(self.path).path
        )
        if attachment_match:
            if user["role"] == "viewer":
                self.send_json(403, {"error": "O perfil de consulta não possui acesso aos reports."}); return
            try:
                content, content_type, filename = get_report_attachment(int(attachment_match.group(1)))
                self.send_bytes(200, content, content_type, filename)
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
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
            is_report_attachment = bool(re.fullmatch(
                r"/api/reports/\d+/attachments", urllib.parse.urlparse(self.path).path
            ))
            max_body = 3_000_000 if is_report_attachment else 16_384
            if length > max_body:
                raise ValueError("A requisição excede o tamanho permitido.")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
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
            if self.path == "/api/activity/ping":
                _, _, token_hash = self.auth_context()
                if token_hash:
                    record_portal_activity(user["id"], token_hash, str(data.get("area", "")))
                self.send_json(200, {"ok": True}); return
            if self.path == "/api/auth/logout":
                _, _, token_hash = self.auth_context()
                if token_hash:
                    record_portal_activity(user["id"], token_hash, "Saiu do portal")
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
                self.send_json(201, save_handover(data, actor=user))
                return
            handover_cycle_action = re.fullmatch(r"/api/handovers/cycles/(\d+)/(publish|receive)", self.path)
            if handover_cycle_action:
                if user["role"] not in {"admin", "supervisor", "operator"}:
                    self.send_json(403, {"error": "Perfil de consulta não pode operar passagens."}); return
                cycle_id = int(handover_cycle_action.group(1))
                saved = (
                    publish_handover_cycle(cycle_id, user)
                    if handover_cycle_action.group(2) == "publish"
                    else receive_handover_cycle(cycle_id, user)
                )
                self.send_json(200, saved)
                return
            handover_item_action = re.fullmatch(r"/api/handovers/(\d+)/actions", self.path)
            if handover_item_action:
                if user["role"] not in {"admin", "supervisor", "operator"}:
                    self.send_json(403, {"error": "Perfil de consulta não pode operar passagens."}); return
                self.send_json(200, transition_handover_item(int(handover_item_action.group(1)), data, user))
                return
            if self.path == "/api/reports":
                if user["role"] not in {"admin", "supervisor", "operator"}:
                    self.send_json(403, {"error": "Perfil de consulta não pode registrar reports."}); return
                self.send_json(201, create_report(data, user))
                return
            report_comment_match = re.fullmatch(r"/api/reports/(\d+)/comments", self.path)
            if report_comment_match:
                if user["role"] == "viewer":
                    self.send_json(403, {"error": "O perfil de consulta não pode comentar reports."}); return
                self.send_json(201, add_report_comment(
                    int(report_comment_match.group(1)), str(data.get("body", "")), user
                ))
                return
            report_attachment_match = re.fullmatch(r"/api/reports/(\d+)/attachments", self.path)
            if report_attachment_match:
                if user["role"] == "viewer":
                    self.send_json(403, {"error": "O perfil de consulta não pode anexar arquivos."}); return
                self.send_json(201, add_report_attachment(
                    int(report_attachment_match.group(1)), data, user
                ))
                return
            if self.path == "/api/searches":
                record_id = save_search_history(
                    str(data.get("question", "")), "local", str(data.get("confidence", "low")),
                    presentation=data.get("presentation") if isinstance(data.get("presentation"), dict) else None,
                )
                self.send_json(201, {"id": record_id})
                return
            reprocess_match = re.fullmatch(r"/api/rule-candidates/(\d+)/reprocess", self.path)
            if reprocess_match:
                if user["role"] not in {"admin", "supervisor"}:
                    self.send_json(403, {"error": "Somente Supervisor ou Administrador pode reprocessar lacunas."}); return
                self.send_json(200, reprocess_rule_candidate(int(reprocess_match.group(1)), user))
                return
            if self.path != "/api/ask":
                self.send_json(404, {"error": "Rota não encontrada."}); return
            question = str(data.get("question", "")).strip()
            if not question or len(question) > MAX_QUESTION_LENGTH:
                self.send_json(400, {"error": "Pergunta vazia ou muito longa."}); return
            self.send_json(200, answer_question(question, user))
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
        rule_match = re.fullmatch(r"/api/rule-candidates/(\d+)", urllib.parse.urlparse(self.path).path)
        if rule_match:
            if user["role"] not in {"admin", "supervisor"}:
                self.send_json(403, {"error": "Somente Supervisor ou Administrador pode revisar regras."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                self.send_json(200, review_rule_candidate(int(rule_match.group(1)), data, user))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": str(error)})
            return
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
            if user["role"] == "viewer":
                self.send_json(403, {"error": "O perfil de consulta não pode alterar reports."}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(length, 16_384)).decode("utf-8"))
                saved = (
                    update_report(int(report_match.group(1)), data, user)
                    if user["role"] in {"admin", "supervisor"}
                    else update_own_report(int(report_match.group(1)), data, user)
                )
                self.send_json(200, saved)
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
                self.send_json(200, save_handover(data, int(handover_match.group(1)), actor=user))
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
        attachment_match = re.fullmatch(
            r"/api/report-attachments/(\d+)", urllib.parse.urlparse(self.path).path
        )
        if attachment_match:
            if user["role"] == "viewer":
                self.send_json(403, {"error": "O perfil de consulta não pode excluir anexos."}); return
            try:
                delete_report_attachment(int(attachment_match.group(1)), user)
                self.send_json(200, {"ok": True})
            except PermissionError as error:
                self.send_json(403, {"error": str(error)})
            except LookupError as error:
                self.send_json(404, {"error": str(error)})
            return
        handover_match = re.fullmatch(r"/api/handovers/(\d+)", urllib.parse.urlparse(self.path).path)
        if handover_match:
            if user["role"] not in {"admin", "supervisor", "operator"}:
                self.send_json(403, {"error": "Perfil de consulta não pode excluir passagens."}); return
            try:
                delete_handover(int(handover_match.group(1)), actor=user)
                self.send_json(200, {"ok": True})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
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
    initialize_portal_storage()
    print(
        f"SAFE CCO API em http://{HOST}:{PORT} | modelo local={LOCAL_MODEL} "
        f"| contingência={FALLBACK_MODEL} | modelo ANAC={EXTERNAL_MODEL} "
        f"| conhecimento={KNOWLEDGE_ROOT}"
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
