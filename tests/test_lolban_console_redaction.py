from __future__ import annotations

import unittest

from lanzou_update_push_api_server.lolban_console import _redact_url


class LolbanConsoleRedactionTests(unittest.TestCase):
    def test_malformed_ipv6_credential_url_fails_closed(self) -> None:
        value = "https://user:secret@[::1/query?token=literal-token"
        self.assertEqual(_redact_url(value), "***")

    def test_invalid_port_credential_url_fails_closed(self) -> None:
        value = "https://user:secret@example.test:not-a-port/query?token=literal-token"
        self.assertEqual(_redact_url(value), "***")

    def test_valid_url_still_masks_credentials_and_sensitive_query(self) -> None:
        value = "https://user:secret@example.test/query?qq=97077000&token=literal-token"
        redacted = _redact_url(value)
        self.assertNotIn("user", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("literal-token", redacted)
        self.assertIn("qq=97077000", redacted)
        self.assertIn("token=%2A%2A%2A", redacted)


if __name__ == "__main__":
    unittest.main()
