import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lanzou_update_push_api_server.config import (
    AppConfig,
    NotifyTargetConfig,
    WatcherConfig,
)
from lanzou_update_push_api_server.content_risk import scan_share_notice
from lanzou_update_push_api_server.monitor import LanzouMonitorService
from lanzou_update_push_api_server.providers import (
    FileEntry,
    ShareSnapshot,
    _extract_share_notice,
)


def snapshot(
    notice: str,
    *,
    available: bool = True,
    file_id: str = "release",
) -> ShareSnapshot:
    return ShareSnapshot(
        watcher_id="demo",
        title="Demo",
        url="https://example.test/share",
        provider="lanzou_web",
        fetched_at="2026-09-19T00:00:00+00:00",
        files=[FileEntry(id=file_id, name="release.zip", size="1 M")],
        share_notice=notice,
        share_notice_available=available,
    )


class LanzouContentRiskDetectorTests(unittest.TestCase):
    def test_explicit_group_with_spaced_digits_is_high_risk(self):
        result = scan_share_notice("问题反馈 Q Q 群：1 2 3 4 5 6 7 8 9")

        self.assertEqual(result["status"], "risk")
        self.assertEqual(result["severity"], "critical")
        self.assertTrue(
            any(
                item["kind"] == "qq_group" and item["value"] == "123456789"
                for item in result["findings"]
            )
        )

    def test_contact_types_are_detected(self):
        result = scan_share_notice(
            "微信 wx_test01，电话 138 0013 8000，邮箱 a@example.com，详情 https://example.com/help"
        )
        kinds = {item["kind"] for item in result["findings"]}

        self.assertEqual(result["status"], "risk")
        self.assertTrue({"wechat", "phone", "email", "url"}.issubset(kinds))

    def test_standalone_long_number_is_suspected(self):
        result = scan_share_notice("有问题请看 123456789")

        self.assertEqual(result["status"], "suspected")
        self.assertEqual(result["findings"][0]["kind"], "number")

    def test_date_and_build_context_do_not_trigger(self):
        result = scan_share_notice("版本 build 20260919，更新日期 2026-09-19")

        self.assertEqual(result["status"], "clear")
        self.assertEqual(result["findings"], [])

    def test_zero_width_and_full_width_text_are_normalized(self):
        result = scan_share_notice("Ｑ\u200bＱ群：１２３４５６７８９")

        self.assertEqual(result["status"], "risk")
        self.assertIn("123456789", result["summary"])

    def test_native_share_notice_extractors_cover_known_lanzou_markup(self):
        notice, available = _extract_share_notice(
            '<span id="filename">反馈群 123456789</span>'
        )
        self.assertTrue(available)
        self.assertEqual(notice, "反馈群 123456789")

        notice, available = _extract_share_notice(
            '<div class="user-radio-0"></div>售后群 987654321</div>'
        )
        self.assertTrue(available)
        self.assertEqual(notice, "售后群 987654321")


class LanzouContentRiskMonitorTests(unittest.TestCase):
    def make_service(self, temp_dir: str) -> LanzouMonitorService:
        watcher = WatcherConfig(
            id="demo",
            title="Demo",
            url="https://example.test/share",
        )
        return LanzouMonitorService(
            AppConfig(
                state_path=Path(temp_dir) / "state.json",
                watchers=[watcher],
                notify_targets=[
                    NotifyTargetConfig(
                        name="webhook",
                        url="https://notify.test/event",
                    )
                ],
            )
        )

    def test_existing_risk_is_reported_on_first_baseline_scan(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)

            class StaticProvider:
                def fetch(self, _watcher):
                    return snapshot("反馈群：123456789")

            service.provider_chain = StaticProvider()
            events = []
            service._notify_targets = lambda event, *_names: (
                events.append(event)
                or [
                    {
                        "target": "webhook",
                        "ok": True,
                        "delivery_state": "complete",
                    }
                ]
            )

            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertTrue(result["baseline"])
            self.assertEqual(result["content_risk"]["status"], "risk")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["kind"], "content_risk")
            self.assertIn("立即检查并下架", events[0]["message"])
            self.assertEqual(
                service.store.content_risk_for("demo")["status"],
                "risk",
            )

    def test_unchanged_risk_is_not_repeated(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)

            class StaticProvider:
                def fetch(self, _watcher):
                    return snapshot("QQ 群 123456789")

            service.provider_chain = StaticProvider()
            events = []
            service._notify_targets = lambda event, *_names: (
                events.append(event)
                or [{"target": "webhook", "ok": True, "delivery_state": "complete"}]
            )

            asyncio.run(service.scan_watcher("demo", notify=True))
            second = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertEqual(len(events), 1)
            self.assertIsNone(second["content_risk"]["event"])

    def test_non_notifying_scan_keeps_risk_notification_pending(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)

            class StaticProvider:
                def fetch(self, _watcher):
                    return snapshot("QQ群：123456789")

            service.provider_chain = StaticProvider()
            events = []
            service._notify_targets = lambda event, *_names: (
                events.append(event)
                or [{"target": "webhook", "ok": True, "delivery_state": "complete"}]
            )

            preview = asyncio.run(service.scan_watcher("demo", notify=False))
            delivered = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertTrue(preview["content_risk"]["notification_pending"])
            self.assertEqual(events, [delivered["content_risk"]["event"]])
            self.assertFalse(delivered["content_risk"]["notification_pending"])

    def test_unavailable_notice_does_not_clear_previous_risk(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)

            class MutableProvider:
                current = snapshot("反馈群 123456789")

                def fetch(self, _watcher):
                    return self.current

            provider = MutableProvider()
            service.provider_chain = provider
            service._notify_targets = lambda _event, *_names: [
                {"target": "webhook", "ok": True, "delivery_state": "complete"}
            ]

            asyncio.run(service.scan_watcher("demo", notify=True))
            provider.current = snapshot("", available=False)
            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertEqual(result["content_risk"]["status"], "risk")
            self.assertEqual(result["content_risk"]["coverage"], "unavailable")
            state = service.store.content_risk_for("demo")
            self.assertEqual(state["status"], "risk")
            self.assertEqual(state["coverage"], "unavailable")

    def test_clear_notice_sends_recovery_after_risk_was_delivered(self):
        with TemporaryDirectory() as temp_dir:
            service = self.make_service(temp_dir)

            class MutableProvider:
                current = snapshot("反馈群 123456789")

                def fetch(self, _watcher):
                    return self.current

            provider = MutableProvider()
            service.provider_chain = provider
            events = []
            service._notify_targets = lambda event, *_names: (
                events.append(event)
                or [{"target": "webhook", "ok": True, "delivery_state": "complete"}]
            )

            asyncio.run(service.scan_watcher("demo", notify=True))
            provider.current = snapshot("软件说明，不包含联系方式")
            result = asyncio.run(service.scan_watcher("demo", notify=True))

            self.assertEqual(result["content_risk"]["status"], "clear")
            self.assertEqual([event["kind"] for event in events], [
                "content_risk",
                "content_risk_cleared",
            ])
            self.assertIn("风险已清除", events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
