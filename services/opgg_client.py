from typing import Optional

import requests


def opgg_request(url: str) -> requests.Response:
    last_exc: Optional[Exception] = None
    for _ in range(2):
        try:
            return requests.get(
                url,
                timeout=25,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
        except Exception as exc:
            last_exc = exc
    raise last_exc or RuntimeError("OP.GG request failed")
