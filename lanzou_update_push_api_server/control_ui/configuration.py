from __future__ import annotations

from .components import icon, render_console_shell


_STYLES = (
    "/control-assets/console.css",
    "/control-assets/operations.css",
    "/control-assets/configuration.css",
)
_SCRIPTS = ("/control-assets/configuration.js",)


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
    return f'''<dialog class="dialog" id="configurationConfirmDialog" aria-labelledby="configurationConfirmTitle">
  <form class="dialog-card" id="configurationConfirmForm">
    <header class="dialog-header">
      <div><p class="eyebrow">需要确认</p><h2 id="configurationConfirmTitle">确认操作</h2></div>
      <button class="icon-button" id="configurationConfirmClose" type="button" aria-label="关闭对话框">{icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description" id="configurationConfirmMessage">请确认是否继续。</p>
      <div class="alert alert-warning" id="configurationConfirmWarning">保存前会自动备份当前配置。</div>
    </div>
    <footer class="dialog-footer">
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="configurationConfirmCancel" type="button">取消</button>
      <button class="button button-primary" id="configurationConfirmSubmit" type="submit">确认执行</button>
    </footer>
  </form>
</dialog>'''


def _snapshot_dialog() -> str:
    return f'''<dialog class="dialog dialog-wide" id="snapshotDialog" aria-labelledby="snapshotDialogTitle">
  <div class="dialog-card">
    <header class="dialog-header">
      <div><p class="eyebrow">只读结果</p><h2 id="snapshotDialogTitle">监控文件快照</h2></div>
      <button class="icon-button" id="snapshotDialogClose" type="button" aria-label="关闭对话框">{icon('x')}</button>
    </header>
    <div class="dialog-body"><pre class="operations-result configuration-result" id="snapshotDialogContent">暂无内容</pre></div>
    <footer class="dialog-footer"><span class="dialog-footer-spacer"></span><button class="button button-secondary" id="snapshotDialogDone" type="button">关闭</button></footer>
  </div>
</dialog>'''


def render_main_config_page() -> str:
    actions = (
        f'<button class="button button-secondary" id="mainConfigRefreshButton" type="button">{icon("refresh")}<span>重新读取</span></button>'
        f'<button class="button button-primary" id="mainConfigSaveButton" type="button">{icon("save")}<span>保存配置</span></button>'
    )
    content = _page_header(
        eyebrow="P3B · 系统管理",
        title="主接口配置",
        description="安全编辑 5001、MySQL、缓存、SO1、数据源和控制台配置。Secret 不回显，留空表示保留原值。",
        actions=actions,
    ) + '''
<section class="metric-grid metric-grid-3">
  <article class="metric-card"><div class="metric-icon">''' + icon("settings") + '''</div><div><span>配置字段</span><strong id="mainConfigFieldCount" class="skeleton-text">0</strong><small>当前允许通过 WebUI 管理</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("key") + '''</div><div><span>已配置 Secret</span><strong id="mainConfigSecretCount" class="skeleton-text">0</strong><small>只显示状态，不返回真实值</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("refresh") + '''</div><div><span>生效方式</span><strong>重启服务</strong><small>保存后重启 LOLDataSystem</small></div></article>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>配置字段</h2><p id="mainConfigPath">正在读取配置来源</p></div><span class="badge badge-warning">保存前自动备份</span></header>
  <div class="panel-body configuration-form" id="mainConfigForm"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取主接口配置</div></div>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>最后一次操作</h2><p>仅展示脱敏后的保存结果和备份信息</p></div><a class="text-link" href="/system">查看备份与回滚</a></header>
  <div class="panel-body"><pre class="operations-result configuration-result" id="configurationResult">尚未执行操作</pre></div>
</section>''' + _confirm_dialog()
    return render_console_shell(
        active="main-config",
        title="主接口配置",
        content=content,
        body_marker="main-config",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


def render_lanzou_config_page() -> str:
    actions = (
        f'<button class="button button-secondary" id="lanzouConfigRefreshButton" type="button">{icon("refresh")}<span>重新读取</span></button>'
        f'<button class="button button-primary" id="lanzouConfigSaveButton" type="button">{icon("save")}<span>保存并热更新</span></button>'
    )
    content = _page_header(
        eyebrow="P3B · 蓝奏监控",
        title="蓝奏全局配置",
        description="管理扫描策略、解析器顺序、状态文件、WER 参数和通知模板；扫描策略保存后立即刷新运行态。",
        actions=actions,
    ) + '''
<section class="dashboard-grid">
  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>基础与扫描策略</h2><p>监听地址、端口或状态路径变化后建议重启服务</p></div></header>
    <div class="panel-body configuration-grid">
      <label class="field"><span>监听地址</span><input id="lzHost" autocomplete="off"></label>
      <label class="field"><span>监听端口</span><input id="lzPort" type="number" min="1" max="65535"></label>
      <label class="field"><span>完整扫描间隔（秒）</span><input id="lzInterval" type="number" min="5" max="86400"></label>
      <label class="field"><span>每批扫描数量</span><input id="lzBatch" type="number" min="0" max="1000"></label>
      <label class="field"><span>批次等待（秒）</span><input id="lzPause" type="number" min="0" max="86400"></label>
      <label class="field"><span>解析器顺序（逗号分隔）</span><input id="lzProviders" autocomplete="off"></label>
      <label class="field configuration-span-2"><span>状态文件路径</span><input id="lzStatePath" autocomplete="off"></label>
      <label class="switch-card configuration-span-2"><span><strong>启动后立即扫描</strong><small>服务启动完成后自动执行第一轮扫描</small></span><input id="lzScanStart" type="checkbox"></label>
    </div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>环境变量覆盖</h2><p>环境变量优先于配置文件，可能使页面保存值不生效</p></div></header>
    <div class="panel-body stack-list" id="lanzouOverrideList"><div class="empty-state">正在读取覆盖项</div></div>
  </article>
  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>WER 解析器</h2><p>API Key 不回显，留空表示保留当前值</p></div><span class="badge badge-neutral" id="werKeyStatus">状态未知</span></header>
    <div class="panel-body configuration-grid">
      <label class="field configuration-span-2"><span>WER API 地址</span><input id="lzWerEndpoint" autocomplete="off"></label>
      <label class="field"><span>请求方法</span><select id="lzWerMethod"><option value="GET">GET</option><option value="POST">POST</option></select></label>
      <label class="field"><span>URL 参数名</span><input id="lzWerUrlParam" autocomplete="off"></label>
      <label class="field"><span>密码参数名</span><input id="lzWerPwdParam" autocomplete="off"></label>
      <label class="field"><span>WER API Key</span><input id="lzWerKey" type="password" autocomplete="new-password" placeholder="留空不修改"></label>
    </div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>通知模板</h2><p>可使用标题、链接等现有模板变量</p></div></header>
    <div class="panel-body">
      <div class="alert alert-warning" id="lzTemplateEncodingWarning" hidden>检测到历史 WebUI 编码损坏。当前运行模板保持原样；只有重新输入内容后才会替换。</div>
      <label class="field"><span>推送消息模板</span><textarea id="lzTemplate" rows="10" placeholder="留空保留当前运行模板"></textarea></label>
    </div>
  </article>
</section>
<section class="panel"><header class="panel-header"><div><h2>最后一次操作</h2><p>保存成功后显示备份与运行态刷新结果</p></div><a class="text-link" href="/lanzou/watchers">管理监控项目</a></header><div class="panel-body"><pre class="operations-result configuration-result" id="configurationResult">尚未执行操作</pre></div></section>''' + _confirm_dialog()
    return render_console_shell(
        active="lanzou-config",
        title="蓝奏全局配置",
        content=content,
        body_marker="lanzou-config",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


def render_watchers_page() -> str:
    actions = (
        f'<button class="button button-secondary" id="watchersRefreshButton" type="button">{icon("refresh")}<span>重新读取</span></button>'
        f'<button class="button button-secondary" id="watcherAddButton" type="button">{icon("plus")}<span>新增监控</span></button>'
        f'<button class="button button-primary" id="watchersSaveButton" type="button">{icon("save")}<span>保存监控项目</span></button>'
    )
    content = _page_header(
        eyebrow="P3B · 蓝奏监控",
        title="监控项目",
        description="新增、编辑、扫描、测试推送和查看文件快照。网盘密码不回显，留空表示保留原值。",
        actions=actions,
    ) + '''
<section class="metric-grid metric-grid-3">
  <article class="metric-card"><div class="metric-icon">''' + icon("radar") + '''</div><div><span>监控项目</span><strong id="watcherCount" class="skeleton-text">0</strong><small>当前配置总数</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("check") + '''</div><div><span>已启用</span><strong id="watcherEnabledCount" class="skeleton-text">0</strong><small>参与自动扫描</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("alert") + '''</div><div><span>需要关注</span><strong id="watcherIssueCount" class="skeleton-text">0</strong><small>最近扫描失败或待推送</small></div></article>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>监控项目列表</h2><p>修改 ID 时会按原位置保留未重新填写的密码</p></div><span class="badge badge-warning">保存前自动备份</span></header>
  <div class="table-wrap"><table class="configuration-table"><thead><tr><th>启用</th><th>ID / 名称</th><th>分享地址</th><th>密码</th><th>页数</th><th>最近状态</th><th>操作</th></tr></thead><tbody id="watcherRows"><tr><td colspan="7"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取监控项目</div></td></tr></tbody></table></div>
</section>
<section class="panel"><header class="panel-header"><div><h2>最后一次操作</h2><p>扫描、推送、保存结果均在此显示</p></div></header><div class="panel-body"><pre class="operations-result configuration-result" id="configurationResult">尚未执行操作</pre></div></section>''' + _confirm_dialog() + _snapshot_dialog()
    return render_console_shell(
        active="watchers",
        title="监控项目",
        content=content,
        body_marker="watchers",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


def render_targets_page() -> str:
    actions = (
        f'<button class="button button-secondary" id="targetsRefreshButton" type="button">{icon("refresh")}<span>重新读取</span></button>'
        f'<button class="button button-secondary" id="targetAddButton" type="button">{icon("plus")}<span>新增目标</span></button>'
        f'<button class="button button-secondary" id="targetsTestButton" type="button">{icon("send")}<span>测试推送</span></button>'
        f'<button class="button button-primary" id="targetsSaveButton" type="button">{icon("save")}<span>保存通知目标</span></button>'
    )
    content = _page_header(
        eyebrow="P3B · 蓝奏监控",
        title="通知目标",
        description="管理多个通知回调地址、超时和请求 Headers。Header 与 URL 敏感查询值只返回掩码，未修改的掩码会安全保留原值。",
        actions=actions,
    ) + '''
<section class="metric-grid metric-grid-3">
  <article class="metric-card"><div class="metric-icon">''' + icon("bell") + '''</div><div><span>通知目标</span><strong id="targetCount" class="skeleton-text">0</strong><small>当前配置总数</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("check") + '''</div><div><span>已启用</span><strong id="targetEnabledCount" class="skeleton-text">0</strong><small>参与事件推送</small></div></article>
  <article class="metric-card"><div class="metric-icon">''' + icon("key") + '''</div><div><span>敏感 Header</span><strong>始终掩码</strong><small>保存 *** 时保留原值</small></div></article>
</section>
<section class="panel">
  <header class="panel-header"><div><h2>通知目标列表</h2><p>从 Headers JSON 删除字段可移除该 Header；值为 *** 时保留已有值</p></div><span class="badge badge-warning">保存前自动备份</span></header>
  <div class="table-wrap"><table class="configuration-table"><thead><tr><th>启用</th><th>名称</th><th>回调地址</th><th>超时</th><th>Headers JSON</th><th>操作</th></tr></thead><tbody id="targetRows"><tr><td colspan="6"><div class="empty-state loading-state"><span class="loading-spinner"></span>正在读取通知目标</div></td></tr></tbody></table></div>
</section>
<section class="panel"><header class="panel-header"><div><h2>最后一次操作</h2><p>保存和测试推送结果均在此显示</p></div></header><div class="panel-body"><pre class="operations-result configuration-result" id="configurationResult">尚未执行操作</pre></div></section>''' + _confirm_dialog()
    return render_console_shell(
        active="targets",
        title="通知目标",
        content=content,
        body_marker="targets",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


def render_debugger_page() -> str:
    actions = f'<button class="button button-secondary" id="debuggerRefreshButton" type="button">{icon("refresh")}<span>刷新 OpenAPI</span></button>'
    content = _page_header(
        eyebrow="P3B · 开发与文档",
        title="接口调试器",
        description="从 5001 与 6178 OpenAPI 自动生成接口清单，经服务端安全转发请求，不允许任意外部地址。",
        actions=actions,
    ) + '''
<section class="debugger-layout">
  <article class="panel">
    <header class="panel-header"><div><h2>请求</h2><p id="debuggerRouteCount">正在读取接口清单</p></div></header>
    <div class="panel-body configuration-form">
      <label class="field"><span>接口</span><select id="debuggerRouteSelect"><option value="">正在读取...</option></select></label>
      <div class="configuration-grid">
        <label class="field"><span>超时（秒）</span><input id="debuggerTimeout" type="number" min="1" max="120" value="30"></label>
        <label class="field"><span>服务</span><input id="debuggerService" readonly value="-"></label>
      </div>
      <div class="alert alert-neutral" id="debuggerRouteHint">请选择接口</div>
      <label class="field"><span>Query 与 Path 参数 JSON</span><textarea id="debuggerQuery" rows="9">{}</textarea></label>
      <label class="field"><span>请求 Headers JSON</span><textarea id="debuggerHeaders" rows="6">{}</textarea></label>
      <label class="field"><span>请求体 JSON</span><textarea id="debuggerBody" rows="9">{}</textarea></label>
      <button class="button button-primary" id="debuggerSendButton" type="button">''' + icon("send") + '''<span>发送请求</span></button>
    </div>
  </article>
  <article class="panel">
    <header class="panel-header"><div><h2>响应</h2><p id="debuggerResponseMeta">尚未发送请求</p></div></header>
    <div class="panel-body"><pre class="operations-console debugger-response" id="debuggerResponse">暂无响应</pre><div class="debugger-image" id="debuggerImage"></div></div>
  </article>
</section>'''
    return render_console_shell(
        active="api-debugger",
        title="接口调试器",
        content=content,
        body_marker="api-debugger",
        styles=_STYLES,
        scripts=_SCRIPTS,
    )


__all__ = [
    "render_debugger_page",
    "render_lanzou_config_page",
    "render_main_config_page",
    "render_targets_page",
    "render_watchers_page",
]
