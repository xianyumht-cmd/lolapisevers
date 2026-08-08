from __future__ import annotations

from .components import icon, render_console_shell


def _metric_card(label: str, value_id: str, detail_id: str) -> str:
    return f'''<article class="metric-card">
  <div>
    <span>{label}</span>
    <strong id="{value_id}" class="skeleton-text skeleton-title">读取中</strong>
    <small id="{detail_id}" class="skeleton-text">等待 5001 状态</small>
  </div>
</article>'''


def render_target_file_watch_page() -> str:
    content = f'''
<section class="page-header">
  <div>
    <p class="eyebrow">TARGET-FILE-WATCH · 5001</p>
    <h1>定向文件监控</h1>
    <p>只负责查看 5001 的蓝奏目录监控、Provider、baseline 和投递状态；业务配置由 GroupGuard 6108 统一管理。</p>
  </div>
  <div class="page-actions">
    <button class="button button-secondary" id="targetWatchRefreshButton" type="button">{icon('refresh')}<span>刷新状态</span></button>
    <button class="button button-primary" id="targetWatchCheckButton" type="button">{icon('radar')}<span>立即检查</span></button>
  </div>
</section>

<section class="metric-grid" aria-label="定向文件监控核心状态">
  {_metric_card('功能状态', 'targetWatchEnabled', 'targetWatchEnabledDetail')}
  {_metric_card('后台循环', 'targetWatchRunning', 'targetWatchRunningDetail')}
  {_metric_card('当前 Provider', 'targetWatchProvider', 'targetWatchProviderDetail')}
  {_metric_card('Baseline 文件', 'targetWatchBaselineCount', 'targetWatchBaselineDetail')}
</section>

<section class="dashboard-grid">
  <article class="panel panel-span-2">
    <header class="panel-header">
      <div><h2>监控来源</h2><p>以下值由 GroupGuard 6108 保存并同步到 5001，本页只读。</p></div>
      <a class="text-link" href="http://192.168.3.89:6108/target-file-push.html" target="_blank" rel="noopener noreferrer">打开 GroupGuard 配置 {icon('arrow-up-right')}</a>
    </header>
    <div class="service-list">
      <div class="service-row">
        <div class="service-name"><span class="service-symbol">{icon('radar')}</span><div><strong>蓝奏目录</strong><small id="targetWatchSourceUrl">读取中</small></div></div>
        <span class="badge badge-neutral" id="targetWatchInterval">读取中</span>
        <span class="service-message">配置源：GroupGuard 6108</span>
      </div>
      <div class="service-row">
        <div class="service-name"><span class="service-symbol">{icon('workflow')}</span><div><strong>回调状态</strong><small id="targetWatchCallbackUrl">读取中</small></div></div>
        <span class="badge badge-neutral" id="targetWatchCallbackToken">读取中</span>
        <span class="service-message">5001 检测更新后回调 GroupGuard 上传群文件</span>
      </div>
    </div>
  </article>

  <article class="panel">
    <header class="panel-header"><div><h2>最近运行</h2><p>检查、投递和错误时间</p></div></header>
    <div class="stack-list">
      <div class="stack-item"><strong>最近检查</strong><span id="targetWatchLastCheck">-</span></div>
      <div class="stack-item"><strong>最近成功</strong><span id="targetWatchLastSuccess">-</span></div>
      <div class="stack-item"><strong>最近投递</strong><span id="targetWatchLastDelivery">-</span></div>
      <div class="stack-item"><strong>最近事件</strong><span id="targetWatchLastEvent">-</span></div>
    </div>
  </article>

  <article class="panel panel-span-2">
    <header class="panel-header">
      <div><h2>当前 Baseline</h2><p>首次启用只建立 baseline，不上传目录里已经存在的文件。</p></div>
      <a class="text-link" href="/lanzou/config">查看 Provider 配置 {icon('arrow-up-right')}</a>
    </header>
    <div class="table-wrap">
      <table>
        <thead><tr><th>文件名</th><th>大小</th><th>修改时间</th><th>Stable ID</th></tr></thead>
        <tbody id="targetWatchBaselineRows"><tr><td colspan="4"><div class="empty-state">正在读取 baseline…</div></td></tr></tbody>
      </table>
    </div>
  </article>

  <article class="panel">
    <header class="panel-header"><div><h2>待投递事件</h2><p>只有新增或替换文件会进入投递；上游删除不会上传。</p></div></header>
    <div class="stack-list" id="targetWatchPendingList"><div class="empty-state">正在读取待投递状态…</div></div>
  </article>

  <article class="panel panel-span-2">
    <header class="panel-header">
      <div><h2>诊断与安全操作</h2><p>重新建立基线会丢弃当前监控差异，只在确认状态异常时使用。</p></div>
    </header>
    <div class="quick-actions">
      <button class="button button-secondary" id="targetWatchRebaselineButton" type="button">{icon('refresh')}<span><strong>重新建立基线</strong><small>下一次检查只建立当前目录快照，不上传现有文件</small></span></button>
      <a href="/api-debugger">{icon('plug')}<span><strong>接口调试器</strong><small>查看 /api/v1/target-file-watch/* 原始响应</small></span>{icon('chevron-right')}</a>
      <a href="/logs">{icon('file-text')}<span><strong>运行日志</strong><small>排查 Provider、直链和 callback 错误</small></span>{icon('chevron-right')}</a>
    </div>
    <div class="log-summary" id="targetWatchErrorBox"><div class="empty-state">当前没有已读取的错误</div></div>
  </article>
</section>

<dialog class="dialog" id="targetWatchRebaselineDialog" aria-labelledby="targetWatchRebaselineTitle">
  <div class="dialog-card">
    <header class="dialog-header">
      <div><p class="eyebrow">危险操作确认</p><h2 id="targetWatchRebaselineTitle">重新建立定向文件 baseline</h2></div>
      <button class="icon-button" id="targetWatchRebaselineClose" type="button" aria-label="关闭">{icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description">这会清空 5001 当前定向监控差异状态。下一次检查只把蓝奏目录现状建立为新 baseline，不会上传目录里已经存在的文件。</p>
      <div class="inline-status"><span class="status-dot status-dot-warning"></span><span>只在 baseline 损坏、Provider 切换异常或明确需要重置监控起点时使用。</span></div>
    </div>
    <footer class="dialog-footer">
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="targetWatchRebaselineCancel" type="button">取消</button>
      <button class="button button-danger-ghost" id="targetWatchRebaselineConfirm" type="button">确认重新建立基线</button>
    </footer>
  </div>
</dialog>
'''
    return render_console_shell(
        active="target-file-watch",
        title="定向文件监控",
        content=content,
        body_marker="target-file-watch",
        scripts=("/control-assets/target-file-watch.js",),
    )


__all__ = ["render_target_file_watch_page"]
