import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lanzou_update_push_api_server.lolban_presets import (
    FOURPNG_PROVIDER,
    LOL2099_PROVIDER,
    ensure_lolban_provider_presets,
)
from services.api_parser_center import (
    ProviderResponseError,
    load_config,
    parse_response,
    prepare_request,
    to_lolban_payload,
)


class LolbanProviderPresetTests(unittest.TestCase):
    def test_lol2099_request_matches_captured_protocol(self):
        request = LOL2099_PROVIDER["request"]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://lol2099.top/")
        self.assertEqual(request["form"]["action"], "query_lol")
        self.assertEqual(request["form"]["qq"], "$qq")
        self.assertEqual(request["headers"]["X-Requested-With"], "XMLHttpRequest")
        self.assertFalse(LOL2099_PROVIDER["enabled"])

        prepared = prepare_request(LOL2099_PROVIDER, {"qq": "97077000"})
        self.assertEqual(prepared.form, {"action": "query_lol", "qq": "97077000"})
        self.assertEqual(prepared.query, {})

    def test_lol2099_captured_clear_and_banned_responses(self):
        clear_response = {
            "code": 200,
            "by": "q.lolmap.cn",
            "msg": "此账号状态正常",
            "data": {
                "qq": "2320006072",
                "ban_time": "",
                "end_time": "账号状态正常",
                "status": "正常",
                "ban_reason": "",
            },
        }
        parsed_clear = parse_response(LOL2099_PROVIDER, clear_response, status_code=200)
        normalized_clear = to_lolban_payload("2320006072", parsed_clear)
        self.assertEqual(normalized_clear["data"]["status"], "正常")
        self.assertNotIn("lol2099.top", normalized_clear["public_text"])
        self.assertNotIn("q.lolmap.cn", normalized_clear["public_text"])

        banned_response = {
            "code": 200,
            "by": "q.lolmap.cn",
            "msg": "此账号已被封禁",
            "data": {
                "qq": "97077000",
                "ban_time": "2031-1-2 14:03:35",
                "end_time": "1611天13小时28分钟55秒",
                "status": "封禁",
                "ban_reason": "违规传播违规信息或大量刷屏",
            },
        }
        parsed_banned = parse_response(LOL2099_PROVIDER, banned_response, status_code=200)
        normalized_banned = to_lolban_payload("97077000", parsed_banned)
        self.assertEqual(normalized_banned["data"]["status"], "封禁")
        self.assertEqual(normalized_banned["data"]["ban_time"], "2031-1-2 14:03:35")
        self.assertEqual(normalized_banned["data"]["end_time"], "1611天13小时28分钟55秒")
        self.assertEqual(normalized_banned["data"]["ban_reason"], "违规传播违规信息或大量刷屏")
        self.assertNotIn("lol2099.top", normalized_banned["public_text"])
        self.assertNotIn("q.lolmap.cn", normalized_banned["public_text"])

    def test_lol2099_unknown_or_failed_response_is_not_success(self):
        with self.assertRaises(ProviderResponseError):
            parse_response(
                LOL2099_PROVIDER,
                {"code": 500, "msg": "查询服务暂时不可用"},
                status_code=200,
            )
        with self.assertRaises(ProviderResponseError):
            parse_response(
                LOL2099_PROVIDER,
                {"code": 200, "data": {"qq": "97077000", "status": "未知"}},
                status_code=200,
            )

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

    def test_one_time_migration_adds_disabled_presets_and_respects_later_removal(self):
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
                by_id = {item.get("id"): item for item in providers}
                self.assertTrue(first["ok"])
                self.assertIn("lolban-lol2099", by_id)
                self.assertIn("lolban-4png", by_id)
                self.assertFalse(by_id["lolban-lol2099"]["enabled"])
                self.assertFalse(by_id["lolban-4png"]["enabled"])
                self.assertEqual(
                    first["added_provider_ids"],
                    ["lolban-lol2099", "lolban-4png"],
                )

                config["features"]["lolban"]["providers"] = [
                    item
                    for item in providers
                    if item.get("id") not in {"lolban-lol2099", "lolban-4png"}
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
                self.assertNotIn("lolban-lol2099", ids)
                self.assertNotIn("lolban-4png", ids)


if __name__ == "__main__":
    unittest.main()
