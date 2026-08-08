from __future__ import annotations

from .components import icon, render_console_shell


def _metric_card(
    icon_name: str,
    label: str,
    state_id: str,
    detail_id: str,
    detail: str,
) -> str:
    return f'''<article class="metric-card">
  <div class="metric-icon">{icon(icon_name)}</div>
  <div>
    <span>{label}</span>
    <strong id="{state_id}" class="skeleton-text skeleton-title">读取中</strong>
    <small id="{detail_id}" class="skeleton-text">{detail}</small>
  </div>
</article>'''


def _loading_state(label: str) -> str:
    return (
        '<div class="empty-state loading-state">'
        '<span class="loading-spinner" aria-hidden="true"></span>'
        f'{label}</div>'
    )


def render_overview_page() -> str:
    content = f'''
<section class="page-header">
  <div>
    <p class="eyebrow">WEBUI-CONTROL-PANEL-003 · P0</p>
    <h1>控制台总览</h1>
    <p>统一查看服务健康、查询 Provider、降级项、配置变更和最近错误。</p>
  </div>
  <div class="page-actions">
    <button class="button button-primary" id="refreshButton" type="button">{icon('refresh')}<span>刷新状态</span></button>
  </div>
</section>

<section class="metric-grid" aria-label="核心状态">
  {_metric_card('server', '5001 主接口', 'mainServiceState', 'mainServiceDetail', '等待健康检查')}
  {_metric_card('monitor', '6178 控制台', 'controlServiceState', 'controlServiceDetail', '等待服务状态')}
  {_metric_card('plug', '已加载 Provider', 'providerMetric', 'providerMetricDetail', '等待运行态数据')}
  {_metric_card('alert-triangle', '当前降级项', 'degradedMetric', 'degradedMetricDetail', '等待诊断结果')}
</section>

<section class="dashboard-grid">
  <article class="panel panel-span-2">
    <header class="panel-header">
      <div><h2>服务运行状态</h2><p>5001 与 6178 的实时健康和构建信息</p></div>
      <span class="badge badge-neutral skeleton-text" id="buildBadge">构建信息读取中</span>
    </header>
    <div class="service-list">
      <div class="service-row">
        <div class="service-name"><span class="service-symbol">{icon('server')}</span><div><strong>LOLDataSystem API</strong><small>http://127.0.0.1:5001</small></div></div>
        <span class="badge badge-neutral" id="mainServiceBadge">读取中</span>
        <span class="service-message skeleton-text" id="mainServiceMessage">等待健康检查</span>
      </div>
      <div class="service-row">
        <div class="service-name"><span class="service-symbol">{icon('monitor')}</span><div><strong>Control WebUI</strong><small>http://127.0.0.1:6178</small></div></div>
        <span class="badge badge-neutral" id="controlServiceBadge">读取中</span>
        <span class="service-message skeleton-text" id="controlServiceMessage">等待运行状态</span>
      </div>
    </div>
  </article>

  <article class="panel">
    <header class="panel-header"><div><h2>快捷操作</h2><p>进入常用管理功能</p></div></header>
    <div class="quick-actions">
      <a href="/query-console/lolban">{icon('shield')}<span><strong>封号查询</strong><small>Provider 与正式链路</small></span>{icon('chevron-right')}</a>
      <a href="/parser-center">{icon('workflow')}<span><strong>接口与解析中心</strong><small>请求、解析和模板</small></span>{icon('chevron-right')}</a>
      <a href="/parser-center/secrets">{icon('key')}<span><strong>Secret 与备份</strong><small>密钥、备份和回滚</small></span>{icon('chevron-right')}</a>
      <a href="/diagnostics">{icon('activity')}<span><strong>诊断与修复</strong><small>检查生产运行状态</small></span>{icon('chevron-right')}</a>
    </div>
  </article>

  <article class="panel panel-span-2">
    <header class="panel-header">
      <div><h2>封号 Provider</h2><p>磁盘配置与 5001 当前运行态</p></div>
      <a class="text-link" href="/query-console/lolban">管理 Provider {icon('arrow-up-right')}</a>
    </header>
    <div class="table-wrap">
      <table>
        <thead><tr><th>顺序</th><th>Provider</th><th>方法</th><th>状态</th><th>运行态</th></tr></thead>
        <tbody id="providerRows"><tr><td colspan="5">{_loading_state('正在读取 Provider…')}</td></tr></tbody>
      </table>
    </div>
  </article>

  <article class="panel">
    <header class="panel-header"><div><h2>降级与告警</h2><p>需要关注但未必阻断服务</p></div></header>
    <div class="stack-list" id="degradedList">{_loading_state('正在读取诊断状态…')}</div>
  </article>

  <article class="panel">
    <header class="panel-header"><div><h2>最近配置变更</h2><p>来自操作审计记录</p></div><a class="text-link" href="/?tab=system">查看审计</a></header>
    <div class="timeline" id="auditList">{_loading_state('正在读取审计记录…')}</div>
  </article>

  <article class="panel panel-span-2">
    <header class="panel-header"><div><h2>最近错误与日志</h2><p>只展示文件与状态，不暴露 Secret</p></div><a class="text-link" href="/?tab=logs">打开日志中心</a></header>
    <div class="log-summary" id="logList">{_loading_state('正在读取日志摘要…')}</div>
  </article>
</section>
'''
    return render_console_shell(
        active="overview",
        title="控制台总览",
        content=content,
        body_marker="p0",
    )
