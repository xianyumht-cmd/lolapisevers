import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server.lolban_presets import (
    FOURPNG_PROVIDER,
    ensure_lolban_provider_presets,
)
from services.api_parser_center import (
    ProviderResponseError,
    load_config,
    parse_response,
    to_lolban_payload,
)


class LolbanProviderPresetTests(unittest.TestCase):
    def test_fourpng_request_and_ban_response_shape(self):
        request = FOURPNG_PROVIDER["request"]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["url"], "https://yun.4png.com/api/query.html")
        self.assertEqual(request["query"]["qq"], "$qq")
        self.assertEqual(request["query"]["token"], "$secret:LOL_BAN_4PNG_TOKEN")
        self.assertFalse(FOURPNG_PROVIDER["enabled"])

        response = {
            "code": 200,
            "name": "上游推广名称不应输出",
            "by": "yun.4png.com",
            "msg": "此账号已被封禁",
            "data": {
                "banmsg": "账号97077000封禁至 2031-1-2 14:03:37",
                "rammsg": "距离解封还有 1987天2小时32分41秒",
                "return": "封禁",
            },
        }
        parsed = parse_response(FOURPNG_PROVIDER, response, status_code=200)
        normalized = to_lolban_payload("97077000", parsed)

        self.assertEqual(normalized["data"]["status"], "封禁")
        self.assertIn("封禁至", normalized["data"]["ban_time"])
        self.assertIn("距离解封", normalized["data"]["end_time"])
        self.assertNotIn("yun.4png.com", normalized["public_text"])
        self.assertNotIn("推广名称", normalized["public_text"])

    def test_fourpng_quota_advertisement_is_not_a_success(self):
        response = {
            "code": 400,
            "msg": "已达到今日查询上限，请付费使用 https://yun.4png.com",
        }
        with self.assertRaises(ProviderResponseError):
            parse_response(FOURPNG_PROVIDER, response, status_code=200)

    def test_one_time_migration_adds_disabled_preset_and_respects_later_removal(self):
        with tempfile.TemporaryDirectory() as temp_value:
            target = Path(temp_value) / "interface-parser-center.json"
            with patch.dict(
                os.environ,
                {"INTERFACE_PARSER_CENTER_PATH": str(target)},
                clear=False,
            ):
                first = ensure_lolban_provider_presets()
                config = load_config(target)
                providers = config["features"]["lolban"]["providers"]
                matching = [item for item in providers if item.get("id") == "lolban-4png"]
                self.assertTrue(first["ok"])
                self.assertEqual(len(matching), 1)
                self.assertFalse(matching[0]["enabled"])

                config["features"]["lolban"]["providers"] = [
                    item for item in providers if item.get("id") != "lolban-4png"
                ]
                target.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                second = ensure_lolban_provider_presets()
                reloaded = load_config(target)
                ids = {
                    item.get("id")
                    for item in reloaded["features"]["lolban"]["providers"]
                }
                self.assertFalse(second["changed"])
                self.assertNotIn("lolban-4png", ids)


if __name__ == "__main__":
    unittest.main()
