from typing import Optional

import requests


DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
DEFAULT_READ_TIMEOUT_SECONDS = 7.0
DEFAULT_ATTEMPTS = 2
MAX_ATTEMPTS = 2
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def opgg_request(
    url: str,
    *,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
) -> requests.Response:
    """Fetch an OP.GG page within a bounded retry budget.

    The default worst-case socket timeout budget is about 20 seconds
    (two attempts at 3 seconds to connect plus 7 seconds to read).
    """

    last_exc: Optional[Exception] = None
    bounded_attempts = max(1, min(int(attempts), MAX_ATTEMPTS))
    for attempt in range(bounded_attempts):
        try:
            response = requests.get(
                url,
                timeout=(max(float(connect_timeout), 0.1), max(float(read_timeout), 0.1)),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 >= bounded_attempts:
                return response
            close = getattr(response, "close", None)
            if callable(close):
                close()
        except Exception as exc:
            last_exc = exc
    raise last_exc or RuntimeError("OP.GG request failed")
