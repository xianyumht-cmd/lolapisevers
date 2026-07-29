import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from routers.groupguard_delivery import groupguard_query
from services.persistent_snapshot_store import PersistentSnapshotStore
from services.upstream_http_client import UpstreamError, UpstreamResponse
from services.video_query_service import (
    build_video_request_url,
    extract_video_url,
    load_video_provider_templates,
    query_video,
)


def decode(response):
    return json.loads(bytes(response.body).decode("utf-8"))


def request_with_ctx(ctx=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ctx=ctx if ctx is not None else object())),
        headers={},
    )


class FakeUpstreamClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, source_id, url, **kwargs):
        self.calls.append((source_id, url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected extra upstream request")
        return self.responses.pop(0)


class VideoQueryServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_template_configuration_and_url_builder(self):
        raw = json.dumps({"热门": "https://provider.example/api?type={category}"}, ensure_ascii=False)
        with patch.dict(os.environ, {"QUERY_VIDEO_PROVIDERS_JSON": raw}, clear=False):
            templates = load_video_provider_templates()
        self.assertEqual(templates["热门"], "https://provider.example/api?type={category}")
        url = build_video_request_url(templates["热门"], "搞笑 视频")
        self.assertIn("%E6%90%9E%E7%AC%91%20%E8%A7%86%E9%A2%91", url)

    def test_extract_video_url_rejects_private_and_accepts_public(self):
        self.assertEqual(extract_video_url({"url": "http://127.0.0.1/private.mp4"}), "")
        self.assertEqual(extract_video_url({"url": "http://192.168.3.89/private.mp4"}), "")
        self.assertEqual(
            extract_video_url({"data": {"play_url": "https://cdn.example.com/video.mp4"}}),
            "https://cdn.example.com/video.mp4",
        )

    async def test_live_video_result_is_saved_and_reused_as_snapshot(self):
        mapping = json.dumps({"热门": "https://provider.example/api?category={category}"}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp:
            store = PersistentSnapshotStore(Path(temp))
            live_client = FakeUpstreamClient([
                UpstreamResponse(
                    ok=True,
                    source_id="video_provider_test",
                    status="success",
                    status_code=200,
                    attempts=1,
                    text=json.dumps({"data": {"url": "https://cdn.example.com/live.mp4"}}),
                )
            ])
            ctx = SimpleNamespace(
                upstream_http_client=live_client,
                upstream_snapshot_store=store,
            )
            with patch.dict(os.environ, {"QUERY_VIDEO_PROVIDERS_JSON": mapping}, clear=False):
                live = await query_video(ctx, "热门")
            self.assertEqual(live["source"], "live")
            self.assertEqual(live["url"], "https://cdn.example.com/live.mp4")
            self.assertEqual(len(live_client.calls), 1)
            self.assertNotIn("provider.example", live_client.calls[0][0])

            failed_client = FakeUpstreamClient([
                UpstreamResponse(
                    ok=False,
                    source_id="video_provider_test",
                    status="failed",
                    attempts=2,
                    error=UpstreamError("timeout", "redacted timeout", True),
                )
            ])
            stale_ctx = SimpleNamespace(
                upstream_http_client=failed_client,
                upstream_snapshot_store=store,
            )
            with patch.dict(os.environ, {"QUERY_VIDEO_PROVIDERS_JSON": mapping}, clear=False):
                stale = await query_video(stale_ctx, "热门")
            self.assertEqual(stale["source"], "snapshot")
            self.assertTrue(stale["is_stale"])
            self.assertEqual(stale["url"], "https://cdn.example.com/live.mp4")
            self.assertEqual(len(failed_client.calls), 1)

    async def test_private_video_result_is_not_delivered(self):
        mapping = json.dumps({"热门": "https://provider.example/api"}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp:
            client = FakeUpstreamClient([
                UpstreamResponse(
                    ok=True,
                    source_id="video_provider_test",
                    status="success",
                    text=json.dumps({"url": "http://127.0.0.1/internal.mp4"}),
                )
            ])
            ctx = SimpleNamespace(
                upstream_http_client=client,
                upstream_snapshot_store=PersistentSnapshotStore(Path(temp)),
            )
            with patch.dict(os.environ, {"QUERY_VIDEO_PROVIDERS_JSON": mapping}, clear=False):
                with self.assertRaises(HTTPException) as raised:
                    await query_video(ctx, "热门")
        self.assertEqual(raised.exception.status_code, 503)

    async def test_video_router_returns_final_text_only(self):
        payload = {
            "category": "搞笑",
            "url": "https://cdn.example.com/funny.mp4",
            "source": "live",
            "is_stale": False,
            "snapshot_updated_at": "",
            "provider": "搞笑",
        }
        with patch(
            "routers.groupguard_delivery.query_video",
            new=AsyncMock(return_value=payload),
        ) as query, patch(
            "routers.groupguard_delivery._render_feature_image",
            new=AsyncMock(side_effect=AssertionError("video must not render image")),
        ) as renderer:
            response = await groupguard_query(
                request_with_ctx(),
                {
                    "feature": "我要看",
                    "parameters": {"category": "搞笑"},
                    "preferred": "image",
                    "capabilities": {"image": True, "text": True, "forward": True},
                },
            )
        query.assert_awaited_once_with(unittest.mock.ANY, "搞笑")
        renderer.assert_not_awaited()
        body = decode(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["feature"], "video")
        self.assertEqual(body["delivery"]["segments"][0]["type"], "text")
        self.assertIn("https://cdn.example.com/funny.mp4", body["delivery"]["segments"][0]["text"])
        self.assertNotIn("QUERY_VIDEO_PROVIDERS_JSON", str(body))


if __name__ == "__main__":
    unittest.main()
