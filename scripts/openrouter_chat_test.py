import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
PRIMARY_MODEL = os.getenv("OPENAI_PRIMARY_MODEL", "openrouter/kimi-k2.5")
FALLBACK_MODEL = os.getenv("OPENAI_FALLBACK_MODEL", "openrouter/deepseek-chat-v3:free")
TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))


MODEL_ALIASES = {
    "openrouter/kimi-k2.5": "moonshotai/kimi-k2.5",
    "openrouter/deepseek-chat-v3:free": "deepseek/deepseek-chat-v3-0324",
}


def normalize_model(model: str) -> str:
    m = (model or "").strip()
    if m in MODEL_ALIASES:
        return MODEL_ALIASES[m]
    if m.startswith("openrouter/"):
        return m.split("/", 1)[1]
    return m


def chat_once(model: str, user_text: str) -> dict:
    model_id = normalize_model(model)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "你是一个简洁的助手。"},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.2,
        "max_tokens": 256,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{BASE_URL}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)


def extract_text(result: dict) -> str:
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return ""


def main() -> int:
    if not API_KEY:
        print("ERROR: 缺少 OPENAI_API_KEY", file=sys.stderr)
        return 2
    prompt = "请回复：接口联通成功。"
    errors = []
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            result = chat_once(model, prompt)
            text = extract_text(result)
            if not text:
                errors.append(f"{model}: 返回结构无内容")
                continue
            print(
                json.dumps(
                    {"ok": True, "model": normalize_model(model), "requested_model": model, "content": text},
                    ensure_ascii=False,
                )
            )
            return 0
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}: HTTP {exc.code} {detail}")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
