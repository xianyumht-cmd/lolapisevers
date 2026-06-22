import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from so1_client import LEGACY_HISTORY_URL, So1Client


BASE_URL = "http://127.0.0.1:5001"

CASES: List[Dict[str, str]] = [
    {"name": "新的朋友#58527", "region": ""},
    {"name": "呆呆大王#68512", "region": "班德尔城"},
]


def get_json(path: str, timeout: int = 45) -> Dict[str, Any]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def query_case(case: Dict[str, str]) -> Dict[str, Any]:
    params = {
        "name": case["name"],
        "output": "pretty",
    }
    if case.get("region"):
        params["region"] = case["region"]
    path = f"/cross_query?{urllib.parse.urlencode(params)}"
    started = time.perf_counter()
    payload = get_json(path)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        "name": case["name"],
        "region": case.get("region", ""),
        "elapsed_ms": elapsed_ms,
        "source": payload.get("source"),
        "raw_ok": payload.get("raw_ok"),
        "matches": len(payload.get("recent_matches") or []),
        "fallback_reason": payload.get("fallback_reason", ""),
    }


def main() -> int:
    results: Dict[str, Any] = {"health": get_json("/health"), "cases": [], "synthetic": {}}
    failures = []
    client = So1Client(username="", password="")
    synthetic_raw = client._build_legacy_payload(
        {
            "overview": {
                "success": True,
                "data": {
                    "base": {"gameName": "empty", "tagLine": "0000", "level": 1},
                    "ranked": {"queues": []},
                },
            },
            "match_analysis": {"success": True, "data": {"matchHistory": []}},
        }
    )
    empty_history_ok = synthetic_raw[LEGACY_HISTORY_URL].get("success") is True
    results["synthetic"]["empty_history_success"] = empty_history_ok
    if not empty_history_ok:
        failures.append("empty matchHistory should be treated as a successful empty result")
    for case in CASES:
        try:
            result = query_case(case)
            results["cases"].append(result)
            if result["raw_ok"] is not True:
                failures.append(f"{case['name']} returned raw_ok={result['raw_ok']}")
        except Exception as exc:
            failures.append(f"{case['name']} failed: {exc}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if failures:
        print("FAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
