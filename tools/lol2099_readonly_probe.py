from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from playwright.async_api import async_playwright

TARGET = "https://lol2099.top/"
TEST_QQ = "10000"
OUTPUT = Path("lol2099-readonly-probe.json")
MAX_BODY = 200_000

SENSITIVE_KEYS = {
    "token",
    "key",
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
}


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        safe_query = []
        for key, val in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in SENSITIVE_KEYS or any(word in key.lower() for word in ("token", "secret", "pass", "key")):
                val = "***"
            safe_query.append((key, val))
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, urlencode(safe_query), parsed.fragment))
    except Exception:
        return value


def redact_text(value: str) -> str:
    text = str(value or "")[:MAX_BODY]
    text = re.sub(
        r'(?i)(token|api[_-]?key|authorization|password|secret)(\s*[=:]\s*)[^&\s"\']+',
        lambda match: f"{match.group(1)}{match.group(2)}***",
        text,
    )
    return text


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in {"cookie", "set-cookie", "authorization", "proxy-authorization"}:
            result[key] = "***"
        else:
            result[key] = redact_text(value)
    return result


async def main() -> None:
    report: dict[str, Any] = {
        "target": TARGET,
        "test_qq": TEST_QQ,
        "mode": "read-only single form submission",
        "requests": [],
        "responses": [],
        "forms": [],
        "inputs": [],
        "buttons": [],
        "scripts": [],
        "errors": [],
    }

    # Also capture the paid API's unauthenticated/invalid-token response shape.
    for token_value in ("", "invalid-probe-token"):
        try:
            response = requests.get(
                "https://yun.4png.com/api/query.html",
                params={"qq": TEST_QQ, "token": token_value},
                timeout=15,
                headers={"User-Agent": "LOLDataSystem-readonly-probe/1.0"},
            )
            report.setdefault("four_png", []).append(
                {
                    "request_url": redact_url(response.url),
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "body": redact_text(response.text),
                }
            )
        except Exception as exc:
            report.setdefault("four_png", []).append({"error_class": type(exc).__name__})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        )
        page = await context.new_page()
        submission_started = False

        def on_request(request: Any) -> None:
            nonlocal submission_started
            if not submission_started:
                return
            resource_type = str(request.resource_type or "")
            if resource_type in {"image", "font", "stylesheet", "media"}:
                return
            report["requests"].append(
                {
                    "method": request.method,
                    "url": redact_url(request.url),
                    "resource_type": resource_type,
                    "headers": safe_headers(request.headers),
                    "post_data": redact_text(request.post_data or ""),
                }
            )

        async def on_response(response: Any) -> None:
            if not submission_started:
                return
            resource_type = str(response.request.resource_type or "")
            if resource_type in {"image", "font", "stylesheet", "media"}:
                return
            item: dict[str, Any] = {
                "status": response.status,
                "url": redact_url(response.url),
                "resource_type": resource_type,
                "headers": safe_headers(await response.all_headers()),
            }
            try:
                body = await response.text()
                item["body"] = redact_text(body)
            except Exception as exc:
                item["body_error"] = type(exc).__name__
            report["responses"].append(item)

        page.on("request", on_request)
        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        try:
            await page.goto(TARGET, wait_until="networkidle", timeout=60_000)
            report["title"] = await page.title()
            report["initial_url"] = redact_url(page.url)
            report["forms"] = await page.locator("form").evaluate_all(
                "els => els.map((e, i) => ({index:i, action:e.action, method:e.method, html:e.outerHTML.slice(0,4000)}))"
            )
            report["inputs"] = await page.locator("input").evaluate_all(
                "els => els.map((e, i) => ({index:i, type:e.type, name:e.name, id:e.id, placeholder:e.placeholder, value:e.type === 'password' ? '***' : e.value}))"
            )
            report["buttons"] = await page.locator("button, input[type=submit]").evaluate_all(
                "els => els.map((e, i) => ({index:i, tag:e.tagName, type:e.type, id:e.id, name:e.name, text:(e.innerText || e.value || '').trim()}))"
            )
            report["scripts"] = await page.locator("script").evaluate_all(
                "els => els.map((e, i) => ({index:i, src:e.src, inline:e.src ? '' : (e.textContent || '').slice(0,12000)}))"
            )

            candidate = page.locator(
                "input[name*=qq i], input[id*=qq i], input[placeholder*=QQ i], input[type=number], input[type=text]"
            ).first
            if await candidate.count() == 0:
                raise RuntimeError("No query input found")
            await candidate.fill(TEST_QQ)

            submission_started = True
            query_button = page.get_by_text(re.compile("查询|封禁状态"), exact=False).last
            if await query_button.count() > 0:
                await query_button.click(timeout=15_000)
            else:
                await candidate.press("Enter")
            await page.wait_for_timeout(8_000)
            report["final_url"] = redact_url(page.url)
            report["final_text"] = redact_text(await page.locator("body").inner_text())
        except Exception as exc:
            report["errors"].append({"error_class": type(exc).__name__, "message": redact_text(str(exc))})
        finally:
            await browser.close()

    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
