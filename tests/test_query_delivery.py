import base64
import hashlib
import unittest

from services.query_delivery import (
    DELIVERY_PROTOCOL,
    choose_text_delivery,
    error_envelope,
    format_aram_text,
    format_shard_text,
    image_delivery,
    safe_meta,
    split_forward_text,
    success_envelope,
)


class QueryDeliveryTests(unittest.TestCase):
    def test_image_delivery_round_trip_and_hash(self):
        body = b"\x89PNG\r\ncontract-test"
        delivery = image_delivery(body, filename="shard-Kalista.png")
        segment = delivery["segments"][0]

        self.assertEqual(delivery["kind"], "segments")
        self.assertEqual(segment["type"], "image")
        self.assertEqual(base64.b64decode(segment["data"]), body)
        self.assertEqual(segment["bytes"], len(body))
        self.assertEqual(segment["sha256"], hashlib.sha256(body).hexdigest())

    def test_long_text_prefers_forward_when_supported(self):
        text = "\n".join(f"第 {index} 行：" + "内容" * 40 for index in range(120))
        delivery = choose_text_delivery(
            text,
            {"text": True, "image": False, "forward": True},
            "auto",
        )
        self.assertEqual(delivery["kind"], "forward")
        nodes = delivery["segments"][0]["nodes"]
        self.assertGreater(len(nodes), 1)
        self.assertLessEqual(len(nodes), 32)
        self.assertTrue(all(len(node["segments"][0]["text"]) <= 1200 for node in nodes))

    def test_forward_split_handles_single_oversized_line(self):
        chunks = split_forward_text("A" * 2600, max_chars=1000)
        self.assertEqual([len(item) for item in chunks], [1000, 1000, 600])

    def test_success_and_error_envelopes_have_stable_protocol(self):
        success = success_envelope(
            feature="lolban",
            delivery={"kind": "segments", "segments": [{"type": "text", "text": "ok"}]},
            meta={"source": "live"},
            client_request_id="client-safe-token",
            server_request_id="server1",
        )
        self.assertEqual(success["protocol"], DELIVERY_PROTOCOL)
        self.assertTrue(success["ok"])
        self.assertEqual(success["client_request_id"], "client-safe-token")
        self.assertFalse(success["retry"]["allowed"])

        error = error_envelope(
            feature="shard",
            code="temporarily_unavailable",
            user_message="服务暂不可用",
            retryable=True,
            retry_after_seconds=30,
            server_request_id="server2",
        )
        self.assertEqual(error["protocol"], DELIVERY_PROTOCOL)
        self.assertFalse(error["ok"])
        self.assertEqual(error["delivery"]["segments"][0]["text"], "服务暂不可用")
        self.assertTrue(error["retry"]["allowed"])
        self.assertEqual(error["retry"]["after_seconds"], 30)

    def test_invalid_request_id_is_rejected_instead_of_rewritten(self):
        with self.assertRaises(ValueError):
            success_envelope(
                feature="lolban",
                delivery={"kind": "segments", "segments": [{"type": "text", "text": "ok"}]},
                meta={},
                client_request_id="a b",
                server_request_id="server1",
            )

    def test_forward_overflow_and_payload_limits_fail_loudly(self):
        with self.assertRaises(ValueError):
            split_forward_text("A" * (4000 * 33), max_chars=4000)
        from services.query_delivery import text_delivery
        with self.assertRaises(ValueError):
            text_delivery("A" * 20001)
        with self.assertRaises(ValueError):
            image_delivery(b"x" * (12 * 1024 * 1024 + 1))

    def test_formatters_do_not_require_plugin_business_parsing(self):
        shard = format_shard_text(
            {
                "hero": {"title": "复仇之矛", "name": "卡莉丝塔", "alias": "Kalista"},
                "pick_rate": 0.12,
                "win_rate": 0.51,
                "count": 1,
                "rows": [{"name": "测试合集", "pick_rate": 0.8, "win_rate": 0.6}],
            }
        )
        self.assertIn("复仇之矛", shard)
        self.assertIn("测试合集", shard)
        self.assertIn("80%", shard)

        aram = format_aram_text(
            {
                "hero": {"title": "九尾妖狐", "name": "阿狸", "alias": "Ahri"},
                "total": 1,
                "rows": [
                    {
                        "name": "测试强化",
                        "rarity": "gold",
                        "performance": 0.6,
                        "popular": 0.4,
                        "desc": "测试说明",
                    }
                ],
                "starter_items": [],
                "item_builds": [],
                "boots": [],
                "summoner_spells": [],
                "skill_order": [],
            }
        )
        self.assertIn("海克斯大乱斗强化榜", aram)
        self.assertIn("测试强化", aram)
        self.assertIn("60%", aram)

    def test_safe_meta_excludes_source_url_and_business_rows(self):
        meta = safe_meta(
            {
                "source": "stale",
                "provider": "opgg",
                "source_url": "https://secret.example/token=abc",
                "rows": [{"secret": "value"}],
                "hero": {"alias": "Ahri", "name": "阿狸", "title": "九尾妖狐"},
                "snapshot_age_seconds": 30,
                "stale": True,
            }
        )
        self.assertEqual(meta["source"], "stale")
        self.assertEqual(meta["hero"]["alias"], "Ahri")
        self.assertNotIn("source_url", meta)
        self.assertNotIn("rows", meta)
        self.assertNotIn("secret.example", str(meta))


if __name__ == "__main__":
    unittest.main()
