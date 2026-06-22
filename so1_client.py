import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class So1ClientError(Exception):
    pass


LEGACY_BASIC_URL = "https://ww1.lolso1.com/game-lol/customize-summoner-basic-by-name-region"
LEGACY_RANKED_URL = "https://ww1.lolso1.com/game-lol/origin-summoner-ranked-stats"
LEGACY_HISTORY_URL = "https://ww1.lolso1.com/game-lol/customize-normal-match-history-simplified"


class So1Client:
    _instance: Optional["So1Client"] = None
    _browser: Optional[Browser] = None
    _pw_manager: Any = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(So1Client, cls).__new__(cls)
        return cls._instance

    def __init__(self, username: str, password: str, headless: bool = True, timeout_ms: int = 15000) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.username = username
        self.password = password
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.logger = logging.getLogger(self.__class__.__name__)
        self._state_path = os.path.join(os.path.dirname(__file__), ".so1_state.json")
        self._token_path = os.path.join(os.path.dirname(__file__), ".so1_token.txt")
        self._browser_lock = asyncio.Lock()
        self._max_concurrent_pages = max(int(os.getenv("SO1_MAX_CONCURRENT_PAGES", "2")), 1)
        self._query_semaphore = asyncio.Semaphore(self._max_concurrent_pages)
        self._initialized = True

    async def init_browser(self):
        async with self._browser_lock:
            if self._browser is not None and self._browser.is_connected():
                return
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw_manager is None:
                self._pw_manager = await async_playwright().start()
            self._browser = await self._pw_manager.chromium.launch(headless=self.headless)
            self.logger.info("Chromium browser started")

    async def close_browser(self):
        async with self._browser_lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._pw_manager:
                await self._pw_manager.stop()
                self._pw_manager = None
        self.logger.info("Chromium browser closed")

    async def bootstrap_manual_login(self, wait_seconds: int = 180) -> None:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context: BrowserContext
            if os.path.exists(self._state_path):
                context = await browser.new_context(storage_state=self._state_path)
            else:
                context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://lolso1.com/login", wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                await page.wait_for_timeout(1000)
                if await self._is_logged_in(page):
                    await context.storage_state(path=self._state_path)
                    await context.close()
                    await browser.close()
                    return
            await context.close()
            await browser.close()
            raise So1ClientError("manual login timed out")

    async def _is_logged_in(self, page: Page) -> bool:
        try:
            result = await page.evaluate(
                """async () => {
                    const res = await fetch('https://r1.lolso1.com/user/me', {
                        method: 'GET',
                        credentials: 'include',
                        cache: 'no-store'
                    })
                    const data = await res.json().catch(() => null)
                    return !!(data && data.errCode === '0000' && data.data && data.data.username)
                }"""
            )
            return bool(result)
        except Exception:
            return False

    async def _login(self, page: Page) -> None:
        if await self._is_logged_in(page):
            return
        self.logger.info("so1 session is missing or expired, logging in")
        payload = await page.evaluate(
            """async ({account, password}) => {
                const res = await fetch('https://r1.lolso1.com/user/login', {
                    method: 'POST',
                    credentials: 'include',
                    cache: 'no-store',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({account, password, rememberMe: true})
                })
                const data = await res.json().catch(() => null)
                return {ok: res.ok, status: res.status, data}
            }""",
            {"account": self.username, "password": self.password},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not (isinstance(data, dict) and data.get("errCode") == "0000"):
            msg = ""
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("errCode") or "")
            raise So1ClientError(f"so1 login failed: {msg or payload}")
        await page.context.storage_state(path=self._state_path)
        if not await self._is_logged_in(page):
            raise So1ClientError("so1 login did not produce a valid session")
        self.logger.info("so1 login succeeded")

    async def _capture_debug_screenshot(self, page: Page, filename: str = "debug.png") -> None:
        try:
            logs_dir = os.path.join(os.path.dirname(__file__), "logs")
            os.makedirs(logs_dir, exist_ok=True)
            target = os.path.join(logs_dir, filename)
            await page.screenshot(path=target, full_page=True)
            self.logger.info("debug screenshot saved: %s", target)
        except Exception as exc:
            self.logger.warning("failed to save debug screenshot: %s", exc)

    async def _validate_page_state(self, page: Page) -> None:
        url = page.url or ""
        title = await page.title() or ""
        self.logger.info("so1 page state url=%s title=%s", url, title)
        if "lolso1.com" not in url:
            await self._capture_debug_screenshot(page)
            raise So1ClientError(f"unexpected page url: {url}")
        state = await page.evaluate(
            """() => {
                const text = document.body && document.body.innerText ? document.body.innerText : ''
                const hasApp = !!document.querySelector('#__next, [data-nextjs-root], main, input')
                return {textLen: text.length, hasApp, text: text.slice(0, 1000)}
            }"""
        )
        if int((state or {}).get("textLen") or 0) < 20 and not bool((state or {}).get("hasApp")):
            await self._capture_debug_screenshot(page)
            raise So1ClientError("so1 page content is abnormal")
        challenge_text = str((state or {}).get("text") or "").lower()
        if "captcha" in challenge_text or "verify" in challenge_text:
            await self._capture_debug_screenshot(page)
            raise So1ClientError("so1 page requires verification; run /cross_session_init first")

    async def _new_context(self) -> BrowserContext:
        await self.init_browser()
        try:
            if os.path.exists(self._state_path):
                return await self._browser.new_context(storage_state=self._state_path)
            return await self._browser.new_context()
        except Exception as exc:
            msg = str(exc).lower()
            if "browser has been closed" in msg or "target page, context or browser has been closed" in msg:
                self.logger.warning("browser instance is stale, rebuilding: %s", exc)
                await self.close_browser()
                await self.init_browser()
                if os.path.exists(self._state_path):
                    return await self._browser.new_context(storage_state=self._state_path)
                return await self._browser.new_context()
            raise

    async def query_summoner(self, summoner_name: str, region_name: Optional[str] = None) -> Dict[str, Any]:
        async with self._query_semaphore:
            last_error = ""
            for attempt in range(3):
                context = None
                page = None
                try:
                    context = await self._new_context()
                    page = await context.new_page()
                    await page.goto("https://lolso1.com/", wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_selector("input", state="visible", timeout=30000)
                    await self._validate_page_state(page)
                    await self._login(page)
                    if region_name:
                        await page.evaluate("(region) => window.localStorage.setItem('default-area', region)", region_name)

                    try:
                        raw = await self._query_summoner_via_signed_api(page, summoner_name)
                        await context.storage_state(path=self._state_path)
                        return raw
                    except So1ClientError as exc:
                        self.logger.info("signed api query unavailable, falling back to page search: %s", exc)
                        last_error = str(exc)

                    responses: Dict[str, Dict[str, Any]] = {}
                    response_tasks = []

                    def handle_response(response):
                        if "r1.lolso1.com/league/player/" not in response.url:
                            return
                        if not any(key in response.url for key in ("server_info", "overview", "match_analysis")):
                            return
                        response_tasks.append(asyncio.create_task(self._parse_and_store_response(response, responses)))

                    page.on("response", handle_response)

                    inputs = page.locator("input")
                    input_count = await inputs.count()
                    if input_count < 1:
                        raise So1ClientError("so1 search input was not found")
                    await inputs.first.fill(summoner_name)
                    await page.keyboard.press("Enter")

                    for _ in range(max(int(self.timeout_ms / 500), 20)):
                        await page.wait_for_timeout(500)
                        if response_tasks:
                            done, pending = await asyncio.wait(response_tasks, timeout=0.05)
                            response_tasks = list(pending)
                        if responses.get("overview") and responses.get("match_analysis"):
                            break
                        if responses.get("server_info") and not responses["server_info"].get("success", True):
                            break

                    if response_tasks:
                        await asyncio.gather(*response_tasks, return_exceptions=True)

                    raw = self._build_legacy_payload(responses)
                    if not raw[LEGACY_BASIC_URL].get("success"):
                        raise So1ClientError(self._extract_response_error(raw[LEGACY_BASIC_URL]) or "so1 player lookup failed")
                    if not raw[LEGACY_HISTORY_URL].get("success"):
                        raise So1ClientError(self._extract_response_error(raw[LEGACY_HISTORY_URL]) or "so1 match history lookup failed")

                    await context.storage_state(path=self._state_path)
                    return raw
                except So1ClientError as exc:
                    last_error = str(exc)
                    self.logger.error("so1 query failed attempt=%s error=%s", attempt + 1, exc)
                    if page is not None:
                        await self._capture_debug_screenshot(page)
                except Exception as exc:
                    last_error = str(exc)
                    self.logger.exception("so1 query exception attempt=%s error=%s", attempt + 1, exc)
                    if page is not None:
                        await self._capture_debug_screenshot(page)
                    msg = str(exc).lower()
                    if "browser has been closed" in msg or "target page, context or browser has been closed" in msg:
                        await self.close_browser()
                finally:
                    if context is not None:
                        try:
                            await context.close()
                        except Exception:
                            pass
            raise So1ClientError(f"so1 query failed after retries: {last_error or 'unknown error'}")

    async def _query_summoner_via_signed_api(self, page: Page, summoner_name: str) -> Dict[str, Any]:
        game_name, tag_line = self._split_riot_id(summoner_name)
        if not game_name or not tag_line:
            raise So1ClientError("signed api requires Riot ID format: name#tag")

        payload = await page.evaluate(
            """async ({gameName, tagLine}) => {
                const API_BASE_URL = 'https://r1.lolso1.com'
                const SIGN_KEY = 'bnGke6jCHJLKvPt9N4DRhMCLCj9TVYG9'
                const encoder = new TextEncoder()

                const hex = (bytes) => [...new Uint8Array(bytes)]
                    .map((byte) => byte.toString(16).padStart(2, '0'))
                    .join('')

                const stableStringify = (value) => {
                    if (value == null) return ''
                    if (value instanceof Date) return JSON.stringify(value.toISOString())
                    if (Array.isArray(value)) {
                        return `[${value.map((item) => stableStringify(item) || 'null').join(',')}]`
                    }
                    if (typeof value === 'object') {
                        return `{${Object.keys(value)
                            .sort()
                            .filter((key) => value[key] !== undefined)
                            .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key]) || 'null'}`)
                            .join(',')}}`
                    }
                    return JSON.stringify(value)
                }

                const sha256 = async (text) => {
                    const digest = await crypto.subtle.digest('SHA-256', encoder.encode(text))
                    return hex(digest)
                }

                const hmacSha256 = async (key, text) => {
                    const cryptoKey = await crypto.subtle.importKey(
                        'raw',
                        encoder.encode(key),
                        {name: 'HMAC', hash: 'SHA-256'},
                        false,
                        ['sign']
                    )
                    const signature = await crypto.subtle.sign('HMAC', cryptoKey, encoder.encode(text))
                    return hex(signature)
                }

                const nonce = () => {
                    const bytes = new Uint8Array(16)
                    crypto.getRandomValues(bytes)
                    return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
                }

                const signedPost = async (path, body) => {
                    const bodyText = JSON.stringify(body)
                    const bodyHash = await sha256(stableStringify(body))
                    const timestamp = String(Math.floor(Date.now() / 1000))
                    const requestNonce = nonce()
                    const signBase = ['v1', 'POST', path, '', bodyHash, timestamp, requestNonce].join('\\n')
                    const signature = await hmacSha256(SIGN_KEY, signBase)
                    const response = await fetch(`${API_BASE_URL}${path}`, {
                        method: 'POST',
                        credentials: 'include',
                        cache: 'no-store',
                        headers: {
                            'Content-Type': 'application/json',
                            'x-leso-sign-version': 'v1',
                            'x-leso-timestamp': timestamp,
                            'x-leso-nonce': requestNonce,
                            'x-leso-signature': signature
                        },
                        body: bodyText
                    })
                    const text = await response.text()
                    let data = null
                    try {
                        data = text ? JSON.parse(text) : null
                    } catch {
                        data = {message: text}
                    }
                    return {ok: response.ok, status: response.status, data}
                }

                const serverInfo = await signedPost('/league/player/server_info', {gameName, tagLine})
                const serverData = serverInfo && serverInfo.data && serverInfo.data.data
                    ? serverInfo.data.data
                    : null
                const serverId = serverData && serverData.serverId
                const puuid = serverData && serverData.puuid
                if (!serverInfo.ok || !serverId || !puuid) {
                    return {ok: false, stage: 'server_info', server_info: serverInfo.data, status: serverInfo.status}
                }

                const [overview, matchAnalysis] = await Promise.all([
                    signedPost('/league/player/overview', {serverId, puuid}),
                    signedPost('/league/player/match_analysis', {serverId, puuid, page: 1, size: 15, tag: -1})
                ])
                return {
                    ok: overview.ok && matchAnalysis.ok,
                    stage: overview.ok && matchAnalysis.ok ? 'done' : 'detail',
                    server_info: serverInfo.data,
                    overview: overview.data,
                    match_analysis: matchAnalysis.data,
                    statuses: {
                        server_info: serverInfo.status,
                        overview: overview.status,
                        match_analysis: matchAnalysis.status
                    }
                }
            }""",
            {"gameName": game_name, "tagLine": tag_line},
        )
        if not isinstance(payload, dict) or not payload.get("ok"):
            stage = payload.get("stage") if isinstance(payload, dict) else "unknown"
            raise So1ClientError(f"signed api query failed at {stage}")

        responses = {
            "server_info": self._unwrap_new_response(payload.get("server_info")),
            "overview": self._unwrap_new_response(payload.get("overview")),
            "match_analysis": self._unwrap_new_response(payload.get("match_analysis")),
        }
        raw = self._build_legacy_payload(responses)
        if not raw[LEGACY_BASIC_URL].get("success"):
            raise So1ClientError(self._extract_response_error(raw[LEGACY_BASIC_URL]) or "signed api player lookup failed")
        if not raw[LEGACY_HISTORY_URL].get("success"):
            raise So1ClientError(self._extract_response_error(raw[LEGACY_HISTORY_URL]) or "signed api match history lookup failed")
        return raw

    def _split_riot_id(self, summoner_name: str) -> tuple[str, str]:
        if "#" not in summoner_name:
            return summoner_name.strip(), ""
        game_name, tag_line = summoner_name.split("#", 1)
        return game_name.strip(), tag_line.strip()

    async def _parse_and_store_response(self, response, responses_dict):
        try:
            resp_json = await response.json()
            if "/server_info" in response.url:
                responses_dict["server_info"] = self._unwrap_new_response(resp_json)
            elif "/overview" in response.url:
                responses_dict["overview"] = self._unwrap_new_response(resp_json)
            elif "/match_analysis" in response.url:
                responses_dict["match_analysis"] = self._unwrap_new_response(resp_json)
            self.logger.debug("intercepted %s", response.url)
        except Exception as exc:
            self.logger.debug("failed to parse response from %s: %s", response.url, exc)

    def _unwrap_new_response(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"success": False, "error": {"message": "invalid response"}}
        err_code = payload.get("errCode", payload.get("code"))
        if err_code in (None, "0000", "0", 0):
            return {"success": True, "data": payload.get("data", payload)}
        return {
            "success": False,
            "error": {
                "errCode": err_code,
                "message": payload.get("message") or "request failed",
                "requestID": payload.get("requestID"),
            },
        }

    def _build_legacy_payload(self, responses: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        overview = responses.get("overview") or {}
        match_analysis = responses.get("match_analysis") or {}
        overview_data = overview.get("data") if overview.get("success") else {}
        match_data = match_analysis.get("data") if match_analysis.get("success") else {}
        overview_data = overview_data if isinstance(overview_data, dict) else {}
        match_data = match_data if isinstance(match_data, dict) else {}

        base = overview_data.get("base") if isinstance(overview_data.get("base"), dict) else {}
        ranked = overview_data.get("ranked") if isinstance(overview_data.get("ranked"), dict) else {}
        queues = ranked.get("queues") if isinstance(ranked.get("queues"), dict) else ranked.get("queues")
        if isinstance(queues, dict):
            queues = list(queues.values())
        elif not isinstance(queues, list):
            queues = []

        basic_data = dict(base)
        if base:
            game_name = str(base.get("gameName") or base.get("name") or "").strip()
            tag_line = str(base.get("tagLine") or base.get("riotIdTagline") or "").strip()
            display_name = f"{game_name}#{tag_line}" if game_name and tag_line else game_name
            basic_data.setdefault("name", display_name)
            basic_data.setdefault("displayName", display_name)
            basic_data.setdefault("summonerName", display_name)
            basic_data.setdefault("profileIconId", base.get("profileIconId"))
            basic_data.setdefault("level", base.get("level"))

        history = match_data.get("matchHistory")
        if not isinstance(history, list):
            history = []

        basic_payload = {"success": bool(base), "data": basic_data if base else None}
        ranked_payload = {"success": True, "data": {"queues": queues}}
        history_payload = {"success": bool(match_analysis.get("success")), "data": history}

        if not basic_payload["success"]:
            basic_payload["error"] = self._legacy_error(responses.get("server_info"), responses.get("overview"))
        if not history_payload["success"]:
            history_payload["error"] = self._legacy_error(responses.get("match_analysis"))

        return {
            LEGACY_BASIC_URL: basic_payload,
            LEGACY_RANKED_URL: ranked_payload,
            LEGACY_HISTORY_URL: history_payload,
        }

    def _legacy_error(self, *payloads: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            if payload.get("success") is False and isinstance(payload.get("error"), dict):
                return payload["error"]
        return {"message": "no valid so1 response"}

    def _extract_response_error(self, payload: Dict[str, Any]) -> str:
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return str(error.get("message") or error.get("errCode") or "")
        return ""
