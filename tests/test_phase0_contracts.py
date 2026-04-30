#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock
from urllib import error

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "web" / "app.py"
SPEC = importlib.util.spec_from_file_location("llama_model_manager_web_app", APP_PATH)
assert SPEC and SPEC.loader
WEB_APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEB_APP)

GATEWAY_PATH = ROOT_DIR / "scripts" / "glyphos_openai_gateway.py"
CONTEXT_BRIDGE_PATH = ROOT_DIR / "scripts" / "context_mcp_bridge.py"
LMM_CONFIG_PATH = ROOT_DIR / "scripts" / "lmm_config.py"
LMM_ERRORS_PATH = ROOT_DIR / "scripts" / "lmm_errors.py"
LMM_STORAGE_PATH = ROOT_DIR / "scripts" / "lmm_storage.py"
LMM_TYPES_PATH = ROOT_DIR / "scripts" / "lmm_types.py"
LMM_HEALTH_PATH = ROOT_DIR / "scripts" / "lmm_health.py"
LMM_PROVIDERS_PATH = ROOT_DIR / "scripts" / "lmm_providers.py"


class Phase0ContractTests(unittest.TestCase):
    def load_gateway_module(self) -> object:
        gateway_spec = importlib.util.spec_from_file_location("llama_model_manager_gateway", GATEWAY_PATH)
        assert gateway_spec and gateway_spec.loader
        gateway = importlib.util.module_from_spec(gateway_spec)
        original_path = list(sys.path)
        try:
            gateway_spec.loader.exec_module(gateway)
        finally:
            sys.path[:] = original_path
        return gateway

    def load_script_module(self, module_name: str, path: Path) -> object:
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        original_path = list(sys.path)
        original_module = sys.modules.get(module_name)
        try:
            sys.path.insert(0, str(ROOT_DIR / "scripts"))
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            sys.path[:] = original_path
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module
        return module

    def load_context_bridge_module(self) -> object:
        bridge_spec = importlib.util.spec_from_file_location("llama_model_manager_context_bridge", CONTEXT_BRIDGE_PATH)
        assert bridge_spec and bridge_spec.loader
        bridge = importlib.util.module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge)
        return bridge

    def load_providers_module(self) -> object:
        return self.load_script_module("llama_model_manager_providers", LMM_PROVIDERS_PATH)

    def test_lmm_config_validates_gateway_environment(self) -> None:
        config_module = self.load_script_module("llama_model_manager_config", LMM_CONFIG_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "gateway-state.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LLAMA_MODEL_GATEWAY_HOST": "127.0.0.9",
                    "LLAMA_MODEL_GATEWAY_PORT": "4510",
                    "LLAMA_MODEL_BACKEND_BASE_URL": "http://127.0.0.1:8089/v1",
                    "LMM_GATEWAY_STATE_FILE": str(state_file),
                    "LMM_GATEWAY_SSE_HEARTBEAT_SECONDS": "2.5",
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                    "LMM_CONTEXT_MCP_TIMEOUT_MS": "2500",
                },
                clear=False,
            ):
                config = config_module.load_lmm_config_from_env()

        self.assertEqual(config.gateway.host, "127.0.0.9")
        self.assertEqual(config.gateway.port, 4510)
        self.assertEqual(config.gateway.backend_base_url, "http://127.0.0.1:8089/v1")
        self.assertEqual(config.gateway.state_file, state_file)
        self.assertEqual(config.gateway.sse_heartbeat_seconds, 2.5)
        self.assertTrue(config.context.enabled)
        self.assertEqual(config.context.timeout_ms, 2500)

    def test_lmm_config_rejects_invalid_gateway_values(self) -> None:
        config_module = self.load_script_module("llama_model_manager_config_invalid", LMM_CONFIG_PATH)
        with mock.patch.dict(
            os.environ,
            {
                "LLAMA_MODEL_GATEWAY_PORT": "70000",
                "LLAMA_MODEL_BACKEND_BASE_URL": "not-a-url",
            },
            clear=False,
        ):
            with self.assertRaises(Exception) as raised:
                config_module.load_lmm_config_from_env()
        self.assertIn("configuration", raised.exception.__class__.__name__.lower())

    def test_lmm_error_payloads_are_machine_readable(self) -> None:
        errors_module = self.load_script_module("llama_model_manager_errors", LMM_ERRORS_PATH)
        exc = errors_module.ProviderTimeoutError("llama.cpp", 1800)
        payload = exc.to_dict()
        self.assertEqual(payload["type"], "provider_timeout_error")
        self.assertEqual(payload["details"]["provider"], "llama.cpp")
        self.assertEqual(payload["details"]["timeout_seconds"], 1800)

    def test_json_gateway_storage_adapter_caps_recent_requests_and_counts(self) -> None:
        storage_module = self.load_script_module("llama_model_manager_storage", LMM_STORAGE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "gateway-state.json"
            store = storage_module.JsonGatewayTelemetryStore(path, recent_limit=2)
            store.append_event(
                {"mode": "routed-basic", "route_target": "llamacpp", "context_status": "empty", "success": True, "n": 1}
            )
            store.append_event(
                {
                    "mode": "routed-full",
                    "route_target": "llamacpp",
                    "context_status": "retrieved",
                    "success": True,
                    "n": 2,
                }
            )
            state = store.append_event(
                {
                    "mode": "routed-basic",
                    "route_target": "fallback",
                    "context_status": "timeout",
                    "success": False,
                    "n": 3,
                }
            )

        self.assertEqual([item["n"] for item in state["recent_requests"]], [3, 2])
        self.assertEqual(state["counters"]["mode:routed-basic"], 2)
        self.assertEqual(state["counters"]["success:True"], 2)
        self.assertEqual(state["counters"]["success:False"], 1)

    def test_run_record_round_trips_to_dict(self) -> None:
        types_module = self.load_script_module("llama_model_manager_types_round_trip", LMM_TYPES_PATH)
        run_record = types_module.RunRecord(
            id="",
            created_at=None,
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            prompt="ping",
            model="test.gguf",
            provider="llamacpp",
            route_target="llamacpp",
            route_reason_code="high_coherence_local",
            completion_chars=12,
            harness="pytest-agent",
            context_status="ok",
            context_used=True,
            status=types_module.RunStatus.PENDING,
            exit_result=None,
            duration_ms=None,
            error_message=None,
        )

        payload = run_record.to_dict()
        restored = types_module.RunRecord.from_dict(payload)

        self.assertEqual(payload["status"], types_module.RunStatus.PENDING.value)
        self.assertEqual(restored.to_dict(), payload)

    def test_run_record_truncates_long_prompt(self) -> None:
        types_module = self.load_script_module("llama_model_manager_types_prompt_limit", LMM_TYPES_PATH)
        record = types_module.RunRecord(
            id="",
            created_at=None,
            started_at=None,
            completed_at=None,
            prompt="x" * 8000,
            model="qwen.gguf",
            provider="llamacpp",
            route_target="llamacpp",
            route_reason_code="high_coherence_local",
            completion_chars=0,
            harness="pytest-agent",
            context_status="empty",
            context_used=False,
        )

        self.assertEqual(len(record.prompt), 4000)

    def test_run_record_auto_generates_id_and_timestamp(self) -> None:
        types_module = self.load_script_module("llama_model_manager_types_identity", LMM_TYPES_PATH)
        record = types_module.RunRecord(
            id="",
            created_at=None,
            started_at=None,
            completed_at=None,
            prompt="hello",
            model="qwen.gguf",
            provider="llamacpp",
            route_target="llamacpp",
            route_reason_code="high_coherence_local",
            completion_chars=0,
            harness="pytest-agent",
            context_status="empty",
            context_used=False,
        )

        self.assertEqual(len(record.id), 12)
        self.assertIsInstance(record.created_at, str)
        self.assertTrue(record.created_at)

    def test_json_run_record_store_caps_recent_records(self) -> None:
        storage_module = self.load_script_module("llama_model_manager_storage_run_caps", LMM_STORAGE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run-records.json"
            store = storage_module.JsonRunRecordStore(path, recent_limit=3)
            for index in range(5):
                store.append_record(
                    {
                        "id": f"record-{index}",
                        "status": "completed",
                        "model": "model.gguf",
                    }
                )

            self.assertEqual(len(store.list_recent(limit=10)), 3)
            recent = store.list_recent()
            self.assertEqual([record["id"] for record in recent], ["record-4", "record-3", "record-2"])

    def test_json_run_record_store_filters_by_status(self) -> None:
        storage_module = self.load_script_module("llama_model_manager_storage_run_filter", LMM_STORAGE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run-records.json"
            store = storage_module.JsonRunRecordStore(path, recent_limit=10)
            store.append_record({"id": "r1", "status": "completed", "model": "m1"})
            store.append_record({"id": "r2", "status": "failed", "model": "m2"})
            store.append_record({"id": "r3", "status": "completed", "model": "m3"})

            completed = store.list_recent(status="completed")
            self.assertEqual([record["id"] for record in completed], ["r3", "r1"])

    def test_json_run_record_store_latest_completed(self) -> None:
        storage_module = self.load_script_module("llama_model_manager_storage_run_latest", LMM_STORAGE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run-records.json"
            store = storage_module.JsonRunRecordStore(path, recent_limit=10)
            store.append_record({"id": "r1", "status": "completed", "model": "m1"})
            store.append_record({"id": "r2", "status": "failed", "model": "m2"})
            store.append_record({"id": "r3", "status": "completed", "model": "m3"})
            self.assertEqual(store.latest_completed(), {"id": "r3", "status": "completed", "model": "m3"})

    def test_json_run_record_store_atomic_writes(self) -> None:
        storage_module = self.load_script_module("llama_model_manager_storage_run_atomic", LMM_STORAGE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run-records.json"
            store = storage_module.JsonRunRecordStore(path)
            store.append_record({"id": "r1", "status": "completed", "model": "m1"})
            store.append_record({"id": "r2", "status": "failed", "model": "m2"})

            tmp_files = sorted(path.parent.glob(f".{path.name}.tmp*"))
            self.assertEqual(tmp_files, [])

    def test_lmm_config_imports_without_scripts_on_sys_path(self) -> None:
        """Verify lmm_config.py is self-contained when loaded directly."""
        config_spec = importlib.util.spec_from_file_location(
            "lmm_config_isolated_test",
            LMM_CONFIG_PATH,
        )
        assert config_spec and config_spec.loader
        config_module = importlib.util.module_from_spec(config_spec)
        # Temporarily strip scripts/ from sys.path before exec
        scripts_entry = str(ROOT_DIR / "scripts")
        original_path = list(sys.path)
        cleaned_path = [p for p in sys.path if p != scripts_entry]
        try:
            sys.path[:] = cleaned_path
            # dataclass decorator in Python 3.12 requires the module to be
            # registered in sys.modules during exec, so we register it
            # temporarily and clean up afterward.
            sys.modules[config_spec.name] = config_module
            config_spec.loader.exec_module(config_module)
        finally:
            sys.path[:] = original_path
            sys.modules.pop(config_spec.name, None)

        config = config_module.load_lmm_config_from_env()
        self.assertIsInstance(config.gateway.port, int)
        self.assertGreater(config.gateway.port, 0)

    def test_gateway_server_factory_returns_configured_server(self) -> None:
        """Verify create_gateway_server() attaches expected attributes."""
        gateway = self.load_gateway_module()
        server = gateway.create_gateway_server(
            host="127.0.0.1",
            port=0,  # ephemeral — test doesn't bind long
            backend_base_url="http://test:9999/v1",
            model_id="test-model",
        )

        try:
            self.assertEqual(server.backend_base_url, "http://test:9999/v1")  # type: ignore[attr-defined]
            self.assertEqual(server.model_id, "test-model")  # type: ignore[attr-defined]
            self.assertIsInstance(server.gateway, gateway.LMMOpenAIGateway)  # type: ignore[attr-defined]
            self.assertEqual(server.gateway.backend_base_url, "http://test:9999/v1")
            self.assertEqual(server.gateway.model_id, "test-model")
        finally:
            server.server_close()

    def test_gateway_server_factory_defaults_match_config(self) -> None:
        """Verify create_gateway_server() defaults align with load_lmm_config_from_env()."""
        gateway = self.load_gateway_module()
        config_module = self.load_script_module("llama_model_manager_config_defaults", LMM_CONFIG_PATH)
        config = config_module.load_lmm_config_from_env()
        # Use ephemeral port (0) to avoid address conflicts with existing tests
        server = gateway.create_gateway_server(host=config.gateway.host, port=0)

        try:
            self.assertEqual(server.server_address[0], config.gateway.host)
            self.assertEqual(server.backend_base_url, config.gateway.backend_base_url)  # type: ignore[attr-defined]
        finally:
            server.server_close()

    def test_gateway_context_status_reports_bridge_readiness(self) -> None:
        gateway = self.load_gateway_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            app_root = Path(tmpdir)
            mcp_root = app_root / "integrations" / "context-mode-mcp"
            bridge_path = app_root / "scripts" / "context_mcp_bridge.py"

            with mock.patch.object(gateway, "APP_ROOT", app_root):
                with mock.patch.dict(os.environ, {"LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1"}, clear=True):
                    self.assertEqual(gateway.context_status(), ("missing", False))

                    mcp_root.mkdir(parents=True)
                    (mcp_root / "package.json").write_text("{}", encoding="utf-8")
                    self.assertEqual(gateway.context_status(), ("missing_bridge", False))
                    self.assertEqual(
                        gateway.retrieve_context({}, "hello", model="status-model", stream=False)["status"],
                        "missing_bridge",
                    )

                    bridge_path.parent.mkdir(parents=True)
                    bridge_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
                    self.assertEqual(gateway.context_status(), ("missing_dist", False))
                    self.assertEqual(
                        gateway.retrieve_context({}, "hello", model="status-model", stream=False)["status"],
                        "missing_dist",
                    )

                    (mcp_root / "dist").mkdir()
                    (mcp_root / "dist" / "index.js").write_text("// built\n", encoding="utf-8")
                    self.assertEqual(gateway.context_status(), ("bridge_ready", False))

                    with mock.patch.dict(os.environ, {"LMM_CONTEXT_MCP_COMMAND": "custom-ctx"}, clear=False):
                        self.assertEqual(gateway.context_status(), ("command_configured", False))

    def make_manager(self, tmpdir: str) -> object:
        env = {
            "HOME": str(Path(tmpdir) / "home"),
            "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
            "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
            "LLAMA_SERVER_RUNTIME_DIR": str(Path(tmpdir) / "runtime"),
            "LLAMA_MODEL_WEB_DISABLE_ACTIVITY_LOG": "1",
        }
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        config_dir = Path(env["XDG_CONFIG_HOME"]) / "llama-server"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "defaults.env").write_text(
            "LLAMA_SERVER_HOST=127.0.0.1\nLLAMA_SERVER_PORT=8081\n",
            encoding="utf-8",
        )

        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return WEB_APP.Manager(ROOT_DIR / "web")

    def wait_for_download_terminal_status(
        self, manager: object, job_id: str, *, timeout: float = 5.0
    ) -> dict[str, object]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            store = manager.read_download_jobs_store()
            job = next((item for item in store["items"] if item["id"] == job_id), None)
            if job and str(job.get("status", "")).strip() in {"completed", "failed", "cancelled"}:
                return job
            time.sleep(0.05)
        self.fail(f"download job {job_id} did not reach terminal status in time")

    def wait_for_download_thread(self, manager: object, job_id: str, *, timeout: float = 5.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            worker = manager.download_threads.get(job_id)
            if worker is None:
                store = manager.read_download_jobs_store()
                if not any(item["id"] == job_id for item in store.get("items", [])):
                    return
                break
            if not worker.is_alive():
                return
            time.sleep(0.05)

        # If the thread is still running, we let downstream status reads drive the assertion.
        # This fallback avoids a hard dependency on a specific scheduler interleaving.
        self.wait_for_download_terminal_status(manager, job_id)

    def start_app_server(self, manager: object) -> ThreadingHTTPServer:
        handler = type("Phase0ContractAppHandler", (WEB_APP.AppHandler,), {})
        handler.manager = manager
        handler.web_root = ROOT_DIR / "web"
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        return server

    def start_gateway_server(
        self,
        *,
        gateway_module: object | None = None,
        model_id: str = "test-model",
        backend_base_url: str = "http://127.0.0.1:9/v1",
    ) -> ThreadingHTTPServer:
        gateway = gateway_module or self.load_gateway_module()
        handler = type("Phase0GatewayHandler", (gateway.GatewayHandler,), {})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.backend_base_url = backend_base_url  # type: ignore[attr-defined]
        server.model_id = model_id  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        return server

    def start_backend_status_server(
        self,
        *,
        status: int = 200,
        payload: dict[str, object] | None = None,
    ) -> ThreadingHTTPServer:
        response_body = (
            payload
            if payload is not None
            else {
                "object": "list",
                "data": [{"id": "mock-model", "object": "model"}],
            }
        )

        class BackendHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path.split("?", 1)[0] == "/v1/models":
                    body = json.dumps(response_body).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        return server

    def post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json_raw(self, url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode("utf-8")
        return status, json.loads(body)

    def get_json_raw(self, url: str) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            status = exc.code
            body = exc.read().decode("utf-8")
        return status, json.loads(body)

    def test_static_assets_are_served_without_browser_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            url = f"http://127.0.0.1:{app_server.server_port}/index.html"

            with urllib.request.urlopen(url, timeout=10) as response:
                self.assertEqual(response.status, HTTPStatus.OK)
                self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")

    def test_state_includes_dashboard_session_start_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)

            payload = manager.state()
            started_at = payload["meta"]["dashboard_started_at"]

            self.assertIsInstance(started_at, str)
            self.assertTrue(started_at)
            self.assertEqual(started_at, manager.started_at)

    def test_demo_state_loads_from_json_file(self) -> None:
        demo_path = ROOT_DIR / "web" / "demo_state.json"
        self.assertTrue(demo_path.is_file())

        payload = json.loads(demo_path.read_text(encoding="utf-8"))

        self.assertIn("state", payload)
        self.assertIn("discovery", payload)
        self.assertIn("log", payload)
        self.assertEqual(payload["state"]["title"], "LLM Model Manager")
        self.assertEqual(len(payload["discovery"]), 2)
        self.assertIn("model loaded", payload["log"])

    def test_demo_state_matches_hardcoded_values(self) -> None:
        demo_path = ROOT_DIR / "web" / "demo_state.json"
        payload = json.loads(demo_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["state"]["title"], WEB_APP.DEMO_STATE["title"])
        self.assertEqual(payload["state"]["brand"], WEB_APP.DEMO_STATE["brand"])
        self.assertEqual(len(payload["state"]["models"]), len(WEB_APP.DEMO_STATE["models"]))

    def test_manager_load_run_history_returns_empty_when_no_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing-run-records.json"
            with mock.patch.dict(os.environ, {"LMM_RUN_RECORDS_FILE": str(missing)}, clear=False):
                manager = self.make_manager(tmpdir)

                run_history = manager._load_run_history()

            self.assertEqual(run_history["records"], [])
            self.assertEqual(run_history["total"], 0)
            self.assertEqual(run_history["by_status"], {})
            self.assertNotIn("error", run_history)

    def test_manager_load_run_history_returns_records_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            records_path = Path(tmpdir) / "run-records.json"
            storage = self.load_script_module("llama_model_manager_storage_task3", LMM_STORAGE_PATH)
            store = storage.JsonRunRecordStore(records_path)
            store.append_record({"id": "completed-1", "status": "completed", "model": "m1"})
            store.append_record({"id": "failed-1", "status": "failed", "model": "m2"})

            with mock.patch.dict(os.environ, {"LMM_RUN_RECORDS_FILE": str(records_path)}, clear=False):
                manager = self.make_manager(tmpdir)
                run_history = manager._load_run_history()

            self.assertEqual(run_history["total"], 2)
            self.assertEqual([item["id"] for item in run_history["records"]], ["failed-1", "completed-1"])
            self.assertEqual(run_history["by_status"], {"completed": 1, "failed": 1})
            self.assertEqual(run_history["latest_completed"]["id"], "completed-1")

    def test_demo_mode_state_includes_run_history_key(self) -> None:
        manager = WEB_APP.Manager(ROOT_DIR / "web", demo=True)
        state = manager.state()

        self.assertTrue(state["demo"])
        self.assertEqual(state["run_history"], {"records": [], "total": 0, "by_status": {}})

    def test_dashboard_markup_separates_glyph_routes_from_control_activity(self) -> None:
        html = (ROOT_DIR / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Observed Glyph Routes", html)
        self.assertIn('id="observed-glyph-feed"', html)
        self.assertIn('id="glyphos-badge"', html)
        self.assertIn('id="glyphos-status"', html)
        self.assertIn('id="toggle-activity-panel"', html)
        self.assertIn("Context + Glyph Encoding + GlyphOS", html)
        self.assertIn('id="context-trace-status"', html)
        self.assertIn('id="context-trace-encoding"', html)
        self.assertIn("Control-plane actions only", html)

    def test_unknown_post_field_is_rejected_with_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.post_json_raw(
                f"{api_base}/api/downloads/policy",
                {
                    "max_active_downloads": 4,
                    "unexpected_field": "nope",
                },
            )

            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "unknown_field")

    def test_unknown_post_route_returns_not_found_with_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.post_json_raw(f"{api_base}/api/does-not-exist", {})

            self.assertEqual(status, HTTPStatus.NOT_FOUND)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "unknown_route")

    def test_unknown_get_route_returns_not_found_with_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.get_json_raw(f"{api_base}/api/does-not-exist")

            self.assertEqual(status, HTTPStatus.NOT_FOUND)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "unknown_route")

    def test_invalid_lines_query_param_is_bad_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.get_json_raw(f"{api_base}/api/logs?lines=abc")

            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_query_param")

    def test_oversized_post_body_is_rejected_with_request_entity_too_large(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            patcher = mock.patch.dict(os.environ, {"LLAMA_MODEL_WEB_MAX_REQUEST_BYTES": "1024"}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)

            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.post_json_raw(
                f"{api_base}/api/discover",
                {
                    "root": "a" * 2048,
                },
            )

            self.assertEqual(status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "payload_too_large")

    def test_download_control_routes_require_non_empty_string_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            for path in (
                "/api/downloads/cancel",
                "/api/downloads/retry",
                "/api/downloads/resume",
                "/api/downloads/remove-queued",
                "/api/downloads/prioritize-queued",
                "/api/downloads/deprioritize-queued",
            ):
                status, response = self.post_json_raw(f"{api_base}{path}", {})
                self.assertEqual(status, HTTPStatus.BAD_REQUEST, path)
                self.assertFalse(response["ok"], path)
                self.assertEqual(response["code"], "missing_required_field", path)

                status, response = self.post_json_raw(f"{api_base}{path}", {"id": 123})
                self.assertEqual(status, HTTPStatus.BAD_REQUEST, path)
                self.assertFalse(response["ok"], path)
                self.assertEqual(response["code"], "invalid_field_type", path)

                status, response = self.post_json_raw(f"{api_base}{path}", {"id": "   "})
                self.assertEqual(status, HTTPStatus.BAD_REQUEST, path)
                self.assertFalse(response["ok"], path)
                self.assertEqual(response["code"], "invalid_field_type", path)

    def test_download_api_state_transitions_return_structured_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            status, response = self.post_json_raw(f"{api_base}/api/downloads/cancel", {"id": "missing"})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_request")

            status, response = self.post_json_raw(f"{api_base}/api/downloads/retry", {"id": "missing"})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_request")

            status, response = self.post_json_raw(f"{api_base}/api/downloads/resume", {"id": "missing"})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_request")

            partial_path = Path(tmpdir) / "downloads" / "has.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "queued-one",
                            "status": "queued",
                            "repo_id": "author/model",
                            "artifact_name": "queued.gguf",
                        },
                        {
                            "id": "done-no-partial",
                            "status": "failed",
                            "repo_id": "author/model",
                            "artifact_name": "failed.gguf",
                            "partial_path": str(Path(tmpdir) / "downloads" / "missing.part"),
                        },
                        {
                            "id": "done-with-partial",
                            "status": "failed",
                            "repo_id": "author/model",
                            "artifact_name": "failed.gguf",
                            "partial_path": str(partial_path),
                            "destination_root": str(Path(tmpdir) / "downloads"),
                        },
                    ],
                },
            )

            status, response = self.post_json_raw(f"{api_base}/api/downloads/remove-queued", {"id": "done-no-partial"})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_request")

            status, response = self.post_json_raw(f"{api_base}/api/downloads/resume", {"id": "done-no-partial"})
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertFalse(response["ok"])
            self.assertEqual(response["code"], "invalid_request")

            status, response = self.post_json_raw(f"{api_base}/api/downloads/resume", {"id": "queued-one"})
            self.assertEqual(status, HTTPStatus.OK)
            self.assertTrue(response["ok"])
            self.assertIn("job", response)

    def test_remote_search_and_download_lifecycle_post_routes_are_wired(self) -> None:
        class RouteTableManager:
            discovery_root = "/tmp"
            max_active_downloads = 2

            def __init__(self) -> None:
                self.calls: list[tuple[str, object]] = []

            def search_remote_models(self, payload):
                self.calls.append(("search_remote_models", dict(payload)))
                return {"query": payload.get("query"), "items": []}

            def start_remote_download(self, payload):
                self.calls.append(("start_remote_download", dict(payload)))
                return {"id": "started", "status": "running"}

            def cancel_download_job(self, job_id):
                self.calls.append(("cancel_download_job", job_id))
                return {"id": job_id, "status": "cancelled"}

            def retry_download_job(self, job_id):
                self.calls.append(("retry_download_job", job_id))
                return {"id": job_id, "status": "queued"}

            def resume_download_job(self, job_id):
                self.calls.append(("resume_download_job", job_id))
                return {"id": job_id, "status": "running"}

            def cleanup_stale_partial_downloads(self, *, max_age_seconds):
                self.calls.append(("cleanup_stale_partial_downloads", max_age_seconds))
                return {"removed": [], "max_age_seconds": max_age_seconds}

            def cleanup_duplicate_completed_job_records(self):
                self.calls.append(("cleanup_duplicate_completed_job_records", None))
                return {"removed": []}

            def delete_orphaned_download_artifacts(self, paths):
                self.calls.append(("delete_orphaned_download_artifacts", paths))
                return {"deleted": paths or []}

            def recover_stale_download_jobs(self):
                self.calls.append(("recover_stale_download_jobs", None))
                return {"recovered": []}

            def pause_download_queue(self):
                self.calls.append(("pause_download_queue", None))
                return {"queue_paused": True}

            def resume_download_queue(self):
                self.calls.append(("resume_download_queue", None))
                return {"queue_paused": False}

            def set_max_active_downloads(self, value):
                self.calls.append(("set_max_active_downloads", value))
                return {"max_active_downloads": value}

            def remove_queued_download_job(self, job_id):
                self.calls.append(("remove_queued_download_job", job_id))
                return {"id": job_id, "status": "queued"}

            def clear_queued_download_jobs(self):
                self.calls.append(("clear_queued_download_jobs", None))
                return {"removed": []}

            def prioritize_queued_download_job(self, job_id):
                self.calls.append(("prioritize_queued_download_job", job_id))
                return {"id": job_id, "status": "queued"}

            def deprioritize_queued_download_job(self, job_id):
                self.calls.append(("deprioritize_queued_download_job", job_id))
                return {"id": job_id, "status": "queued"}

        manager = RouteTableManager()
        app_server = self.start_app_server(manager)
        api_base = f"http://127.0.0.1:{app_server.server_port}"
        cases = [
            ("/api/remote/search", {"query": "qwen"}, "search_remote_models", "remote_models"),
            (
                "/api/downloads/start",
                {"repo_id": "author/model", "artifact_name": "model.gguf"},
                "start_remote_download",
                "job",
            ),
            ("/api/downloads/cancel", {"id": "job-cancel"}, "cancel_download_job", "job"),
            ("/api/downloads/retry", {"id": "job-retry"}, "retry_download_job", "job"),
            ("/api/downloads/resume", {"id": "job-resume"}, "resume_download_job", "job"),
            ("/api/downloads/cleanup", {"max_age_seconds": 123}, "cleanup_stale_partial_downloads", "removed"),
            ("/api/downloads/cleanup-duplicates", {}, "cleanup_duplicate_completed_job_records", "removed"),
            (
                "/api/downloads/delete-orphans",
                {"paths": ["/tmp/orphan.part"]},
                "delete_orphaned_download_artifacts",
                "deleted",
            ),
            ("/api/downloads/recover", {}, "recover_stale_download_jobs", "recovered"),
            ("/api/downloads/pause-queue", {}, "pause_download_queue", "download_policy"),
            ("/api/downloads/resume-queue", {}, "resume_download_queue", "download_policy"),
            ("/api/downloads/policy", {"max_active_downloads": 4}, "set_max_active_downloads", "download_policy"),
            ("/api/downloads/remove-queued", {"id": "queued-remove"}, "remove_queued_download_job", "job"),
            ("/api/downloads/clear-queued", {}, "clear_queued_download_jobs", "removed"),
            ("/api/downloads/prioritize-queued", {"id": "queued-up"}, "prioritize_queued_download_job", "job"),
            ("/api/downloads/deprioritize-queued", {"id": "queued-down"}, "deprioritize_queued_download_job", "job"),
        ]

        for path, payload, _method_name, response_key in cases:
            response = self.post_json(f"{api_base}{path}", payload)
            self.assertTrue(response["ok"], path)
            self.assertIn(response_key, response, path)

        self.assertEqual([method_name for method_name, _arg in manager.calls], [case[2] for case in cases])
        self.assertEqual(manager.calls[0][1], {"query": "qwen"})
        self.assertEqual(manager.calls[5][1], 123)
        self.assertEqual(manager.calls[7][1], ["/tmp/orphan.part"])
        self.assertEqual(manager.calls[11][1], 4)

    def test_remote_search_api_returns_cached_store_without_network_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "cached-qwen",
                    "fetched_at": "2026-04-23T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": "https://huggingface.co/author/model/resolve/main/model-Q4_K_M.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": 1048576,
                        }
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/remote/search", {})

            self.assertTrue(payload["ok"])
            remote_models = payload["remote_models"]
            self.assertEqual(remote_models["query"], "cached-qwen")
            self.assertEqual(remote_models["items"][0]["repo_id"], "author/model")
            self.assertEqual(remote_models["items"][0]["artifact_name"], "model-Q4_K_M.gguf")
            self.assertEqual(remote_models["items"][0]["size_human"], "1.0 MiB")
            self.assertIn("compatibility_status", remote_models["items"][0])

    def test_state_creates_phase0_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            runtime_dir = Path(tmpdir) / "runtime" / "llama-server" / "linux-x86_64-cuda"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            binary_path = runtime_dir / "llama-server"
            binary_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            binary_path.chmod(0o755)
            (runtime_dir / "llama-server.compat.env").write_text(
                "\n".join(
                    [
                        "LLAMA_BUNDLE_OS=linux",
                        "LLAMA_BUNDLE_ARCH=x86_64",
                        "LLAMA_BUNDLE_BACKEND=cuda",
                        "LLAMA_BUNDLE_LABEL=NVIDIA CUDA",
                        "LLAMA_BUNDLE_SOURCE_REF=b8851",
                        "LLAMA_BUNDLE_BUILT_AT=2026-04-20T00:00:00+00:00",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            outputs = {
                "current": "\n".join(
                    [
                        "alias: stopped",
                        "model:",
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
                "doctor": "\n".join(
                    [
                        "host_os: linux",
                        "host_arch: x86_64",
                        "host_backends: cpu,cuda",
                        "binary_ok: yes",
                        f"binary: {binary_path}",
                        "binary_source: bundled",
                        "binary_backend: cuda",
                        "binary_status: compatible",
                        "binary_label: NVIDIA CUDA",
                        "binary_message: validated bundled NVIDIA CUDA binary",
                        f"binary_manifest: {runtime_dir / 'llama-server.compat.env'}",
                    ]
                ),
                "mode": "\n".join(
                    [
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
            }
            manager.run_cli = lambda command, *args: outputs[command]  # type: ignore[method-assign]

            state = manager.state()

            self.assertIn("remote_models", state)
            self.assertIn("download_jobs", state)
            self.assertIn("runtime_profiles", state)
            self.assertIn("validation_results", state)
            self.assertIn("host_capability", state)
            self.assertEqual(state["runtime_profiles"]["items"][0]["label"], "NVIDIA CUDA")
            self.assertEqual(
                state["host_capability"]["selected_binary"]["manifest_path"],
                str(runtime_dir / "llama-server.compat.env"),
            )

            state_dir = Path(tmpdir) / "state" / "llama-server"
            config_dir = Path(tmpdir) / "config" / "llama-server"
            self.assertTrue((state_dir / "remote-models.json").is_file())
            self.assertTrue((state_dir / "download-jobs.json").is_file())
            self.assertTrue((state_dir / "validation-results.json").is_file())
            self.assertTrue((state_dir / "host-capability.json").is_file())
            self.assertTrue((config_dir / "runtime-profiles.json").is_file())

    def test_state_includes_glyphos_telemetry_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            outputs = {
                "current": "\n".join(
                    [
                        "alias: stopped",
                        "model:",
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
                "doctor": "\n".join(
                    [
                        "host_os: linux",
                        "host_arch: x86_64",
                        "host_backends: cpu",
                        "binary_ok: yes",
                        "binary: /tmp/llama-server",
                        "binary_source: bundled",
                        "binary_backend: cpu",
                        "binary_status: compatible",
                        "binary_label: CPU",
                        "binary_message: validated bundled CPU binary",
                    ]
                ),
                "mode": "\n".join(
                    [
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
            }
            manager.run_cli = lambda command, *args: outputs[command]  # type: ignore[method-assign]

            state = manager.state()

            self.assertIn("glyphos_telemetry", state)
            telemetry = state["glyphos_telemetry"]
            self.assertIn("available", telemetry)
            self.assertIn("routing", telemetry)
            routing = telemetry["routing"]
            for key in ("attempts_by_target", "fallback_reason_counts", "total_attempts", "recent_attempts"):
                self.assertIn(key, routing)

    def test_glyphos_telemetry_prefers_bundled_package_over_stale_loaded_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            fake_root = Path(tmpdir) / "stale"
            fake_package = fake_root / "glyphos_ai"
            fake_compute = fake_package / "ai_compute"
            fake_compute.mkdir(parents=True)

            stale_package = types.ModuleType("glyphos_ai")
            stale_package.__path__ = [str(fake_package)]  # type: ignore[attr-defined]
            stale_compute = types.ModuleType("glyphos_ai.ai_compute")
            stale_compute.__path__ = [str(fake_compute)]  # type: ignore[attr-defined]
            old_modules = {name: sys.modules.get(name) for name in ("glyphos_ai", "glyphos_ai.ai_compute")}
            sys.modules["glyphos_ai"] = stale_package
            sys.modules["glyphos_ai.ai_compute"] = stale_compute
            self.addCleanup(
                lambda: [
                    sys.modules.pop(name, None) if module is None else sys.modules.__setitem__(name, module)
                    for name, module in old_modules.items()
                ]
            )

            telemetry = manager.glyphos_telemetry_snapshot()

            self.assertTrue(telemetry["available"])
            self.assertTrue(telemetry["installed"])
            self.assertEqual(telemetry["source"], "bundled")

    def test_glyphos_telemetry_finds_installed_integration_when_web_root_is_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_root = Path(tmpdir) / "isolated-web"
            app_root.mkdir()
            data_root = Path(tmpdir) / "data"
            installed_root = data_root / "llama-model-manager" / "integrations" / "public-glyphos-ai-compute"
            installed_package = installed_root / "glyphos_ai" / "ai_compute"
            installed_package.mkdir(parents=True)
            (installed_root / "glyphos_ai" / "__init__.py").write_text("", encoding="utf-8")
            (installed_package / "__init__.py").write_text("", encoding="utf-8")
            (installed_package / "router.py").write_text(
                "def routing_telemetry_snapshot(limit=10):\n"
                "    return {'attempts_by_target': {}, 'fallback_reason_counts': {}, 'total_attempts': 0, 'recent_attempts': []}\n",
                encoding="utf-8",
            )
            env = {
                "HOME": str(Path(tmpdir) / "home"),
                "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                "XDG_DATA_HOME": str(data_root),
                "LLAMA_MODEL_WEB_DISABLE_ACTIVITY_LOG": "1",
            }
            Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
            (Path(env["XDG_CONFIG_HOME"]) / "llama-server").mkdir(parents=True)
            with mock.patch.dict(os.environ, env, clear=False):
                manager = WEB_APP.Manager(app_root)

            telemetry = manager.glyphos_telemetry_snapshot()

            self.assertTrue(telemetry["available"])
            self.assertTrue(telemetry["installed"])
            self.assertEqual(Path(telemetry["integration_root"]), installed_root)

    def test_state_falls_back_when_remote_items_shape_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)

            outputs = {
                "current": "\n".join(
                    [
                        "alias: stopped",
                        "model:",
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
                "doctor": "\n".join(
                    [
                        "host_os: linux",
                        "host_arch: x86_64",
                        "host_backends: cpu,cuda",
                        "binary_ok: yes",
                        "binary: /tmp/llama-server",
                        "binary_source: bundled",
                        "binary_backend: cuda",
                        "binary_status: compatible",
                        "binary_label: NVIDIA CUDA",
                        "binary_message: validated bundled NVIDIA CUDA binary",
                    ]
                ),
                "mode": "\n".join(
                    [
                        "configured_mode: single-client",
                        "configured_parallel: 1",
                        "active_mode: stopped",
                        "active_parallel: stopped",
                    ]
                ),
            }
            manager.run_cli = lambda command, *args: outputs[command]  # type: ignore[method-assign]
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": {"bad": "shape"},
                },
            )

            state = manager.state()
            self.assertEqual(state["remote_models"]["items"], [])

    def test_read_download_jobs_store_rewrites_invalid_items_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": {"bad": "shape"},
                },
            )

            store = manager.read_download_jobs_store()
            self.assertEqual(store["items"], [])

            persisted = json.loads(manager.download_jobs_file.read_text(encoding="utf-8"))
            self.assertIsInstance(persisted.get("items"), list)
            self.assertEqual(persisted["items"], [])

    def test_host_capability_shape_is_normalized_when_items_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.host_capability_file,
                {
                    "schema_version": 1,
                    "host_os": "linux",
                    "host_arch": "x86_64",
                    "host_backends": "cpu,cuda",
                    "preferred_backend": "cuda",
                    "memory_bytes": "not-an-int",
                    "binary_ok": "yes",
                    "selected_binary": "legacy",
                },
            )

            contracts = manager.phase0_contracts()
            host_capability = contracts["host_capability"]
            self.assertEqual(host_capability["host_backends"], ["cpu", "cuda"])
            self.assertEqual(host_capability["preferred_backend"], "cuda")
            self.assertEqual(host_capability["memory_bytes"], 0)
            self.assertIsInstance(host_capability["selected_binary"], dict)

    def test_download_storage_summary_reports_partials_and_duplicate_completed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            partial_path = Path(tmpdir) / "downloads" / "partial.part"
            completed_path = Path(tmpdir) / "downloads" / "model.gguf"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            completed_path.write_bytes(b"model")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "partial-job",
                            "status": "cancelled",
                            "repo_id": "author/model",
                            "artifact_name": "partial.gguf",
                            "partial_path": str(partial_path),
                        },
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                        {
                            "id": "completed-b",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                    ],
                },
            )

            state = manager.phase0_contracts()
            storage = state["download_storage"]

            self.assertEqual(storage["partial_bytes"], len(b"partial"))
            self.assertEqual(storage["duplicate_completed_count"], 1)
            self.assertEqual(storage["duplicate_completed_job_records"], 1)
            self.assertEqual(storage["duplicate_cleanup_mode"], "advisory")
            self.assertIn("not removed automatically", storage["duplicate_cleanup_guidance"])
            self.assertEqual(
                storage["duplicate_completed_artifacts"],
                [{"path": str(completed_path), "job_ids": ["completed-a", "completed-b"]}],
            )

    def test_download_policy_summary_reports_capacity_and_duplicate_active_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.max_active_downloads = 2
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "active-a",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                        },
                        {
                            "id": "active-b",
                            "status": "queued",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                        },
                    ],
                },
            )

            policy = manager.phase0_contracts()["download_policy"]

            self.assertEqual(policy["max_active_downloads"], 2)
            self.assertEqual(policy["active_downloads"], 2)
            self.assertEqual(policy["running_downloads"], 1)
            self.assertEqual(policy["queued_downloads"], 1)
            self.assertEqual(policy["available_slots"], 1)
            self.assertFalse(policy["at_capacity"])
            self.assertEqual(policy["next_queued_job"]["id"], "active-b")
            self.assertEqual(policy["duplicate_active_count"], 1)
            self.assertEqual(policy["duplicate_active_artifacts"][0]["job_ids"], ["active-a", "active-b"])

    def test_read_download_jobs_store_assigns_queue_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "running-a",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                        {
                            "id": "failed-a",
                            "status": "failed",
                            "repo_id": "author/model",
                            "artifact_name": "failed.gguf",
                        },
                    ],
                },
            )

            store = manager.read_download_jobs_store()
            positions = {item["id"]: item["queue_position"] for item in store["items"]}

            self.assertEqual(positions["running-a"], 0)
            self.assertEqual(positions["queued-a"], 1)
            self.assertEqual(positions["queued-b"], 2)
            self.assertEqual(positions["failed-a"], 0)

            jobs = {item["id"]: item for item in store["items"]}
            self.assertFalse(jobs["queued-a"]["can_prioritize"])
            self.assertTrue(jobs["queued-a"]["can_deprioritize"])
            self.assertTrue(jobs["queued-b"]["can_prioritize"])
            self.assertFalse(jobs["queued-b"]["can_deprioritize"])
            self.assertFalse(jobs["running-a"]["can_prioritize"])
            self.assertFalse(jobs["failed-a"]["can_deprioritize"])

    def test_start_remote_download_queues_new_artifact_when_running_slots_are_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.max_active_downloads = 1
            release = threading.Event()
            worker = threading.Thread(target=release.wait, daemon=True)
            worker.start()
            self.addCleanup(release.set)
            self.addCleanup(worker.join, 1)
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/other",
                            "artifact_name": "other.gguf",
                            "alias": "other",
                            "download_url": "https://example.invalid/other.gguf",
                            "source_url": "https://huggingface.co/author/other",
                            "size_bytes": 1,
                        }
                    ],
                },
            )
            manager.upsert_download_job(
                {
                    "id": "active-a",
                    "status": "running",
                    "repo_id": "author/model",
                    "artifact_name": "model.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )
            manager._register_download_controls("active-a", thread=worker)

            queued = manager.start_remote_download(
                {
                    "repo_id": "author/other",
                    "artifact_name": "other.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            self.assertEqual(queued["status"], "queued")
            self.assertNotIn(queued["id"], manager.download_threads)
            policy = manager.download_policy_summary(manager.read_download_jobs_store())
            self.assertEqual(policy["running_downloads"], 1)
            self.assertEqual(policy["queued_downloads"], 1)
            self.assertTrue(policy["at_capacity"])

    def test_start_remote_download_returns_existing_same_artifact_even_at_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.max_active_downloads = 1
            release = threading.Event()
            worker = threading.Thread(target=release.wait, daemon=True)
            worker.start()
            self.addCleanup(release.set)
            self.addCleanup(worker.join, 1)
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "alias": "model",
                            "download_url": "https://example.invalid/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": 1,
                        }
                    ],
                },
            )
            manager.upsert_download_job(
                {
                    "id": "active-a",
                    "status": "running",
                    "repo_id": "author/model",
                    "artifact_name": "model.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )
            manager._register_download_controls("active-a", thread=worker)

            existing = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            self.assertEqual(existing["id"], "active-a")

    def test_scheduler_starts_next_queued_download_when_slot_opens(self) -> None:
        payload = b"scheduler-payload" * 100_000

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            manager.max_active_downloads = 1
            release = threading.Event()
            worker = threading.Thread(target=release.wait, daemon=True)
            worker.start()
            self.addCleanup(release.set)
            self.addCleanup(worker.join, 1)
            manager.upsert_download_job(
                {
                    "id": "active-a",
                    "status": "running",
                    "repo_id": "author/model",
                    "artifact_name": "active.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )
            manager._register_download_controls("active-a", thread=worker)
            queued = {
                "id": "queued-b",
                "provider": "huggingface",
                "repo_id": "author/queued",
                "artifact_name": "queued.gguf",
                "alias": "queued",
                "download_url": f"http://127.0.0.1:{server.server_port}/queued.gguf",
                "source_url": "https://huggingface.co/author/queued",
                "sha256": "",
                "destination_root": str(Path(tmpdir) / "downloads"),
                "destination_path": str(
                    Path(tmpdir) / "downloads" / "huggingface" / "author" / "queued" / "queued.gguf"
                ),
                "partial_path": str(
                    Path(tmpdir) / "downloads" / "huggingface" / "author" / "queued" / "queued.gguf.queued-b.part"
                ),
                "bytes_downloaded": 0,
                "bytes_total": len(payload),
                "progress": 0.0,
                "status": "queued",
                "created_at": manager.iso_now(),
                "cancel_requested": False,
                "error": "",
            }
            manager.upsert_download_job(queued)

            manager._clear_download_controls("active-a")
            manager._schedule_downloads()

            for _ in range(200):
                time.sleep(0.01)
                active = manager.find_download_job("queued-b")
                if active and active.get("status") == "running":
                    break
            self.assertIn("queued-b", manager.download_threads)

            manager.cancel_download_job("queued-b")
            final_job = self.wait_for_download_terminal_status(manager, "queued-b", timeout=10)
            self.assertEqual(final_job["status"], "cancelled")

    def test_paused_download_queue_does_not_start_queued_jobs_until_resumed(self) -> None:
        payload = b"pause-payload" * 100_000

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            manager.max_active_downloads = 1
            manager.pause_download_queue()
            manager.upsert_download_job(
                {
                    "id": "queued-paused",
                    "provider": "huggingface",
                    "status": "queued",
                    "repo_id": "author/model",
                    "artifact_name": "model.gguf",
                    "alias": "model",
                    "download_url": f"http://127.0.0.1:{server.server_port}/model.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                    "destination_path": str(
                        Path(tmpdir) / "downloads" / "huggingface" / "author" / "model" / "model.gguf"
                    ),
                    "partial_path": str(
                        Path(tmpdir)
                        / "downloads"
                        / "huggingface"
                        / "author"
                        / "model"
                        / "model.gguf.queued-paused.part"
                    ),
                    "bytes_total": len(payload),
                    "bytes_downloaded": 0,
                    "progress": 0.0,
                    "cancel_requested": False,
                    "error": "",
                }
            )

            manager._schedule_downloads()
            self.assertNotIn("queued-paused", manager.download_threads)
            paused_policy = manager.download_policy_summary(manager.read_download_jobs_store())
            self.assertTrue(paused_policy["queue_paused"])
            self.assertEqual(paused_policy["available_slots"], 0)

            manager.resume_download_queue()
            resumed_job = None
            for _ in range(200):
                time.sleep(0.01)
                resumed_job = manager.find_download_job("queued-paused")
                if resumed_job and resumed_job.get("status") != "queued":
                    break
            self.assertIsNotNone(resumed_job)
            self.assertNotEqual(resumed_job["status"], "queued")
            if resumed_job["status"] in {"running", "queued"}:
                manager.cancel_download_job("queued-paused")
            final_job = self.wait_for_download_terminal_status(manager, "queued-paused", timeout=10)
            self.assertIn(final_job["status"], {"cancelled", "completed"})

    def test_download_queue_pause_and_resume_api_updates_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            paused = self.post_json(f"{api_base}/api/downloads/pause-queue", {})
            resumed = self.post_json(f"{api_base}/api/downloads/resume-queue", {})

            self.assertTrue(paused["ok"])
            self.assertTrue(paused["download_policy"]["queue_paused"])
            self.assertTrue(resumed["ok"])
            self.assertFalse(resumed["download_policy"]["queue_paused"])

    def test_download_queue_pause_state_persists_across_manager_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.pause_download_queue()

            restarted = WEB_APP.Manager(ROOT_DIR / "web")

            self.assertTrue(restarted.download_queue_paused)
            policy = restarted.phase0_contracts()["download_policy"]
            self.assertTrue(policy["queue_paused"])

    def test_download_queue_pause_env_override_wins_over_persisted_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.pause_download_queue()
            patcher = mock.patch.dict(os.environ, {"LLAMA_MODEL_DOWNLOAD_QUEUE_PAUSED": "0"}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)

            restarted = WEB_APP.Manager(ROOT_DIR / "web")

            self.assertFalse(restarted.download_queue_paused)

    def test_max_active_downloads_persists_across_manager_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            policy = manager.set_max_active_downloads(4)

            restarted = WEB_APP.Manager(ROOT_DIR / "web")

            self.assertEqual(policy["max_active_downloads"], 4)
            self.assertEqual(restarted.max_active_downloads, 4)
            self.assertEqual(restarted.phase0_contracts()["download_policy"]["max_active_downloads"], 4)

    def test_max_active_downloads_env_override_wins_over_persisted_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.set_max_active_downloads(4)
            patcher = mock.patch.dict(os.environ, {"LLAMA_MODEL_MAX_ACTIVE_DOWNLOADS": "3"}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)

            restarted = WEB_APP.Manager(ROOT_DIR / "web")

            self.assertEqual(restarted.max_active_downloads, 3)

    def test_download_policy_api_updates_max_active_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"

            payload = self.post_json(f"{api_base}/api/downloads/policy", {"max_active_downloads": 5})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["download_policy"]["max_active_downloads"], 5)
            self.assertEqual(manager.max_active_downloads, 5)

    def test_remove_queued_download_job_removes_only_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "queued-remove",
                            "status": "queued",
                            "repo_id": "author/model",
                            "artifact_name": "queued.gguf",
                        },
                        {
                            "id": "running-keep",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                    ],
                },
            )

            removed = manager.remove_queued_download_job("queued-remove")

            self.assertEqual(removed["id"], "queued-remove")
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["running-keep"])

            with self.assertRaisesRegex(ValueError, "Only queued download jobs can be removed"):
                manager.remove_queued_download_job("running-keep")

    def test_remove_queued_download_job_api_removes_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "queued-api-remove",
                            "status": "queued",
                            "repo_id": "author/model",
                            "artifact_name": "queued.gguf",
                        }
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/remove-queued", {"id": "queued-api-remove"})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["job"]["id"], "queued-api-remove")
            self.assertEqual(manager.read_download_jobs_store()["items"], [])

    def test_clear_queued_download_jobs_removes_only_queued_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "running-keep",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                        {
                            "id": "completed-keep",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "done.gguf",
                        },
                    ],
                },
            )

            result = manager.clear_queued_download_jobs()

            self.assertEqual(result["removed"], ["queued-a", "queued-b"])
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["running-keep", "completed-keep"])

    def test_clear_queued_download_jobs_api_removes_only_queued_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "running-keep",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/clear-queued", {})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["removed"], ["queued-a"])
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["running-keep"])

    def test_prioritize_queued_download_job_moves_job_before_other_queued_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "running-keep",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                    ],
                },
            )

            prioritized = manager.prioritize_queued_download_job("queued-b")

            self.assertEqual(prioritized["id"], "queued-b")
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["running-keep", "queued-b", "queued-a"])

            with self.assertRaisesRegex(ValueError, "Only queued download jobs can be prioritized"):
                manager.prioritize_queued_download_job("running-keep")

    def test_prioritize_queued_download_job_api_moves_job_before_other_queued_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/prioritize-queued", {"id": "queued-b"})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["job"]["id"], "queued-b")
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["queued-b", "queued-a"])

    def test_deprioritize_queued_download_job_moves_job_after_next_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "running-keep",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                        },
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                        {"id": "queued-c", "status": "queued", "repo_id": "author/model", "artifact_name": "c.gguf"},
                    ],
                },
            )

            deprioritized = manager.deprioritize_queued_download_job("queued-a")

            self.assertEqual(deprioritized["id"], "queued-a")
            store = manager.read_download_jobs_store()
            self.assertEqual(
                [item["id"] for item in store["items"]], ["running-keep", "queued-b", "queued-a", "queued-c"]
            )

            manager.deprioritize_queued_download_job("queued-c")
            store_after_last = manager.read_download_jobs_store()
            self.assertEqual(
                [item["id"] for item in store_after_last["items"]], ["running-keep", "queued-b", "queued-a", "queued-c"]
            )

            with self.assertRaisesRegex(ValueError, "Only queued download jobs can be deprioritized"):
                manager.deprioritize_queued_download_job("running-keep")

    def test_deprioritize_queued_download_job_api_moves_job_after_next_queued_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {"id": "queued-a", "status": "queued", "repo_id": "author/model", "artifact_name": "a.gguf"},
                        {"id": "queued-b", "status": "queued", "repo_id": "author/model", "artifact_name": "b.gguf"},
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/deprioritize-queued", {"id": "queued-a"})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["job"]["id"], "queued-a")
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["queued-b", "queued-a"])

    def test_cleanup_duplicate_completed_job_records_keeps_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            completed_path = Path(tmpdir) / "downloads" / "model.gguf"
            completed_path.parent.mkdir(parents=True, exist_ok=True)
            completed_path.write_bytes(b"model")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                        {
                            "id": "completed-b",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                    ],
                },
            )

            result = manager.cleanup_duplicate_completed_job_records()

            self.assertEqual(result["kept"], ["completed-a"])
            self.assertEqual(result["removed"], ["completed-b"])
            self.assertTrue(completed_path.is_file())
            store = manager.read_download_jobs_store()
            self.assertEqual([item["id"] for item in store["items"]], ["completed-a"])
            self.assertEqual(manager.download_storage_summary(store)["duplicate_completed_count"], 0)

    def test_download_storage_summary_reports_orphaned_artifacts_as_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            destination_root = Path(tmpdir) / "downloads"
            referenced_path = destination_root / "huggingface" / "author" / "model" / "model.gguf"
            orphan_path = destination_root / "huggingface" / "author" / "model" / "orphan.gguf"
            referenced_path.parent.mkdir(parents=True, exist_ok=True)
            referenced_path.write_bytes(b"referenced")
            orphan_path.write_bytes(b"orphan")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "destination_root": str(destination_root),
                            "local_path": str(referenced_path),
                        }
                    ],
                },
            )

            storage = manager.phase0_contracts()["download_storage"]

            self.assertEqual(storage["orphaned_artifact_count"], 1)
            self.assertEqual(storage["orphaned_artifact_bytes"], len(b"orphan"))
            self.assertEqual(storage["orphaned_cleanup_mode"], "advisory")
            self.assertIn("not removed automatically", storage["orphaned_cleanup_guidance"])
            self.assertEqual(storage["orphaned_artifacts"][0]["path"], str(orphan_path.resolve()))

    def test_delete_orphaned_download_artifacts_removes_only_current_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            destination_root = Path(tmpdir) / "downloads"
            referenced_path = destination_root / "huggingface" / "author" / "model" / "model.gguf"
            orphan_path = destination_root / "huggingface" / "author" / "model" / "orphan.gguf"
            referenced_path.parent.mkdir(parents=True, exist_ok=True)
            referenced_path.write_bytes(b"referenced")
            orphan_path.write_bytes(b"orphan")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "destination_root": str(destination_root),
                            "local_path": str(referenced_path),
                        }
                    ],
                },
            )

            result = manager.delete_orphaned_download_artifacts(
                [str(orphan_path.resolve()), str(referenced_path.resolve())]
            )

            self.assertEqual(result["removed"], [str(orphan_path.resolve())])
            self.assertEqual(result["skipped"], [str(referenced_path.resolve())])
            self.assertFalse(orphan_path.exists())
            self.assertTrue(referenced_path.exists())

    def test_delete_orphaned_download_artifacts_api_removes_only_current_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            destination_root = Path(tmpdir) / "downloads"
            referenced_path = destination_root / "huggingface" / "author" / "model" / "model.gguf"
            orphan_path = destination_root / "huggingface" / "author" / "model" / "orphan.gguf"
            referenced_path.parent.mkdir(parents=True, exist_ok=True)
            referenced_path.write_bytes(b"referenced")
            orphan_path.write_bytes(b"orphan")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "destination_root": str(destination_root),
                            "local_path": str(referenced_path),
                        }
                    ],
                },
            )

            payload = self.post_json(
                f"{api_base}/api/downloads/delete-orphans",
                {"paths": [str(orphan_path.resolve()), str(referenced_path.resolve())]},
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["removed"], [str(orphan_path.resolve())])
            self.assertEqual(payload["skipped"], [str(referenced_path.resolve())])
            self.assertFalse(orphan_path.exists())
            self.assertTrue(referenced_path.exists())

    def test_download_cleanup_duplicates_api_keeps_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            completed_path = Path(tmpdir) / "downloads" / "model.gguf"
            completed_path.parent.mkdir(parents=True, exist_ok=True)
            completed_path.write_bytes(b"model")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "completed-a",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                        {
                            "id": "completed-b",
                            "status": "completed",
                            "repo_id": "author/model",
                            "artifact_name": "model.gguf",
                            "local_path": str(completed_path),
                        },
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/cleanup-duplicates", {})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kept"], ["completed-a"])
            self.assertEqual(payload["removed"], ["completed-b"])
            self.assertTrue(completed_path.is_file())

    def test_phase0_contracts_resyncs_runtime_profiles_when_store_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            runtime_dir = Path(tmpdir) / "runtime" / "llama-server" / "linux-x86_64-cpu"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            binary_path = runtime_dir / "llama-server"
            binary_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            binary_path.chmod(0o755)
            (runtime_dir / "llama-server.compat.env").write_text(
                "\n".join(
                    [
                        "LLAMA_BUNDLE_OS=linux",
                        "LLAMA_BUNDLE_ARCH=x86_64",
                        "LLAMA_BUNDLE_BACKEND=cpu",
                        "LLAMA_BUNDLE_LABEL=CPU",
                        "LLAMA_BUNDLE_SOURCE_REF=b8851",
                        "LLAMA_BUNDLE_BUILT_AT=2026-04-20T00:00:00+00:00",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            (manager.runtime_profiles_file).write_text(
                json.dumps({"schema_version": 1, "items": {"broken": True}}, indent=2),
                encoding="utf-8",
            )

            doctor = {
                "host_os": "linux",
                "host_arch": "x86_64",
                "host_backends": "cpu,cuda",
                "binary_ok": "yes",
                "binary": str(binary_path),
                "binary_source": "bundled",
                "binary_backend": "cpu",
                "binary_status": "compatible",
                "binary_label": "CPU",
                "binary_message": "validated bundled CPU binary",
                "binary_guidance": "",
                "binary_manifest": str(runtime_dir / "llama-server.compat.env"),
            }

            phase0 = manager.phase0_contracts(doctor)
            self.assertEqual(len(phase0["runtime_profiles"].get("items", [])), 1)
            self.assertEqual(phase0["runtime_profiles"]["items"][0]["id"], "linux-x86_64-cpu")

    def test_save_model_returns_full_persisted_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            model_path = Path(tmpdir) / "models" / "sample.gguf"
            mmproj_path = Path(tmpdir) / "models" / "sample-mmproj.gguf"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_text("", encoding="utf-8")
            mmproj_path.write_text("", encoding="utf-8")

            saved = manager.save_model(
                {
                    "alias": "sample",
                    "path": str(model_path),
                    "mmproj": str(mmproj_path),
                    "extra_args": "--no-warmup",
                    "context": "8192",
                }
            )

            self.assertEqual(saved["alias"], "sample")
            self.assertEqual(saved["mmproj"], str(mmproj_path.resolve()))
            self.assertEqual(saved["extra_args"], "--no-warmup")
            self.assertEqual(saved["exists"], "yes")
            self.assertIn("--mmproj", saved["extra"])
            self.assertIn("--no-warmup", saved["extra"])

            models = manager.read_models()
            self.assertEqual(models[0]["alias"], "sample")
            self.assertEqual(models[0]["mmproj"], str(mmproj_path.resolve()))

    def test_state_annotates_models_with_validation_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            model_path = Path(tmpdir) / "models" / "ready.gguf"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_text("", encoding="utf-8")

            manager.save_model({"alias": "ready", "path": str(model_path)})
            (Path(tmpdir) / "state" / "llama-server" / "validation-results.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            (Path(tmpdir) / "state" / "llama-server" / "validation-results.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "items": [
                            {
                                "alias": "ready",
                                "model_path": str(model_path.resolve()),
                                "status": "available",
                                "summary": "model file and runtime selection look consistent",
                                "guidance": "",
                                "checked_at": "2026-04-21T00:00:00+00:00",
                                "runtime": {"backend": "cpu", "status": "compatible"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            outputs = {
                "current": "alias: stopped\nmodel:\nconfigured_mode: single-client\nconfigured_parallel: 1\nactive_mode: stopped\nactive_parallel: stopped\n",
                "doctor": "host_os: linux\nhost_arch: x86_64\nhost_backends: cpu\nbinary_ok: yes\nbinary: /tmp/llama-server\nbinary_source: bundled\nbinary_backend: cpu\nbinary_status: compatible\nbinary_label: CPU\nbinary_message: validated bundled CPU binary\n",
                "mode": "configured_mode: single-client\nconfigured_parallel: 1\nactive_mode: stopped\nactive_parallel: stopped\n",
            }
            manager.run_cli = lambda command, *args: outputs[command]  # type: ignore[method-assign]

            state = manager.state()
            self.assertEqual(state["models"][0]["validation_status"], "available")
            self.assertEqual(
                state["models"][0]["validation_summary"],
                "model file and runtime selection look consistent",
            )

    def test_gateway_chat_completion_passes_generation_parameters_and_records_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "gateway-state.json"
            captured: dict[str, object] = {}

            def fake_route(
                prompt: str, model: str, max_tokens: int, temperature: float
            ) -> tuple[dict[str, object], dict[str, str]]:
                captured.update(
                    {
                        "prompt": prompt,
                        "model": model,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    }
                )
                return {
                    "text": "routed ok",
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                    "latency_ms": 7,
                }, {
                    "X-LMM-Route-Mode": "routed",
                    "X-LMM-GlyphOS-Target": "llamacpp",
                    "X-LMM-GlyphOS-Reason": "default_local",
                }

            gateway = self.load_gateway_module()
            with mock.patch.dict(os.environ, {"LMM_GATEWAY_STATE_FILE": str(state_path)}, clear=False):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway, model_id="fallback-model")
                    payload = {
                        "model": "requested-model",
                        "messages": [{"role": "user", "content": "hello gateway"}],
                        "max_tokens": 123,
                        "temperature": 0.25,
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json", "User-Agent": "phase0-test"},
                        method="POST",
                    )

                    with urllib.request.urlopen(req, timeout=5) as response:
                        body = json.loads(response.read().decode("utf-8"))

            self.assertEqual(captured["model"], "requested-model")
            self.assertEqual(captured["max_tokens"], 123)
            self.assertEqual(captured["temperature"], 0.25)
            self.assertIn("user: hello gateway", str(captured["prompt"]))
            self.assertEqual(body["choices"][0]["message"]["content"], "routed ok")
            self.assertEqual(body["lmm"]["glyphos_target"], "llamacpp")
            telemetry = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(telemetry["counters"]["success:True"], 1)
            self.assertEqual(telemetry["recent_requests"][0]["route_target"], "llamacpp")

    def test_gateway_context_payload_is_glyph_encoded_before_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "gateway-state.json"
            captured: dict[str, object] = {}

            def fake_route(
                prompt: str, model: str, max_tokens: int, temperature: float
            ) -> tuple[dict[str, object], dict[str, str]]:
                captured["prompt"] = prompt
                return {
                    "text": "encoded ok",
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                    "latency_ms": 9,
                }, {"X-LMM-Route-Mode": "routed"}

            context = {
                "items": [
                    {"path": "/repo/a.py", "content": "alpha beta gamma", "summary": "first file"},
                    {"path": "/repo/b.py", "content": "alpha beta gamma", "summary": "second file"},
                    {"path": "/repo/c.py", "content": "alpha beta gamma", "summary": "third file"},
                ]
            }
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(state_path),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    body = self.post_json(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {
                            "model": "context-model",
                            "messages": [{"role": "user", "content": "answer using the latest instruction"}],
                            "lmm_context": context,
                        },
                    )

            routed_prompt = str(captured["prompt"])
            self.assertIn("[Glyph Encoding v1]", routed_prompt)
            self.assertIn("[Conversation and latest user request]", routed_prompt)
            self.assertIn("answer using the latest instruction", routed_prompt)
            self.assertTrue(body["lmm"]["context_used"])
            self.assertTrue(body["lmm"]["glyph_encoding_used"])
            self.assertLess(body["lmm"]["encoding_ratio"], 1)
            telemetry = json.loads(state_path.read_text(encoding="utf-8"))
            recent = telemetry["recent_requests"][0]
            self.assertEqual(recent["mode"], "routed-full")
            self.assertTrue(recent["context_used"])
            self.assertTrue(recent["glyph_encoding_used"])
            self.assertGreater(recent["estimated_token_delta"], 0)

    def test_gateway_context_timeout_degrades_without_blocking_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "gateway-state.json"
            captured: dict[str, object] = {}

            def fake_route(
                prompt: str, model: str, max_tokens: int, temperature: float
            ) -> tuple[dict[str, object], dict[str, str]]:
                captured["prompt"] = prompt
                return {
                    "text": "timeout degraded ok",
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                    "latency_ms": 10,
                }, {"X-LMM-Route-Mode": "routed"}

            gateway = self.load_gateway_module()
            sleeper = f"{sys.executable} -c 'import time; time.sleep(1)'"
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(state_path),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                    "LMM_CONTEXT_MCP_COMMAND": sleeper,
                    "LMM_CONTEXT_MCP_TIMEOUT_MS": "10",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    body = self.post_json(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {
                            "model": "context-timeout-model",
                            "messages": [{"role": "user", "content": "continue despite context timeout"}],
                        },
                    )

            self.assertEqual(body["choices"][0]["message"]["content"], "timeout degraded ok")
            self.assertFalse(body["lmm"]["context_used"])
            telemetry = json.loads(state_path.read_text(encoding="utf-8"))
            recent = telemetry["recent_requests"][0]
            self.assertEqual(recent["context_status"], "timeout")
            self.assertEqual(recent["mode"], "routed-basic")
            self.assertIn("continue despite context timeout", str(captured["prompt"]))

    def test_gateway_context_command_timeout_kills_process_group(self) -> None:
        gateway = self.load_gateway_module()

        class TimeoutProc:
            pid = 4242
            returncode = -9

            def __init__(self) -> None:
                self.communicate_calls = 0

            def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]:
                self.communicate_calls += 1
                if self.communicate_calls == 1:
                    raise subprocess.TimeoutExpired(["ctx-bridge"], timeout or 0.01, output="", stderr="")
                return "", ""

            def kill(self) -> None:
                pass

        proc = TimeoutProc()
        with mock.patch.object(gateway.subprocess, "Popen", return_value=proc):
            with mock.patch.object(gateway.os, "killpg") as killpg:
                with self.assertRaises(subprocess.TimeoutExpired):
                    gateway.run_context_command(
                        ["ctx-bridge"],
                        input_text="{}",
                        timeout_seconds=0.01,
                        cwd=str(ROOT_DIR),
                    )

        killpg.assert_called_once_with(proc.pid, gateway.signal.SIGKILL)
        self.assertEqual(proc.communicate_calls, 2)

    def test_gateway_context_mcp_command_result_is_used(self) -> None:
        captured: dict[str, object] = {}

        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            captured["prompt"] = prompt
            return {
                "text": "mcp context ok",
                "target": "llamacpp",
                "reason_code": "default_local",
                "reason": "default - use local llama.cpp",
                "latency_ms": 12,
            }, {"X-LMM-Route-Mode": "routed"}

        completed = subprocess.CompletedProcess(
            args=["ctx-bridge"],
            returncode=0,
            stdout=json.dumps({"context": {"path": "/repo/context.md", "content": "retrieved from mcp"}}),
            stderr="",
        )
        gateway = self.load_gateway_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                    "LMM_CONTEXT_MCP_COMMAND": "ctx-bridge",
                    "LMM_CONTEXT_MCP_TIMEOUT_MS": "500",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "run_context_command", return_value=completed):
                    with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                        server = self.start_gateway_server(gateway_module=gateway)
                        body = self.post_json(
                            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                            {
                                "model": "context-command-model",
                                "messages": [{"role": "user", "content": "use command context"}],
                            },
                        )

        self.assertTrue(body["lmm"]["context_used"])
        self.assertEqual(body["lmm"]["context_status"], "retrieved")
        self.assertIn("retrieved from mcp", str(captured["prompt"]))

    def test_gateway_empty_context_command_output_is_not_used(self) -> None:
        captured: dict[str, object] = {}

        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            captured["prompt"] = prompt
            return {
                "text": "empty context ok",
                "target": "llamacpp",
                "reason_code": "default_local",
                "reason": "default - use local llama.cpp",
                "latency_ms": 12,
            }, {"X-LMM-Route-Mode": "routed"}

        gateway = self.load_gateway_module()
        for stdout in ("{}", '{"results":[]}', '{"snippets":[]}', '{"context":""}'):
            with self.subTest(stdout=stdout):
                completed = subprocess.CompletedProcess(args=["ctx-bridge"], returncode=0, stdout=stdout, stderr="")
                with tempfile.TemporaryDirectory() as tmpdir:
                    with mock.patch.dict(
                        os.environ,
                        {
                            "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                            "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                            "LMM_CONTEXT_MCP_COMMAND": "ctx-bridge",
                        },
                        clear=False,
                    ):
                        with mock.patch.object(gateway, "run_context_command", return_value=completed):
                            with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                                server = self.start_gateway_server(gateway_module=gateway)
                                body = self.post_json(
                                    f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                                    {
                                        "model": "empty-context-model",
                                        "messages": [{"role": "user", "content": "do not overclaim context"}],
                                    },
                                )

                    telemetry = json.loads((Path(tmpdir) / "gateway-state.json").read_text(encoding="utf-8"))

                self.assertFalse(body["lmm"]["context_used"])
                self.assertEqual(body["lmm"]["context_status"], "empty")
                self.assertEqual(telemetry["recent_requests"][0]["mode"], "routed-basic")
                self.assertNotIn("[Retrieved Context]", str(captured["prompt"]))

    def test_context_mcp_bridge_speaks_stdio_protocol(self) -> None:
        bridge = self.load_context_bridge_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            mcp_root = tmp / "context-mode-mcp"
            (mcp_root / "dist").mkdir(parents=True)
            (mcp_root / "dist" / "index.js").write_text("// fake entrypoint\n", encoding="utf-8")
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fake_node = fake_bin / "node"
            fake_node.write_text(
                """#!/usr/bin/env python3
import json
import sys

def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            sys.exit(0)
        line = line.decode().strip()
        if not line:
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    raw = sys.stdin.buffer.read(int(headers.get("content-length", "0")))
    return json.loads(raw)

def send(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\\r\\n\\r\\n".encode() + raw)
    sys.stdout.buffer.flush()

while True:
    message = read_message()
    method = message.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {}}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": message.get("id"), "result": {"structuredContent": {"context": {"items": [{"title": "Doc", "snippet": "bridge context"}]}}}})
        break
""",
                encoding="utf-8",
            )
            fake_node.chmod(0o755)
            stdin = io.StringIO(json.dumps({"query": "find bridge context", "limit": 3}))
            stdout = io.StringIO()
            with mock.patch.object(bridge, "MCP_ROOT", mcp_root):
                with mock.patch.dict(os.environ, {"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}, clear=False):
                    with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", stdout):
                        status = bridge.main()

        self.assertEqual(status, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["context"]["items"][0]["snippet"], "bridge context")

    def test_gateway_telemetry_redacts_raw_request_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "gateway-state.json"

            def fake_route(
                prompt: str, model: str, max_tokens: int, temperature: float
            ) -> tuple[dict[str, object], dict[str, str]]:
                return {
                    "text": "redacted ok",
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                    "latency_ms": 12,
                }, {"X-LMM-Route-Mode": "routed"}

            gateway = self.load_gateway_module()
            with mock.patch.dict(os.environ, {"LMM_GATEWAY_STATE_FILE": str(state_path)}, clear=False):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    self.post_json(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {
                            "model": "privacy-model",
                            "messages": [{"role": "user", "content": "SECRET_TOKEN_SHOULD_NOT_PERSIST"}],
                            "metadata": {"workspace": "/private/workspace", "session": "secret-session"},
                        },
                    )

            telemetry_text = state_path.read_text(encoding="utf-8")
            telemetry = json.loads(telemetry_text)
            request = telemetry["recent_requests"][0]["request"]
            self.assertNotIn("raw_messages", request)
            self.assertNotIn("SECRET_TOKEN_SHOULD_NOT_PERSIST", telemetry_text)
            self.assertNotIn("/private/workspace", telemetry_text)
            self.assertNotIn("secret-session", telemetry_text)
            self.assertEqual(request["messages"]["count"], 1)
            self.assertEqual(request["messages"]["roles"]["user"], 1)
            self.assertNotIn("content_hash", json.dumps(request))

    def test_gateway_context_command_stderr_is_sanitized_in_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "gateway-state.json"

            def fake_route(
                prompt: str, model: str, max_tokens: int, temperature: float
            ) -> tuple[dict[str, object], dict[str, str]]:
                return {
                    "text": "sanitized context failure ok",
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                    "latency_ms": 12,
                }, {"X-LMM-Route-Mode": "routed"}

            failed = subprocess.CompletedProcess(
                args=["ctx-bridge"],
                returncode=1,
                stdout="",
                stderr="SECRET_CONTEXT_COMMAND_STDERR",
            )
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(state_path),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                    "LMM_CONTEXT_MCP_COMMAND": "ctx-bridge",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "run_context_command", return_value=failed):
                    with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                        server = self.start_gateway_server(gateway_module=gateway)
                        self.post_json(
                            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                            {
                                "model": "privacy-model",
                                "messages": [{"role": "user", "content": "hello"}],
                            },
                        )

            telemetry_text = state_path.read_text(encoding="utf-8")
            telemetry = json.loads(telemetry_text)
            recent = telemetry["recent_requests"][0]
            self.assertEqual(recent["context_error"], "context_command_failed")
            self.assertNotIn("SECRET_CONTEXT_COMMAND_STDERR", telemetry_text)

    def test_gateway_glyph_encoding_failure_uses_raw_context_fallback(self) -> None:
        captured: dict[str, object] = {}

        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            captured["prompt"] = prompt
            return {
                "text": "raw fallback ok",
                "target": "llamacpp",
                "reason_code": "default_local",
                "reason": "default - use local llama.cpp",
                "latency_ms": 11,
            }, {"X-LMM-Route-Mode": "routed"}

        gateway = self.load_gateway_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                    "LMM_GLYPH_ENCODING_FORCE_ERROR": "1",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    body = self.post_json(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {
                            "model": "raw-fallback-model",
                            "messages": [{"role": "user", "content": "use raw context"}],
                            "lmm_context": {"path": "/repo/a.py", "content": "important context"},
                        },
                    )

        self.assertTrue(body["lmm"]["context_used"])
        self.assertFalse(body["lmm"]["glyph_encoding_used"])
        self.assertEqual(body["lmm"]["glyph_encoding_status"], "error_raw_fallback")
        self.assertIn("[Retrieved Context]", str(captured["prompt"]))
        self.assertNotIn("[Glyph Encoding v1]", str(captured["prompt"]))

    def test_gateway_chat_completion_does_not_fail_when_telemetry_write_fails(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            return {
                "text": "routed despite telemetry",
                "target": "llamacpp",
                "reason_code": "default_local",
                "reason": "default - use local llama.cpp",
                "latency_ms": 8,
            }, {"X-LMM-Route-Mode": "routed"}

        gateway = self.load_gateway_module()
        with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
            with mock.patch.object(gateway, "record_gateway_request", side_effect=OSError("telemetry unwritable")):
                server = self.start_gateway_server(gateway_module=gateway)
                payload = {
                    "model": "telemetry-model",
                    "messages": [{"role": "user", "content": "hello"}],
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=5) as response:
                    body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(body["choices"][0]["message"]["content"], "routed despite telemetry")
        self.assertEqual(body["lmm"]["glyphos_target"], "llamacpp")

    def test_gateway_chat_completion_supports_openai_sse_streaming(self) -> None:
        captured: dict[str, object] = {}

        def fake_stream_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str], object]:
            captured.update(
                {
                    "prompt": prompt,
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
            )

            def chunks() -> object:
                yield "streamed "
                yield "ok"

            return (
                {
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                },
                {"X-LMM-Route-Mode": "routed"},
                chunks(),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ, {"LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json")}, clear=False
            ):
                with mock.patch.object(gateway, "route_prompt_stream", side_effect=fake_stream_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    payload = {
                        "model": "stream-model",
                        "messages": [{"role": "user", "content": "stream please"}],
                        "stream": True,
                        "max_tokens": 42,
                        "temperature": 0.1,
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )

                    with urllib.request.urlopen(req, timeout=5) as response:
                        content_type = response.headers.get("Content-Type", "")
                        raw = response.read().decode("utf-8")

        self.assertIn("text/event-stream", content_type)
        self.assertIn("chat.completion.chunk", raw)
        self.assertIn('"content": "streamed "', raw)
        self.assertIn('"content": "ok"', raw)
        self.assertIn("data: [DONE]", raw)
        self.assertEqual(captured["model"], "stream-model")
        self.assertEqual(captured["max_tokens"], 42)
        self.assertEqual(captured["temperature"], 0.1)

    def test_gateway_streaming_sends_headers_before_first_content_chunk(self) -> None:
        gateway = self.load_gateway_module()
        events: list[str] = []

        class RecordingWriter:
            def write(self, data: bytes) -> int:
                events.append(data.decode("utf-8"))
                return len(data)

            def flush(self) -> None:
                events.append("flush")

        class FakeHandler:
            def __init__(self) -> None:
                self.wfile = RecordingWriter()

            def send_response(self, status: int) -> None:
                events.append(f"status:{status}")

            def send_header(self, key: str, value: str) -> None:
                events.append(f"header:{key}")

            def end_headers(self) -> None:
                events.append("end_headers")

        def delayed_chunks() -> object:
            events.append("first_content_requested")
            yield "late content"

        text, success, error_message, _latency_ms = gateway.stream_completion(
            FakeHandler(),
            started=time.time(),
            model="stream-order-model",
            chunks=delayed_chunks(),
            headers={},
        )

        role_index = next(index for index, item in enumerate(events) if '"role": "assistant"' in item)
        first_content_index = events.index("first_content_requested")
        self.assertLess(role_index, first_content_index)
        self.assertEqual(text, "late content")
        self.assertTrue(success)
        self.assertEqual(error_message, "")

    def test_gateway_streaming_sends_keepalive_while_backend_is_quiet(self) -> None:
        gateway = self.load_gateway_module()
        events: list[str] = []

        class RecordingWriter:
            def write(self, data: bytes) -> int:
                events.append(data.decode("utf-8"))
                return len(data)

            def flush(self) -> None:
                events.append("flush")

        class FakeHandler:
            def __init__(self) -> None:
                self.wfile = RecordingWriter()

            def send_response(self, status: int) -> None:
                events.append(f"status:{status}")

            def send_header(self, key: str, value: str) -> None:
                events.append(f"header:{key}")

            def end_headers(self) -> None:
                events.append("end_headers")

        def delayed_chunks() -> object:
            time.sleep(0.04)
            yield "eventual content"

        text, success, error_message, _latency_ms = gateway.stream_completion(
            FakeHandler(),
            started=time.time(),
            model="heartbeat-model",
            chunks=delayed_chunks(),
            headers={},
            heartbeat_seconds=0.01,
        )

        self.assertTrue(any(item.startswith(": lmm-keepalive") for item in events))
        self.assertEqual(text, "eventual content")
        self.assertTrue(success)
        self.assertEqual(error_message, "")

    def test_gateway_streaming_uses_same_context_enrichment_path(self) -> None:
        captured: dict[str, object] = {}

        def fake_stream_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str], object]:
            captured["prompt"] = prompt

            def chunks() -> object:
                yield "context stream"

            return (
                {
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default - use local llama.cpp",
                },
                {"X-LMM-Route-Mode": "routed"},
                chunks(),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                    "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE": "1",
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt_stream", side_effect=fake_stream_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(
                            {
                                "model": "stream-context-model",
                                "messages": [{"role": "user", "content": "stream with context"}],
                                "stream": True,
                                "lmm_context": {
                                    "items": [
                                        {"path": "/repo/a.py", "content": "stream context alpha"},
                                        {"path": "/repo/b.py", "content": "stream context beta"},
                                    ]
                                },
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        raw = response.read().decode("utf-8")

            telemetry = json.loads((Path(tmpdir) / "gateway-state.json").read_text(encoding="utf-8"))

        self.assertIn("data: [DONE]", raw)
        self.assertIn("[Glyph Encoding v1]", str(captured["prompt"]))
        self.assertEqual(telemetry["recent_requests"][0]["mode"], "routed-full")
        self.assertTrue(telemetry["recent_requests"][0]["context_used"])

    def test_gateway_streaming_client_disconnect_is_recorded_without_raising(self) -> None:
        gateway = self.load_gateway_module()

        class DisconnectingWriter:
            def write(self, data: bytes) -> int:
                raise BrokenPipeError("client went away")

            def flush(self) -> None:
                return None

        class FakeHandler:
            def __init__(self) -> None:
                self.wfile = DisconnectingWriter()

            def send_response(self, status: int) -> None:
                self.status = status

            def send_header(self, key: str, value: str) -> None:
                return None

            def end_headers(self) -> None:
                return None

        text, success, error_message, latency_ms = gateway.stream_completion(
            FakeHandler(),
            started=time.time(),
            model="disconnect-model",
            chunks=iter(["unwritten"]),
            headers={},
        )

        self.assertEqual(text, "")
        self.assertFalse(success)
        self.assertIn("client disconnected", error_message)
        self.assertGreaterEqual(latency_ms, 0)

    def test_gateway_chat_completion_returns_503_when_backend_route_fails(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            raise RuntimeError("llama.cpp backend is offline")

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ, {"LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json")}, clear=False
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    payload = {
                        "model": "offline-model",
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )

                    with self.assertRaises(error.HTTPError) as raised:
                        urllib.request.urlopen(req, timeout=5)
                    body = json.loads(raised.exception.read().decode("utf-8"))

        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(body["error"]["type"], "lmm_gateway_error")
        self.assertIn("offline", body["error"]["message"])
        self.assertFalse(body["lmm"]["success"])

    def test_gateway_chat_completion_returns_400_for_invalid_request_payload(self) -> None:
        gateway = self.load_gateway_module()
        server = self.start_gateway_server(gateway_module=gateway)
        payload = {
            "model": "invalid-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": "not-a-number",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=5)
        body = json.loads(raised.exception.read().decode("utf-8"))

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(body["error"]["type"], "invalid_request_error")
        self.assertIn("max_tokens", body["error"]["message"])

    def test_gateway_chat_completion_returns_400_for_non_integer_max_tokens(self) -> None:
        gateway = self.load_gateway_module()
        server = self.start_gateway_server(gateway_module=gateway)
        for value in (True, 1.9):
            with self.subTest(max_tokens=value):
                payload = {
                    "model": "invalid-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": value,
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with self.assertRaises(error.HTTPError) as raised:
                    urllib.request.urlopen(req, timeout=5)
                body = json.loads(raised.exception.read().decode("utf-8"))

                self.assertEqual(raised.exception.code, 400)
                self.assertEqual(body["error"]["type"], "invalid_request_error")
                self.assertIn("max_tokens", body["error"]["message"])

    def test_gateway_chat_completion_returns_400_for_non_finite_temperature(self) -> None:
        gateway = self.load_gateway_module()
        server = self.start_gateway_server(gateway_module=gateway)
        payload = {
            "model": "invalid-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": "NaN",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=5)
        body = json.loads(raised.exception.read().decode("utf-8"))

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(body["error"]["type"], "invalid_request_error")
        self.assertIn("temperature", body["error"]["message"])

    def test_glyphos_route_stream_complex_action_falls_back_to_local_llamacpp(self) -> None:
        integration_root = str(ROOT_DIR / "integrations" / "public-glyphos-ai-compute")
        original_path = list(sys.path)
        try:
            if integration_root not in sys.path:
                sys.path.insert(0, integration_root)
            from glyphos_ai.ai_compute.router import AdaptiveRouter  # type: ignore

            class Packet:
                psi_coherence = 0.2
                action = "ANALYZE"

            class FakeLlamaCpp:
                opens_stream_before_return = True

                def stream_generate(self, prompt: str, **kwargs: object) -> object:
                    yield "local stream"

            with tempfile.TemporaryDirectory() as tmpdir:
                telemetry_path = str(Path(tmpdir) / "glyphos-routing.json")
                with mock.patch.dict(os.environ, {"LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE": telemetry_path}, clear=False):
                    router = AdaptiveRouter(llamacpp_client=FakeLlamaCpp())
                    routed, chunks = router.route_stream(Packet(), prompt="complex prompt")

                    self.assertEqual(routed["target"], "llamacpp")
                    self.assertEqual(routed["reason_code"], "complex_action_local_stream")
                    self.assertEqual(list(chunks), ["local stream"])
        finally:
            sys.path[:] = original_path

    def test_glyphos_route_stream_generator_failure_happens_before_return(self) -> None:
        integration_root = str(ROOT_DIR / "integrations" / "public-glyphos-ai-compute")
        original_path = list(sys.path)
        try:
            if integration_root not in sys.path:
                sys.path.insert(0, integration_root)
            from glyphos_ai.ai_compute.router import AdaptiveRouter  # type: ignore

            class Packet:
                psi_coherence = 0.9
                action = "QUERY"

            class FailingLlamaCpp:
                def stream_generate(self, prompt: str, **kwargs: object) -> object:
                    raise RuntimeError("open failed")
                    yield "unreachable"

            with tempfile.TemporaryDirectory() as tmpdir:
                telemetry_path = str(Path(tmpdir) / "glyphos-routing.json")
                with mock.patch.dict(os.environ, {"LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE": telemetry_path}, clear=False):
                    router = AdaptiveRouter(llamacpp_client=FailingLlamaCpp())
                    with self.assertRaises(RuntimeError):
                        router.route_stream(Packet(), prompt="fail before sse")
        finally:
            sys.path[:] = original_path

    def test_external_glyphos_clients_raise_when_not_configured(self) -> None:
        integration_root = str(ROOT_DIR / "integrations" / "public-glyphos-ai-compute")
        original_path = list(sys.path)
        try:
            if integration_root not in sys.path:
                sys.path.insert(0, integration_root)
            from glyphos_ai.ai_compute.api_client import AnthropicClient, OpenAIClient, XAIClient  # type: ignore

            empty_keys = {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "XAI_API_KEY": ""}
            with mock.patch.dict(os.environ, empty_keys, clear=False):
                for client in (OpenAIClient(api_key=""), AnthropicClient(api_key=""), XAIClient(api_key="")):
                    with self.subTest(client=client.__class__.__name__):
                        with self.assertRaises(RuntimeError):
                            client.generate("hello")
        finally:
            sys.path[:] = original_path

    def test_glyphos_external_route_failures_are_recorded_as_errors(self) -> None:
        integration_root = str(ROOT_DIR / "integrations" / "public-glyphos-ai-compute")
        original_path = list(sys.path)
        try:
            if integration_root not in sys.path:
                sys.path.insert(0, integration_root)
            from glyphos_ai.ai_compute.router import AdaptiveRouter  # type: ignore

            class Packet:
                psi_coherence = 0.2
                action = "ANALYZE"

            class FailingOpenAI:
                def generate(self, prompt: str, **kwargs: object) -> str:
                    raise RuntimeError("external unavailable")

            with tempfile.TemporaryDirectory() as tmpdir:
                telemetry_path = str(Path(tmpdir) / "glyphos-routing.json")
                with mock.patch.dict(os.environ, {"LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE": telemetry_path}, clear=False):
                    router = AdaptiveRouter(openai_client=FailingOpenAI())
                    result = router.route(Packet(), prompt="complex prompt")

                    self.assertEqual(result.target.value, "openai")
                    self.assertEqual(result.routing_reason_code, "fallback_complex_action_openai.error")
                    self.assertIn("external unavailable", result.response)
                    telemetry = router.routing_telemetry()
                    self.assertEqual(telemetry["fallback_reason_counts"]["fallback_complex_action_openai.error"], 1)
        finally:
            sys.path[:] = original_path

    def test_gateway_backend_failure_still_returns_503_when_telemetry_write_fails(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            raise RuntimeError("llama.cpp backend is offline")

        gateway = self.load_gateway_module()
        with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
            with mock.patch.object(gateway, "record_gateway_request", side_effect=OSError("telemetry unwritable")):
                server = self.start_gateway_server(gateway_module=gateway)
                payload = {
                    "model": "offline-model",
                    "messages": [{"role": "user", "content": "hello"}],
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with self.assertRaises(error.HTTPError) as raised:
                    urllib.request.urlopen(req, timeout=5)
                body = json.loads(raised.exception.read().decode("utf-8"))

        self.assertEqual(raised.exception.code, 503)
        self.assertEqual(body["error"]["type"], "lmm_gateway_error")
        self.assertIn("offline", body["error"]["message"])
        self.assertFalse(body["lmm"]["success"])

    def test_gateway_streaming_request_returns_503_before_sse_when_backend_route_fails(self) -> None:
        def fake_stream_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str], object]:
            raise RuntimeError("llama.cpp backend is offline")

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ, {"LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json")}, clear=False
            ):
                with mock.patch.object(gateway, "route_prompt_stream", side_effect=fake_stream_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    payload = {
                        "model": "offline-model",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )

                    with self.assertRaises(error.HTTPError) as raised:
                        urllib.request.urlopen(req, timeout=5)
                    raw = raised.exception.read().decode("utf-8")
                    body = json.loads(raw)

        self.assertEqual(raised.exception.code, 503)
        self.assertNotIn("text/event-stream", raised.exception.headers.get("Content-Type", ""))
        self.assertEqual(body["error"]["type"], "lmm_gateway_error")

    def test_gateway_models_fallback_keeps_openai_model_shape_when_backend_is_unavailable(self) -> None:
        server = self.start_gateway_server(model_id="fallback-model", backend_base_url="http://127.0.0.1:9/v1")

        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/v1/models", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(body["object"], "list")
        self.assertEqual(body["data"][0]["id"], "fallback-model")
        self.assertIn("warning", body)

    def test_gateway_logs_endpoint_uses_cli_gateway_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            calls: list[tuple[str, ...]] = []

            def fake_run_cli(command: str, *args: str) -> str:
                calls.append((command, *args))
                return "gateway line\n"

            manager.run_cli = fake_run_cli  # type: ignore[method-assign]
            server = self.start_app_server(manager)

            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/api/gateway/logs?lines=12", timeout=5
            ) as response:
                body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(calls, [("gateway", "logs", "12")])
        self.assertEqual(body["lines"], 12)
        self.assertEqual(body["content"], "gateway line\n")

    def test_health_checker_checks_backend_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_server = self.start_backend_status_server(payload={"object": "list", "data": []})
            health_module = self.load_script_module("llama_model_manager_health", LMM_HEALTH_PATH)
            config_module = self.load_script_module("llama_model_manager_config_health", LMM_CONFIG_PATH)
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json"),
                },
                clear=False,
            ):
                config = config_module.load_lmm_config_from_env()
            checker = health_module.HealthChecker(
                backend_url=f"http://127.0.0.1:{backend_server.server_port}/v1",
                config=config,
            )

            checks = checker.check_all()

        self.assertEqual(checks["backend"].status, "healthy")
        self.assertEqual(checks["storage"].status, "healthy")
        self.assertIn(checks["context"].status, {"healthy", "degraded"})

    def test_health_checker_checks_backend_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            health_module = self.load_script_module("llama_model_manager_health_down", LMM_HEALTH_PATH)
            config_module = self.load_script_module("llama_model_manager_config_health_down", LMM_CONFIG_PATH)
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json"),
                },
                clear=False,
            ):
                config = config_module.load_lmm_config_from_env()
            checker = health_module.HealthChecker(backend_url="http://127.0.0.1:9/v1", config=config)

            checks = checker.check_all()

        self.assertEqual(checks["backend"].status, "unhealthy")
        self.assertEqual(checks["storage"].status, "healthy")

    def test_health_checker_readyz_requires_all_healthy(self) -> None:
        health_module = self.load_script_module("llama_model_manager_health_ready", LMM_HEALTH_PATH)
        config_module = self.load_script_module("llama_model_manager_config_health_ready", LMM_CONFIG_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ, {"LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json")}, clear=False
            ):
                config = config_module.load_lmm_config_from_env()
            checker = health_module.HealthChecker(backend_url="http://127.0.0.1:9/v1", config=config)
            with mock.patch.object(
                health_module.HealthChecker,
                "_check_context",
                return_value=health_module.ComponentHealth("context", "degraded", "mocked context unhealthy"),
            ):
                with mock.patch.object(
                    health_module.HealthChecker,
                    "_check_backend",
                    return_value=health_module.ComponentHealth("backend", "healthy", "mocked backend healthy"),
                ):
                    with mock.patch.object(
                        health_module.HealthChecker,
                        "_check_storage",
                        return_value=health_module.ComponentHealth("storage", "healthy", "mocked storage healthy"),
                    ):
                        self.assertFalse(checker.is_ready())
                        self.assertTrue(checker.is_healthy())

    def test_gateway_readiness_endpoint_returns_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_server = self.start_backend_status_server()
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json"),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                server = self.start_gateway_server(
                    gateway_module=gateway,
                    backend_base_url=f"http://127.0.0.1:{backend_server.server_port}/v1",
                )
                status, body = self.get_json_raw(f"http://127.0.0.1:{server.server_port}/readyz")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["status"], "ready")

    def test_gateway_readiness_endpoint_returns_not_ready(self) -> None:
        gateway = self.load_gateway_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json"),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                server = self.start_gateway_server(gateway_module=gateway, backend_base_url="http://127.0.0.1:9/v1")
                status, body = self.get_json_raw(f"http://127.0.0.1:{server.server_port}/readyz")

        self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(body["status"], "not_ready")
        self.assertIn("components", body)

    def test_gateway_emits_run_record_on_success(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            return {
                "text": "response text",
                "target": "llamacpp",
                "reason_code": "default_local",
                "reason": "default route",
                "latency_ms": 9,
            }, {"X-LMM-Route-Mode": "routed"}

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            run_records = Path(tmpdir) / "run-records.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(run_records),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    _ = self.post_json(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {"model": "run-record-model", "messages": [{"role": "user", "content": "hello"}]},
                    )

            state = json.loads(run_records.read_text(encoding="utf-8"))
            records = state.get("records", [])
            self.assertEqual(records[0]["status"], "completed")
            self.assertEqual(records[0]["exit_result"], "success")
            self.assertEqual(records[0]["provider"], "llamacpp")
            self.assertIsInstance(records[0]["duration_ms"], int)

    def test_gateway_emits_run_record_on_failure(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str]]:
            raise RuntimeError("provider unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            run_records = Path(tmpdir) / "run-records.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(run_records),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt", side_effect=fake_route):
                    server = self.start_gateway_server(gateway_module=gateway)
                    status, body = self.post_json_raw(
                        f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        {"model": "run-record-model", "messages": [{"role": "user", "content": "hello"}]},
                    )
                    self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
                    self.assertEqual(body["error"]["type"], "lmm_gateway_error")

            state = json.loads(run_records.read_text(encoding="utf-8"))
            records = state.get("records", [])
            self.assertEqual(records[0]["status"], "failed")
            self.assertEqual(records[0]["exit_result"], "provider_error")

    def test_gateway_emits_run_record_on_client_disconnect(self) -> None:
        def fake_route(
            prompt: str, model: str, max_tokens: int, temperature: float
        ) -> tuple[dict[str, object], dict[str, str], object]:
            return (
                {
                    "target": "llamacpp",
                    "reason_code": "default_local",
                    "reason": "default route",
                    "latency_ms": 7,
                },
                {"X-LMM-Route-Mode": "routed-basic"},
                iter(["partial-token"]),
            )

        def fake_stream_completion(
            handler: Any,
            *,
            started: float,
            model: str,
            chunks: Iterator[str],
            headers: dict[str, str],
        ) -> tuple[str, bool, str, int]:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "close")
            for key, value in headers.items():
                handler.send_header(key, value)
            handler.end_headers()
            handler.wfile.write(b"data: partial\\n\\n")
            handler.wfile.flush()
            return "partial-token", False, "client disconnected", 12

        with tempfile.TemporaryDirectory() as tmpdir:
            gateway = self.load_gateway_module()
            run_records = Path(tmpdir) / "run-records.json"
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(run_records),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                with mock.patch.object(gateway, "route_prompt_stream", side_effect=fake_route):
                    with mock.patch.object(gateway, "stream_completion", side_effect=fake_stream_completion):
                        server = self.start_gateway_server(gateway_module=gateway)
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                            data=json.dumps(
                                {
                                    "model": "run-record-model",
                                    "stream": True,
                                    "messages": [{"role": "user", "content": "hello"}],
                                }
                            ).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request, timeout=10) as response:
                            self.assertEqual(response.status, HTTPStatus.OK)
                            response.read()

            state = json.loads(run_records.read_text(encoding="utf-8"))
            records = state.get("records", [])
            self.assertEqual(records[0]["status"], "cancelled")
            self.assertEqual(records[0]["exit_result"], "user_cancelled")

    def test_gateway_runtime_report_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_server = self.start_backend_status_server()
            gateway = self.load_gateway_module()
            with mock.patch.dict(
                os.environ,
                {
                    "LMM_RUN_RECORDS_FILE": str(Path(tmpdir) / "run-records.json"),
                    "LMM_GATEWAY_STATE_FILE": str(Path(tmpdir) / "gateway-state.json"),
                },
                clear=False,
            ):
                server = self.start_gateway_server(
                    gateway_module=gateway,
                    backend_base_url=f"http://127.0.0.1:{backend_server.server_port}/v1",
                )
                status, body = self.get_json_raw(f"http://127.0.0.1:{server.server_port}/-/runtime/report")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsInstance(body["uptime_seconds"], (int, float))
        self.assertGreaterEqual(body["uptime_seconds"], 0)
        self.assertIn("components", body)
        self.assertIn("backend", body["components"])
        self.assertIn("storage", body["components"])
        self.assertIn("context", body["components"])

    def test_glyphos_shared_telemetry_preserves_concurrent_process_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry_path = Path(tmpdir) / "glyphos-routing.json"
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT_DIR / "integrations" / "public-glyphos-ai-compute"),
                "LLAMA_MODEL_GLYPHOS_TELEMETRY_FILE": str(telemetry_path),
            }
            code = (
                "from glyphos_ai.ai_compute.router import _record_global_attempt\n"
                "import time\n"
                "_record_global_attempt({'target': 'llamacpp', 'reason_code': 'default_local', "
                "'success': True, 'latency_ms': 1, 'error': '', 'time': time.time()})\n"
            )
            processes = [
                subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(8)
            ]
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(
                    process.returncode,
                    0,
                    stderr.decode("utf-8", errors="replace") + stdout.decode("utf-8", errors="replace"),
                )

            telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))

        self.assertEqual(telemetry["attempts_by_target"]["llamacpp"], 8)
        self.assertEqual(telemetry["fallback_reason_counts"]["default_local"], 8)
        self.assertEqual(len(telemetry["recent_attempts"]), 8)

    def test_defaults_preserve_shell_quoted_extra_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            defaults_file = Path(tmpdir) / "config" / "llama-server" / "defaults.env"
            defaults_file.write_text(
                "\n".join(
                    [
                        "LLAMA_SERVER_BIN=/custom/bin/llama-server",
                        "LLAMA_SERVER_WAIT_SECONDS=45",
                        "LLAMA_SERVER_EXTRA_ARGS='--jinja --system-prompt \"hello world\"'",
                        "LLAMA_MODEL_HARNESS_MODE=direct",
                        "LLAMA_MODEL_GATEWAY_HOST=127.0.0.2",
                        "LLAMA_MODEL_GATEWAY_PORT=4510",
                        "LLAMA_MODEL_GATEWAY_LOG=$HOME/models/custom-gateway.log",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            defaults = manager.defaults()

            self.assertEqual(defaults["LLAMA_SERVER_BIN"], "/custom/bin/llama-server")
            self.assertEqual(defaults["LLAMA_SERVER_WAIT_SECONDS"], "45")
            self.assertEqual(defaults["LLAMA_SERVER_EXTRA_ARGS"], '--jinja --system-prompt "hello world"')
            self.assertEqual(defaults["LLAMA_MODEL_HARNESS_MODE"], "direct")
            self.assertEqual(defaults["LLAMA_MODEL_GATEWAY_HOST"], "127.0.0.2")
            self.assertEqual(defaults["LLAMA_MODEL_GATEWAY_PORT"], "4510")
            self.assertEqual(defaults["LLAMA_MODEL_GATEWAY_LOG"], "$HOME/models/custom-gateway.log")
            self.assertEqual(defaults["LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE"], "")

    def test_context_glyphos_pipeline_reports_toggle_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.defaults_file.write_text(
                "\n".join(
                    [
                        "LLAMA_SERVER_HOST=127.0.0.1",
                        "LLAMA_SERVER_PORT=8081",
                        "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE=1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manager.glyphos_config_file.parent.mkdir(parents=True, exist_ok=True)
            manager.glyphos_config_file.write_text("runtime:\n  provider: llamacpp\n", encoding="utf-8")

            defaults = manager.defaults()
            context_mode_mcp = manager.context_mode_mcp_state()
            pipeline = manager.context_glyphos_pipeline_state(
                defaults=defaults,
                current={"alias": "qwen", "model": "/models/qwen.gguf"},
                context_mode_mcp=context_mode_mcp,
                glyphos_telemetry={"available": True, "routing": {}},
            )

            self.assertTrue(pipeline["enabled"])
            self.assertTrue(pipeline["ready"])
            self.assertEqual(pipeline["status"], "ready")
            self.assertEqual(pipeline["blockers"], [])

    def test_context_glyphos_pipeline_requires_glyphos_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.defaults_file.write_text(
                "\n".join(
                    [
                        "LLAMA_SERVER_HOST=127.0.0.1",
                        "LLAMA_SERVER_PORT=8081",
                        "LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE=1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manager.glyphos_config_file.parent.mkdir(parents=True, exist_ok=True)
            manager.glyphos_config_file.write_text("runtime:\n  provider: llamacpp\n", encoding="utf-8")

            pipeline = manager.context_glyphos_pipeline_state(
                defaults=manager.defaults(),
                current={"alias": "qwen", "model": "/models/qwen.gguf"},
                context_mode_mcp=manager.context_mode_mcp_state(),
                glyphos_telemetry={"available": False, "routing": {}},
            )

            self.assertFalse(pipeline["ready"])
            self.assertEqual(pipeline["status"], "activation_pending")
            self.assertIn("GlyphOS integration unavailable", pipeline["blockers"])

    def test_context_glyphos_activation_persists_toggle_and_syncs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)

            def fake_run_cli(command: str, *args: str) -> str:
                if command == "sync-glyphos":
                    manager.glyphos_config_file.parent.mkdir(parents=True, exist_ok=True)
                    manager.glyphos_config_file.write_text("runtime:\n  provider: llamacpp\n", encoding="utf-8")
                    return "status: synced\n"
                if command == "current":
                    return "alias: qwen\nmodel: /models/qwen.gguf\n"
                raise AssertionError(f"unexpected command: {command}")

            manager.run_cli = fake_run_cli  # type: ignore[method-assign]

            result = manager.activate_context_glyphos_pipeline()
            defaults = manager.defaults()

            self.assertTrue(result["activated"])
            self.assertEqual(defaults["LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE"], "1")
            self.assertEqual(defaults["LLAMA_MODEL_SYNC_GLYPHOS"], "1")
            self.assertEqual(result["sync_result"]["status"], "synced")
            self.assertTrue(result["context_glyphos_pipeline"]["ready"])

    def test_json_store_write_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            target = manager.download_jobs_file
            payload = {"schema_version": 1, "updated_at": "2026-04-21T00:00:00+00:00", "items": []}

            manager.write_json_store(target, payload)
            self.assertTrue(target.is_file())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)

            leftovers = sorted(Path(tmpdir).glob("state/llama-server/.llama-json.*"))
            self.assertEqual(leftovers, [])

    def test_parse_extra_cli_args_matches_shell_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            parsed = manager.parse_extra_cli_args('--no-warmup --system-prompt "hello world"')
            self.assertEqual(parsed, ["--no-warmup", "--system-prompt", "hello world"])

    def test_compatibility_estimate_reports_good_fit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            estimate = manager.compatibility_estimate(
                size_bytes=4 * 1024**3,
                host_capability={
                    "host_backends": ["cpu", "cuda"],
                    "preferred_backend": "cuda",
                    "memory_bytes": 32 * 1024**3,
                    "memory_human": "32.0 GiB",
                },
                context="32768",
                device="",
            )
            self.assertEqual(estimate["compatibility_status"], "good-fit")
            self.assertIn("32.0 GiB", estimate["compatibility_summary"])

    def test_compatibility_estimate_reports_requested_backend_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            estimate = manager.compatibility_estimate(
                size_bytes=2 * 1024**3,
                host_capability={
                    "host_backends": ["cpu"],
                    "preferred_backend": "cpu",
                    "memory_bytes": 16 * 1024**3,
                    "memory_human": "16.0 GiB",
                },
                device="cuda0",
            )
            self.assertEqual(estimate["compatibility_status"], "likely-incompatible")
            self.assertIn("requests cuda", estimate["compatibility_summary"])

    def test_normalize_remote_model_entry_extracts_gguf_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            raw = {
                "id": "bartowski/Llama-3.2-1B-Instruct-GGUF",
                "author": "bartowski",
                "downloads": 1234,
                "likes": 98,
                "gated": False,
                "private": False,
                "pipeline_tag": "text-generation",
                "lastModified": "2026-04-21T00:00:00.000Z",
                "gguf": {"architecture": "llama", "context_length": 131072},
                "siblings": [
                    {"rfilename": ".gitattributes"},
                    {"rfilename": "mmproj-model-f16.gguf"},
                    {"rfilename": "Llama-3.2-1B-Instruct-Q4_K_M.gguf"},
                    {"rfilename": "Llama-3.2-1B-Instruct-Q8_0.gguf"},
                ],
            }

            normalized = manager.normalize_remote_model_entry(raw, size_bytes_override=912 * 1024**2)

            assert normalized is not None
            self.assertEqual(normalized["repo_id"], "bartowski/Llama-3.2-1B-Instruct-GGUF")
            self.assertEqual(normalized["artifact_name"], "Llama-3.2-1B-Instruct-Q4_K_M.gguf")
            self.assertEqual(normalized["quant"], "Q4_K_M")
            self.assertEqual(normalized["architecture"], "llama")
            self.assertEqual(normalized["context"], "131072")
            self.assertEqual(normalized["size_bytes"], 912 * 1024**2)
            self.assertEqual(normalized["gated"], "no")
            self.assertEqual(normalized["mmproj_artifact_name"], "mmproj-model-f16.gguf")

    def test_annotate_remote_models_applies_fit_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            items = [
                {
                    "repo_id": "example/model",
                    "artifact_name": "example-Q4_K_M.gguf",
                    "size_bytes": 2 * 1024**3,
                    "context": "32768",
                }
            ]

            annotated = manager.annotate_remote_models(
                items,
                {
                    "host_backends": ["cpu", "cuda"],
                    "preferred_backend": "cuda",
                    "memory_bytes": 24 * 1024**3,
                    "memory_human": "24.0 GiB",
                },
            )

            self.assertEqual(annotated[0]["compatibility_status"], "good-fit")
            self.assertEqual(annotated[0]["size_human"], "2.0 GiB")

    def test_download_remote_model_job_imports_model(self) -> None:
        payload = b"gguf-payload"
        mmproj_payload = b"mmproj-payload"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = mmproj_payload if self.path.endswith("mmproj-model-f16.gguf") else payload
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    return

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            download_url = f"http://127.0.0.1:{server.server_port}/model.gguf"
            remote_store = {
                "schema_version": 1,
                "provider": "huggingface",
                "query": "gguf",
                "fetched_at": "2026-04-21T00:00:00+00:00",
                "items": [
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "mmproj_artifact_name": "mmproj-model-f16.gguf",
                        "mmproj_download_url": f"http://127.0.0.1:{server.server_port}/mmproj-model-f16.gguf",
                        "alias": "model-q4-k-m",
                        "download_url": download_url,
                        "source_url": "https://huggingface.co/author/model",
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "mmproj_size_bytes": len(mmproj_payload),
                        "mmproj_sha256": hashlib.sha256(mmproj_payload).hexdigest(),
                    }
                ],
            }
            manager.write_json_store(manager.remote_models_file, remote_store)

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            self.wait_for_download_thread(manager, job["id"], timeout=10)

            download_jobs = manager.read_download_jobs_store()
            completed = next(item for item in download_jobs["items"] if item["id"] == job["id"])
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(Path(completed["local_path"]).is_file())
            self.assertEqual(Path(completed["local_path"]).read_bytes(), payload)
            self.assertEqual(completed["verification_summary"], "sha256 verified")
            self.assertTrue(Path(completed["mmproj_local_path"]).is_file())
            self.assertEqual(Path(completed["mmproj_local_path"]).read_bytes(), mmproj_payload)
            self.assertEqual(completed["mmproj_verification_summary"], "sha256 verified")

            models = manager.read_models()
            self.assertEqual(models[0]["alias"], "model-q4-k-m")
            self.assertEqual(Path(models[0]["path"]).read_bytes(), payload)
            self.assertEqual(Path(models[0]["mmproj"]).read_bytes(), mmproj_payload)

    def test_start_remote_download_reuses_existing_destination(self) -> None:
        payload = b"existing-payload"

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            destination_root = Path(tmpdir) / "downloads"
            destination_dir = destination_root / "huggingface" / "author" / "model"
            destination_dir.mkdir(parents=True, exist_ok=True)
            existing_path = destination_dir / "model-Q4_K_M.gguf"
            existing_path.write_bytes(payload)

            remote_store = {
                "schema_version": 1,
                "provider": "huggingface",
                "query": "gguf",
                "fetched_at": "2026-04-21T00:00:00+00:00",
                "items": [
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "alias": "model-q4-k-m",
                        "download_url": "https://example.invalid/model-Q4_K_M.gguf",
                        "source_url": "https://huggingface.co/author/model",
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
            manager.write_json_store(manager.remote_models_file, remote_store)

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(destination_root),
                }
            )

            self.wait_for_download_thread(manager, job["id"], timeout=10)

            download_jobs = manager.read_download_jobs_store()
            completed = next(item for item in download_jobs["items"] if item["id"] == job["id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["reuse_reason"], "primary file already existed at destination")
            self.assertEqual(completed["verification_summary"], "sha256 verified")
            self.assertEqual(Path(completed["local_path"]).read_bytes(), payload)

    def test_download_remote_model_job_fails_on_checksum_mismatch(self) -> None:
        payload = b"gguf-payload"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    return

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            download_url = f"http://127.0.0.1:{server.server_port}/model.gguf"
            remote_store = {
                "schema_version": 1,
                "provider": "huggingface",
                "query": "gguf",
                "fetched_at": "2026-04-21T00:00:00+00:00",
                "items": [
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "alias": "model-q4-k-m",
                        "download_url": download_url,
                        "source_url": "https://huggingface.co/author/model",
                        "size_bytes": len(payload),
                        "sha256": "0" * 64,
                    }
                ],
            }
            manager.write_json_store(manager.remote_models_file, remote_store)

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            self.wait_for_download_thread(manager, job["id"], timeout=10)

            download_jobs = manager.read_download_jobs_store()
            failed = next(item for item in download_jobs["items"] if item["id"] == job["id"])
            self.assertEqual(failed["status"], "failed")
            self.assertIn("sha256 mismatch", failed["error"])

            models = manager.read_models()
            self.assertEqual(models, [])

    def test_download_job_can_be_cancelled(self) -> None:
        payload = b"g" * 2_000_000

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            remote_store = {
                "schema_version": 1,
                "provider": "huggingface",
                "query": "gguf",
                "fetched_at": "2026-04-21T00:00:00+00:00",
                "items": [
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "alias": "model-q4-k-m",
                        "download_url": f"http://127.0.0.1:{server.server_port}/model.gguf",
                        "source_url": "https://huggingface.co/author/model",
                        "size_bytes": len(payload),
                    }
                ],
            }
            manager.write_json_store(manager.remote_models_file, remote_store)

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job["id"]), None
                )
                if active and active.get("status") == "running":
                    break

            canceled = manager.cancel_download_job(job["id"])
            self.assertEqual(canceled["status"], "cancelled")

            deadline = time.time() + 10
            final_job = None
            while time.time() < deadline:
                store = manager.read_download_jobs_store()
                final_job = next((item for item in store["items"] if item["id"] == job["id"]), None)
                if final_job and final_job.get("status") in {"cancelled", "failed", "completed"}:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final_job)
            self.assertEqual(final_job["status"], "cancelled")
            self.assertEqual(final_job.get("error"), "Download was cancelled by operator.")
            self.assertFalse(Path(final_job["destination_path"]).exists())
            self.assertEqual(manager.read_models(), [])

    def test_cancel_download_job_is_reentrant(self) -> None:
        payload = b"c" * 2_000_000

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                        }
                    ],
                },
            )

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job["id"]), None
                )
                if active and active.get("status") == "running":
                    break

            first = manager.cancel_download_job(job["id"])
            second = manager.cancel_download_job(job["id"])

            self.assertEqual(first["id"], job["id"])
            self.assertEqual(first["status"], "cancelled")
            self.assertTrue(first["cancel_requested"])
            self.assertEqual(second["id"], job["id"])
            self.assertEqual(second["status"], "cancelled")
            self.assertTrue(second["cancel_requested"])
            self.assertEqual(second["error"], "Download was cancelled by operator.")

            final_job = self.wait_for_download_terminal_status(manager, job["id"], timeout=10)
            self.assertEqual(final_job["status"], "cancelled")
            self.assertTrue(final_job["cancel_requested"])
            self.wait_for_download_thread(manager, job["id"], timeout=10)
            self.assertNotIn(job["id"], manager.download_threads)
            self.assertNotIn(job["id"], manager.download_cancel_events)

    def test_preseeded_cancel_event_is_obeyed_at_job_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            job_id = "preseed0000"
            event = threading.Event()
            event.set()
            manager.download_cancel_events[job_id] = event

            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": "https://example.invalid/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": 0,
                            "sha256": "",
                        }
                    ],
                },
            )

            with mock.patch.object(WEB_APP, "uuid4", return_value=mock.Mock(hex=job_id)):
                job = manager.start_remote_download(
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "destination_root": str(Path(tmpdir) / "downloads"),
                    }
                )

            self.assertEqual(job["id"], job_id)
            terminal = self.wait_for_download_terminal_status(manager, job_id, timeout=10)
            self.assertEqual(terminal["status"], "cancelled")
            self.assertEqual(terminal["error"], "Download was cancelled by operator.")
            self.assertNotIn(job_id, manager.download_threads)

    def test_retry_running_download_returns_same_job(self) -> None:
        payload = b"w" * (2_000_000)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                        }
                    ],
                },
            )

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job["id"]),
                    None,
                )
                if active is not None and active.get("status") == "running":
                    break
            self.assertIsNotNone(active)
            self.assertEqual(active["status"], "running")

            retried = manager.retry_download_job(job["id"])
            self.assertEqual(retried["id"], job["id"])
            self.assertIn(retried["status"], {"queued", "running"})

            store = manager.read_download_jobs_store()
            matching = [
                item
                for item in store["items"]
                if str(item.get("repo_id", "")).strip() == "author/model"
                and str(item.get("artifact_name", "")).strip() == "model-Q4_K_M.gguf"
            ]
            self.assertEqual(len(matching), 1)

            manager.cancel_download_job(job["id"])
            final_job = self.wait_for_download_terminal_status(manager, job["id"], timeout=10)
            self.assertEqual(final_job["status"], "cancelled")

    def test_retry_running_download_is_idempotent_under_concurrency(self) -> None:
        payload = b"q" * (2_000_000)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                        }
                    ],
                },
            )

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            for _ in range(300):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job["id"]), None
                )
                if active is not None and active.get("status") == "running":
                    break
            self.assertIsNotNone(active)
            self.assertEqual(active["status"], "running")

            results = []
            errors = []
            lock = threading.Lock()

            def call_retry() -> None:
                try:
                    retried = manager.retry_download_job(job["id"])
                    with lock:
                        results.append(retried["id"])
                except Exception as exc:  # pragma: no cover - defensive branch
                    with lock:
                        errors.append(str(exc))

            threads = [threading.Thread(target=call_retry) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertFalse(errors)
            self.assertTrue(results)
            self.assertEqual(set(results), {job["id"]})
            self.assertEqual(len(results), 3)

            manager.cancel_download_job(job["id"])
            final_job = self.wait_for_download_terminal_status(manager, job["id"], timeout=10)
            self.assertEqual(final_job["status"], "cancelled")

    def test_retry_download_requeues_job_with_new_identity(self) -> None:
        payload = b"ok-payload"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    return

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)

            manager = self.make_manager(tmpdir)
            remote_store = {
                "schema_version": 1,
                "provider": "huggingface",
                "query": "gguf",
                "fetched_at": "2026-04-21T00:00:00+00:00",
                "items": [
                    {
                        "repo_id": "author/model",
                        "artifact_name": "model-Q4_K_M.gguf",
                        "alias": "model-q4-k-m",
                        "download_url": f"http://127.0.0.1:{server.server_port}/model.gguf",
                        "source_url": "https://huggingface.co/author/model",
                        "size_bytes": len(payload),
                    }
                ],
            }
            manager.write_json_store(manager.remote_models_file, remote_store)

            job = manager.start_remote_download(
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                }
            )

            self.wait_for_download_thread(manager, job["id"], timeout=10)

            store = manager.read_download_jobs_store()
            completed = next(item for item in store["items"] if item["id"] == job["id"])
            self.assertEqual(completed["status"], "completed")

            completed["status"] = "failed"
            completed["error"] = "simulated error"
            manager.upsert_download_job(completed)

            retried = manager.retry_download_job(job["id"])
            self.assertNotEqual(retried["id"], job["id"])
            self.assertIn(retried["status"], {"queued", "running"})

            retried_worker = manager.download_threads.get(retried["id"])
            if retried_worker:
                retried_worker.join(timeout=10)
            else:
                self.wait_for_download_terminal_status(manager, retried["id"], timeout=10)

            refreshed = manager.read_download_jobs_store()
            retry_record = next(item for item in refreshed["items"] if item["id"] == retried["id"])
            self.assertIn(retry_record["status"], {"completed", "running", "queued"})

    def test_download_cancel_api_persists_cancelled_state(self) -> None:
        payload = b"g" * 2_000_000

        class DownloadHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
            download_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            download_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                        }
                    ],
                },
            )

            started = self.post_json(
                f"{api_base}/api/downloads/start",
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                },
            )["job"]
            job_id = str(started["id"])

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job_id), None
                )
                if active and active.get("status") == "running":
                    break

            cancelled = self.post_json(f"{api_base}/api/downloads/cancel", {"id": job_id})["job"]
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled["error"], "Download was cancelled by operator.")

            final_job = self.wait_for_download_terminal_status(manager, job_id, timeout=10)
            self.assertEqual(final_job["status"], "cancelled")
            self.assertEqual(final_job["error"], "Download was cancelled by operator.")
            self.assertFalse(Path(final_job["destination_path"]).exists())

    def test_download_retry_api_requeues_cancelled_job_with_same_contract(self) -> None:
        payload = b"r" * 2_000_000

        class DownloadHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
            download_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            download_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            destination_root = Path(tmpdir) / "downloads"
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    ],
                },
            )

            started = self.post_json(
                f"{api_base}/api/downloads/start",
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(destination_root),
                },
            )["job"]
            original_id = str(started["id"])

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == original_id), None
                )
                if active and active.get("status") == "running" and int(active.get("bytes_downloaded") or 0) > 0:
                    break

            self.post_json(f"{api_base}/api/downloads/cancel", {"id": original_id})
            cancelled = self.wait_for_download_terminal_status(manager, original_id, timeout=10)
            self.assertEqual(cancelled["status"], "cancelled")
            self.wait_for_download_thread(manager, original_id, timeout=10)

            retried = self.post_json(f"{api_base}/api/downloads/retry", {"id": original_id})["job"]
            self.assertNotEqual(retried["id"], original_id)
            self.assertEqual(retried["repo_id"], "author/model")
            self.assertEqual(retried["artifact_name"], "model-Q4_K_M.gguf")
            self.assertEqual(retried["destination_root"], str(destination_root))
            self.assertFalse(retried["cancel_requested"])
            self.assertEqual(retried["bytes_downloaded"], 0)
            self.assertEqual(retried["progress"], 0.0)
            self.assertEqual(retried["error"], "")

            self.wait_for_download_thread(manager, str(retried["id"]), timeout=10)

            refreshed = manager.read_download_jobs_store()
            retry_record = next(item for item in refreshed["items"] if item["id"] == retried["id"])
            self.assertEqual(retry_record["status"], "completed")
            self.assertEqual(retry_record["verification_summary"], "sha256 verified")

    def test_download_resume_api_continues_from_preserved_partial_file(self) -> None:
        payload = b"resume-payload-" * 160_000
        observed_ranges: list[str] = []

        class RangeHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                range_header = self.headers.get("Range", "")
                observed_ranges.append(range_header)
                start = 0
                if range_header.startswith("bytes=") and range_header.endswith("-"):
                    start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                else:
                    self.send_response(200)
                body = payload[start:]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for offset in range(0, len(body), 16_384):
                    try:
                        self.wfile.write(body[offset : offset + 16_384])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
            download_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            download_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            destination_root = Path(tmpdir) / "downloads"
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        }
                    ],
                },
            )

            started = self.post_json(
                f"{api_base}/api/downloads/start",
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(destination_root),
                },
            )["job"]
            original_id = str(started["id"])

            active = None
            for _ in range(300):
                time.sleep(0.02)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == original_id), None
                )
                if active and int(active.get("bytes_downloaded") or 0) > 0:
                    break
            self.assertIsNotNone(active)
            self.assertGreater(int(active.get("bytes_downloaded") or 0), 0)

            self.post_json(f"{api_base}/api/downloads/cancel", {"id": original_id})
            cancelled = self.wait_for_download_terminal_status(manager, original_id, timeout=10)
            self.assertEqual(cancelled["status"], "cancelled")
            partial_path = Path(str(cancelled["partial_path"]))
            self.assertTrue(partial_path.is_file())
            partial_size = partial_path.stat().st_size
            self.assertGreater(partial_size, 0)
            self.assertTrue(cancelled["resume_available"])
            self.assertEqual(cancelled["partial_bytes"], partial_size)
            self.wait_for_download_thread(manager, original_id, timeout=10)
            partial_size = partial_path.stat().st_size
            self.assertGreater(partial_size, 0)

            resumed = self.post_json(f"{api_base}/api/downloads/resume", {"id": original_id})["job"]
            self.assertNotEqual(resumed["id"], original_id)
            self.assertEqual(resumed["resume_source_job_id"], original_id)
            self.assertEqual(resumed["resume_from_bytes"], partial_size)
            self.assertEqual(resumed["partial_path"], str(partial_path))

            self.wait_for_download_thread(manager, str(resumed["id"]), timeout=10)
            refreshed = manager.read_download_jobs_store()
            resume_record = next(item for item in refreshed["items"] if item["id"] == resumed["id"])
            self.assertEqual(resume_record["status"], "completed")
            self.assertEqual(resume_record["verification_summary"], "sha256 verified")
            self.assertEqual(Path(resume_record["local_path"]).read_bytes(), payload)
            self.assertIn(f"bytes={partial_size}-", observed_ranges)

    def test_resume_download_job_requires_preserved_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            manager.upsert_download_job(
                {
                    "id": "no-partial-01",
                    "status": "cancelled",
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                    "partial_path": str(Path(tmpdir) / "downloads" / "missing.part"),
                    "cancel_requested": True,
                }
            )

            with self.assertRaisesRegex(ValueError, "No resumable partial download"):
                manager.resume_download_job("no-partial-01")

    def test_read_download_jobs_store_marks_resumable_partial_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            partial_path = Path(tmpdir) / "downloads" / "model.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial-bytes")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "restart-partial-01",
                            "status": "cancelled",
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "partial_path": str(partial_path),
                            "cancel_requested": True,
                        }
                    ],
                },
            )

            store = manager.read_download_jobs_store()
            job = store["items"][0]

            self.assertEqual(job["partial_bytes"], len(b"partial-bytes"))
            self.assertTrue(job["resume_available"])

            persisted = json.loads(manager.download_jobs_file.read_text(encoding="utf-8"))
            self.assertNotIn("partial_bytes", persisted["items"][0])
            self.assertNotIn("resume_available", persisted["items"][0])

    def test_cleanup_stale_partial_downloads_removes_only_old_terminal_partials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            old_partial = Path(tmpdir) / "downloads" / "old.part"
            fresh_partial = Path(tmpdir) / "downloads" / "fresh.part"
            running_partial = Path(tmpdir) / "downloads" / "running.part"
            for path in (old_partial, fresh_partial, running_partial):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"partial")
            old_mtime = time.time() - 10_000
            os.utime(old_partial, (old_mtime, old_mtime))

            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "old-cancelled",
                            "status": "cancelled",
                            "repo_id": "author/model",
                            "artifact_name": "old.gguf",
                            "partial_path": str(old_partial),
                        },
                        {
                            "id": "fresh-cancelled",
                            "status": "cancelled",
                            "repo_id": "author/model",
                            "artifact_name": "fresh.gguf",
                            "partial_path": str(fresh_partial),
                        },
                        {
                            "id": "running-job",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "running.gguf",
                            "partial_path": str(running_partial),
                        },
                    ],
                },
            )

            result = manager.cleanup_stale_partial_downloads(max_age_seconds=3600)

            self.assertEqual(result["removed"], [str(old_partial)])
            self.assertFalse(old_partial.exists())
            self.assertTrue(fresh_partial.exists())
            self.assertTrue(running_partial.exists())

            store = manager.read_download_jobs_store()
            jobs = {item["id"]: item for item in store["items"]}
            self.assertEqual(jobs["old-cancelled"]["partial_bytes"], 0)
            self.assertFalse(jobs["old-cancelled"]["resume_available"])
            self.assertGreater(jobs["fresh-cancelled"]["partial_bytes"], 0)
            self.assertTrue(jobs["fresh-cancelled"]["resume_available"])

    def test_download_cleanup_api_removes_stale_terminal_partials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            partial_path = Path(tmpdir) / "downloads" / "old.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            old_mtime = time.time() - 10_000
            os.utime(partial_path, (old_mtime, old_mtime))
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "cleanup-api-01",
                            "status": "cancelled",
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "partial_path": str(partial_path),
                        }
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/cleanup", {"max_age_seconds": 3600})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["removed"], [str(partial_path)])
            self.assertFalse(partial_path.exists())

    def test_recover_stale_download_jobs_marks_orphan_running_job_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            partial_path = Path(tmpdir) / "downloads" / "orphan.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "orphan-running-01",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "partial_path": str(partial_path),
                        }
                    ],
                },
            )

            result = manager.recover_stale_download_jobs()

            self.assertEqual(result["recovered"], ["orphan-running-01"])
            store = manager.read_download_jobs_store()
            job = store["items"][0]
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Download worker is not active. Resume or retry this job.")
            self.assertEqual(job["partial_bytes"], len(b"partial"))
            self.assertTrue(job["resume_available"])
            self.assertTrue(partial_path.exists())

    def test_download_recover_api_marks_orphan_running_job_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            partial_path = Path(tmpdir) / "downloads" / "orphan-api.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            manager.write_json_store(
                manager.download_jobs_file,
                {
                    "schema_version": 1,
                    "updated_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "id": "orphan-api-01",
                            "status": "running",
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "partial_path": str(partial_path),
                        }
                    ],
                },
            )

            payload = self.post_json(f"{api_base}/api/downloads/recover", {})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["recovered"], ["orphan-api-01"])
            store = manager.read_download_jobs_store()
            job = store["items"][0]
            self.assertEqual(job["status"], "failed")
            self.assertTrue(job["resume_available"])

    def test_manager_startup_recovers_persisted_orphan_running_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "HOME": str(Path(tmpdir) / "home"),
                "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                "LLAMA_SERVER_RUNTIME_DIR": str(Path(tmpdir) / "runtime"),
            }
            Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
            config_dir = Path(env["XDG_CONFIG_HOME"]) / "llama-server"
            state_dir = Path(env["XDG_STATE_HOME"]) / "llama-server"
            config_dir.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "defaults.env").write_text(
                "LLAMA_SERVER_HOST=127.0.0.1\nLLAMA_SERVER_PORT=8081\n",
                encoding="utf-8",
            )
            partial_path = Path(tmpdir) / "downloads" / "startup.part"
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"startup-partial")
            (state_dir / "download-jobs.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "updated_at": "2026-04-21T00:00:00+00:00",
                        "items": [
                            {
                                "id": "startup-orphan-01",
                                "status": "running",
                                "repo_id": "author/model",
                                "artifact_name": "model-Q4_K_M.gguf",
                                "partial_path": str(partial_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            patcher = mock.patch.dict(os.environ, env, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)

            manager = WEB_APP.Manager(ROOT_DIR / "web")
            store = manager.read_download_jobs_store()
            job = store["items"][0]

            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Download worker is not active. Resume or retry this job.")
            self.assertEqual(job["partial_bytes"], len(b"startup-partial"))
            self.assertTrue(job["resume_available"])

    def test_concurrent_cancel_and_retry_api_calls_clear_stale_download_controls(self) -> None:
        payload = b"z" * 2_000_000

        class DownloadHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                for offset in range(0, len(payload), 16_384):
                    try:
                        self.wfile.write(payload[offset : offset + 16_384])
                        self.wfile.flush()
                    except BrokenPipeError:
                        return
                    time.sleep(0.01)

            def log_message(self, format, *args):  # noqa: A003
                return

        with tempfile.TemporaryDirectory() as tmpdir:
            download_server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
            download_thread = threading.Thread(target=download_server.serve_forever, daemon=True)
            download_thread.start()
            self.addCleanup(download_server.shutdown)
            self.addCleanup(download_server.server_close)

            manager = self.make_manager(tmpdir)
            app_server = self.start_app_server(manager)
            api_base = f"http://127.0.0.1:{app_server.server_port}"
            manager.write_json_store(
                manager.remote_models_file,
                {
                    "schema_version": 1,
                    "provider": "huggingface",
                    "query": "gguf",
                    "fetched_at": "2026-04-21T00:00:00+00:00",
                    "items": [
                        {
                            "repo_id": "author/model",
                            "artifact_name": "model-Q4_K_M.gguf",
                            "alias": "model-q4-k-m",
                            "download_url": f"http://127.0.0.1:{download_server.server_port}/model.gguf",
                            "source_url": "https://huggingface.co/author/model",
                            "size_bytes": len(payload),
                        }
                    ],
                },
            )

            started = self.post_json(
                f"{api_base}/api/downloads/start",
                {
                    "repo_id": "author/model",
                    "artifact_name": "model-Q4_K_M.gguf",
                    "destination_root": str(Path(tmpdir) / "downloads"),
                },
            )["job"]
            job_id = str(started["id"])

            for _ in range(200):
                time.sleep(0.01)
                active = next(
                    (item for item in manager.read_download_jobs_store()["items"] if item["id"] == job_id), None
                )
                if active and active.get("status") == "running":
                    break

            barrier = threading.Barrier(3)
            results: dict[str, dict[str, object]] = {}

            def do_cancel() -> None:
                barrier.wait()
                results["cancel"] = self.post_json(f"{api_base}/api/downloads/cancel", {"id": job_id})["job"]

            def do_retry() -> None:
                barrier.wait()
                results["retry"] = self.post_json(f"{api_base}/api/downloads/retry", {"id": job_id})["job"]

            cancel_thread = threading.Thread(target=do_cancel)
            retry_thread = threading.Thread(target=do_retry)
            cancel_thread.start()
            retry_thread.start()
            barrier.wait()
            cancel_thread.join(timeout=10)
            retry_thread.join(timeout=10)

            self.assertFalse(cancel_thread.is_alive())
            self.assertFalse(retry_thread.is_alive())
            self.assertEqual(results["cancel"]["id"], job_id)
            self.assertEqual(results["cancel"]["status"], "cancelled")
            self.assertEqual(results["retry"]["id"], job_id)
            self.assertIn(results["retry"]["status"], {"running", "cancelled"})

            final_job = self.wait_for_download_terminal_status(manager, job_id, timeout=10)
            self.assertEqual(final_job["status"], "cancelled")

            deadline = time.time() + 5
            while time.time() < deadline:
                if job_id not in manager.download_threads and job_id not in manager.download_cancel_events:
                    break
                time.sleep(0.05)

            self.assertNotIn(job_id, manager.download_threads)
            self.assertNotIn(job_id, manager.download_cancel_events)

    def test_llamacpp_provider_implements_protocol(self) -> None:
        providers_module = self.load_providers_module()
        provider = providers_module.LlamaCppProvider(base_url="http://127.0.0.1:9999/v1")
        self.assertIsInstance(provider.name, str)
        self.assertTrue(provider.supports_streaming)
        self.assertIsInstance(provider.health_check(timeout=0.5), bool)
        self.assertIsInstance(provider.metadata(), dict)

    def test_llamacpp_provider_health_check_unreachable(self) -> None:
        providers_module = self.load_providers_module()
        provider = providers_module.LlamaCppProvider(base_url="http://127.0.0.1:0/v1")
        self.assertFalse(provider.health_check(timeout=0.25))

    def test_provider_registry_registers_and_lists_providers(self) -> None:
        providers_module = self.load_providers_module()
        reg = providers_module.ProviderRegistry()
        p1 = providers_module.LlamaCppProvider(base_url="http://a:8081/v1", timeout=0.1)
        p2 = providers_module.LlamaCppProvider(base_url="http://b:8081/v1", timeout=0.1)

        reg.register(p1, priority=10)
        reg.register(p2, priority=5)

        providers = reg.list_all()
        self.assertEqual(len(providers), 2)
        self.assertEqual(providers[0].name, "llamacpp")
        self.assertIs(providers[0], p1)

    def test_provider_registry_select_by_streaming(self) -> None:
        providers_module = self.load_providers_module()

        non_stream = mock.Mock(spec=providers_module.Provider)
        non_stream.name = "fallback"
        non_stream.supports_streaming = False
        non_stream.health_check.return_value = True
        non_stream.metadata.return_value = {"name": "fallback"}
        non_stream.generate.return_value = "fallback"
        non_stream.generate_stream.return_value = iter(())

        streaming = mock.Mock(spec=providers_module.Provider)
        streaming.name = "llamacpp"
        streaming.supports_streaming = True
        streaming.health_check.return_value = True
        streaming.metadata.return_value = {"name": "llamacpp"}
        streaming.generate.return_value = "streaming"
        streaming.generate_stream.return_value = iter(("a", "b"))

        registry = providers_module.ProviderRegistry()
        registry.register(non_stream, priority=10)
        registry.register(streaming, priority=5)

        selected = registry.select(streaming=True)
        self.assertIs(selected, streaming)

    def test_provider_registry_select_preferred(self) -> None:
        providers_module = self.load_providers_module()

        fallback = mock.Mock(spec=providers_module.Provider)
        fallback.name = "fallback"
        fallback.supports_streaming = False
        fallback.health_check.return_value = True
        fallback.metadata.return_value = {"name": "fallback"}
        fallback.generate.return_value = "fallback"
        fallback.generate_stream.return_value = iter(())

        preferred = mock.Mock(spec=providers_module.Provider)
        preferred.name = "llamacpp"
        preferred.supports_streaming = True
        preferred.health_check.return_value = True
        preferred.metadata.return_value = {"name": "llamacpp"}
        preferred.generate.return_value = "preferred"
        preferred.generate_stream.return_value = iter(("x",))

        registry = providers_module.ProviderRegistry()
        registry.register(fallback, priority=10)
        registry.register(preferred, priority=0)

        selected = registry.select(preferred="llamacpp")
        self.assertIs(selected, preferred)

    def test_provider_registry_freeze_prevents_registration(self) -> None:
        providers_module = self.load_providers_module()
        registry = providers_module.ProviderRegistry()
        provider = providers_module.LlamaCppProvider(base_url="http://127.0.0.1:8081/v1")
        registry.freeze()

        with self.assertRaises(RuntimeError):
            registry.register(provider, priority=1)

    def test_create_default_registry_has_llamacpp(self) -> None:
        providers_module = self.load_providers_module()

        with mock.patch.dict(
            os.environ,
            {
                "LLAMA_MODEL_BACKEND_BASE_URL": "http://127.0.0.1:8099/v1",
                "LMM_GATEWAY_TIMEOUT_SECONDS": "12.5",
            },
            clear=False,
        ):
            registry = providers_module.create_default_registry()

        self.assertIsNotNone(registry.get("llamacpp"))
        self.assertIsInstance(registry.get("llamacpp"), providers_module.LlamaCppProvider)


if __name__ == "__main__":
    unittest.main()
