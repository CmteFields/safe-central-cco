"""Adaptador WSGI para executar o Portal CCO em hospedagens como PythonAnywhere."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Callable, Iterable
from urllib.parse import quote

from backend import server

server.initialize_portal_storage()


class _ResponseBuffer(BytesIO):
    """Mantém a resposta disponível após o fechamento feito pelo handler HTTP."""

    def close(self) -> None:
        self.flush()


class _RequestSocket:
    """Socket mínimo esperado por ``BaseHTTPRequestHandler``."""

    def __init__(self, request: bytes) -> None:
        self.request = BytesIO(request)
        self.response = _ResponseBuffer()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> BytesIO:
        if "r" in mode:
            return self.request
        return self.response

    def sendall(self, data: bytes) -> None:
        self.response.write(data)

    def close(self) -> None:
        return


def _request_target(environ: dict[str, Any]) -> str:
    path = quote(
        str(environ.get("PATH_INFO") or "/"),
        safe="/%:@!$&'()*+,;=-._~",
        encoding="utf-8",
        errors="strict",
    )
    query = str(environ.get("QUERY_STRING") or "")
    return f"{path}?{query}" if query else path


def _request_headers(environ: dict[str, Any]) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            name = key[5:].replace("_", "-").title()
            headers.append((name, str(value)))
    for environ_name, header_name in (
        ("CONTENT_TYPE", "Content-Type"),
        ("CONTENT_LENGTH", "Content-Length"),
    ):
        value = environ.get(environ_name)
        if value not in (None, ""):
            headers.append((header_name, str(value)))
    if not any(name.lower() == "host" for name, _ in headers):
        host = str(environ.get("SERVER_NAME") or "localhost")
        port = str(environ.get("SERVER_PORT") or "")
        headers.append(("Host", f"{host}:{port}" if port else host))
    return headers


def _request_body(environ: dict[str, Any]) -> bytes:
    try:
        length = max(0, int(environ.get("CONTENT_LENGTH") or "0"))
    except (TypeError, ValueError):
        length = 0
    stream = environ.get("wsgi.input")
    if not stream or not length:
        return b""
    return stream.read(length)


def _raw_request(environ: dict[str, Any]) -> bytes:
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    target = _request_target(environ)
    request_line = f"{method} {target} HTTP/1.1\r\n".encode("ascii")
    headers = b"".join(
        f"{name}: {value}\r\n".encode("latin-1")
        for name, value in _request_headers(environ)
    )
    return request_line + headers + b"\r\n" + _request_body(environ)


def _parse_response(raw_response: bytes) -> tuple[str, list[tuple[str, str]], bytes]:
    header_block, separator, body = raw_response.partition(b"\r\n\r\n")
    if not separator:
        raise RuntimeError("O backend não produziu uma resposta HTTP válida.")
    lines = header_block.decode("latin-1").split("\r\n")
    status_parts = lines[0].split(" ", 2)
    if len(status_parts) < 2:
        raise RuntimeError("O backend não informou o status HTTP.")
    status = f"{status_parts[1]} {status_parts[2] if len(status_parts) > 2 else ''}".rstrip()
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if separator:
            headers.append((name.strip(), value.lstrip()))
    return status, headers, body


def application(
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], Any],
) -> Iterable[bytes]:
    """Entrada WSGI usada pelo PythonAnywhere."""

    request_socket = _RequestSocket(_raw_request(environ))
    client_address = (
        str(environ.get("REMOTE_ADDR") or "127.0.0.1"),
        int(environ.get("REMOTE_PORT") or 0),
    )
    server.Handler(request_socket, client_address, None)
    status, headers, body = _parse_response(request_socket.response.getvalue())
    start_response(status, headers)
    return [body]
