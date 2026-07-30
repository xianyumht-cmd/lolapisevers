import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from routers.groupguard_delivery import groupguard_query
from services.dynamic_query_service import (
    DEFAULT_CATALOG_PATH,
    DynamicProviderCatalog,
    _validate_destination,
    query_dynamic,
)
from services.persistent_snapshot_store import PersistentSnapshotStore
from services.query_delivery import DELIVERY_PROTOCOL


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


class GroupGuardDynamicDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.catalog_path = root / "dynamic-providers.json"
        self.catalog_path.write_text(
            json.dumps(
                {
                    "schema": "lolapi-dynamic-query-providers.v1",
                    "commands": [
                        {
                            "id": "custom.search",
                            "provider": {
                                "method": "GET",
                                "url": "https://provider.example/search",
                                "headers": {"Authorization": "Bearer must-not-leak"},
                                "query": {"q": "$keyword"},
                                "timeout_ms": 5000,
                            },
                            "response": {"text_path": "data.url"},
                            "fallback_text": "custom service unavailable",
                            "snapshot_seconds": 3600,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.env = patch.dict(
            os.environ,
            {"DYNAMIC_QUERY_PROVIDERS_PATH": str(self.catalog_path)},
        )
        self.env.start()
        self.ctx = SimpleNamespace(
            upstream_snapshot_store=PersistentSnapshotStore(root / "snapshots")
        )
        self.request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(ctx=self.ctx)),
            headers={},
        )

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    async def test_dynamic_query_returns_final_delivery_without_provider_configuration(self):
        with patch(
            "services.dynamic_query_service._execute_provider",
            return_value="https://result.example/item/1",
        ) as execute:
            response = await groupguard_query(
                self.request,
                {
                    "feature": "dynamic",
                    "parameters": {
                        "command_id": "custom.search",
                        "keyword": "测试歌曲",
                    },
                    "preferred": "text",
                    "request_id": "dynamic-001",
                },
            )
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["protocol"], DELIVERY_PROTOCOL)
        self.assertEqual(body["feature"], "dynamic")
        self.assertEqual(body["delivery"]["segments"][0]["text"], "https://result.example/item/1")
        self.assertEqual(body["meta"]["command_id"], "custom.search")
        self.assertEqual(body["meta"]["source"], "live")
        execute.assert_called_once()
        raw = bytes(response.body).decode("utf-8")
        self.assertNotIn("provider.example", raw)
        self.assertNotIn("must-not-leak", raw)
        self.assertNotIn("Authorization", raw)

    async def test_dynamic_query_uses_parameter_specific_snapshot_after_failure(self):
        with patch(
            "services.dynamic_query_service._execute_provider",
            return_value="first result",
        ):
            live = await query_dynamic(
                self.ctx,
                "custom.search",
                {"command_id": "custom.search", "keyword": "alpha"},
            )
        self.assertEqual(live["source"], "live")

        with patch(
            "services.dynamic_query_service._execute_provider",
            side_effect=RuntimeError("upstream failed"),
        ):
            stale = await query_dynamic(
                self.ctx,
                "custom.search",
                {"command_id": "custom.search", "keyword": "alpha"},
            )
        self.assertEqual(stale["source"], "snapshot")
        self.assertTrue(stale["is_stale"])
        self.assertEqual(stale["text"], "first result")

        with patch(
            "services.dynamic_query_service._execute_provider",
            side_effect=RuntimeError("upstream failed"),
        ):
            with self.assertRaises(HTTPException) as missing:
                await query_dynamic(
                    self.ctx,
                    "custom.search",
                    {"command_id": "custom.search", "keyword": "beta"},
                )
        self.assertEqual(missing.exception.status_code, 503)

    async def test_unknown_command_and_invalid_parameter_are_rejected(self):
        unknown = await groupguard_query(
            self.request,
            {
                "feature": "dynamic_query",
                "parameters": {"command_id": "missing.command", "keyword": "x"},
                "preferred": "text",
            },
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertIn("未在接口端配置", decode(unknown)["error"]["user_message"])

        invalid = await groupguard_query(
            self.request,
            {
                "feature": "dynamic",
                "parameters": {"command_id": "custom.search", "bad key": "x"},
                "preferred": "text",
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("参数名", decode(invalid)["error"]["user_message"])

    def test_private_and_loopback_provider_destinations_are_rejected(self):
        for url in (
            "http://127.0.0.1:8080/query",
            "http://192.168.3.89/query",
            "http://10.0.0.2/query",
            "http://[::1]/query",
        ):
            with self.assertRaises(HTTPException):
                _validate_destination(url, allow_private=False)

    def test_default_catalog_contains_current_repository_commands(self):
        with patch.dict(
            os.environ,
            {"DYNAMIC_QUERY_PROVIDERS_PATH": str(DEFAULT_CATALOG_PATH)},
        ):
            catalog = DynamicProviderCatalog()
            self.assertEqual(catalog.get("quote.daily").method, "GET")
            self.assertEqual(catalog.get("music.search").text_path, "results[0].trackViewUrl")
            with self.assertRaises(HTTPException) as removed:
                catalog.get("video.info")
            self.assertEqual(removed.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
