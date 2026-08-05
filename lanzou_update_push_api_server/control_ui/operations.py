from __future__ import annotations

from .components import icon, render_console_shell


_OPERATIONS_SCRIPT = ("/control-assets/operations.js",)


def _page_header(*, eyebrow: str, title: str, description: str, actions: str) -> str:
    return f'''<header class="page-header">
  <div>
    <p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
    <p>{description}</p>
  </div>
  <div class="page-actions">{actions}</div>
</header>'''


def _confirm_dialog() -> str:
    return f'''<dialog class="dialog" id="operationConfirmDialog" aria-labelledby="operationConfirmTitle">
  <form class="dialog-card" id="operationConfirmForm">
    <header class="dialog-header">
      <div>
        <p class="eyebrow">需要确认</p>
        <h2 id="operationConfirmTitle">确认操作</h2>
      </div>
      <button class="icon-button" id="operationConfirmClose" type="button" aria-label="关闭对话框">{icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description" id="operationConfirmMessage">请确认是否继续。</p>
      <div class="alert alert-warning" id="operationConfirmWarning">该操作可能短暂影响生产服务或改变配置文件。</div>
    </div>
    <footer class="dialog-footer">
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="operationConfirmCancel" type="button">取消</button>
      <button class="button button-primary" id="operationConfirmSubmit" type="submit">确认执行</button>
    </footer>
  </form>
</dialog>'''


def render_logs_page() -> str:
    actions = (
        f'<button class="button button-secondary" id="logsRefreshButton" type="button">{icon("refresh")}<span>刷新目录</span></button>'
        f'<button class="button button-primary" id="loadLogButton" type="button">{icon("file-text")}<span>读取日志</span></button>'
    )
    content = _page_header(
        eyebrow="P3A · 系统管理",
        title="运行日志",
        description="集中查看主接口、6178、服务监管和保活日志，支持尾部行数与关键词过滤。",
        actions=actions,
    ) + '''
<section class="metric-grid metric-grid-3">
  <article class="metric-card"><div class="metric-icon">''' + icon("file-text") + '''</div><div><span>日志文件</span><strong id="logFileCount" class="skeleton-text">0</strong><small>已登记的进程日志</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("activity") + '''</div><div><span>当前存在</span><strong id="logExistingCount" class="skeleton-text">0</strong><small>磁盘中可读取的日志</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("server") + '''</div><div><span>当前选择</span><strong id="logSelectedName" class="skeleton-text skeleton-title">未选择</strong><small id="logSelectedSize">等待读取目录</small></div></article>
</section>
<section class="panel operations-toolbar-panel">
  <div class="form-row form-row-4">
    <label class="field"><span>日志文件</span><select id="logSelect"><option value="">正在读取...</option></select></label>
    <label class="field"><span>尾部行数</span><input id="logLines" type="number" min="1" max="5000" value="300"></label>
    <label class="field field-span-2"><span>关键词过滤</span><input id="logSearch" type="search" placeholder="留空显示全部尾部内容"></label>
  </div>
</section>
<section class="operations-layout">
  <article class="panel">
    <header class="panel-header"><div><h2>日志目录</h2><p>显示文件是否存在及当前大小</p></div></header>
    <div class="table-wrap"><table><thead><tr><th>日志</th><th>状态</th><th>大小</th><th>操作</th></tr></thead><tbody id="logRows"><tr><td colspan="4"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取日志目录</div></td></tr></tbody></table></div>
  </article>
  <article class="panel panel-log-viewer">
    <header class="panel-header"><div><h2>日志内容</h2><p id="logViewerMeta">选择日志后读取</p></div><button class="button button-secondary" id="clearLogSearchButton" type="button">清除过滤</button></header>
    <pre class="operations-console" id="logContent">暂无日志内容</pre>
  </article>
</section>'''
    return render_console_shell(
        active="logs",
        title="运行日志",
        content=content,
        body_marker="logs",
        scripts=_OPERATIONS_SCRIPT,
    )


def render_diagnostics_page() -> str:
    actions = f'<button class="button button-primary" id="runDiagnosticsButton" type="button">{icon("activity")}<span>重新诊断</span></button>'
    content = _page_header(
        eyebrow="P3A · 系统管理",
        title="诊断与修复",
        description="检查端口、配置文件、状态文件、Python、Playwright 和 Windows 服务，不执行破坏性自动修复。",
        actions=actions,
    ) + '''
<section class="metric-grid metric-grid-3">
  <article class="metric-card"><div class="metric-icon">''' + icon("activity") + '''</div><div><span>检查项</span><strong id="diagnosticTotal" class="skeleton-text">0</strong><small>当前诊断项目总数</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("check") + '''</div><div><span>通过</span><strong id="diagnosticPassed" class="skeleton-text">0</strong><small>状态正常的项目</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("alert") + '''</div><div><span>需要处理</span><strong id="diagnosticFailed" class="skeleton-text">0</strong><small>失败或缺失的项目</small></div></article>
</section>
<section class="operations-layout">
  <article class="panel panel-span-wide">
    <header class="panel-header"><div><h2>诊断结果</h2><p id="diagnosticSummary">正在运行诊断</p></div></header>
    <div class="table-wrap"><table><thead><tr><th>检查项</th><th>状态</th><th>说明</th></tr></thead><tbody id="diagnosticRows"><tr><td colspan="3"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在运行诊断</div></td></tr></tbody></table></div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>状态文件修复</h2><p>仅在状态 JSON 损坏或无法读取时使用</p></div></header>
    <div class="panel-body operations-action-card">
      <div class="alert alert-warning">修复会备份异常状态文件并重新建立可用状态。正常运行时不要重复执行。</div>
      <button class="button button-primary" id="repairStateButton" type="button">''' + icon("tool") + '''<span>修复状态文件</span></button>
      <pre class="operations-result" id="repairStateResult">尚未执行修复</pre>
    </div>
  </article>
</section>''' + _confirm_dialog()
    return render_console_shell(
        active="diagnostics",
        title="诊断与修复",
        content=content,
        body_marker="diagnostics",
        scripts=_OPERATIONS_SCRIPT,
    )


def render_system_page() -> str:
    actions = f'<button class="button button-secondary" id="systemRefreshButton" type="button">{icon("refresh")}<span>刷新状态</span></button>'
    content = _page_header(
        eyebrow="P3A · 系统管理",
        title="安全与回滚",
        description="查看控制台访问策略、Windows 服务、配置备份和管理审计，并执行受控重启或回滚。",
        actions=actions,
    ) + '''
<section class="metric-grid">
  <article class="metric-card"><div class="metric-icon">''' + icon("server") + '''</div><div><span>Windows 服务</span><strong id="serviceState" class="skeleton-text">读取中</strong><small id="serviceDetail">等待服务状态</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("lock") + '''</div><div><span>访问控制</span><strong id="securityMode" class="skeleton-text">读取中</strong><small id="securityDetail">等待安全状态</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("archive") + '''</div><div><span>配置备份</span><strong id="backupCount" class="skeleton-text">0</strong><small>可回滚的备份文件</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("file-text") + '''</div><div><span>审计记录</span><strong id="auditCount" class="skeleton-text">0</strong><small>最近读取的管理操作</small></div></article>
</section>
<section class="dashboard-grid">
  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>Windows 服务</h2><p>重启会短暂中断 5001 和 6178，监管脚本会重新拉起进程</p></div><button class="button button-primary" id="restartServiceButton" type="button">''' + icon("refresh") + '''<span>重启服务</span></button></header>
    <div class="panel-body"><pre class="operations-result" id="serviceStatusContent">正在读取服务状态</pre></div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>控制台安全</h2><p>显示本机访问与令牌要求，不展示真实令牌</p></div></header>
    <div class="panel-body"><pre class="operations-result" id="securityStatusContent">正在读取安全状态</pre></div>
  </article>
  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>配置备份</h2><p>回滚前会再次备份当前配置</p></div></header>
    <div class="table-wrap"><table><thead><tr><th>类型</th><th>备份文件</th><th>时间</th><th>大小</th><th>操作</th></tr></thead><tbody id="backupRows"><tr><td colspan="5"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取备份</div></td></tr></tbody></table></div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>操作审计</h2><p>不记录 Token、密码和请求正文</p></div></header>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>操作</th><th>结果</th></tr></thead><tbody id="auditRows"><tr><td colspan="3"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取审计</div></td></tr></tbody></table></div>
  </article>
</section>''' + _confirm_dialog()
    return render_console_shell(
        active="system",
        title="安全与回滚",
        content=content,
        body_marker="system",
        scripts=_OPERATIONS_SCRIPT,
    )


__all__ = ["render_logs_page", "render_diagnostics_page", "render_system_page"]
