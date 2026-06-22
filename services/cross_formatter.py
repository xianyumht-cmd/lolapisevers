from typing import Any, Dict, List

from services.lol_static import (
    POSITION_NAMES,
    RANK_QUEUE_NAMES,
    format_last_online,
    get_static_lol_data,
    queue_display,
    rank_display,
    resolve_region_display,
)
from utils.convert import safe_int
from utils.time_utils import format_ts_ms


def build_cross_pretty(
    name: str,
    region: str,
    basic: Any,
    rank: Any,
    history: Any,
    errors: List[Dict[str, Any]],
    cache=None,
    logger=None,
) -> Dict[str, Any]:
    basic_obj = basic if isinstance(basic, dict) else {}
    rank_obj = rank if isinstance(rank, dict) else {}
    history_list = history if isinstance(history, list) else []
    input_game_name = name.split("#", 1)[0].strip() if "#" in name else name.strip()
    input_tag = name.split("#", 1)[1].strip() if "#" in name else ""
    target_puuid = str(basic_obj.get("puuid") or "").strip()
    static_data = get_static_lol_data(cache=cache, logger=logger)

    def pick_player(game_item: Dict[str, Any]) -> Dict[str, Any]:
        participants = game_item.get("participants") if isinstance(game_item.get("participants"), list) else []
        if not participants:
            return game_item
        for p in participants:
            if not isinstance(p, dict):
                continue
            if target_puuid and str(p.get("puuid") or "").strip() == target_puuid:
                return p
        for p in participants:
            if not isinstance(p, dict):
                continue
            game_name = str(p.get("riotIdGameName") or p.get("summonerName") or "").strip()
            tag = str(p.get("riotIdTagline") or "").strip()
            if input_game_name and game_name == input_game_name:
                if not input_tag or tag == input_tag:
                    return p
        return participants[0] if isinstance(participants[0], dict) else game_item

    recent_matches: List[Dict[str, Any]] = []
    for item in history_list[:10]:
        if not isinstance(item, dict):
            continue
        player = pick_player(item)
        stats = player.get("stats") if isinstance(player.get("stats"), dict) else {}
        kills = safe_int(player.get("kills", stats.get("kills", 0)))
        deaths = safe_int(player.get("deaths", stats.get("deaths", 0)))
        assists = safe_int(player.get("assists", stats.get("assists", 0)))
        champion_id = player.get("championID", player.get("championId", stats.get("championId")))
        champion_raw = player.get("championName") or player.get("champion") or champion_id or ""
        champion_name = (
            static_data.get("champions", {}).get(str(champion_id))
            or static_data.get("champions", {}).get(str(champion_raw))
            or str(champion_raw)
        )
        item_ids = [safe_int(player.get(f"item{i}", 0)) for i in range(7)]
        item_names = [static_data.get("items", {}).get(str(item_id), str(item_id)) for item_id in item_ids if item_id]
        spell_ids = [safe_int(player.get("spell1Id", 0)), safe_int(player.get("spell2Id", 0))]
        spell_names = [static_data.get("spells", {}).get(str(spell_id), str(spell_id)) for spell_id in spell_ids if spell_id]
        perks = player.get("perks") if isinstance(player.get("perks"), dict) else {}
        styles = perks.get("styles") if isinstance(perks.get("styles"), list) else []
        primary_style = styles[0] if styles and isinstance(styles[0], dict) else {}
        sub_style = styles[1] if len(styles) > 1 and isinstance(styles[1], dict) else {}
        primary_runes = primary_style.get("selections") if isinstance(primary_style.get("selections"), list) else []
        main_rune_id = primary_runes[0].get("perk") if primary_runes and isinstance(primary_runes[0], dict) else None
        rune_names = [
            static_data.get("runes", {}).get(str(primary_style.get("style")), str(primary_style.get("style") or "")),
            static_data.get("runes", {}).get(str(main_rune_id), str(main_rune_id or "")),
            static_data.get("runes", {}).get(str(sub_style.get("style")), str(sub_style.get("style") or "")),
        ]
        rune_names = [r for r in rune_names if r]
        queue_id = item.get("queueId", item.get("queueType", item.get("gameMode", "")))
        position_raw = str(player.get("individualPosition") or player.get("lane") or "")
        teams = item.get("teams") if isinstance(item.get("teams"), list) else []
        team_obj: Dict[str, Any] = {}
        for team in teams:
            if isinstance(team, dict) and team.get("teamId") == player.get("teamId"):
                team_obj = team
                break
        objectives = team_obj.get("objectives") if isinstance(team_obj.get("objectives"), dict) else {}
        objective_summary = {
            key: safe_int((objectives.get(key) or {}).get("kills", 0)) if isinstance(objectives.get(key), dict) else 0
            for key in ("tower", "dragon", "baron", "riftHerald", "horde", "inhibitor")
        }
        recent_matches.append(
            {
                "match_id": item.get("gameId"),
                "game_time": format_ts_ms(item.get("gameCreation")),
                "champion": champion_name,
                "champion_raw": champion_raw,
                "champion_id": safe_int(champion_id, 0),
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda": round((kills + assists) / max(deaths, 1), 2),
                "win": bool(player.get("win", stats.get("win", False))),
                "duration": safe_int(item.get("gameDuration", 0)),
                "queue": queue_display(queue_id),
                "queue_id": queue_id,
                "mode": item.get("gameMode") or "",
                "platform_id": item.get("platformId") or "",
                "position": POSITION_NAMES.get(position_raw.upper(), position_raw),
                "champ_level": safe_int(player.get("champLevel", 0)),
                "gold": safe_int(player.get("goldEarned", 0)),
                "gold_spent": safe_int(player.get("goldSpent", 0)),
                "cs": safe_int(player.get("totalMinionsKilled", 0)),
                "jungle_cs": safe_int(player.get("neutralMinionsKilled", 0)),
                "damage": safe_int(player.get("totalDamageDealtToChampions", 0)),
                "damage_taken": safe_int(player.get("totalDamageTaken", 0)),
                "damage_mitigated": safe_int(player.get("damageSelfMitigated", 0)),
                "objective_damage": safe_int(player.get("damageDealtToObjectives", 0)),
                "turret_damage": safe_int(player.get("damageDealtToTurrets", 0)),
                "vision_score": safe_int(player.get("visionScore", 0)),
                "control_wards": safe_int(player.get("detectorWardsPlaced", 0)),
                "items": item_names,
                "item_ids": item_ids,
                "spells": spell_names,
                "spell_ids": spell_ids,
                "runes": rune_names,
                "multi_kills": {
                    "double": safe_int(player.get("doubleKills", 0)),
                    "triple": safe_int(player.get("tripleKills", 0)),
                    "quadra": safe_int(player.get("quadraKills", 0)),
                    "penta": safe_int(player.get("pentaKills", 0)),
                },
                "first_blood": bool(player.get("firstBloodKill", False)),
                "first_tower": bool(player.get("firstTowerKill", False)),
                "dragon_kills": safe_int(player.get("dragonKills", 0)),
                "baron_kills": safe_int(player.get("baronKills", 0)),
                "team_objectives": objective_summary,
            }
        )
    wins = sum(1 for m in recent_matches if m.get("win"))
    total = len(recent_matches)
    winrate = round((wins / total) * 100, 2) if total else 0.0
    avg_kda = round(sum(m["kda"] for m in recent_matches) / total, 2) if total else 0.0
    rank_text = ""
    queues = rank_obj.get("queues") if isinstance(rank_obj.get("queues"), list) else []
    ranked_queues: List[Dict[str, Any]] = []
    for queue_type in ("RANKED_SOLO_5x5", "RANKED_FLEX_SR"):
        for q in queues:
            if isinstance(q, dict) and q.get("queueType") == queue_type:
                text = rank_display(q)
                ranked_queues.append(
                    {
                        "queue_type": q.get("queueType"),
                        "queue_name": RANK_QUEUE_NAMES.get(str(q.get("queueType") or ""), str(q.get("queueType") or "")),
                        "rank": text or "未定级",
                        "wins": safe_int(q.get("wins", 0)),
                        "losses": safe_int(q.get("losses", 0)),
                    }
                )
                if queue_type == "RANKED_SOLO_5x5" and text:
                    rank_text = text
                break
    if not rank_text and ranked_queues:
        rank_text = ranked_queues[0].get("rank") or ""
    display_name = basic_obj.get("name") or basic_obj.get("displayName") or name
    return {
        "name": display_name,
        "region": resolve_region_display(region, basic_obj, history_list),
        "level": safe_int(basic_obj.get("level", 0)),
        "profile_icon": safe_int(basic_obj.get("profileIconId", 0)),
        "rank": rank_text,
        "ranked_queues": ranked_queues,
        "last_online_time": format_last_online(basic_obj),
        "winrate_recent": f"{winrate}%",
        "avg_kda_recent": avg_kda,
        "recent_matches": recent_matches,
        "errors": errors,
        "raw_ok": basic is not None or history is not None or rank is not None,
    }
