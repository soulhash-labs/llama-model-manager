from __future__ import annotations

import json
import math
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from lmm_errors import InvalidRequestError


def json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    raw = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: BaseHTTPRequestHandler, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    length_text = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_text)
    except ValueError as exc:
        raise InvalidRequestError("invalid Content-Length") from exc
    if length < 0 or length > max_bytes:
        raise InvalidRequestError("request body too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError as exc:
        raise InvalidRequestError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise InvalidRequestError("request JSON must be an object")
    return payload


def request_int(payload: dict[str, Any], key: str, default: int, *, minimum: int = 1) -> int:
    raw = payload.get(key, default)
    if isinstance(raw, bool):
        raise InvalidRequestError(f"{key} must be an integer")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    else:
        raise InvalidRequestError(f"{key} must be an integer")
    if value < minimum:
        raise InvalidRequestError(f"{key} must be at least {minimum}")
    return value


def request_float(payload: dict[str, Any], key: str, default: float) -> float:
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{key} must be a number") from exc
    if not math.isfinite(value):
        raise InvalidRequestError(f"{key} must be finite")
    return value


def http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 5,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return int(exc.code), parsed if isinstance(parsed, dict) else {"error": raw}
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc
