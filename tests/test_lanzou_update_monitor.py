import asyncio
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig, NotifyTargetConfig, WatcherConfig, load_config
from lanzou_update_push_api_server.monitor import LanzouMonitorService, compare_snapshots
from lanzou_update_push_api_server import providers
from lanzou_update_push_api_server.providers import FileEntry, LanzouWebProvider, ProviderChain, ProviderError, ShareSnapshot
from lanzou_update_push_api_server.server import create_app


def snapshot(files):
    return ShareSnapshot(
        watcher_id="demo",
        title="Demo",
        url="https://example.test",
        provider="test",
        fetched_at="2026-01-01T00:00:00+00:00",
        files=files,
    )


class LanzouUpdateMonitorTests(unittest.TestCase):
    def test_compare_snapshots_detects_added_removed_and_changed(self):
        previous = snapshot(
            [
                FileEntry(id="a", name="old.exe", size="1 M", modified_time="2026-01-01"),
                FileEntry(id="b", name="remove.exe", size="1 M", modified_time="2026-01-01"),
            ]
        )
        current = snapshot(
            [
                FileEntry(id="a", name="old.exe", size="2 M", modified_time="2026-01-02"),
                FileEntry(id="c", name="new.exe", size="1 M", modified_time="2026-01-03"),
            ]
        )

        diff = compare_snapshots(previous, current)

        self.assertEqual(diff["added"][0]["id"], "c")
        self.assertEqual(diff["removed"][0]["id"], "b")
        self.assertEqual(diff["changed"][0]["before"]["id"], "a")
        self.assertEqual(diff["changed"][0]["after"]["size"], "2 M")

    def test_snapshot_signature_is_stable_for_same_files(self):
        left = snapshot([FileEntry(id="a", name="file.exe", size="1 M")])
        right = snapshot([FileEntry(id="a", name="file.exe", size="1 M")])

        self.assertEqual(left.signature, right.signature)

    def test_snapshot_signature_ignores_rolling_relative_time(self):
        left = snapshot([FileEntry(id="a", name="file.exe", size="1 M", modified_time="13 小时前")])
        right = snapshot([FileEntry(id="a", name="file.exe", size="1 M", modified_time="14 小时前")])

        self.assertEqual(left.signature, right.signature)
        self.assertEqual(compare_snapshots(left, right), {"added": [], "removed": [], "changed": []})

    def test_config_loader_accepts_windows_utf8_bom(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_bytes(
                b"\xef\xbb\xbf"
                + (
                    '{"host":"127.0.0.1","port":6178,'
                    '"notification_template":"hello，{title}网盘检测到更新",'
                    '"watchers":[{"id":"demo","title":"Demo","url":"https://example.test"}]}'
                ).encode("utf-8")
            )

            config = load_config(path)

        self.assertEqual(config.port, 6178)
        self.assertEqual(config.notification_template, "hello，{title}网盘检测到更新")
        self.assertEqual(config.watchers[0].id, "demo")

    def test_default_third_party_api_uses_lanzpro_endpoint(self):
        config = load_config()

        self.assertEqual(config.wer_api_endpoint, "https://api2.wer.plus/api/lanzpro")

    def test_scan_batch_settings_are_loaded(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                '{"scan_batch_size":1,"scan_batch_pause_seconds":90,'
                '"watchers":[{"id":"demo","title":"Demo","url":"https://example.test"}]}',
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.scan_batch_size, 1)
        self.assertEqual(config.scan_batch_pause_seconds, 90)

    def test_provider_chain_does_not_duplicate_provider_name_in_errors(self):
        config = AppConfig(
            provider_order=["lanzou_web"],
            watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
        )
        chain = ProviderChain(config)

        class FailingProvider:
            def fetch(self, _watcher, _config):
                raise ProviderError("anti_bot_challenge")

        chain.providers["lanzou_web"] = FailingProvider()

        with self.assertRaisesRegex(ProviderError, r"^providers_unavailable$") as raised:
            chain.fetch(config.watchers[0])
        self.assertEqual(
            raised.exception.attempts,
            [
                {
                    "provider": "lanzou_web",
                    "error_code": "anti_bot_challenge",
                    "error_class": "ProviderError",
                    "retryable": True,
                }
            ],
        )

    def test_lanzou_web_provider_retries_browser_profile_after_challenge(self):
        original_session = providers.requests.Session
        sessions = []

        class FakeResponse:
            def __init__(self, text="", url="https://example.test/share", payload=None):
                self.text = text
                self.url = url
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeSession:
            def __init__(self):
                self.headers = {}
                sessions.append(self)

            def get(self, url, timeout):
                if len(sessions) == 1:
                    return FakeResponse("<html><script>var arg1='challenge';</script></html>", url)
                page_html = (
                    "<title>Demo Share</title>"
                    "url : '/filemoreajax.php?file=123',"
                    "'lx':2,'fid':123,'uid':'u1','rep':'0','up':1,'vip':0,'webfoldersign':'',"
                    "var iabc = 't1'; var _abc = 'k1'; 't':iabc,'k':_abc"
                )
                return FakeResponse(page_html, url)

            def post(self, url, data, timeout, headers):
                self.last_post = {"url": url, "data": data, "headers": headers}
                return FakeResponse(
                    payload={
                        "zt": 1,
                        "info": "sucess",
                        "text": [{"id": "f1", "name_all": "Demo.zip", "size": "1 M", "time": "today"}],
                    }
                )

        providers.requests.Session = FakeSession
        try:
            watcher = WatcherConfig(
                id="demo",
                title="Demo",
                url="https://example.test/share",
                password="123",
                max_pages=1,
            )
            result = LanzouWebProvider().fetch(watcher, AppConfig(watchers=[watcher]))
        finally:
            providers.requests.Session = original_session

        self.assertEqual(result.files[0].name, "Demo.zip")
        self.assertEqual(result.raw_status["browser_profile"], "desktop_hbpc")
        self.assertEqual(sessions[1].last_post["data"]["pwd"], "123")
        self.assertEqual(sessions[1].last_post["headers"]["X-Requested-With"], "XMLHttpRequest")

    def test_failed_notification_keeps_previous_snapshot_for_retry(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            config = AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=[NotifyTargetConfig(name="webhook", url="https://notify.test")],
            )
            service = LanzouMonitorService(config)
            previous = snapshot([FileEntry(id="old", name="old.zip")])
            current = snapshot([FileEntry(id="new", name="new.zip")])
            service.store.set_snapshot(previous)

            class StaticProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = StaticProvider()
            notify_results = iter(
                [
                    [{"target": "webhook", "ok": False, "status_code": 500}],
                    [{"target": "webhook", "ok": True, "status_code": 204}],
                ]
            )
            service._notify_targets = lambda _event, *_target_names: next(notify_results)

            failed = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertTrue(failed["changed"])
            self.assertFalse(failed["snapshot_committed"])
            self.assertTrue(failed["notification_pending"])
            self.assertEqual(service.store.snapshot_for("demo").signature, previous.signature)
            failed_event_id = failed["event"]["id"]

            retried = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertTrue(retried["changed"])
            self.assertTrue(retried["snapshot_committed"])
            self.assertFalse(retried["notification_pending"])
            self.assertEqual(retried["event"]["id"], failed_event_id)
            self.assertEqual(retried["event"]["delivery_state"], "complete")
            self.assertEqual(service.store.snapshot_for("demo").signature, current.signature)

    def test_non_notifying_scan_does_not_consume_next_notification(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            config = AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=[NotifyTargetConfig(name="webhook", url="https://notify.test")],
            )
            service = LanzouMonitorService(config)
            previous = snapshot([FileEntry(id="old", name="old.zip")])
            current = snapshot([FileEntry(id="new", name="new.zip")])
            service.store.set_snapshot(previous)

            class StaticProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = StaticProvider()
            notifications = []
            service._notify_targets = lambda event, *_target_names: notifications.append(event) or [{"target": "webhook", "ok": True}]

            preview = asyncio.run(service.scan_watcher("demo", notify=False))

            self.assertTrue(preview["changed"])
            self.assertFalse(preview["snapshot_committed"])
            self.assertTrue(preview["notification_pending"])
            self.assertEqual(notifications, [])
            self.assertEqual(service.store.recent_events(), [])
            self.assertEqual(service.store.snapshot_for("demo").signature, previous.signature)

            delivered = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertEqual(len(notifications), 1)
            self.assertEqual(len(service.store.recent_events()), 1)
            self.assertTrue(delivered["snapshot_committed"])
            self.assertEqual(service.store.snapshot_for("demo").signature, current.signature)

    def test_partial_delivery_retries_only_failed_target_with_stable_event_id(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            config = AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=[
                    NotifyTargetConfig(name="groupguard-a", url="https://notify-a.test"),
                    NotifyTargetConfig(name="groupguard-b", url="https://notify-b.test"),
                ],
            )
            service = LanzouMonitorService(config)
            previous = snapshot([FileEntry(id="old", name="old.zip")])
            current = snapshot([FileEntry(id="new", name="new.zip")])
            service.store.set_snapshot(previous)

            class StaticProvider:
                def fetch(self, _watcher):
                    return current

            service.provider_chain = StaticProvider()
            attempts = []

            def notify(_event, target_names):
                attempts.append(set(target_names))
                if len(attempts) == 1:
                    return [
                        {"target": "groupguard-a", "ok": True, "status_code": 200},
                        {"target": "groupguard-b", "ok": False, "status_code": 503},
                    ]
                return [{"target": "groupguard-b", "ok": True, "status_code": 200}]

            service._notify_targets = notify

            first = asyncio.run(service.scan_watcher("demo", notify=True))
            second = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertEqual(first["event"]["delivery_state"], "partial")
            self.assertFalse(first["snapshot_committed"])
            self.assertEqual(second["event"]["delivery_state"], "complete")
            self.assertTrue(second["snapshot_committed"])
            self.assertEqual(first["event"]["id"], second["event"]["id"])
            self.assertEqual(attempts[0], {"groupguard-a", "groupguard-b"})
            self.assertEqual(attempts[1], {"groupguard-b"})

    def test_test_notification_does_not_report_success_without_targets(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            service = LanzouMonitorService(
                AppConfig(
                    state_path=Path(temp_dir) / "state.json",
                    watchers=[watcher],
                    notify_targets=[],
                )
            )

            result = asyncio.run(service.send_test_event("demo"))

            self.assertFalse(result["ok"])
            self.assertEqual(result["delivery_state"], "skipped")

    def test_concurrent_scans_for_same_watcher_are_serialized(self):
        with TemporaryDirectory() as temp_dir:
            watcher = WatcherConfig(id="demo", title="Demo", url="https://example.test")
            config = AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=[NotifyTargetConfig(name="webhook", url="https://notify.test")],
            )
            service = LanzouMonitorService(config)
            service._notify_targets = lambda _event, *_target_names: [{"target": "webhook", "ok": True}]
            baseline = snapshot([FileEntry(id="baseline", name="baseline.zip")])
            first_current = snapshot([FileEntry(id="first", name="first.zip")])
            second_current = snapshot([FileEntry(id="second", name="second.zip")])
            service.store.set_snapshot(baseline)
            first_fetch_started = threading.Event()
            release_first_fetch = threading.Event()
            second_scan_started = threading.Event()

            class SequencedProvider:
                def __init__(self):
                    self.calls = 0
                    self.lock = threading.Lock()

                def fetch(self, _watcher):
                    with self.lock:
                        self.calls += 1
                        call_number = self.calls
                    if call_number == 1:
                        first_fetch_started.set()
                        if not release_first_fetch.wait(timeout=2):
                            raise TimeoutError("test did not release first fetch")
                        return first_current
                    return second_current

            provider = SequencedProvider()
            service.provider_chain = provider
            original_scan_sync = service._scan_watcher_sync
            scan_invocations = 0
            scan_invocations_lock = threading.Lock()

            def observed_scan_sync(_watcher, notify):
                nonlocal scan_invocations
                with scan_invocations_lock:
                    scan_invocations += 1
                    if scan_invocations == 2:
                        second_scan_started.set()
                return original_scan_sync(_watcher, notify)

            service._scan_watcher_sync = observed_scan_sync

            async def run_concurrently():
                first_task = asyncio.create_task(service.scan_watcher("demo", notify=True))
                started = await asyncio.to_thread(first_fetch_started.wait, 1)
                self.assertTrue(started)
                second_task = asyncio.create_task(service.scan_watcher("demo", notify=True))
                try:
                    started = await asyncio.to_thread(second_scan_started.wait, 1)
                    self.assertTrue(started)
                    await asyncio.sleep(0.01)
                    self.assertEqual(provider.calls, 1)
                finally:
                    release_first_fetch.set()
                return await asyncio.gather(first_task, second_task)

            results = asyncio.run(run_concurrently())

            self.assertTrue(all(result["ok"] for result in results))
            self.assertEqual(provider.calls, 2)
            self.assertEqual(service.store.snapshot_for("demo").signature, second_current.signature)

    def test_dashboard_page_is_served_from_root(self):
        with TemporaryDirectory() as temp_dir:
            config = AppConfig(
                scan_on_start=False,
                state_path=Path(temp_dir) / "state.json",
                watchers=[WatcherConfig(id="demo", title="Demo", url="https://example.test")],
            )
            app = create_app(config)

            with TestClient(app) as client:
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("lolapisevers 接口端总控台", response.text)
        self.assertIn("watcherRows", response.text)
        self.assertIn("/notify/test", response.text)


if __name__ == "__main__":
    unittest.main()
