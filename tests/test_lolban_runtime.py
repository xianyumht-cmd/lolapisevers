from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.lolban_runtime import LolBanRuntime


class FakeService:
    def __init__(self, name: str) -> None:
        self.name = name


class LolBanRuntimeTests(unittest.TestCase):
    def test_successful_reload_swaps_service_and_environment(self) -> None:
        original = FakeService("old")
        replacement = FakeService("new")
        runtime = LolBanRuntime(original, service_factory=lambda: replacement)
        loaded_at = runtime.loaded_at()

        with patch.dict(os.environ, {"LOL_BAN_TIMEOUT": "10"}, clear=False):
            result = runtime.reload({"LOL_BAN_TIMEOUT": "12"})
            self.assertIs(result, replacement)
            self.assertIs(runtime.service(), replacement)
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "12")
            self.assertGreaterEqual(runtime.loaded_at(), loaded_at)

    def test_failed_reload_keeps_service_environment_and_loaded_at(self) -> None:
        original = FakeService("old")

        def fail() -> FakeService:
            raise RuntimeError("invalid provider configuration")

        runtime = LolBanRuntime(original, service_factory=fail)
        loaded_at = runtime.loaded_at()

        with patch.dict(os.environ, {"LOL_BAN_TIMEOUT": "10"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "invalid provider configuration"):
                runtime.reload(
                    {
                        "LOL_BAN_TIMEOUT": "99",
                        "LOL_BAN_4PNG_TOKEN": "temporary-secret",
                    }
                )
            self.assertIs(runtime.service(), original)
            self.assertEqual(runtime.loaded_at(), loaded_at)
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "10")
            self.assertNotIn("LOL_BAN_4PNG_TOKEN", os.environ)


if __name__ == "__main__":
    unittest.main()
