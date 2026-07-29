from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from cache import TTLCache
from services.persistent_snapshot_store import PersistentSnapshotStore
from services.query_delivery import (
    DELIVERY_PROTOCOL,
    choose_text_delivery,
    error_envelope,
    format_shard_text,
    image_delivery,
    safe_meta,
    success_envelope,
    text_delivery,
)
from services.shard_service import (
    SHARD_DATA_SOURCE_ID,
    SHARD_HERO_SOURCE_ID,
    query_shard,
)
from services.upstream_http_client import UpstreamError, UpstreamResponse


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "fixtures"
    / "groupguard-query-contracts"
)
EXPECTED_SERVICE_COMMIT = "7764dbec4854a7d39a194f6ec1802f0e8902ea9e"
DELIVERY_KEYS = {
    "protocol",
    "ok",
    "feature",
    "request_id",
    "client_request_id",
    "delivery",
    "error",
    "retry",
    "meta",
}


def _load(name: str) -> Dict[str, Any]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"fixture {name} must be an object")
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_text_segment(segment: Dict[str, Any]) -> None:
    if set(segment) != {"type", "text"}:
        raise AssertionError("text segment fields changed")
    if segment.get("type") != "text" or not isinstance(segment.get("text"), str):
        raise AssertionError("invalid text segment")
    if len(segment["text"]) > 20_000:
        raise AssertionError("text segment exceeded contract limit")


def _validate_image_segment(segment: Dict[str, Any]) -> None:
    expected = {
        "type",
        "mime_type",
        "encoding",
        "data",
        "filename",
        "bytes",
        "sha256",
    }
    if set(segment) != expected:
        raise AssertionError("image segment fields changed")
    if segment.get("type") != "image" or segment.get("encoding") != "base64":
        raise AssertionError("invalid image segment")
    if segment.get("mime_type") not in {"image/png", "image/jpeg", "image/webp"}:
        raise AssertionError("unsupported image mime type")
    raw = base64.b64decode(str(segment.get("data") or ""), validate=True)
    if len(raw) != int(segment.get("bytes") or 0):
        raise AssertionError("image byte count mismatch")
    if hashlib.sha256(raw).hexdigest() != segment.get("sha256"):
        raise AssertionError("image sha256 mismatch")


def _validate_forward_segment(segment: Dict[str, Any]) -> None:
    if set(segment) != {"type", "nodes"} or segment.get("type") != "forward":
        raise AssertionError("invalid forward segment")
    nodes = segment.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 32:
        raise AssertionError("forward node count invalid")
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"segments"}:
            raise AssertionError("forward node fields changed")
        child_segments = node.get("segments")
        if not isinstance(child_segments, list) or not 1 <= len(child_segments) <= 8:
            raise AssertionError("forward child segment count invalid")
        for child in child_segments:
            if not isinstance(child, dict):
                raise AssertionError("forward child must be object")
            if child.get("type") == "text":
                _validate_text_segment(child)
            elif child.get("type") == "image":
                _validate_image_segment(child)
            else:
                raise AssertionError("forward child type is not allowed")


def _validate_delivery(value: Dict[str, Any]) -> None:
    if set(value) != DELIVERY_KEYS:
        raise AssertionError("delivery envelope fields changed")
    if value.get("protocol") != DELIVERY_PROTOCOL:
        raise AssertionError("delivery protocol changed")
    if not isinstance(value.get("ok"), bool):
        raise AssertionError("ok must be boolean")
    if not isinstance(value.get("request_id"), str) or not value["request_id"]:
        raise AssertionError("request_id missing")
    if not isinstance(value.get("client_request_id"), str):
        raise AssertionError("client_request_id invalid")
    delivery = value.get("delivery")
    if not isinstance(delivery, dict) or set(delivery) != {"kind", "segments"}:
        raise AssertionError("delivery fields changed")
    if delivery.get("kind") not in {"segments", "forward"}:
        raise AssertionError("delivery kind invalid")
    segments = delivery.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 16:
        raise AssertionError("delivery segment count invalid")
    for segment in segments:
        if not isinstance(segment, dict):
            raise AssertionError("segment must be object")
        if segment.get("type") == "text":
            _validate_text_segment(segment)
        elif segment.get("type") == "image":
            _validate_image_segment(segment)
        elif segment.get("type") == "forward":
            _validate_forward_segment(segment)
        else:
            raise AssertionError("unknown segment type")
    retry = value.get("retry")
    if not isinstance(retry, dict) or set(retry) != {"allowed", "after_seconds"}:
        raise AssertionError("retry fields changed")
    if not isinstance(retry.get("allowed"), bool):
        raise AssertionError("retry.allowed must be boolean")
    if not isinstance(retry.get("after_seconds"), int) or not 0 <= retry["after_seconds"] <= 3600:
        raise AssertionError("retry.after_seconds invalid")
    error = value.get("error")
    if value["ok"]:
        if error is not None or retry["allowed"]:
            raise AssertionError("successful response cannot contain retryable error")
    else:
        if not isinstance(error, dict) or set(error) != {"code", "user_message", "retryable"}:
            raise AssertionError("error fields changed")
        if bool(error.get("retryable")) != bool(retry.get("allowed")):
            raise AssertionError("error and retry flags disagree")


class _FakeClient:
    def __init__(self, responses: Dict[str, list[UpstreamResponse]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[str] = []

    def get_json(self, source_id: str, _url: str, **_kwargs: Any) -> UpstreamResponse:
        self.calls.append(source_id)
        return self.responses[source_id].pop(0)


def _ok(source_id: str, data: Any) -> UpstreamResponse:
    return UpstreamResponse(True, source_id, "ok", status_code=200, attempts=1, data=data)


def _failed(source_id: str) -> UpstreamResponse:
    return UpstreamResponse(
        False,
        source_id,
        "failed",
        attempts=2,
        error=UpstreamError("network_unreachable", "network_unreachable", True),
    )


def _ctx(root: str, client: _FakeClient) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            shard_data_url="https://public.invalid/shards.json",
            shard_hero_url="https://public.invalid/heroes.json",
            shard_cache_seconds=600,
        ),
        shard_cache=TTLCache(ttl_seconds=600),
        upstream_http_client=client,
        upstream_snapshot_store=PersistentSnapshotStore(Path(root)),
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )


class CrossRepositoryContractGateTests(unittest.TestCase):
    def test_manifest_hashes_and_fixture_contracts(self) -> None:
        manifest = _load("manifest.json")
        self.assertEqual(manifest["service_commit"], EXPECTED_SERVICE_COMMIT)
        self.assertEqual(manifest["delivery_protocol"], DELIVERY_PROTOCOL)
        self.assertTrue(manifest["consumer_rules"]["no_public_fallback"])
        listed = manifest.get("fixtures")
        self.assertIsInstance(listed, list)
        for item in listed:
            name = str(item.get("path") or "")
            fixture = _load(name)
            self.assertEqual(_canonical_sha256(fixture), item.get("sha256"), name)
            if name.startswith("delivery-"):
                _validate_delivery(fixture)

    def test_fixtures_match_delivery_builders(self) -> None:
        text_fixture = _load("delivery-success-text.json")
        expected_text = success_envelope(
            feature="lolban",
            delivery=text_delivery("账号封禁查询结果\nQQ号码：123456789\n账号状态：正常"),
            meta={"source": "live", "account_status": "正常", "stale": False},
            client_request_id="cli-text-001",
            server_request_id="srv-text-001",
        )
        self.assertEqual(text_fixture, expected_text)

        image_fixture = _load("delivery-success-image.json")
        image_bytes = base64.b64decode(image_fixture["delivery"]["segments"][0]["data"])
        expected_image = success_envelope(
            feature="shard",
            delivery=image_delivery(
                image_bytes,
                mime_type="image/png",
                filename="shard-Kalista.png",
            ),
            meta=image_fixture["meta"],
            client_request_id="cli-image-001",
            server_request_id="srv-image-001",
        )
        self.assertEqual(image_fixture, expected_image)

        error_fixture = _load("delivery-error-retryable.json")
        expected_error = error_envelope(
            feature="shard",
            code="temporarily_unavailable",
            user_message="查询服务暂不可用，请稍后再试",
            retryable=True,
            retry_after_seconds=30,
            client_request_id="cli-error-001",
            server_request_id="srv-error-001",
        )
        self.assertEqual(error_fixture, expected_error)

    def test_observability_fixture_is_safe_and_balanced(self) -> None:
        fixture = _load("observability-degraded.json")
        self.assertEqual(fixture["schema_version"], "query-observability.v1")
        self.assertEqual(fixture["status"], "degraded")
        self.assertEqual(sum(fixture["summary"].values()), 4)
        serialized = json.dumps(fixture, ensure_ascii=False).casefold()
        for forbidden in (
            "http://",
            "https://",
            "raw.githubusercontent",
            "game.gtimg",
            "op.gg",
            "token=",
            "password",
            "cookie",
            "123456789",
            "kalista",
            "ahri",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_restart_without_public_network_still_builds_delivery(self) -> None:
        shards = {
            "Kalista": {
                "pick_rate": 0.12,
                "win_rate": 0.51,
                "shards": [
                    {"name": "测试合集", "id": "1", "pick_rate": 0.8, "win_rate": 0.6}
                ],
            }
        }
        heroes = {
            "hero": [
                {
                    "alias": "Kalista",
                    "name": "卡莉丝塔",
                    "title": "复仇之矛",
                    "keywords": "滑板鞋",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp:
            live_client = _FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [_ok(SHARD_DATA_SOURCE_ID, shards)],
                    SHARD_HERO_SOURCE_ID: [_ok(SHARD_HERO_SOURCE_ID, heroes)],
                }
            )
            live = asyncio.run(query_shard(_ctx(temp, live_client), hero="滑板鞋"))
            self.assertEqual(live["source"], "live")
            self.assertEqual(live_client.calls, [SHARD_DATA_SOURCE_ID, SHARD_HERO_SOURCE_ID])

            offline_client = _FakeClient(
                {
                    SHARD_DATA_SOURCE_ID: [_failed(SHARD_DATA_SOURCE_ID)],
                    SHARD_HERO_SOURCE_ID: [_failed(SHARD_HERO_SOURCE_ID)],
                }
            )
            restored = asyncio.run(query_shard(_ctx(temp, offline_client), hero="滑板鞋"))
            self.assertEqual(restored["source"], "stale")
            self.assertTrue(restored["stale"])
            self.assertEqual(offline_client.calls, [SHARD_DATA_SOURCE_ID, SHARD_HERO_SOURCE_ID])

            text = format_shard_text(restored)
            delivery = choose_text_delivery(
                text,
                {"text": True, "image": False, "forward": True},
                "text",
            )
            self.assertIsNotNone(delivery)
            envelope = success_envelope(
                feature="shard",
                delivery=delivery or text_delivery(text),
                meta=safe_meta(restored),
                client_request_id="offline-contract-001",
                server_request_id="offline-server-001",
            )
            _validate_delivery(envelope)
            self.assertTrue(envelope["meta"]["stale"])
            self.assertIn("最近有效结果", envelope["delivery"]["segments"][0]["text"])


if __name__ == "__main__":
    unittest.main()
