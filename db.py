import logging
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import pymysql
from pymysql.cursors import DictCursor


class Database:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        charset: str = "utf8mb4",
    ) -> None:
        """初始化数据库连接配置并自动建库建表。"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.charset = charset
        self._ensure_database_and_tables()

    @contextmanager
    def _connection(self, with_db: bool = True):
        """提供数据库连接上下文。"""
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database if with_db else None,
            charset=self.charset,
            autocommit=True,
            cursorclass=DictCursor,
        )
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_database_and_tables(self) -> None:
        """创建数据库与业务表结构。"""
        with self._connection(with_db=False) as conn:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}` DEFAULT CHARACTER SET {self.charset}")
        with self._connection(with_db=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS summoners (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(64) NOT NULL,
                        puuid VARCHAR(128) NOT NULL UNIQUE,
                        last_update DATETIME NOT NULL,
                        INDEX idx_summoner_name (name),
                        INDEX idx_summoner_last_update (last_update)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS matches (
                        match_id BIGINT PRIMARY KEY,
                        game_time DATETIME NOT NULL,
                        duration INT NOT NULL,
                        INDEX idx_match_game_time (game_time)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS match_participants (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        match_id BIGINT NOT NULL,
                        puuid VARCHAR(128) NOT NULL DEFAULT '',
                        name VARCHAR(64) NOT NULL,
                        champion VARCHAR(64) NOT NULL,
                        kills INT NOT NULL DEFAULT 0,
                        deaths INT NOT NULL DEFAULT 0,
                        assists INT NOT NULL DEFAULT 0,
                        win TINYINT(1) NOT NULL DEFAULT 0,
                        damage INT NULL,
                        gold INT NULL,
                        UNIQUE KEY uq_match_player (match_id, puuid, name),
                        INDEX idx_participant_name (name),
                        INDEX idx_participant_puuid (puuid),
                        INDEX idx_participant_match (match_id),
                        CONSTRAINT fk_match_id FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cross_query_snapshots (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        query_name VARCHAR(128) NOT NULL,
                        region VARCHAR(32) NOT NULL,
                        display_name VARCHAR(128) NULL,
                        payload_pretty LONGTEXT NOT NULL,
                        payload_raw LONGTEXT NULL,
                        is_success TINYINT(1) NOT NULL DEFAULT 0,
                        updated_at DATETIME NOT NULL,
                        UNIQUE KEY uq_cross_snapshot (query_name, region),
                        INDEX idx_cross_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
        self.logger.info("数据库与表初始化完成")

    def ping(self) -> bool:
        """Verify that the configured database can execute a trivial query."""
        with self._connection(with_db=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None

    def upsert_summoner(self, name: str, puuid: str, last_update: Optional[datetime] = None) -> None:
        """插入或更新召唤师记录。"""
        ts = last_update or datetime.now()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO summoners (name, puuid, last_update)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        last_update = VALUES(last_update)
                    """,
                    (name, puuid, ts),
                )

    def touch_summoner(self, puuid: str) -> None:
        """刷新召唤师更新时间。"""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE summoners SET last_update=%s WHERE puuid=%s", (datetime.now(), puuid))

    def get_summoner_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """按名字查询最近更新的召唤师记录。"""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, puuid, last_update FROM summoners WHERE name=%s ORDER BY last_update DESC LIMIT 1",
                    (name,),
                )
                return cur.fetchone()

    def upsert_match(self, match_id: int, game_time: datetime, duration: int) -> None:
        """插入或更新比赛元信息。"""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO matches (match_id, game_time, duration)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        game_time = VALUES(game_time),
                        duration = VALUES(duration)
                    """,
                    (match_id, game_time, duration),
                )

    def upsert_match_participants(self, rows: Iterable[Dict[str, Any]]) -> None:
        """批量插入或更新比赛参与者信息。"""
        values = [
            (
                int(row["match_id"]),
                row.get("puuid") or "",
                row.get("name") or "",
                row.get("champion") or "",
                int(row.get("kills", 0)),
                int(row.get("deaths", 0)),
                int(row.get("assists", 0)),
                1 if row.get("win") else 0,
                row.get("damage"),
                row.get("gold"),
            )
            for row in rows
        ]
        if not values:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO match_participants
                    (match_id, puuid, name, champion, kills, deaths, assists, win, damage, gold)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        champion = VALUES(champion),
                        kills = VALUES(kills),
                        deaths = VALUES(deaths),
                        assists = VALUES(assists),
                        win = VALUES(win),
                        damage = VALUES(damage),
                        gold = VALUES(gold)
                    """,
                    values,
                )

    def get_recent_matches_for_player(self, *, name: Optional[str] = None, puuid: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """按name或puuid读取最近比赛。"""
        if not name and not puuid:
            return []
        where = []
        params: List[Any] = []
        if puuid:
            where.append("mp.puuid = %s")
            params.append(puuid)
        if name:
            where.append("mp.name = %s")
            params.append(name)
        where_sql = " OR ".join(where)
        params.append(limit)
        sql = f"""
            SELECT
                mp.match_id,
                m.game_time,
                m.duration,
                mp.name,
                mp.puuid,
                mp.champion,
                mp.kills,
                mp.deaths,
                mp.assists,
                mp.win,
                mp.damage,
                mp.gold
            FROM match_participants mp
            JOIN matches m ON m.match_id = mp.match_id
            WHERE {where_sql}
            ORDER BY m.game_time DESC
            LIMIT %s
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return cur.fetchall() or []

    def get_hidden_query_data(self, name: str, limit: int = 10) -> Dict[str, Any]:
        """读取隐藏战绩分析所需的统计数据。"""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM match_participants WHERE name=%s", (name,))
                found_matches = int((cur.fetchone() or {}).get("cnt", 0))
                cur.execute(
                    """
                    SELECT champion, COUNT(*) AS use_count
                    FROM match_participants
                    WHERE name=%s
                    GROUP BY champion
                    ORDER BY use_count DESC, champion ASC
                    LIMIT 5
                    """,
                    (name,),
                )
                heroes = cur.fetchall() or []
                cur.execute(
                    """
                    SELECT AVG((kills + assists) / GREATEST(deaths, 1)) AS avg_kda
                    FROM match_participants
                    WHERE name=%s
                    """,
                    (name,),
                )
                avg_kda = float((cur.fetchone() or {}).get("avg_kda") or 0.0)
                cur.execute(
                    """
                    SELECT
                        mp.match_id,
                        m.game_time,
                        mp.champion,
                        mp.kills,
                        mp.deaths,
                        mp.assists,
                        mp.win
                    FROM match_participants mp
                    JOIN matches m ON m.match_id = mp.match_id
                    WHERE mp.name=%s
                    ORDER BY m.game_time DESC
                    LIMIT %s
                    """,
                    (name, limit),
                )
                recent = cur.fetchall() or []
                return {
                    "found_matches": found_matches,
                    "recent_heroes": heroes,
                    "kda_estimate": avg_kda,
                    "recent_matches": recent,
                }

    def upsert_cross_snapshot(
        self,
        *,
        query_name: str,
        region: str,
        display_name: str,
        payload_pretty: Dict[str, Any],
        payload_raw: Optional[Dict[str, Any]],
        is_success: bool,
        updated_at: Optional[datetime] = None,
    ) -> None:
        """写入或更新跨区查询快照。"""
        ts = updated_at or datetime.now()
        pretty_text = json.dumps(payload_pretty, ensure_ascii=False)
        raw_text = json.dumps(payload_raw, ensure_ascii=False) if payload_raw is not None else None
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cross_query_snapshots
                    (query_name, region, display_name, payload_pretty, payload_raw, is_success, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        payload_pretty = VALUES(payload_pretty),
                        payload_raw = VALUES(payload_raw),
                        is_success = VALUES(is_success),
                        updated_at = VALUES(updated_at)
                    """,
                    (query_name, region, display_name, pretty_text, raw_text, 1 if is_success else 0, ts),
                )

    def get_cross_snapshot(self, *, query_name: str, region: str) -> Optional[Dict[str, Any]]:
        """读取跨区查询最近快照。"""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT query_name, region, display_name, payload_pretty, payload_raw, is_success, updated_at
                    FROM cross_query_snapshots
                    WHERE query_name=%s AND region=%s
                    LIMIT 1
                    """,
                    (query_name, region),
                )
                row = cur.fetchone()
                if not row:
                    return None
                pretty = row.get("payload_pretty")
                raw = row.get("payload_raw")
                try:
                    row["payload_pretty"] = json.loads(pretty) if isinstance(pretty, str) else None
                except Exception:
                    row["payload_pretty"] = None
                try:
                    row["payload_raw"] = json.loads(raw) if isinstance(raw, str) else None
                except Exception:
                    row["payload_raw"] = None
                return row
