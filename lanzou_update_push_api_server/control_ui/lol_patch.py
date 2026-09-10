from __future__ import annotations

from datetime import date as Date
from html import escape

from services.lol_patch_schedule_service import PATCH_SCHEDULE_2026, get_patch_status

from .components import icon, render_console_shell


_STYLES = ("/control-assets/console.css", "/control-assets/operations.css")
_SCRIPTS = ("/control-assets/operations.js", "/control-assets/release-update.js")


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
            state = '<span class="status-pill status-pill-success">今天更新</span>'
        elif iso_date == next_update:
            state = '<span class="status-pill status-pill-warning">下一次</span>'
        elif patch_date < requested:
            state = '<span class="status-pill status-pill-neutral">已发布</span>'
        else:
            state = '<span class="status-pill status-pill-neutral">计划</span>'
        rows.append(
            "<tr>"
            f"<td><strong>{escape(patch)}</strong></td>"
            f"<td>{escape(iso_date)}</td>"
            f"<td>{state}</td>"
            "</tr>"
        )
    return "".join(rows)


def _update_confirm_dialog() -> str:
    return f'''<dialog class="dialog" id="releaseUpdateConfirmDialog" aria-labelledby="releaseUpdateConfirmTitle">
  <form class="dialog-card" id="releaseUpdateConfirmForm">
    <header class="dialog-header">
      <div>
        <p class="eyebrow">Release 安全升级</p>
        <h2 id="releaseUpdateConfirmTitle">确认一键升级</h2>
      </div>
      <button class="icon-button" id="releaseUpdateConfirmClose" type="button" aria-label="关闭对话框">{icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description" id="releaseUpdateConfirmMessage">将下载并校验最新 V3 安全部署包。</p>
      <div class="alert alert-warning">升级会短暂中断 5001 和 6178。部署器会先验证候选、备份生产，并在验证失败时自动回滚。</div>
    </div>
    <footer class="dialog-footer">
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="releaseUpdateConfirmCancel" type="button">取消</button>
      <button class="button button-primary" id="releaseUpdateConfirmSubmit" type="submit">确认升级</button>
    </footer>
  </form>
</dialog>'''


def render_lol_patch_page() -> str:
    status = get_patch_status()
    is_update_day = bool(status.get("is_update_today"))
    update_label = "今天是更新日" if is_update_day else "今天不是更新日"
    update_class = "status-pill-success" if is_update_day else "status-pill-neutral"
    next_summary = (
        f'{_text(status.get("next_patch"))} · {_text(status.get("next_update_date"))}'
        if status.get("next_patch")
        else "2026 已无后续计划"
    )
    source_url = escape(str(status.get("source_url") or "#"), quote=True)

    actions = (
        f'<a class="button button-secondary" href="/lol-patch">{icon("refresh")}<span>刷新补丁状态</span></a>'
        f'<button class="button button-primary" id="releaseUpdateCheckButton" type="button">{icon("activity")}<span>检查程序更新</span></button>'
    )
    content = f'''<header class="page-header">
  <div>
    <p class="eyebrow">LOL · 版本日历</p>
    <h1>LOL 更新日</h1>
    <p>查看国服版本更新计划，并直接使用现有 GitHub Release V3 安全链路升级 LOLDataSystem。</p>
  </div>
  <div class="page-actions">{actions}</div>
</header>
<section class="metric-grid">
  <article class="metric-card"><div class="metric-icon">{icon("history")}</div><div><span>当前版本</span><strong>{_text(status.get("patch"))}</strong><small>按当前日期对应的计划版本</small></div></article>
  <article class="metric-card"><div class="metric-icon">{icon("activity")}</div><div><span>今日状态</span><strong><span class="status-pill {update_class}">{update_label}</span></strong><small>{_text(status.get("date"))}</small></div></article>
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
    <div class="panel-body"><div class="alert alert-info">真正的更新日 @全体 调度、授权群过滤、重试和去重仍由 GroupGuard 负责；这里不会主动发群消息。</div></div>
  </article>
</section>
<section class="panel">
  <header class="panel-header">
    <div><h2>GitHub Release 一键升级</h2><p>与“安全与回滚”页共用同一套更新后端：前向提交校验、V3 metadata、SHA-256、候选测试、生产备份和失败自动回滚。</p></div>
    <div class="page-actions">
      <button class="button button-primary" id="releaseUpdateStartButton" type="button" disabled>{icon("activity")}<span>一键升级</span></button>
    </div>
  </header>
  <div class="panel-body">
    <section class="metric-grid metric-grid-3">
      <article class="metric-card"><div><span>当前提交</span><strong id="releaseCurrentCommit" class="code">读取中</strong><small id="releaseCurrentName">等待 build-info</small></div></article>
      <article class="metric-card"><div><span>最新 Release</span><strong id="releaseLatestName">读取中</strong><small id="releaseTargetCommit">等待目标提交</small></div></article>
      <article class="metric-card"><div><span>更新状态</span><strong id="releaseUpdateState">读取中</strong><small id="releasePackageInfo">等待 Release metadata</small></div></article>
    </section>
    <div class="form-row form-row-4">
      <label class="field field-span-2"><span>GitHub Release 只读 Token</span><input id="releaseTokenInput" type="password" autocomplete="off" spellcheck="false" placeholder="私有仓库首次配置；保存后不会回显"><small id="releaseTokenHint">Token 仅保存在生产机更新目录，不进入源码、页面或普通日志。</small></label>
      <div class="field"><span>Token 状态</span><div class="inline-status" id="releaseTokenStatus"><span class="status-dot status-dot-neutral"></span><span>读取中</span></div></div>
      <div class="field"><span>操作</span><button class="button button-secondary" id="releaseTokenSaveButton" type="button">保存 Token</button></div>
    </div>
    <pre class="operations-result" id="releaseUpdateResult">正在读取 Release 更新状态...</pre>
  </div>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>2026 更新日历</h2><p>来源为当前服务内置的 Riot 官方 2026 Patch Schedule 快照；官方日期若调整，只需更新 schedule service。</p></div></header>
  <div class="table-wrap"><table>
    <thead><tr><th>版本</th><th>计划日期</th><th>状态</th></tr></thead>
    <tbody>{_calendar_rows(status)}</tbody>
  </table></div>
</section>
{_update_confirm_dialog()}'''
    return render_console_shell(
        active="lol-patch",
        title="LOL 更新日",
        content=content,
        body_marker="lol-patch",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


__all__ = ["render_lol_patch_page"]
