from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "interface-parser-center.json"
CONFIG_SCHEMA = "lapi-parser-center.v1"

_PATH_TOKEN_RE = re.compile(r"([^.[\]]+)|\[(\d+)\]")
_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")
_RECORD_BLOCK_RE = re.compile(r"\{\{#records\}\}(.*?)\{\{/records\}\}", re.DOTALL)
_PARAM_TOKEN_RE = re.compile(r"\$(?:param:)?([A-Za-z_][A-Za-z0-9_.-]*)")
_SECRET_EXACT_RE = re.compile(r"^\$secret:([A-Za-z_][A-Za-z0-9_]*)$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|cookie|api[_-]?key|access[_-]?key)",
    re.I,
)
_PUBLIC_FORBIDDEN_FIELDS = {
    "provider",
    "provider_name",
    "source",
    "by",
    "domain",
    "endpoint",
    "request_url",
    "provider_url",
}


class ParserCenterError(RuntimeError):
    pass


class ParserConfigError(ParserCenterError):
    pass


class ProviderResponseError(ParserCenterError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str
    headers: Dict[str, Any]
    query: Dict[str, Any]
    form: Dict[str, Any]
    json_body: Any
    timeout_seconds: float

    def requests_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "headers": self.headers,
            "timeout": self.timeout_seconds,
        }
        if self.query:
            kwargs["params"] = self.query
        if self.form:
            kwargs["data"] = self.form
        if self.json_body not in (None, {}, []):
            kwargs["json"] = self.json_body
        return kwargs

    def redacted(self) -> Dict[str, Any]:
        return redact(
            {
                "method": self.method,
                "url": self.url,
                "headers": self.headers,
                "query": self.query,
                "form": self.form,
                "json": self.json_body,
                "timeout_seconds": self.timeout_seconds,
            }
        )


@dataclass(frozen=True)
class ProviderExecution:
    status_code: int
    elapsed_ms: int
    content_type: str
    payload: Any
    text: str


_MISSING = object()


def configured_path() -> Path:
    configured = str(os.getenv("INTERFACE_PARSER_CENTER_PATH") or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_CONFIG_PATH


def extract_path(payload: Any, path: str, default: Any = None) -> Any:
    path = str(path or "").strip()
    if not path:
        return payload
    current = payload
    for match in _PATH_TOKEN_RE.finditer(path):
        key, index_text = match.groups()
        if key is not None:
            if not isinstance(current, Mapping) or key not in current:
                return default
            current = current[key]
        else:
            index = int(index_text)
            if not isinstance(current, list) or index >= len(current):
                return default
            current = current[index]
    return current


def extract_first(payload: Any, paths: Iterable[str], default: Any = None) -> Any:
    for path in paths:
        value = extract_path(payload, str(path), _MISSING)
        if value is not _MISSING and value not in (None, ""):
            return value
    return default


def _normalize_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _map_value(value: Any, mapping: Any) -> Any:
    if not isinstance(mapping, Mapping):
        return value
    candidates = [value, _stringify(value), _stringify(value).lower()]
    for candidate in candidates:
        if candidate in mapping:
            return mapping[candidate]
    for key, mapped in mapping.items():
        if _stringify(key).lower() == _stringify(value).lower():
            return mapped
    return value


def parse_field(payload: Any, spec: Any) -> Any:
    if isinstance(spec, str):
        spec = {"paths": [spec]}
    if not isinstance(spec, Mapping):
        raise ParserConfigError("字段解析规则必须是对象或路径字符串")
    paths = _normalize_paths(spec.get("paths") or spec.get("path"))
    default = spec.get("default")
    value = extract_first(payload, paths, default)
    value = _map_value(value, spec.get("map") or spec.get("transform"))
    if spec.get("string") is True:
        value = _stringify(value)
    if spec.get("required") and value in (None, ""):
        raise ProviderResponseError(f"第三方响应缺少必需字段：{paths or ['unknown']}")
    return value


def evaluate_condition(payload: Any, rule: Any, *, status_code: int = 200) -> bool:
    if rule in (None, {}, []):
        return 200 <= int(status_code) < 300
    if isinstance(rule, list):
        return all(evaluate_condition(payload, item, status_code=status_code) for item in rule)
    if not isinstance(rule, Mapping):
        raise ParserConfigError("条件规则必须是对象或数组")
    if "all" in rule:
        values = rule.get("all") if isinstance(rule.get("all"), list) else []
        return all(evaluate_condition(payload, item, status_code=status_code) for item in values)
    if "any" in rule:
        values = rule.get("any") if isinstance(rule.get("any"), list) else []
        return any(evaluate_condition(payload, item, status_code=status_code) for item in values)
    if "status_code" in rule:
        actual: Any = int(status_code)
    else:
        actual = extract_path(payload, str(rule.get("path") or ""), _MISSING)
    op = str(rule.get("op") or "eq").strip().lower()
    expected = rule.get("value")
    if op == "exists":
        return actual is not _MISSING
    if op == "not_exists":
        return actual is _MISSING
    if actual is _MISSING:
        return False
    if op == "truthy":
        return bool(actual)
    if op == "falsy":
        return not bool(actual)
    if op == "eq":
        return actual == expected or _stringify(actual) == _stringify(expected)
    if op == "ne":
        return not evaluate_condition(payload, {**rule, "op": "eq"}, status_code=status_code)
    if op in {"in", "not_in"}:
        choices = expected if isinstance(expected, list) else [expected]
        hit = any(_stringify(actual) == _stringify(item) for item in choices)
        return not hit if op == "not_in" else hit
    if op == "contains":
        return _stringify(expected) in _stringify(actual)
    if op == "regex":
        return bool(re.search(str(expected or ""), _stringify(actual)))
    if op in {"gt", "gte", "lt", "lte"}:
        left = float(actual)
        right = float(expected)
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[op]
    raise ParserConfigError(f"不支持的条件操作：{op}")


def _resolve_scalar(value: Any, parameters: Mapping[str, Any], env: Mapping[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    exact_secret = _SECRET_EXACT_RE.fullmatch(value.strip())
    if exact_secret:
        name = exact_secret.group(1)
        secret = str(env.get(name) or "")
        if not secret:
            raise ParserConfigError(f"Secret 未配置：{name}")
        return secret

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _stringify(parameters.get(key))

    return _PARAM_TOKEN_RE.sub(replace, value)


def resolve_value(value: Any, parameters: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> Any:
    source_env = env or os.environ
    if isinstance(value, Mapping):
        return {
            str(key): resolve_value(item, parameters, source_env)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_value(item, parameters, source_env) for item in value]
    return _resolve_scalar(value, parameters, source_env)


def _redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return value
        query = []
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "***" if _SENSITIVE_KEY_RE.search(key) else item))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return "***"


def redact(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY_RE.search(str(key or "")):
        return "***"
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_url(value)
    return value


def prepare_request(
    provider: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    env: Optional[Mapping[str, str]] = None,
) -> PreparedRequest:
    request_spec = provider.get("request") if isinstance(provider.get("request"), Mapping) else provider
    method = str(request_spec.get("method") or "GET").strip().upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ParserConfigError(f"不支持的请求方法：{method}")
    url = str(resolve_value(request_spec.get("url") or "", parameters, env)).strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ParserConfigError("Provider URL 必须是有效的 http/https 地址")
    headers = resolve_value(request_spec.get("headers") or {}, parameters, env)
    query = resolve_value(request_spec.get("query") or {}, parameters, env)
    form = resolve_value(request_spec.get("form") or {}, parameters, env)
    json_body = resolve_value(request_spec.get("json") or request_spec.get("json_body"), parameters, env)
    try:
        timeout_seconds = max(
            1.0,
            min(float(request_spec.get("timeout_seconds") or request_spec.get("timeout_ms", 10000) / 1000), 60.0),
        )
    except (TypeError, ValueError):
        timeout_seconds = 10.0
    return PreparedRequest(
        method=method,
        url=url,
        headers={str(k): v for k, v in dict(headers or {}).items()},
        query={str(k): v for k, v in dict(query or {}).items()},
        form={str(k): v for k, v in dict(form or {}).items()},
        json_body=json_body,
        timeout_seconds=timeout_seconds,
    )


def execute_request(prepared: PreparedRequest) -> ProviderExecution:
    started = time.monotonic()
    response = requests.request(prepared.method, prepared.url, **prepared.requests_kwargs())
    elapsed_ms = int((time.monotonic() - started) * 1000)
    text = response.content.decode("utf-8", errors="replace").strip().lstrip("\ufeff")
    content_type = str(response.headers.get("content-type") or "")
    try:
        payload: Any = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = text
    return ProviderExecution(
        status_code=int(response.status_code),
        elapsed_ms=elapsed_ms,
        content_type=content_type,
        payload=payload,
        text=text,
    )


def _error_message(payload: Any, parser: Mapping[str, Any], status_code: int) -> str:
    paths = _normalize_paths(parser.get("error_message_paths") or ["msg", "message", "error", "detail"])
    message = extract_first(payload, paths, "")
    if message not in (None, ""):
        return _stringify(message)[:500]
    return f"第三方接口返回错误（HTTP {status_code}）"


def _determine_outcome(payload: Any, parser: Mapping[str, Any], status_code: int) -> str:
    rules = parser.get("outcomes") or parser.get("outcome_rules") or []
    if isinstance(rules, Mapping):
        rules = [
            {"name": str(name), **(dict(rule) if isinstance(rule, Mapping) else {})}
            for name, rule in rules.items()
        ]
    if isinstance(rules, list):
        for item in rules:
            if not isinstance(item, Mapping):
                continue
            condition = item.get("when") or item.get("condition") or {
                key: item[key]
                for key in ("path", "op", "value", "status_code")
                if key in item
            }
            if evaluate_condition(payload, condition, status_code=status_code):
                return str(item.get("name") or item.get("outcome") or "unknown").strip() or "unknown"
    return str(parser.get("default_outcome") or "unknown").strip() or "unknown"


def _parse_fields(payload: Any, parser: Mapping[str, Any]) -> Dict[str, Any]:
    fields_spec = parser.get("fields") if isinstance(parser.get("fields"), Mapping) else {}
    return {str(name): parse_field(payload, spec) for name, spec in fields_spec.items()}


def _parse_records(payload: Any, parser: Mapping[str, Any]) -> list[Dict[str, Any]]:
    spec = parser.get("records") if isinstance(parser.get("records"), Mapping) else {}
    if not spec:
        return []
    items = extract_first(payload, _normalize_paths(spec.get("paths") or spec.get("path")), [])
    if not isinstance(items, list):
        return []
    fields_spec = spec.get("fields") if isinstance(spec.get("fields"), Mapping) else {}
    limit = max(0, min(int(spec.get("limit") or 20), 100))
    result: list[Dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, (Mapping, list)):
            continue
        record = {str(name): parse_field(item, field_spec) for name, field_spec in fields_spec.items()}
        if record:
            result.append(record)
    return result


def _template_fields(template: str) -> set[str]:
    fields: set[str] = set()
    for match in _TEMPLATE_RE.finditer(template):
        expression = str(match.group(1) or "").strip()
        name = expression.split("|", 1)[0].strip()
        if name:
            fields.add(name)
    return fields


def validate_public_template(template: str, *, provider_url: str = "") -> None:
    fields = {item.lower() for item in _template_fields(template)}
    forbidden = sorted(fields.intersection(_PUBLIC_FORBIDDEN_FIELDS))
    if forbidden:
        raise ParserConfigError(f"公开模板禁止输出来源字段：{', '.join(forbidden)}")
    try:
        hostname = (urlsplit(provider_url).hostname or "").lower()
    except Exception:
        hostname = ""
    if hostname and hostname in template.lower():
        raise ParserConfigError("公开模板禁止包含第三方域名")


def _replace_placeholders(template: str, values: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = str(match.group(1) or "")
        name, separator, fallback = expression.partition("|")
        value = values.get(name.strip())
        text = _stringify(value)
        return text if text else fallback.strip() if separator else ""

    return _TEMPLATE_RE.sub(replace, template)


def render_template(template: str, fields: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> str:
    records_list = [dict(item) for item in records]

    def render_records(match: re.Match[str]) -> str:
        block = match.group(1)
        chunks: list[str] = []
        for index, record in enumerate(records_list, start=1):
            values = {**fields, **record, "index": index, "序号": index}
            rendered = _replace_placeholders(block, values).strip()
            if rendered:
                chunks.append(rendered)
        return "\n".join(chunks)

    expanded = _RECORD_BLOCK_RE.sub(render_records, template)
    return _replace_placeholders(expanded, fields).strip()


def parse_response(
    provider: Mapping[str, Any],
    payload: Any,
    *,
    status_code: int = 200,
) -> Dict[str, Any]:
    parser = provider.get("parser") if isinstance(provider.get("parser"), Mapping) else {}
    success_condition = parser.get("success") or parser.get("success_condition")
    if not evaluate_condition(payload, success_condition, status_code=status_code):
        raise ProviderResponseError(
            _error_message(payload, parser, status_code),
            status_code=502 if 200 <= status_code < 500 else 503,
        )
    outcome = _determine_outcome(payload, parser, status_code)
    fields = _parse_fields(payload, parser)
    records = _parse_records(payload, parser)
    templates = parser.get("templates") if isinstance(parser.get("templates"), Mapping) else {}
    template = str(templates.get(outcome) or templates.get("default") or "").strip()
    provider_url = str(
        (provider.get("request") if isinstance(provider.get("request"), Mapping) else provider).get("url")
        or ""
    )
    if template:
        validate_public_template(template, provider_url=provider_url)
    public_text = render_template(template, fields, records) if template else ""
    return {
        "outcome": outcome,
        "fields": fields,
        "records": records,
        "public_text": public_text,
    }


def to_lolban_payload(qq: str, parsed: Mapping[str, Any]) -> Dict[str, Any]:
    fields = parsed.get("fields") if isinstance(parsed.get("fields"), Mapping) else {}
    status = _stringify(fields.get("status"))
    if status not in {"正常", "封禁"}:
        outcome = str(parsed.get("outcome") or "")
        status = "封禁" if outcome == "hit" else "正常" if outcome == "clear" else ""
    if status not in {"正常", "封禁"}:
        raise ProviderResponseError("第三方响应无法判定账号状态")
    upstream_qq = _stringify(fields.get("qq"))
    if upstream_qq and upstream_qq != qq:
        raise ProviderResponseError("第三方响应账号与查询账号不一致")
    ban_reason = _stringify(fields.get("ban_reason"))
    if status == "封禁" and not ban_reason:
        ban_reason = "第三方接口未提供封禁原因"
    result = {
        "code": 200,
        "by": "configured-provider",
        "msg": "此账号状态正常" if status == "正常" else "此账号已被封禁",
        "data": {
            "qq": qq,
            "status": status,
            "ban_time": _stringify(fields.get("ban_time")),
            "end_time": _stringify(fields.get("end_time") or fields.get("remaining_time")),
            "ban_reason": ban_reason,
        },
    }
    public_text = _stringify(parsed.get("public_text"))
    if public_text:
        result["public_text"] = public_text
    return result


def validate_provider(provider: Mapping[str, Any]) -> None:
    provider_id = str(provider.get("id") or provider.get("name") or "").strip()
    if not provider_id:
        raise ParserConfigError("Provider 缺少 id")
    request_spec = provider.get("request") if isinstance(provider.get("request"), Mapping) else provider
    method = str(request_spec.get("method") or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ParserConfigError(f"Provider {provider_id} 请求方法无效")
    raw_url = str(request_spec.get("url") or "").strip()
    sample_url = _PARAM_TOKEN_RE.sub("sample", raw_url)
    parts = urlsplit(sample_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ParserConfigError(f"Provider {provider_id} URL 无效")
    parser = provider.get("parser") if isinstance(provider.get("parser"), Mapping) else {}
    templates = parser.get("templates") if isinstance(parser.get("templates"), Mapping) else {}
    for template in templates.values():
        validate_public_template(str(template or ""), provider_url=raw_url)


def validate_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ParserConfigError("解析中心配置必须是 JSON 对象")
    normalized = copy.deepcopy(dict(config))
    if normalized.get("schema") != CONFIG_SCHEMA:
        raise ParserConfigError(f"解析中心 schema 必须是 {CONFIG_SCHEMA}")
    features = normalized.get("features")
    if not isinstance(features, Mapping):
        raise ParserConfigError("解析中心配置缺少 features 对象")
    for feature_name, feature in features.items():
        if not isinstance(feature, Mapping):
            raise ParserConfigError(f"功能 {feature_name} 配置必须是对象")
        providers = feature.get("providers")
        if not isinstance(providers, list):
            raise ParserConfigError(f"功能 {feature_name} 缺少 providers 数组")
        seen: set[str] = set()
        for provider in providers:
            if not isinstance(provider, Mapping):
                raise ParserConfigError(f"功能 {feature_name} Provider 必须是对象")
            validate_provider(provider)
            provider_id = str(provider.get("id") or provider.get("name") or "").strip()
            if provider_id in seen:
                raise ParserConfigError(f"功能 {feature_name} Provider id 重复：{provider_id}")
            seen.add(provider_id)
    return normalized


def empty_config() -> Dict[str, Any]:
    return {"schema": CONFIG_SCHEMA, "features": {}}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path or configured_path())
    if not target.is_file():
        return empty_config()
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParserConfigError("解析中心配置无法读取或不是有效 JSON") from exc
    return validate_config(raw)


def enabled_providers(feature: str, *, operation: str = "query", path: Optional[Path] = None) -> list[Dict[str, Any]]:
    config = load_config(path)
    feature_config = config.get("features", {}).get(feature)
    if not isinstance(feature_config, Mapping):
        return []
    configured_operation = str(feature_config.get("operation") or "query").strip().lower()
    if configured_operation != operation:
        return []
    providers = feature_config.get("providers") if isinstance(feature_config.get("providers"), list) else []
    return [copy.deepcopy(dict(item)) for item in providers if isinstance(item, Mapping) and item.get("enabled") is True]


def find_provider(config: Mapping[str, Any], feature: str, provider_id: str) -> Dict[str, Any]:
    feature_config = config.get("features", {}).get(feature)
    providers = feature_config.get("providers") if isinstance(feature_config, Mapping) else []
    for provider in providers if isinstance(providers, list) else []:
        if isinstance(provider, Mapping) and str(provider.get("id") or "") == provider_id:
            return copy.deepcopy(dict(provider))
    raise ParserConfigError("未找到指定 Provider")


def test_provider(provider: Mapping[str, Any], parameters: Mapping[str, Any]) -> Dict[str, Any]:
    validate_provider(provider)
    prepared = prepare_request(provider, parameters)
    execution = execute_request(prepared)
    parsed = parse_response(provider, execution.payload, status_code=execution.status_code)
    return {
        "ok": True,
        "request": prepared.redacted(),
        "response": {
            "status_code": execution.status_code,
            "elapsed_ms": execution.elapsed_ms,
            "content_type": execution.content_type,
            "payload": redact(execution.payload),
        },
        "parsed": redact(parsed),
        "public_text": parsed.get("public_text") or "",
    }


def atomic_write_config(config: Mapping[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    normalized = validate_config(config)
    target = Path(path or configured_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = ""
    if target.is_file():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = target.with_name(f"{target.name}.bak.{stamp}")
        backup.write_bytes(target.read_bytes())
        backup_path = str(backup)
    text = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "ok": True,
        "path": str(target),
        "backup_path": backup_path,
        "config": redact(normalized),
    }
