from __future__ import annotations

from datetime import date as Date
from html import escape

from services.lol_patch_schedule_service import PATCH_SCHEDULE_2026, get_patch_status

from .components import icon, render_console_shell


_STYLES = ("/control-assets/console.css", "/control-assets/operations.css")
_SCRIPTS = ("/control-assets/operations.js",)


def _text(value: object | None, fallback: str = "-") -> str:
    raw = fallback if value is None or value == "" else str(value)
    return escape(raw)


def _calendar_rows(status: dict[str, object]) -> str:
    requested = Date.fromisoformat(str(status["date"]))
    next_update = str(status.get("next_update_date") or "")
    rows: list[str] = []
    for patch_date, patch in PATCH_SCHEDULE_2026:
        iso_date = patch_date.isoformat()
        if patch_date == requested and bool(status.get("is_update_today")):
            state = '<span class="badge badge-success">今天更新</span>'
        elif iso_date == next_update:
            state = '<span class="badge badge-warning">下一次</span>'
        elif patch_date < requested:
            state = '<span class="badge badge-neutral">已发布</span>'
        else:
            state = '<span class="badge badge-neutral">计划</span>'
        rows.append(
            "<tr>"
            f"<td><strong>{escape(patch)}</strong></td>"
            f"<td>{escape(iso_date)}</td>"
            f"<td>{state}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_lol_patch_page() -> str:
    status = get_patch_status()
    is_update_day = bool(status.get("is_update_today"))
    update_label = "今天是更新日" if is_update_day else "今天不是更新日"
    update_class = "badge-success" if is_update_day else "badge-neutral"
    next_summary = (
        f'{_text(status.get("next_patch"))} · {_text(status.get("next_update_date"))}'
        if status.get("next_patch")
        else "2026 已无后续计划"
    )
    source_url = escape(str(status.get("source_url") or "#"), quote=True)

    actions = (
        f'<a class="button button-secondary" href="/lol-patch">{icon("refresh")}<span>刷新补丁状态</span></a>'
        f'<a class="button button-secondary" href="/system">{icon("lock")}<span>安全与回滚</span></a>'
    )
    content = f'''<header class="page-header">
  <div>
    <p class="eyebrow">LOL · 版本日历</p>
    <h1>LOL 更新日</h1>
    <p>查看国服版本更新计划与更新日通知状态。LOLDataSystem 程序升级统一在“安全与回滚”页面管理。</p>
  </div>
  <div class="page-actions">{actions}</div>
</header>
<section class="metric-grid">
  <article class="metric-card"><div class="metric-icon">{icon("history")}</div><div><span>当前版本</span><strong>{_text(status.get("patch"))}</strong><small>按当前日期对应的计划版本</small></div></article>
  <article class="metric-card"><div class="metric-icon">{icon("activity")}</div><div><span>今日状态</span><strong><span class="badge {update_class}">{update_label}</span></strong><small>{_text(status.get("date"))}</small></div></article>
  <article class="metric-card"><div class="metric-icon">{icon("arrow-up-right")}</div><div><span>下一版本</span><strong>{next_summary}</strong><small>Riot 2026 官方计划快照</small></div></article>
  <article class="metric-card"><div class="metric-icon">{icon("server")}</div><div><span>计划时区</span><strong>{_text(status.get("schedule_timezone"))}</strong><small>检查于 {_text(status.get("checked_at"))}</small></div></article>
</section>
<section class="dashboard-grid">
  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>补丁状态</h2><p>与 GroupGuard 使用同一份 patch schedule service；这里仅展示，不触发 QQ 通知。</p></div></header>
    <div class="panel-body">
      <div class="form-row form-row-4">
        <div class="field"><span>日期</span><strong>{_text(status.get("date"))}</strong></div>
        <div class="field"><span>补丁</span><strong>{_text(status.get("patch"))}</strong></div>
        <div class="field"><span>Event ID</span><strong class="code">{_text(status.get("event_id"), "非更新日无事件")}</strong></div>
        <div class="field"><span>数据源</span><a href="{source_url}" target="_blank" rel="noopener">Riot Patch Schedule</a></div>
      </div>
    </div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>通知说明</h2><p>页面只负责观察版本计划</p></div></header>
    <div class="panel-body"><div class="alert">真正的更新日 @全体 调度、授权群过滤、重试和去重仍由 GroupGuard 负责；这里不会主动发群消息。</div></div>
  </article>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>2026 更新日历</h2><p>来源为当前服务内置的 Riot 官方 2026 Patch Schedule 快照；官方日期若调整，只需更新 schedule service。</p></div></header>
  <div class="table-wrap"><table>
    <thead><tr><th>版本</th><th>计划日期</th><th>状态</th></tr></thead>
    <tbody>{_calendar_rows(status)}</tbody>
  </table></div>
</section>'''
    return render_console_shell(
        active="lol-patch",
        title="LOL 更新日",
        content=content,
        body_marker="lol-patch",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


__all__ = ["render_lol_patch_page"]
