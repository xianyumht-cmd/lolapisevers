from __future__ import annotations

from typing import Any, Dict

from services.api_parser_center import ParserConfigError, PreparedRequest


_ENCODING_HEADER = "x-lapi-request-encoding"
_INSTALLED_MARKER = "_lapi_multipart_support_installed"


def _pop_header_case_insensitive(headers: Dict[str, Any], name: str) -> str:
    expected = name.strip().lower()
    for key in list(headers):
        if str(key).strip().lower() == expected:
            return str(headers.pop(key) or "").strip().lower()
    return ""


def _has_header_case_insensitive(headers: Dict[str, Any], name: str) -> bool:
    expected = name.strip().lower()
    return any(str(key).strip().lower() == expected for key in headers)


def _multipart_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def install_parser_center_multipart_support() -> None:
    """Teach PreparedRequest to send configured form fields as multipart text parts.

    Parser-center configuration selects this transport with the internal header
    ``X-LAPI-Request-Encoding: multipart``. The selector is removed before the
    request is sent. Requests generates the Content-Type boundary itself; a
    manually configured Content-Type is rejected because it would omit or
    corrupt that boundary.
    """

    if bool(getattr(PreparedRequest, _INSTALLED_MARKER, False)):
        return

    def requests_kwargs(self: PreparedRequest) -> Dict[str, Any]:
        headers = {str(key): value for key, value in dict(self.headers or {}).items()}
        encoding = _pop_header_case_insensitive(headers, _ENCODING_HEADER)
        if encoding not in {"", "form", "urlencoded", "multipart"}:
            raise ParserConfigError(f"不支持的请求编码：{encoding}")

        kwargs: Dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout_seconds,
        }
        if self.query:
            kwargs["params"] = self.query

        if encoding == "multipart":
            if self.json_body not in (None, {}, []):
                raise ParserConfigError("multipart 请求不能同时配置 JSON Body")
            if _has_header_case_insensitive(headers, "content-type"):
                raise ParserConfigError(
                    "multipart 请求不得手工设置 Content-Type；boundary 必须由 HTTP 客户端生成"
                )
            if not self.form:
                raise ParserConfigError("multipart 请求至少需要一个表单字段")
            kwargs["files"] = [
                (str(key), (None, _multipart_text(value)))
                for key, value in dict(self.form).items()
            ]
        else:
            if self.form:
                kwargs["data"] = self.form
            if self.json_body not in (None, {}, []):
                kwargs["json"] = self.json_body
        return kwargs

    setattr(PreparedRequest, "requests_kwargs", requests_kwargs)
    setattr(PreparedRequest, _INSTALLED_MARKER, True)
