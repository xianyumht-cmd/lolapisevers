import html
import json
import re
from typing import Any, Dict, List


def extract_json_array_after(decoded: str, marker: str) -> List[Dict[str, Any]]:
    start_marker = decoded.find(marker)
    if start_marker < 0:
        return []
    arr_start = decoded.find("[", start_marker)
    if arr_start < 0:
        return []
    depth = 0
    in_string = False
    escaped = False
    arr_end = -1
    for idx in range(arr_start, len(decoded)):
        ch = decoded[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    arr_end = idx + 1
                    break
    if arr_end < 0:
        return []
    try:
        data = json.loads(decoded[arr_start:arr_end])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def extract_opgg_augments(html_text: str) -> List[Dict[str, Any]]:
    scripts = re.findall(r"self\.__next_f\.push\(\[1,\"(.*?)\"\]\)</script>", html_text, re.S)
    for raw_script in scripts:
        if '\\"data\\":[{\\"id\\"' not in raw_script or "largeIcon" not in raw_script:
            continue
        try:
            decoded = json.loads(f'"{raw_script}"')
        except Exception:
            continue
        data = extract_json_array_after(decoded, '"data":')
        rows: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            icon = str(item.get("largeIcon") or item.get("smallIcon") or "").strip()
            if not name or not icon:
                continue
            rows.append(
                {
                    "name": name,
                    "icon": icon,
                    "rarity": item.get("rarity"),
                    "performance": item.get("performance"),
                    "popular": item.get("popular"),
                    "desc": re.sub(r"<[^>]+>", "", str(item.get("desc") or "")).strip(),
                }
            )
        if rows:
            return rows
    return []


def extract_opgg_item_rows(html_text: str, prefix: str, limit: int = 3, max_items: int = 5) -> List[Dict[str, Any]]:
    builds: List[Dict[str, Any]] = []
    seen = set()
    for idx in range(limit):
        key = f"{prefix}_{idx}"
        start = html_text.find(key)
        if start < 0:
            continue
        next_start = html_text.find(f"{prefix}_{idx + 1}", start + 1)
        row = html_text[start: next_start if next_start > start else start + 9000]
        items = []
        for item_id, src, name in re.findall(r'metaId\\":(\d+).*?src\\":\\"([^\\"]+)\\".*?alt\\":\\"([^\\"]+)\\"', row, re.S):
            items.append({"id": item_id, "name": name, "icon": src})
            if len(items) >= max_items:
                break
        if not items:
            continue
        item_key = tuple(item.get("id") for item in items)
        if item_key in seen:
            continue
        seen.add(item_key)
        builds.append({"rank": idx + 1, "items": items})
    return builds


def extract_opgg_core_builds(html_text: str) -> List[Dict[str, Any]]:
    return extract_opgg_item_rows(html_text, "core_items", limit=3, max_items=5)


def extract_opgg_summoner_spells(html_text: str) -> List[Dict[str, str]]:
    marker = "SummonerSpells Table"
    start = html_text.find(marker)
    if start < 0:
        return []
    segment = html_text[start:start + 5000]
    spells = []
    seen = set()
    for src, name in re.findall(r'src="([^"]*/spell/Summoner[^"]+).*?alt="([^"]+)"', segment, re.S):
        clean_src = src.split("?image=", 1)[0]
        if clean_src in seen:
            continue
        seen.add(clean_src)
        spells.append({"name": name, "icon": clean_src})
        if len(spells) >= 2:
            break
    return spells


def extract_opgg_skill_order(html_text: str) -> List[Dict[str, str]]:
    marker = "SkillOrder Table"
    start = html_text.find(marker)
    if start < 0:
        return []
    segment = html_text[start:start + 18000]
    skills = []
    seen = set()

    for name, src, key in re.findall(r'<img alt="([^"]+)"[^>]+src="([^"]*/spell/[^"]+)".*?<strong[^>]*>([QWER])</strong>', segment, re.S):
        key_text = key.strip()
        if key_text in seen or key_text == "R":
            continue
        seen.add(key_text)
        skills.append({"key": key_text, "name": html.unescape(name), "icon": html.unescape(src).split("?image=", 1)[0]})
        if len(skills) >= 3:
            break
    if len(skills) >= 3:
        return skills

    for idx in range(3):
        key_marker = f"skill_{idx}"
        item_start = segment.find(key_marker)
        if item_start < 0:
            continue
        next_item = segment.find(f"skill_{idx + 1}", item_start + 1)
        part = segment[item_start: next_item if next_item > item_start else item_start + 2600]
        key_match = re.search(r'extraData\\?":\\?"([QWER])\\?"', part)
        icon_match = re.search(r'src\\?":\\?"([^"\\]+/spell/[^"\\]+)\\?".*?alt\\?":\\?"([^"\\]+)\\?"', part, re.S)
        if not key_match or not icon_match:
            continue
        key_text = key_match.group(1)
        if key_text in seen or key_text == "R":
            continue
        seen.add(key_text)
        skills.append({"key": key_text, "name": html.unescape(icon_match.group(2)), "icon": icon_match.group(1).split("?image=", 1)[0]})
        if len(skills) >= 3:
            break
    if len(skills) >= 3:
        return skills

    for src, name, key in re.findall(r'src\\?":\\?"([^"\\]+/spell/[^"\\]+)\\?".*?alt\\?":\\?"([^"\\]+)\\?".*?children\\?":\\?"([QWER])\\?"', segment, re.S):
        key_text = key.strip()
        if key_text in seen or key_text == "R":
            continue
        seen.add(key_text)
        skills.append({"key": key_text, "name": html.unescape(name), "icon": src.split("?image=", 1)[0]})
        if len(skills) >= 3:
            break
    return skills
