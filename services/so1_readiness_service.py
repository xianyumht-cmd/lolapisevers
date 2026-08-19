import asyncio
import json
import os
import time
from typing import Any, Dict


_RECOVERY_MIN_INTERVAL_SECONDS = 60.0
_RECOVERY_FAILURE_COOLDOWN_SECONDS = 300.0
_RECOVERABLE_REASONS = {
    "session_missing",
    "session_state_invalid",
    "session_expired",
    # Backward compatibility with the old probe reason.
    "session_expired_or_challenge",
}
_CHALLENGE_MARKERS = (
    "captcha",
    "verify you are human",
    "checking your browser",
    "cloudflare",
    "人机验证",
    "安全验证",
    "请完成验证",
    "验证码",
)


def _result(
    *,
    browser_up: bool,
    authenticated: bool,
    reason: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "browser_up": browser_up,
        "session_authenticated": authenticated,
        "reason": reason,
    }
    payload.update(extra)
    return payload


def _state_status(client: Any) -> str:
    path = str(getattr(client, "_state_path", "") or "")
    if not path or not os.path.isfile(path):
        return "missing"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return "invalid"
    except (OSError, ValueError, TypeError):
        return "invalid"
    return "valid"


def _supports_recovery(client: Any) -> bool:
    browser = getattr(client, "_browser", None)
    login = getattr(client, "_login", None)
    return (
        browser is not None
        and callable(getattr(browser, "new_context", None))
        and callable(login)
    )


def _get_recovery_lock(client: Any) -> asyncio.Lock:
    lock = getattr(client, "_readiness_recovery_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(client, "_readiness_recovery_lock", lock)
    return lock


def _clear_recovery_state(client: Any) -> None:
    setattr(client, "_readiness_recovery_blocked_until", 0.0)
    setattr(client, "_readiness_recovery_last_attempt_at", 0.0)
    setattr(client, "_readiness_recovery_last_failure_at", 0.0)
    setattr(client, "_readiness_recovery_block_reason", "")


def _blocked_result(client: Any, now: float) -> Dict[str, Any] | None:
    blocked_until = float(
        getattr(client, "_readiness_recovery_blocked_until", 0.0) or 0.0
    )
    if blocked_until > now:
        reason = str(
            getattr(client, "_readiness_recovery_block_reason", "")
            or "login_cooldown"
        )
        return _result(
            browser_up=True,
            authenticated=False,
            reason=reason,
            recovery="blocked",
            recovery_retry_after_seconds=max(1, int(blocked_until - now + 0.999)),
        )

    last_failure = float(
        getattr(client, "_readiness_recovery_last_failure_at", 0.0) or 0.0
    )
    if last_failure:
        retry_at = last_failure + _RECOVERY_FAILURE_COOLDOWN_SECONDS
        if retry_at > now:
            return _result(
                browser_up=True,
                authenticated=False,
                reason="login_cooldown",
                recovery="cooldown",
                recovery_retry_after_seconds=max(1, int(retry_at - now + 0.999)),
            )

    last_attempt = float(
        getattr(client, "_readiness_recovery_last_attempt_at", 0.0) or 0.0
    )
    if last_attempt:
        retry_at = last_attempt + _RECOVERY_MIN_INTERVAL_SECONDS
        if retry_at > now:
            return _result(
                browser_up=True,
                authenticated=False,
                reason="login_cooldown",
                recovery="cooldown",
                recovery_retry_after_seconds=max(1, int(retry_at - now + 0.999)),
            )
    return None


async def _page_snapshot(page: Any) -> Dict[str, Any]:
    try:
        value = await page.evaluate(
            """() => {
                const text = document.body && document.body.innerText
                    ? document.body.innerText
                    : ''
                return {
                    url: String(location.href || ''),
                    title: String(document.title || ''),
                    text: text.slice(0, 3000)
                }
            }"""
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _challenge_detected(snapshot: Dict[str, Any]) -> bool:
    haystack = " ".join(
        str(snapshot.get(key) or "")
        for key in ("url", "title", "text")
    ).lower()
    return any(marker in haystack for marker in _CHALLENGE_MARKERS)


async def _user_me_payload(page: Any) -> Dict[str, Any]:
    value = await page.evaluate(
        """async () => {
            try {
                const res = await fetch('https://r1.lolso1.com/user/me', {
                    method: 'GET',
                    credentials: 'include',
                    cache: 'no-store'
                })
                const data = await res.json().catch(() => null)
                return {status: res.status, ok: res.ok, data}
            } catch (error) {
                return {status: 0, ok: false, data: null}
            }
        }"""
    )
    return value if isinstance(value, dict) else {}


def _classify_user_me(payload: Dict[str, Any]) -> tuple[bool, str]:
    status = int(payload.get("status") or 0)
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    err_code = str(data.get("errCode") or data.get("code") or "").upper()
    user_data = data.get("data")
    user_data = user_data if isinstance(user_data, dict) else {}

    if err_code in {"0000", "0"} and str(user_data.get("username") or "").strip():
        return True, "authenticated"
    if status in {401, 403}:
        return False, "session_expired"
    if "UNAUTHORIZED" in err_code or "NOT_LOGIN" in err_code or "LOGIN_REQUIRED" in err_code:
        return False, "session_expired"
    if status == 429:
        return False, "upstream_rate_limited"
    if status >= 500:
        return False, "upstream_unavailable"
    return False, "session_rejected"


async def _open_context(client: Any, state_status: str) -> Any:
    browser = getattr(client, "_browser", None)
    if browser is None:
        raise RuntimeError("browser_unavailable")
    state_path = str(getattr(client, "_state_path", "") or "")
    if state_status == "valid":
        return await browser.new_context(storage_state=state_path)
    return await browser.new_context()


async def _fresh_probe(client: Any) -> Dict[str, Any]:
    probe = getattr(client, "check_readiness", None)
    if not callable(probe):
        return _result(
            browser_up=False,
            authenticated=False,
            reason="session_probe_unavailable",
        )
    try:
        value = await probe(ttl_seconds=0.0)
    except TypeError:
        value = await probe()
    return value if isinstance(value, dict) else {}


async def _recover_or_refine(
    client: Any,
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    if not bool(baseline.get("browser_up")):
        return baseline

    if not _supports_recovery(client):
        return baseline

    state_status = _state_status(client)
    baseline_reason = str(baseline.get("reason") or "")
    if state_status == "invalid":
        baseline_reason = "session_state_invalid"
    elif state_status == "missing":
        baseline_reason = "session_missing"
    if baseline_reason not in _RECOVERABLE_REASONS:
        return baseline

    lock = _get_recovery_lock(client)
    async with lock:
        # A query or another readiness request may already have refreshed state.
        fresh = await _fresh_probe(client)
        if bool(fresh.get("browser_up")) and bool(
            fresh.get("session_authenticated")
        ):
            _clear_recovery_state(client)
            return fresh

        state_status = _state_status(client)
        fresh_reason = str(fresh.get("reason") or baseline_reason)
        if state_status == "invalid":
            fresh_reason = "session_state_invalid"
        elif state_status == "missing":
            fresh_reason = "session_missing"
        if fresh_reason not in _RECOVERABLE_REASONS:
            return fresh or baseline

        now = time.monotonic()
        blocked = _blocked_result(client, now)
        if blocked is not None:
            blocked["original_reason"] = fresh_reason
            return blocked

        username = str(getattr(client, "username", "") or "").strip()
        password = str(getattr(client, "password", "") or "").strip()
        if not username or not password:
            return _result(
                browser_up=True,
                authenticated=False,
                reason="credentials_missing",
                recovery="not_attempted",
                original_reason=fresh_reason,
            )

        context = None
        try:
            context = await _open_context(client, state_status)
            page = await context.new_page()
            timeout_ms = int(getattr(client, "timeout_ms", 10000) or 10000)
            await page.goto(
                "https://lolso1.com/",
                wait_until="domcontentloaded",
                timeout=min(max(timeout_ms, 1000), 8000),
            )

            snapshot = await _page_snapshot(page)
            if _challenge_detected(snapshot):
                blocked_until = now + _RECOVERY_FAILURE_COOLDOWN_SECONDS
                setattr(client, "_readiness_recovery_blocked_until", blocked_until)
                setattr(
                    client,
                    "_readiness_recovery_block_reason",
                    "challenge_detected",
                )
                setattr(client, "_readiness_recovery_last_attempt_at", now)
                return _result(
                    browser_up=True,
                    authenticated=False,
                    reason="challenge_detected",
                    recovery="blocked",
                    recovery_retry_after_seconds=int(
                        _RECOVERY_FAILURE_COOLDOWN_SECONDS
                    ),
                    original_reason=fresh_reason,
                )

            me_payload = await _user_me_payload(page)
            authenticated, classified_reason = _classify_user_me(me_payload)
            if authenticated:
                _clear_recovery_state(client)
                return _result(
                    browser_up=True,
                    authenticated=True,
                    reason="authenticated",
                    recovery="already_recovered",
                    original_reason=fresh_reason,
                )

            if classified_reason not in {"session_expired", "session_rejected"}:
                return _result(
                    browser_up=True,
                    authenticated=False,
                    reason=classified_reason,
                    recovery="not_attempted",
                    original_reason=fresh_reason,
                )

            setattr(client, "_readiness_recovery_last_attempt_at", now)
            try:
                await client._login(page)
            except Exception as exc:
                setattr(client, "_readiness_recovery_last_failure_at", now)
                return _result(
                    browser_up=True,
                    authenticated=False,
                    reason="login_failed",
                    recovery="failed",
                    recovery_retry_after_seconds=int(
                        _RECOVERY_FAILURE_COOLDOWN_SECONDS
                    ),
                    original_reason=classified_reason,
                    error_class=type(exc).__name__,
                )

            _clear_recovery_state(client)
            return _result(
                browser_up=True,
                authenticated=True,
                reason="authenticated",
                recovery="auto_recovered",
                original_reason=classified_reason,
            )
        except Exception as exc:
            setattr(client, "_readiness_recovery_last_failure_at", now)
            return _result(
                browser_up=True,
                authenticated=False,
                reason="session_probe_failed",
                recovery="failed",
                recovery_retry_after_seconds=int(
                    _RECOVERY_FAILURE_COOLDOWN_SECONDS
                ),
                original_reason=fresh_reason,
                error_class=type(exc).__name__,
            )
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass


async def ensure_so1_readiness(client: Any) -> Dict[str, Any]:
    """Return SO1 readiness and self-heal a recoverable expired/missing session.

    Healthy probes remain read-only and cheap. Recovery is single-flight, rate
    limited, challenge-aware, and exposes only safe reason/error-class metadata.
    """
    probe = getattr(client, "check_readiness", None)
    if not callable(probe):
        return _result(
            browser_up=False,
            authenticated=False,
            reason="session_probe_unavailable",
        )

    value = await probe()
    baseline = value if isinstance(value, dict) else {}
    if bool(baseline.get("browser_up")) and bool(
        baseline.get("session_authenticated")
    ):
        _clear_recovery_state(client)
        return baseline
    return await _recover_or_refine(client, baseline)
