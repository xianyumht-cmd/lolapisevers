import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lanzou_update_push_api_server import release_download_accelerator as accel


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, body=b""):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._body = body

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_content(self, chunk_size=65536):
        for index in range(0, len(self._body), chunk_size):
            yield self._body[index : index + chunk_size]


class _ResetRequested(RuntimeError):
    pass


class _ReconnectRequested(RuntimeError):
    pass


class ReleaseDownloadAcceleratorTests(unittest.TestCase):
    def test_extra_mirrors_include_current_china_friendly_sources(self):
        core = SimpleNamespace(
            _DEFAULT_RELEASE_MIRRORS=(
                ("gh-proxy.com", "https://gh-proxy.com/"),
                ("ghproxy.net", "https://ghproxy.net/"),
            )
        )
        accel._extend_default_mirrors(core)
        labels = [label for label, _prefix in core._DEFAULT_RELEASE_MIRRORS]
        self.assertIn("gh.xmly.dev", labels)
        self.assertIn("hub.glowp.xyz", labels)
        self.assertIn("proxy.vvvv.ee", labels)
        self.assertIn("cors.isteed.cc", labels)
        self.assertIn("githubcdn.com", labels)
        self.assertGreaterEqual(len(labels), 9)

    def test_signed_cdn_candidate_uses_token_only_on_github_api(self):
        core = SimpleNamespace(
            _headers=lambda token, accept="": {
                "Authorization": f"Bearer {token}",
                "Accept": accept,
            },
            _public_headers=lambda: {"Accept": "application/octet-stream"},
        )
        response = _FakeResponse(
            status_code=302,
            headers={
                "location": "https://release-assets.githubusercontent.com/github-production-release-asset/x/file.zip?sig=temporary"
            },
        )
        with patch.object(accel.requests, "get", return_value=response) as get:
            candidate = accel._signed_cdn_candidate(
                {"url": "https://api.github.com/repos/o/r/releases/assets/1"},
                "secret-token",
                core,
            )
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate["parallel_ranges"])
        self.assertTrue(candidate["official"])
        self.assertNotIn("Authorization", candidate["headers"])
        self.assertIn("Authorization", get.call_args.kwargs["headers"])
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_signed_cdn_candidate_rejects_untrusted_redirect_host(self):
        core = SimpleNamespace(
            _headers=lambda token, accept="": {"Authorization": f"Bearer {token}"},
            _public_headers=lambda: {},
        )
        response = _FakeResponse(
            status_code=302,
            headers={"location": "https://example.invalid/private.zip?sig=temporary"},
        )
        with patch.object(accel.requests, "get", return_value=response):
            candidate = accel._signed_cdn_candidate(
                {"url": "https://api.github.com/repos/o/r/releases/assets/1"},
                "secret-token",
                core,
            )
        self.assertIsNone(candidate)

    def test_split_ranges_cover_exact_interval_without_gaps(self):
        ranges = accel._split_ranges(11, 100, 6)
        self.assertEqual(ranges[0][0], 11)
        self.assertEqual(ranges[-1][1], 100)
        for left, right in zip(ranges, ranges[1:]):
            self.assertEqual(left[1] + 1, right[0])
        self.assertEqual(sum(end - start + 1 for start, end in ranges), 90)

    def test_validate_content_range_requires_exact_bounds_and_size(self):
        self.assertTrue(accel._validate_content_range("bytes 10-19/100", 10, 19, 100))
        self.assertFalse(accel._validate_content_range("bytes 10-18/100", 10, 19, 100))
        self.assertFalse(accel._validate_content_range("bytes 10-19/101", 10, 19, 100))

    def test_parallel_range_download_resumes_prefix_and_assembles_exact_file(self):
        payload = bytes((index % 251 for index in range(8192)))
        ranges_seen = []

        class Controller:
            _RESET_EVENT = threading.Event()
            _RECONNECT_EVENT = threading.Event()
            _PAUSE_EVENT = threading.Event()
            _ResetRequested = _ResetRequested
            _ReconnectRequested = _ReconnectRequested

            @staticmethod
            def _pause_if_requested(**_kwargs):
                return None

            @staticmethod
            def _write_runtime_state(**kwargs):
                return kwargs

        def fake_get(_url, *, headers, **_kwargs):
            raw = headers["Range"]
            ranges_seen.append(raw)
            start, end = [int(value) for value in raw.removeprefix("bytes=").split("-")]
            return _FakeResponse(
                status_code=206,
                headers={"content-range": f"bytes {start}-{end}/{len(payload)}"},
                body=payload[start : end + 1],
            )

        with tempfile.TemporaryDirectory() as tempdir:
            destination = Path(tempdir) / "package.zip"
            part = destination.with_suffix(destination.suffix + ".part")
            prefix = 777
            part.write_bytes(payload[:prefix])
            candidate = {
                "label": "github-cdn-3x",
                "url": "https://release-assets.githubusercontent.com/file.zip?sig=x",
                "headers": {},
                "parallel_ranges": True,
            }
            with (
                patch.object(accel, "_MIN_PARALLEL_BYTES", 1024),
                patch.object(accel, "_cdn_connections", return_value=3),
                patch.object(accel.requests, "get", side_effect=fake_get),
            ):
                result = accel._parallel_range_download(
                    candidate,
                    destination,
                    len(payload),
                    Controller,
                )
            self.assertEqual(result, len(payload))
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(part.exists())
            self.assertEqual(len(ranges_seen), 2)
            parsed = [
                tuple(int(value) for value in raw.removeprefix("bytes=").split("-"))
                for raw in ranges_seen
            ]
            parsed.sort()
            self.assertEqual(parsed[0][0], prefix)
            self.assertEqual(parsed[-1][1], len(payload) - 1)
            self.assertEqual(parsed[0][1] + 1, parsed[1][0])

    def test_install_is_idempotent_and_wraps_controller_download(self):
        original_candidates = Mock(return_value=[])
        original_download = Mock(return_value=1)
        core = SimpleNamespace(
            _DEFAULT_RELEASE_MIRRORS=(),
            _download_candidates=original_candidates,
            _headers=lambda *_args, **_kwargs: {},
            _public_headers=lambda: {},
        )
        controller = SimpleNamespace(
            _download_one_connection=original_download,
            _ResetRequested=_ResetRequested,
            _ReconnectRequested=_ReconnectRequested,
            _write_runtime_state=Mock(),
        )
        accel.install(core, controller)
        first_candidates = core._download_candidates
        first_download = controller._download_one_connection
        accel.install(core, controller)
        self.assertIs(core._download_candidates, first_candidates)
        self.assertIs(controller._download_one_connection, first_download)
        self.assertTrue(core._cn_release_accelerator_installed)
        self.assertTrue(controller._cn_accel_downloader_installed)


if __name__ == "__main__":
    unittest.main()
