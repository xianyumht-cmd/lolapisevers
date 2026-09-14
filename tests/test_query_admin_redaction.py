import unittest

from routers.query_admin import _redact_url


class QueryAdminRedactionTests(unittest.TestCase):
    def test_malformed_ipv6_url_is_fully_redacted(self):
        value = "https://[broken?token=top-secret-token"
        self.assertEqual(_redact_url(value), "***")

    def test_invalid_port_url_is_fully_redacted(self):
        value = "https://example.test:not-a-port/query?token=top-secret-token"
        self.assertEqual(_redact_url(value), "***")


if __name__ == "__main__":
    unittest.main()
