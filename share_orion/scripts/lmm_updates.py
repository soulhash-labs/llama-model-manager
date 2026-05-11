#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Self-contained import: support direct loading from CLI snippets and tests.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_SCRIPT_DIR))

from lmm_storage import _FileLockedJsonStore  # noqa: E402


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    release_notes_preview: str
    checked_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "release_url": self.release_url,
            "release_notes_preview": self.release_notes_preview,
            "checked_at": self.checked_at,
        }


class UpdateStateStore(_FileLockedJsonStore):
    """Persist last known update check results for both components."""

    def read_state(self) -> dict[str, object]:
        return self._read_state(
            {
                "schema_version": 1,
                "updated_at": "",
                "lmm": {},
                "llamacpp": {},
            }
        )

    def _normalize_result(self, raw: object) -> dict[str, object]:
        if not isinstance(raw, dict):
            return {}
        return {
            "current_version": str(raw.get("current_version", "")),
            "latest_version": str(raw.get("latest_version", "")),
            "update_available": bool(raw.get("update_available", False)),
            "release_url": str(raw.get("release_url", "")),
            "release_notes_preview": str(raw.get("release_notes_preview", "")),
            "checked_at": str(raw.get("checked_at", "")),
        }

    def update_result(self, component: str, result: UpdateCheckResult) -> None:
        with self._lock():
            payload = self.read_state()
            payload.setdefault("schema_version", 1)
            payload["updated_at"] = _utc_timestamp()
            payload[component] = result.to_dict()
            self._write_state(payload)

    def result_for(self, component: str) -> dict[str, object]:
        state = self.read_state()
        return self._normalize_result(state.get(component))


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _to_tuple(value: str) -> tuple[int, ...]:
    text = value.strip().lower().lstrip("v")
    if not text:
        return (0,)
    parts = []
    for piece in text.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            return (0,)
    return tuple(parts)


def _normalize_preview(value: str, *, limit: int = 320) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return ""
    return f"{text[: limit - 1]}…"


class UpdateChecker:
    def __init__(
        self,
        *,
        current_lmm_version: str,
        lmm_repo: str,
        llamacpp_repo: str,
        timeout: int,
        state_file: Path,
    ) -> None:
        self.current_lmm_version = str(current_lmm_version).strip() or "v0.0.0"
        self.lmm_repo = str(lmm_repo or "").strip() or "soulhash-labs/llama-model-manager"
        self.llamacpp_repo = str(llamacpp_repo or "").strip() or "ggml-org/llama.cpp"
        self.timeout = max(1, int(timeout))
        self.state_store = UpdateStateStore(state_file)

    def _fetch_latest_release(self, owner: str, repo: str) -> dict[str, object] | None:
        if not owner or not repo:
            return None
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "lmm-update-checker",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _is_newer(self, current: str, latest: str) -> bool:
        current_tuple = _to_tuple(current)
        latest_tuple = _to_tuple(latest)
        if latest_tuple == (0,) or current_tuple == latest_tuple:
            return False
        return latest_tuple > current_tuple

    def _cached_result(self, component: str) -> UpdateCheckResult:
        cached = self.state_store.result_for(component)
        return UpdateCheckResult(
            current_version=str(cached.get("current_version", "") or ""),
            latest_version=cached.get("latest_version", "") or "",
            update_available=bool(cached.get("update_available", False)),
            release_url=str(cached.get("release_url", "") or ""),
            release_notes_preview=str(cached.get("release_notes_preview", "") or ""),
            checked_at=str(cached.get("checked_at", "") or _utc_timestamp()),
        )

    def _check_repo(self, component: str, repo_full_name: str, current_version: str) -> UpdateCheckResult:
        cached = self._cached_result(component)
        current_version = str(current_version or cached.current_version)
        cached_update_available = (
            self._is_newer(current_version, cached.latest_version) if cached.latest_version else cached.update_available
        )

        owner, _, repo = repo_full_name.partition("/")
        if not owner or not repo:
            return UpdateCheckResult(
                current_version=current_version,
                latest_version=cached.latest_version,
                update_available=False,
                release_url=cached.release_url,
                release_notes_preview=cached.release_notes_preview,
                checked_at=cached.checked_at,
            )

        data = self._fetch_latest_release(owner, repo)
        if data is None:
            return UpdateCheckResult(
                current_version=current_version,
                latest_version=cached.latest_version,
                update_available=bool(cached_update_available),
                release_url=cached.release_url,
                release_notes_preview=cached.release_notes_preview,
                checked_at=cached.checked_at,
            )

        latest_version = str(data.get("tag_name", "")).strip()
        preview = str(data.get("body", "") or "")
        release_url = str(data.get("html_url", "")).strip()
        if not latest_version:
            return UpdateCheckResult(
                current_version=current_version,
                latest_version=cached.latest_version,
                update_available=bool(cached_update_available),
                release_url=cached.release_url,
                release_notes_preview=cached.release_notes_preview,
                checked_at=cached.checked_at,
            )

        result = UpdateCheckResult(
            current_version=current_version,
            latest_version=latest_version,
            update_available=self._is_newer(current_version, latest_version),
            release_url=release_url,
            release_notes_preview=_normalize_preview(preview),
            checked_at=_utc_timestamp(),
        )
        self.state_store.update_result(component, result)
        return result

    def check_lmm_update(self) -> UpdateCheckResult:
        return self._check_repo("lmm", self.lmm_repo, self.current_lmm_version)

    def check_llamacpp_update(self, current_version: str = "") -> UpdateCheckResult:
        current = str(current_version).strip() or os.environ.get("LLAMA_CPP_REF", "unknown")
        return self._check_repo("llamacpp", self.llamacpp_repo, current)
