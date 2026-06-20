import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LCUConnectionError(Exception):
    pass


class LCUClient:
    def __init__(self, timeout: int = 3) -> None:
        """初始化LCU客户端。"""
        self.timeout = timeout
        self.base_url: Optional[str] = None
        self.session = requests.Session()
        self.logger = logging.getLogger(self.__class__.__name__)

    def connect(self) -> None:
        """读取lockfile并建立LCU连接参数。"""
        port, password = self._find_connection_info()
        if not port or not password:
            raise LCUConnectionError("未找到可用LCU连接信息，请确认客户端已登录运行。")
        auth = base64.b64encode(f"riot:{password}".encode("utf-8")).decode("utf-8")
        self.session.headers.update({"Authorization": f"Basic {auth}"})
        self.base_url = f"https://127.0.0.1:{port}"
        self.logger.info("LCU连接成功，端口=%s", port)

    def _find_connection_info(self) -> Tuple[Optional[int], Optional[str]]:
        """从进程参数或lockfile中提取port与token。"""
        from_cmdline = self._find_from_cmdline()
        if from_cmdline:
            return from_cmdline
        lockfile = self._find_lockfile()
        if not lockfile:
            return None, None
        return self._parse_lockfile(lockfile)

    def _find_from_cmdline(self) -> Optional[Tuple[int, str]]:
        """优先从LeagueClientUx进程参数中读取连接信息。"""
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name != "leagueclientux.exe":
                    continue
                cmdline = proc.info.get("cmdline") or []
                port: Optional[int] = None
                token: Optional[str] = None
                for item in cmdline:
                    if not isinstance(item, str):
                        continue
                    lower_item = item.lower()
                    if lower_item.startswith("--app-port="):
                        port = int(item.split("=", 1)[1])
                    elif lower_item.startswith("--remoting-auth-token="):
                        token = item.split("=", 1)[1]
                if port and token:
                    return port, token
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
                continue
        return None

    def _find_lockfile(self) -> Optional[Path]:
        """自动定位LeagueClientUx对应的lockfile文件。"""
        candidates: List[Path] = []
        for proc in psutil.process_iter(["name", "cwd", "exe", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name != "leagueclientux.exe":
                    continue
                cwd = proc.info.get("cwd")
                exe = proc.info.get("exe")
                cmdline = proc.info.get("cmdline") or []
                if cwd:
                    candidates.append(Path(cwd) / "lockfile")
                if exe:
                    candidates.append(Path(exe).parent / "lockfile")
                for item in cmdline:
                    if not isinstance(item, str):
                        continue
                    lower_item = item.lower()
                    if lower_item.startswith("--install-directory="):
                        install_dir = item.split("=", 1)[1].strip('"')
                        candidates.append(Path(install_dir) / "lockfile")
                    if "league of legends" in lower_item and os.path.isdir(item):
                        candidates.append(Path(item) / "lockfile")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        unique_candidates = []
        seen = set()
        for c in candidates:
            key = str(c).lower()
            if key not in seen:
                seen.add(key)
                unique_candidates.append(c)
        for lockfile in unique_candidates:
            if lockfile.exists() and lockfile.is_file():
                return lockfile
        return None

    def _parse_lockfile(self, lockfile: Path) -> Tuple[int, str]:
        """解析lockfile并返回端口和密码。"""
        try:
            content = lockfile.read_text(encoding="utf-8").strip()
            parts = content.split(":")
            if len(parts) < 5:
                raise ValueError("lockfile格式错误")
            port = int(parts[2])
            password = parts[3]
            return port, password
        except Exception as exc:
            raise LCUConnectionError(f"解析lockfile失败: {exc}") from exc

    def _ensure_connection(self) -> None:
        """确保当前请求前已有可用连接信息。"""
        if not self.base_url:
            self.connect()

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """向LCU发送请求并返回JSON数据。"""
        self._ensure_connection()
        assert self.base_url is not None
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                timeout=self.timeout,
                verify=False,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            if response.text:
                return response.json()
            return None
        except requests.RequestException as exc:
            self.logger.error("LCU请求失败 %s %s: %s", method, path, exc)
            self.base_url = None
            raise LCUConnectionError(f"LCU请求失败: {exc}") from exc

    def get_summoner_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """通过召唤师名查询召唤师信息。"""
        candidates = [name]
        if "#" in name:
            base_name = name.split("#", 1)[0].strip()
            if base_name and base_name not in candidates:
                candidates.append(base_name)
        for candidate in candidates:
            paths = [
                ("/lol-summoner/v1/summoners", {"name": candidate}),
                ("/lol-summoner/v2/summoners", {"name": candidate}),
            ]
            for path, params in paths:
                try:
                    data = self._request("GET", path, params=params)
                except LCUConnectionError as exc:
                    msg = str(exc)
                    if "422" in msg and "#" in candidate:
                        continue
                    raise
                if data:
                    if isinstance(data, list):
                        for item in data:
                            if (
                                item.get("displayName") == candidate
                                or item.get("gameName") == candidate
                                or item.get("displayName") == name
                                or item.get("gameName") == name
                            ):
                                return item
                        return data[0] if data else None
                    if isinstance(data, dict):
                        return data
        return None

    def get_match_history(self, puuid: str, beg_index: int = 0, end_index: int = 20) -> List[Dict[str, Any]]:
        """查询指定puuid的比赛历史。"""
        path = f"/lol-match-history/v1/products/lol/{puuid}/matches"
        data = self._request("GET", path, params={"begIndex": beg_index, "endIndex": end_index})
        if not data:
            return []
        if isinstance(data, dict) and isinstance(data.get("games"), dict):
            return data["games"].get("games", []) or []
        if isinstance(data, dict) and isinstance(data.get("games"), list):
            return data.get("games", [])
        if isinstance(data, list):
            return data
        return []

    def get_match_detail(self, match_id: int) -> Optional[Dict[str, Any]]:
        """查询单场比赛详情。"""
        return self._request("GET", f"/lol-match-history/v1/games/{match_id}")

    def get_rank(self, summoner_id: Optional[int]) -> str:
        """查询并格式化段位信息。"""
        if not summoner_id:
            return ""
        data = self._request("GET", f"/lol-ranked/v1/ranked-stats/{summoner_id}")
        if not data:
            return ""
        queues = data.get("queues") if isinstance(data, dict) else None
        if not queues:
            return ""
        solo = None
        for queue in queues:
            if queue.get("queueType") == "RANKED_SOLO_5x5":
                solo = queue
                break
        if not solo:
            solo = queues[0]
        tier = solo.get("tier", "")
        division = solo.get("division", "")
        league_points = solo.get("leaguePoints", "")
        rank = f"{tier} {division} {league_points}LP".strip()
        return rank
