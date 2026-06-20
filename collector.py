import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import Database
from lcu_client import LCUClient


class DataCollector:
    def __init__(self, db: Optional[Database], lcu_client: LCUClient) -> None:
        """初始化数据采集器。"""
        self.db = db
        self.lcu = lcu_client
        self.logger = logging.getLogger(self.__class__.__name__)

    def collect_player(self, name: str) -> Dict[str, Any]:
        """采集召唤师最近比赛并写入数据库。"""
        if self.db is None:
            raise RuntimeError("数据库未初始化")
        summoner = self.lcu.get_summoner_by_name(name)
        if not summoner:
            raise ValueError(f"未找到召唤师: {name}")
        resolved_name = summoner.get("displayName") or summoner.get("gameName") or name
        puuid = summoner.get("puuid")
        if not puuid:
            raise ValueError(f"召唤师缺少puuid: {name}")
        self.db.upsert_summoner(resolved_name, puuid, datetime.now())
        history = self.lcu.get_match_history(puuid, beg_index=0, end_index=20)
        self.logger.info("开始采集召唤师=%s 最近比赛数=%s", resolved_name, len(history))
        collected = 0
        for game in history:
            match_id = self._extract_match_id(game)
            if not match_id:
                continue
            if self.collect_match_and_players(match_id):
                collected += 1
        self.db.touch_summoner(puuid)
        return {"name": resolved_name, "puuid": puuid, "collected_matches": collected, "summoner_id": summoner.get("summonerId")}

    def collect_match_and_players(self, match_id: int) -> bool:
        """采集单场比赛及10名参与者信息。"""
        if self.db is None:
            raise RuntimeError("数据库未初始化")
        detail = self.lcu.get_match_detail(match_id)
        if not detail:
            self.logger.warning("比赛详情为空，match_id=%s", match_id)
            return False
        game_time, duration = self._extract_game_meta(detail)
        participants = self._extract_participants(detail, match_id)
        if not participants:
            self.logger.warning("比赛参与者为空，match_id=%s", match_id)
            return False
        self.db.upsert_match(match_id, game_time, duration)
        self.db.upsert_match_participants(participants)
        self.logger.info("采集比赛完成 match_id=%s participants=%s", match_id, len(participants))
        return True

    def _extract_match_id(self, game: Dict[str, Any]) -> Optional[int]:
        """从比赛概要数据中提取match_id。"""
        for key in ("gameId", "id", "matchId"):
            value = game.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        metadata = game.get("game") if isinstance(game.get("game"), dict) else {}
        value = metadata.get("gameId")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_game_meta(self, detail: Dict[str, Any]) -> Tuple[datetime, int]:
        """从比赛详情提取时间与时长。"""
        game_obj = detail.get("game", detail)
        raw_time = game_obj.get("gameCreation") or game_obj.get("gameCreationDate") or game_obj.get("gameStartTime") or detail.get("gameCreation")
        duration = game_obj.get("gameDuration") or detail.get("gameDuration") or 0
        game_time = datetime.now()
        if isinstance(raw_time, (int, float)):
            if raw_time > 10_000_000_000:
                raw_time = raw_time / 1000
            game_time = datetime.fromtimestamp(raw_time)
        return game_time, int(duration or 0)

    def _extract_participants(self, detail: Dict[str, Any], match_id: int) -> List[Dict[str, Any]]:
        """从比赛详情提取参与者结构化字段。"""
        game_obj = detail.get("game", detail)
        participants = game_obj.get("participants") or detail.get("participants") or []
        identities = game_obj.get("participantIdentities") or detail.get("participantIdentities") or []
        identity_map: Dict[int, Dict[str, Any]] = {}
        for item in identities:
            pid = item.get("participantId")
            player = item.get("player") or {}
            if pid is not None:
                identity_map[int(pid)] = player
        result: List[Dict[str, Any]] = []
        for p in participants:
            participant_id = p.get("participantId")
            player_identity = identity_map.get(int(participant_id)) if participant_id is not None else {}
            stats = p.get("stats") if isinstance(p.get("stats"), dict) else p
            name = (
                p.get("summonerName")
                or player_identity.get("summonerName")
                or player_identity.get("gameName")
                or p.get("name")
                or ""
            )
            puuid = p.get("puuid") or player_identity.get("puuid") or ""
            champion = (
                p.get("championName")
                or p.get("champion")
                or p.get("championId")
                or stats.get("championName")
                or stats.get("championId")
                or ""
            )
            row = {
                "match_id": match_id,
                "puuid": str(puuid or ""),
                "name": str(name or ""),
                "champion": str(champion or ""),
                "kills": int(stats.get("kills", 0) or 0),
                "deaths": int(stats.get("deaths", 0) or 0),
                "assists": int(stats.get("assists", 0) or 0),
                "win": bool(stats.get("win", False)),
                "damage": self._to_int_or_none(
                    stats.get("totalDamageDealtToChampions")
                    or stats.get("totalDamageDealt")
                    or stats.get("physicalDamageDealtToChampions")
                ),
                "gold": self._to_int_or_none(stats.get("goldEarned") or stats.get("gold")),
            }
            result.append(row)
        return result

    def _to_int_or_none(self, value: Any) -> Optional[int]:
        """将字段安全转换为整数。"""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
