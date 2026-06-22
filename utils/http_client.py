from typing import Any

import requests


def fetch_json_url(url: str, timeout: int = 10) -> Any:
    response = requests.get(url, timeout=timeout, headers={"Accept": "application/json,text/plain,*/*"})
    response.raise_for_status()
    text = response.text.replace("\x00", "").strip()
    return response.json() if text else {}
