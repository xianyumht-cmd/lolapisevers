import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clients.channel_neutral_query_client import IntranetQueryClient, QueryClientError
from core.config import load_config as load_main_config
from db import Database
from lanzou_update_push_api_server import maintenance, management
from lanzou_update_push_api_server.config import AppConfig, WatcherConfig, load_config as load_lanzou_config
from lanzou_update_push_api_server.monitor import LanzouMonitorService
from lanzou_update_push_api_server.server import create_app as create_lanzou_app
from routers import cross_session
from routers.groupguard_delivery import groupguard_report
from services import dynamic_query_service
from services.contact_risk_store import ContactRiskStore
from services.dynamic_query_service import DynamicProviderDefinition
from services.upstream_http_client import UpstreamHttpClient
from so1_client import So1Client


class StreamingResponse:
    def __init__(self, chunks, *, status_code=200, headers=None, body=None, url="http://127.0.0.1/test"):
        self._chunks = list(chunks)
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.headers = dict(headers or {})
        self.content = b"" if body is None else body
        self.url = url
        self.closed = False
        self.yield_count = 0

    def iter_content(self, chunk_size=65536):
        del chunk_size
        for chunk in self._chunks:
            self.yield_count += 1
            yield chunk

    def close(self):
        self.closed = True


class ConfirmedBugRepairTests(unittest.TestCase):
    def test_gg001_same_source_different_urls_do_not_share_result(self):
        entered = threading.Event()
        release = threading.Event()

        class Response:
            def __init__(self, text):
                self.status_code = 200
                self.ok = True
                self.text = text
                self.headers = {}
                self.closed = False

            def close(self):
                self.closed = True

        class Session:
            def __init__(self):
                self.calls = []
                self.lock = threading.Lock()

            def request(self, method, url, **kwargs):
                del kwargs
                with self.lock:
                    self.calls.append((method, url))
                if url.endswith("11111"):
                    entered.set()
                    release.wait(2)
                    return Response('{"account":"11111"}')
                return Response('{"account":"22222"}')

        session = Session()
        client = UpstreamHttpClient(session=session, sleep_fn=lambda _: None)
        results = {}

        first = threading.Thread(target=lambda: results.setdefault("a", client.get_json("provider", "https://example.test/11111")))
        second = threading.Thread(target=lambda: results.setdefault("b", client.get_json("provider", "https://example.test/22222")))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        second.join(1)
        release.set()
        first.join(2)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(results["a"].data["account"], "11111")
        self.assertEqual(results["b"].data["account"], "22222")
        self.assertFalse(results["b"].shared)

    def test_gg008_client_stops_stream_at_response_limit(self):
        response = StreamingResponse([b"a" * 6, b"b" * 6], headers={"content-type": "application/json"})
        session = Mock(spec=requests.Session)
        session.post.return_value = response
        client = IntranetQueryClient("http://10.0.0.8:5001", session=session)
        with patch("clients.channel_neutral_query_client.MAX_RESPONSE_BYTES", 10):
            with self.assertRaises(QueryClientError) as caught:
                client.query("shard", {"hero": "滑板鞋"}, request_id="stream-limit-1")
        self.assertEqual(caught.exception.code, "response_too_large")
        self.assertEqual(response.yield_count, 2)
        self.assertTrue(response.closed)

    def test_dyn001_redirect_to_loopback_is_rejected(self):
        definition = DynamicProviderDefinition(
            command_id="demo", method="GET", url="https://public.test/start", headers={}, query={}, body={},
            timeout_ms=1000, text_path="", response_template="", fallback_text="fail", snapshot_seconds=0,
            allow_private=False,
        )
        calls = []

        def request_once(_definition, url, _headers, _body, _timeout):
            calls.append(url)
            if len(calls) % 2 == 1:
                return dynamic_query_service._ProviderHttpResponse(302, {"Location": "http://127.0.0.1/admin"}, b"")
            dynamic_query_service._validate_destination(url, False)
            raise AssertionError("private destination was not rejected")

        with patch.object(dynamic_query_service, "_request_once", side_effect=request_once):
            with self.assertRaises(RuntimeError):
                dynamic_query_service._execute_provider(definition, {})
        self.assertIn("http://127.0.0.1/admin", calls)

    def test_dyn001_connection_uses_validated_ip_and_original_host_header(self):
        definition = DynamicProviderDefinition(
            command_id="demo", method="GET", url="http://provider.example/data", headers={}, query={}, body={},
            timeout_ms=1000, text_path="", response_template="", fallback_text="fail", snapshot_seconds=0,
            allow_private=False,
        )

        class PoolResponse:
            status = 200
            headers = {}
            def read(self, amount, decode_content=True):
                del amount, decode_content
                return b"ok"
            def release_conn(self):
                return None

        pool = Mock()
        pool.urlopen.return_value = PoolResponse()
        with patch("services.dynamic_query_service.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]), patch(
            "services.dynamic_query_service.urllib3.HTTPConnectionPool", return_value=pool
        ) as pool_factory:
            result = dynamic_query_service._request_once(definition, definition.url, {}, {}, 1.0)
        pool_factory.assert_called_once_with("93.184.216.34", 80, maxsize=1, block=True)
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "provider.example")
        self.assertEqual(result.body, b"ok")

    def test_web001_remote_report_requires_token_and_accepts_correct_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContactRiskStore(Path(temp_dir) / "risk.db")
            ctx = SimpleNamespace(contact_risk_store=store, upstream_http_client=object())
            request = SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)),
                headers={}, client=SimpleNamespace(host="192.168.3.55"),
            )
            payload = {"feature": "scammer_report", "parameters": {"qq": "123456", "content": "证据"}, "request_id": "auth-1"}
            with patch.dict(os.environ, {"GROUPGUARD_WRITE_TOKEN": ""}, clear=False):
                denied = asyncio.run(groupguard_report(request, payload))
            self.assertEqual(denied.status_code, 403)
            request.headers = {"x-groupguard-token": "correct"}
            with patch.dict(os.environ, {"GROUPGUARD_WRITE_TOKEN": "correct"}, clear=False):
                accepted = asyncio.run(groupguard_report(request, payload))
            self.assertEqual(accepted.status_code, 200)

    def test_web002_manual_login_requires_admin_token(self):
        app = FastAPI()
        app.include_router(cross_session.router)

        class Client:
            async def bootstrap_manual_login(self, wait_seconds):
                self.wait_seconds = wait_seconds

        app.state.so1_client = Client()
        with patch.dict(os.environ, {"GROUPGUARD_WRITE_TOKEN": "secret"}, clear=False), patch.object(cross_session, "_last_started_at", 0.0):
            with TestClient(app) as client:
                self.assertEqual(client.post("/cross_session_init?wait_seconds=10").status_code, 401)
                response = client.post("/cross_session_init?wait_seconds=10", headers={"x-groupguard-token": "secret"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(app.state.so1_client.wait_seconds, 10)

    def test_so1002_instances_keep_separate_configuration_and_locks(self):
        first = So1Client("first", "one", headless=True, timeout_ms=1000)
        second = So1Client("second", "two", headless=False, timeout_ms=2000)
        self.assertIsNot(first, second)
        self.assertEqual(first.username, "first")
        self.assertEqual(second.username, "second")
        self.assertIsNot(first._query_semaphore, second._query_semaphore)

    def test_lz002_duplicate_and_blank_watcher_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(watchers=[WatcherConfig(id="", title="A", url="https://a.test")])
        with self.assertRaises(ValueError):
            AppConfig(watchers=[
                WatcherConfig(id="same", title="A", url="https://a.test"),
                WatcherConfig(id="same", title="B", url="https://b.test"),
            ])

    def test_lz003_scan_on_start_false_is_ready_during_warmup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                scan_interval_seconds=300, scan_on_start=False,
                state_path=Path(temp_dir) / "state.json",
                watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
            )
            service = LanzouMonitorService(config)
            service._task = SimpleNamespace(done=lambda: False)
            service._started_monotonic = time.monotonic()
            status = service.status()
        self.assertTrue(status["ready"])
        self.assertTrue(status["warming_up"])
        self.assertNotIn("never_scanned", status["degraded_reasons"])

    def test_lz004_invalid_boolean_method_and_timeout_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps({
                "scan_on_start": "not-a-bool",
                "watchers": [{"id": "demo", "url": "https://example.test"}],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_lanzou_config(config_path)
            config_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"LANZOU_MONITOR_CONFIG": str(config_path)}, clear=False):
                with self.assertRaises(ValueError):
                    management.update_lanzou_config({"wer_api_method": "DELETE"})
                with self.assertRaises(ValueError):
                    management.update_lanzou_config({"notify_targets": [{
                        "name": "n", "url": "https://notify.test", "timeout_seconds": 0,
                    }]})

    def test_cfg001_invalid_numeric_and_boolean_values_are_aggregated(self):
        with patch.dict(os.environ, {"APP_PORT": "abc", "MYSQL_PORT": "70000", "SO1_HEADLESS": "maybe"}, clear=False):
            with self.assertRaises(ValueError) as caught:
                load_main_config()
        message = str(caught.exception)
        self.assertIn("APP_PORT", message)
        self.assertIn("MYSQL_PORT", message)
        self.assertIn("SO1_HEADLESS", message)

    def test_db001_database_and_charset_are_whitelisted(self):
        with patch.object(Database, "_ensure_database_and_tables", return_value=None):
            with self.assertRaises(ValueError):
                Database("localhost", 3306, "root", "", "bad-name")
            with self.assertRaises(ValueError):
                Database("localhost", 3306, "root", "", "safe_name", charset="utf8mb4;DROP")
            valid = Database("localhost", 3306, "root", "", "safe_name", charset="utf8mb4")
        self.assertEqual(valid.database, "safe_name")

    def test_sec001_audit_rotates_and_tail_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audit = Path(temp_dir) / "admin_audit.jsonl"
            with patch.object(maintenance, "AUDIT_PATH", audit), patch.object(maintenance, "LOGS_DIR", audit.parent), patch.dict(
                os.environ, {"ADMIN_AUDIT_MAX_BYTES": "65536", "ADMIN_AUDIT_BACKUPS": "2"}, clear=False
            ):
                for index in range(40):
                    maintenance.append_audit(action="denied", ok=False, detail={"padding": "x" * 3000, "index": index})
                events = maintenance.read_audit(3)["events"]
            self.assertTrue(audit.with_name("admin_audit.jsonl.1").exists())
            self.assertEqual(len(events), 3)
            self.assertEqual(events[0]["detail"]["index"], 39)

    def test_web003_upstream_stream_is_stopped_at_hard_limit(self):
        response = StreamingResponse([b"a" * 600, b"b" * 600], headers={})

        class Session:
            def request(self, *args, **kwargs):
                self.kwargs = kwargs
                return response

        session = Session()
        client = UpstreamHttpClient(session=session, max_response_bytes=1024, attempts=1, sleep_fn=lambda _: None)
        result = client.get_json("bounded", "https://example.test/data")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.error_class, "validation_error")
        self.assertTrue(session.kwargs["stream"])
        self.assertTrue(response.closed)

    def test_web003_lanzou_provider_rejects_oversized_stream(self):
        from lanzou_update_push_api_server.providers import ProviderError, _bounded_bytes

        response = StreamingResponse([b"a" * 6, b"b" * 6])
        with self.assertRaises(ProviderError) as caught:
            _bounded_bytes(response, 10)
        self.assertEqual(caught.exception.error_code, "response_too_large")

    def test_admin001_diagnostics_use_configured_ports(self):
        observed = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(json.dumps({"port": 7100, "state_path": str(state_path)}), encoding="utf-8")
            state_path.write_text("{}", encoding="utf-8")
            env_path = root / "app_env.local.ps1"
            env_path.write_text('$env:APP_PORT = "6100"\n$env:MYSQL_PORT = "4306"\n', encoding="utf-8")

            def tcp(host, port, timeout=0.8):
                del timeout
                observed.append((host, port))
                return True, "connected"

            with patch.object(management, "APP_ENV_PATH", env_path), patch.object(management, "_tcp_check", side_effect=tcp), patch.dict(
                os.environ, {"LANZOU_MONITOR_CONFIG": str(config_path), "APP_PORT": "", "MYSQL_PORT": ""}, clear=False
            ):
                management.run_diagnostics()
        self.assertIn(("127.0.0.1", 6100), observed)
        self.assertIn(("127.0.0.1", 7100), observed)
        self.assertIn(("127.0.0.1", 4306), observed)

    def test_admin002_internal_debugger_injects_token_without_returning_it(self):
        class Response:
            ok = True
            status_code = 200
            headers = {"content-type": "application/json"}
            content = b'{"ok":true}'
            url = "http://127.0.0.1:6178/config"
            def close(self):
                return None

        with patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": "secret", "LANZOU_MONITOR_PORT": "6178"}, clear=False), patch(
            "lanzou_update_push_api_server.api_debugger.requests.request", return_value=Response()
        ) as request_call:
            result = management.invoke_local_api({"service": "lanzou", "method": "GET", "path": "/config"})
        self.assertEqual(request_call.call_args.kwargs["headers"]["x-admin-token"], "secret")
        self.assertNotIn("secret", json.dumps(result))

    def test_ops_scripts_are_scoped_verified_and_use_current_logs(self):
        root = Path(__file__).resolve().parents[1]
        takeover = (root / "ops" / "formal_service_takeover.ps1").read_text(encoding="utf-8-sig")
        install = (root / "ops" / "install_persistence.ps1").read_text(encoding="utf-8-sig")
        health = (root / "ops" / "health_check.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ExpectedAppPath", takeover)
        self.assertIn("ProjectRoot", takeover)
        self.assertNotIn("service.stderr.log", takeover)
        self.assertIn("NssmZipSha256", install)
        self.assertIn("Get-FileHash", install)
        self.assertIn("$saved", install)
        self.assertIn("main_api.stderr.log", health)
        self.assertNotIn('D:\\project2\\lolapisevers', health)


class LanzouRouteRepairTests(unittest.TestCase):
    def _app(self, root: Path):
        config = AppConfig(
            state_path=root / "state.json",
            watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
        )
        app = create_lanzou_app(config)

        async def start():
            return None
        async def stop():
            return None
        async def send_test_event(watcher_id=None):
            return {"ok": True, "watcher_id": watcher_id}

        app.state.service.start = start
        app.state.service.stop = stop
        app.state.service.send_test_event = send_test_event
        return app

    def test_lz001_both_test_push_routes_call_live_service_method(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": "secret"}, clear=False):
            with TestClient(self._app(Path(temp_dir))) as client:
                old = client.post("/notify/test", json={"watcher_id": "demo"}, headers={"x-admin-token": "secret"})
                new = client.post("/test-push", json={"watcher_id": "demo"}, headers={"x-admin-token": "secret"})
        self.assertEqual(old.status_code, 200)
        self.assertEqual(new.status_code, 200)
        self.assertEqual(old.json()["watcher_id"], "demo")

    def test_api001_invalid_lanzou_config_returns_400(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"WEBUI_ADMIN_TOKEN": "secret", "LANZOU_MONITOR_CONFIG": str(config_path)}, clear=False):
                with TestClient(self._app(root)) as client:
                    response = client.post(
                        "/admin/lanzou-config", json={"wer_api_method": "DELETE"}, headers={"x-admin-token": "secret"}
                    )
        self.assertEqual(response.status_code, 400)
        self.assertIn("GET or POST", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
