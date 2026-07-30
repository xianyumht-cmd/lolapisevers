import json
import unittest

import requests

from services.upstream_http_client import UpstreamHttpClient


class RaisingSession:
    def __init__(self, message):
        self.message = message

    def request(self, _method, _url, **_kwargs):
        raise requests.exceptions.ReadTimeout(self.message)


class UpstreamHttpClientRedactionTests(unittest.TestCase):
    def test_exception_containing_full_url_is_redacted(self):
        secret_url = "https://user:password@example.invalid/private?token=secret"
        client = UpstreamHttpClient(
            session=RaisingSession(f"read timed out for {secret_url}"),
            attempts=1,
            sleep_fn=lambda _seconds: None,
        )

        result = client.get_json("redacted-source", secret_url)
        rendered = json.dumps(result.__dict__, default=lambda value: value.__dict__)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.error_class, "read_timeout")
        self.assertNotIn(secret_url, rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn("token=secret", rendered)
        self.assertIn("[redacted]", rendered)
        self.assertIn("redacted-source", rendered)


if __name__ == "__main__":
    unittest.main()
