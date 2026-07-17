import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from lanzou_update_push_api_server.config import AppConfig, WatcherConfig, load_config
from lanzou_update_push_api_server.monitor import compare_snapshots
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
                raise ProviderError("lanzou_web: anti-bot challenge page returned")

        chain.providers["lanzou_web"] = FailingProvider()

        with self.assertRaisesRegex(ProviderError, r"^lanzou_web: anti-bot challenge page returned$"):
            chain.fetch(config.watchers[0])

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
