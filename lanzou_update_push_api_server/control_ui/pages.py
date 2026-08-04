from __future__ import annotations


def _icon(name: str) -> str:
    return (
        '<svg class="ui-icon" aria-hidden="true">'
        f'<use href="/control-assets/icons.svg#icon-{name}"></use>'
        "</svg>"
    )


def _nav_link(path: str, label: str, icon: str, *, active: bool = False) -> str:
    active_attr = ' aria-current="page" class="nav-link is-active"' if active else ' class="nav-link"'
    return f'<a href="{path}"{active_attr}>{_icon(icon)}<span>{label}</span></a>'


def render_overview_page() -> str:
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>LOLDataSystem 控制台</title>
<link rel="stylesheet" href="/control-assets/console.css">
</head>
<body data-console-ui="p0">
<div class="app-shell">
  <aside class="sidebar" id="consoleSidebar" aria-label="主导航">
    <div class="brand">
      <div class="brand-mark">LD</div>
      <div><strong>LOLDataSystem</strong><span>运维控制台 · 6178</span></div>
    </div>
    <nav class="nav-groups">
      <section class="nav-group">
        <h2>总览</h2>
        {_nav_link('/', '控制台总览', 'dashboard', active=True)}
      </section>
      <section class="nav-group">
        <h2>查询服务</h2>
        {_nav_link('/query-console/lolban', '封号查询', 'shield')}
        {_nav_link('/parser-center', '接口与解析中心', 'workflow')}
        {_nav_link('/parser-center/secrets', 'Secret 与备份', 'key')}
      </section>
      <section class="nav-group">
        <h2>蓝奏监控</h2>
        {_nav_link('/?tab=lanzouconfig', '全局配置', 'settings')}
        {_nav_link('/?tab=watchers', '监控项目', 'radar')}
        {_nav_link('/?tab=targets', '通知目标', 'bell')}
      </section>
      <section class="nav-group">
        <h2>系统管理</h2>
        {_nav_link('/?tab=mainconfig', '主接口配置', 'server')}
        {_nav_link('/?tab=logs', '运行日志', 'file-text')}
        {_nav_link('/?tab=diagnostics', '诊断与修复', 'activity')}
        {_nav_link('/?tab=system', '安全与回滚', 'lock')}
      </section>
      <section class="nav-group">
        <h2>开发与文档</h2>
        {_nav_link('/docs', 'OpenAPI 文档', 'book')}
        {_nav_link('/legacy-ui', '旧版控制台', 'history')}
      </section>
    </nav>
    <div class="sidebar-footer">
      <span class="status-dot status-dot-neutral"></span>
      <span>生产操作会校验、备份并记录审计</span>
    </div>
  </aside>

  <div class="workspace">
    <header class="topbar">
      <button class="icon-button mobile-only" id="sidebarToggle" type="button" aria-label="打开导航">{_icon('menu')}</button>
      <div class="breadcrumb"><span>LOLDataSystem</span><b>/</b><strong>控制台总览</strong></div>
      <div class="topbar-actions">
        <span class="environment-badge"><span class="status-dot" id="globalStatusDot"></span><span id="globalStatusText">正在读取状态</span></span>
        <button class="button button-secondary" id="adminTokenButton" type="button">{_icon('key')}<span>管理令牌</span></button>
        <a class="button button-secondary" href="/legacy-ui">旧版入口</a>
      </div>
    </header>

    <main class="content">
      <section class="page-header">
        <div>
          <p class="eyebrow">WEBUI-CONTROL-PANEL-003 · P0</p>
          <h1>控制台总览</h1>
          <p>统一查看服务健康、查询 Provider、降级项、配置变更和最近错误。</p>
        </div>
        <div class="page-actions">
          <button class="button button-primary" id="refreshButton" type="button">{_icon('refresh')}<span>刷新状态</span></button>
        </div>
      </section>

      <section class="metric-grid" aria-label="核心状态">
        <article class="metric-card">
          <div class="metric-icon">{_icon('server')}</div>
          <div><span>5001 主接口</span><strong id="mainServiceState" class="skeleton-text skeleton-title">读取中</strong><small id="mainServiceDetail" class="skeleton-text">等待健康检查</small></div>
        </article>
        <article class="metric-card">
          <div class="metric-icon">{_icon('monitor')}</div>
          <div><span>6178 控制台</span><strong id="controlServiceState" class="skeleton-text skeleton-title">读取中</strong><small id="controlServiceDetail" class="skeleton-text">等待服务状态</small></div>
        </article>
        <article class="metric-card">
          <div class="metric-icon">{_icon('plug')}</div>
          <div><span>已加载 Provider</span><strong id="providerMetric" class="skeleton-text skeleton-title">-</strong><small id="providerMetricDetail" class="skeleton-text">等待运行态数据</small></div>
        </article>
        <article class="metric-card">
          <div class="metric-icon">{_icon('alert-triangle')}</div>
          <div><span>当前降级项</span><strong id="degradedMetric" class="skeleton-text skeleton-title">-</strong><small id="degradedMetricDetail" class="skeleton-text">等待诊断结果</small></div>
        </article>
      </section>

      <section class="dashboard-grid">
        <article class="panel panel-span-2">
          <header class="panel-header">
            <div><h2>服务运行状态</h2><p>5001 与 6178 的实时健康和构建信息</p></div>
            <span class="badge badge-neutral skeleton-text" id="buildBadge">构建信息读取中</span>
          </header>
          <div class="service-list">
            <div class="service-row">
              <div class="service-name"><span class="service-symbol">{_icon('server')}</span><div><strong>LOLDataSystem API</strong><small>http://127.0.0.1:5001</small></div></div>
              <span class="badge badge-neutral" id="mainServiceBadge">读取中</span>
              <span class="service-message skeleton-text" id="mainServiceMessage">等待健康检查</span>
            </div>
            <div class="service-row">
              <div class="service-name"><span class="service-symbol">{_icon('monitor')}</span><div><strong>Control WebUI</strong><small>http://127.0.0.1:6178</small></div></div>
              <span class="badge badge-neutral" id="controlServiceBadge">读取中</span>
              <span class="service-message skeleton-text" id="controlServiceMessage">等待运行状态</span>
            </div>
          </div>
        </article>

        <article class="panel">
          <header class="panel-header"><div><h2>快捷操作</h2><p>进入常用管理功能</p></div></header>
          <div class="quick-actions">
            <a href="/query-console/lolban">{_icon('shield')}<span><strong>封号查询</strong><small>Provider 与正式链路</small></span>{_icon('chevron-right')}</a>
            <a href="/parser-center">{_icon('workflow')}<span><strong>接口与解析中心</strong><small>请求、解析和模板</small></span>{_icon('chevron-right')}</a>
            <a href="/parser-center/secrets">{_icon('key')}<span><strong>Secret 与备份</strong><small>密钥、备份和回滚</small></span>{_icon('chevron-right')}</a>
            <a href="/?tab=diagnostics">{_icon('activity')}<span><strong>诊断与修复</strong><small>检查生产运行状态</small></span>{_icon('chevron-right')}</a>
          </div>
        </article>

        <article class="panel panel-span-2">
          <header class="panel-header">
            <div><h2>封号 Provider</h2><p>磁盘配置与 5001 当前运行态</p></div>
            <a class="text-link" href="/query-console/lolban">管理 Provider {_icon('arrow-up-right')}</a>
          </header>
          <div class="table-wrap">
            <table>
              <thead><tr><th>顺序</th><th>Provider</th><th>方法</th><th>状态</th><th>运行态</th></tr></thead>
              <tbody id="providerRows"><tr><td colspan="5"><div class="empty-state loading-state"><span class="loading-spinner" aria-hidden="true"></span>正在读取 Provider…</div></td></tr></tbody>
            </table>
          </div>
        </article>

        <article class="panel">
          <header class="panel-header"><div><h2>降级与告警</h2><p>需要关注但未必阻断服务</p></div></header>
          <div class="stack-list" id="degradedList"><div class="empty-state loading-state"><span class="loading-spinner" aria-hidden="true"></span>正在读取诊断状态…</div></div>
        </article>

        <article class="panel">
          <header class="panel-header"><div><h2>最近配置变更</h2><p>来自操作审计记录</p></div><a class="text-link" href="/?tab=system">查看审计</a></header>
          <div class="timeline" id="auditList"><div class="empty-state loading-state"><span class="loading-spinner" aria-hidden="true"></span>正在读取审计记录…</div></div>
        </article>

        <article class="panel panel-span-2">
          <header class="panel-header"><div><h2>最近错误与日志</h2><p>只展示文件与状态，不暴露 Secret</p></div><a class="text-link" href="/?tab=logs">打开日志中心</a></header>
          <div class="log-summary" id="logList"><div class="empty-state loading-state"><span class="loading-spinner" aria-hidden="true"></span>正在读取日志摘要…</div></div>
        </article>
      </section>
    </main>
  </div>
</div>
<div class="sidebar-backdrop" id="sidebarBackdrop"></div>

<dialog class="dialog" id="adminTokenDialog" aria-labelledby="adminTokenTitle">
  <form class="dialog-card" id="adminTokenForm">
    <header class="dialog-header">
      <div>
        <p class="eyebrow">访问控制</p>
        <h2 id="adminTokenTitle">管理令牌</h2>
      </div>
      <button class="icon-button" id="adminTokenClose" type="button" aria-label="关闭对话框">{_icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description">令牌仅保存在当前浏览器标签页的会话存储中，关闭标签页后自动清除，不会写入服务配置或页面源码。</p>
      <label class="field" for="adminTokenInput">
        <span>WEBUI_ADMIN_TOKEN</span>
        <input id="adminTokenInput" name="admin_token" type="password" autocomplete="off" spellcheck="false" placeholder="请输入管理令牌">
        <small id="adminTokenHint">未配置令牌时，本机回环访问可以直接使用管理功能。</small>
      </label>
      <div class="inline-status" id="adminTokenStatus"><span class="status-dot status-dot-neutral"></span><span>当前标签页尚未保存令牌</span></div>
    </div>
    <footer class="dialog-footer">
      <button class="button button-danger-ghost" id="adminTokenClear" type="button">清除令牌</button>
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="adminTokenCancel" type="button">取消</button>
      <button class="button button-primary" type="submit">保存并重新读取</button>
    </footer>
  </form>
</dialog>

<div class="toast-region" id="toastRegion" aria-live="polite"></div>
<!-- legacy compatibility markers: lolapisevers 接口端总控台 watcherRows /notify/test -->
<script src="/control-assets/console.js" defer></script>
</body>
</html>'''
