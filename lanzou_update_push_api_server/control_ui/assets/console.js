(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = { loading: false };

  function adminToken() {
    try {
      return sessionStorage.getItem('lolapisevers_admin_token') || '';
    } catch (_error) {
      return '';
    }
  }

  async function api(path) {
    const headers = { accept: 'application/json' };
    const token = adminToken();
    if (token) headers['x-admin-token'] = token;
    const response = await fetch(path, { headers, cache: 'no-store' });
    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (_error) {
      data = { ok: false, error: text || response.statusText };
    }
    if (!response.ok) {
      throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function text(value, fallback = '-') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  }

  function escapeHtml(value) {
    return text(value, '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function badge(label, kind = 'neutral') {
    return `<span class="badge badge-${kind}">${escapeHtml(label)}</span>`;
  }

  function setBadge(id, label, kind) {
    const node = $(id);
    if (!node) return;
    node.textContent = label;
    node.className = `badge badge-${kind}`;
  }

  function isHealthy(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (payload.ok === false) return false;
    if (payload.status === 'error' || payload.status === 'down') return false;
    if (payload.ready === false || payload.running === false) return false;
    return Boolean(
      payload.ok === true ||
      payload.status === 'ok' ||
      payload.status === 'healthy' ||
      payload.ready === true ||
      payload.running === true ||
      payload.liveness === 'up'
    );
  }

  function healthMessage(payload) {
    if (!payload || typeof payload !== 'object') return '未返回状态';
    return text(
      payload.message ||
      payload.error ||
      payload.status ||
      payload.detail ||
      (payload.ready === true ? '服务已就绪' : ''),
      '状态已读取'
    );
  }

  function showToast(message, isError = false) {
    const region = $('toastRegion');
    if (!region) return;
    const node = document.createElement('div');
    node.className = `toast${isError ? ' is-error' : ''}`;
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(() => node.remove(), 3600);
  }

  function renderMainService(overview) {
    const health = overview?.mainApi?.health || {};
    const healthy = isHealthy(health);
    $('mainServiceState').textContent = healthy ? '运行正常' : '需要关注';
    $('mainServiceDetail').textContent = healthy ? '5001 健康检查通过' : healthMessage(health);
    $('mainServiceMessage').textContent = healthMessage(health);
    setBadge('mainServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');
    return healthy;
  }

  function renderControlService(overview, serviceStatus) {
    const health = overview?.lanzou?.health || {};
    const serviceRunning = serviceStatus?.running === true || String(serviceStatus?.status || '').toLowerCase() === 'running';
    const healthy = isHealthy(health) || serviceRunning;
    $('controlServiceState').textContent = healthy ? '运行正常' : '需要关注';
    $('controlServiceDetail').textContent = healthy ? '6178 控制台可用' : healthMessage(health);
    $('controlServiceMessage').textContent = serviceRunning ? 'Windows 服务正在运行' : healthMessage(health);
    setBadge('controlServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');
    return healthy;
  }

  function renderBuild(buildInfo) {
    const release = text(buildInfo?.release || buildInfo?.version, '未知版本');
    const commit = text(buildInfo?.commit || buildInfo?.git_commit || buildInfo?.sha, '');
    $('buildBadge').textContent = commit ? `${release} · ${commit.slice(0, 8)}` : release;
  }

  function providerRuntimeMap(lolban) {
    const map = new Map();
    const items = Array.isArray(lolban?.runtime_provider_identity) ? lolban.runtime_provider_identity : [];
    items.forEach((item) => map.set(String(item.id || item.name || ''), item));
    return map;
  }

  function renderProviders(lolban) {
    const body = $('providerRows');
    const diskItems = Array.isArray(lolban?.disk?.active_provider_identity)
      ? lolban.disk.active_provider_identity
      : [];
    const runtimeMap = providerRuntimeMap(lolban);
    const runtimeCount = Array.isArray(lolban?.runtime?.providers) ? lolban.runtime.providers.length : runtimeMap.size;

    $('providerMetric').textContent = String(runtimeCount);
    $('providerMetricDetail').textContent = lolban?.runtime_matches_disk ? '磁盘与运行态一致' : '磁盘与运行态需要核对';

    if (!diskItems.length) {
      body.innerHTML = '<tr><td colspan="5"><div class="empty-state">当前没有启用的封号 Provider</div></td></tr>';
      return { count: runtimeCount, mismatch: !lolban?.runtime_matches_disk };
    }

    body.innerHTML = diskItems.map((item, index) => {
      const id = String(item.id || item.name || `provider-${index + 1}`);
      const runtime = runtimeMap.get(id);
      const enabled = item.enabled !== false;
      return `<tr>
        <td>${escapeHtml(item.order || index + 1)}</td>
        <td><strong>${escapeHtml(id)}</strong></td>
        <td><span class="code">${escapeHtml(item.method || 'GET')}</span></td>
        <td>${badge(enabled ? '已启用' : '已停用', enabled ? 'success' : 'neutral')}</td>
        <td>${badge(runtime ? '已加载' : '未加载', runtime ? 'success' : 'warning')}</td>
      </tr>`;
    }).join('');

    return { count: runtimeCount, mismatch: !lolban?.runtime_matches_disk };
  }

  function collectDegraded(overview, lolban, serviceStatus) {
    const items = [];
    const mainHealth = overview?.mainApi?.health || {};
    const lanzouHealth = overview?.lanzou?.health || {};
    if (!isHealthy(mainHealth)) items.push({ title: '5001 主接口健康异常', detail: healthMessage(mainHealth), kind: 'danger' });
    if (!isHealthy(lanzouHealth)) items.push({ title: '6178 监控状态异常', detail: healthMessage(lanzouHealth), kind: 'danger' });
    if (lolban && lolban.runtime_matches_disk === false) {
      items.push({ title: '封号 Provider 配置未同步', detail: '磁盘配置与 5001 当前运行态不一致', kind: 'warning' });
    }
    const secret = lolban?.fourpng_secret;
    if (secret?.disk_configured && !secret?.runtime_configured) {
      items.push({ title: '4PNG Token 尚未加载到 5001', detail: 'Token 已保存，但运行态未加载', kind: 'warning' });
    }
    const serviceText = String(serviceStatus?.status || '').toLowerCase();
    if (serviceStatus?.running === false || (serviceText && serviceText !== 'running')) {
      items.push({ title: 'Windows 服务状态需要关注', detail: text(serviceStatus?.message || serviceStatus?.status), kind: 'warning' });
    }
    return items;
  }

  function renderDegraded(items) {
    $('degradedMetric').textContent = String(items.length);
    $('degradedMetricDetail').textContent = items.length ? '存在需要处理的状态' : '当前没有已识别的降级项';
    const container = $('degradedList');
    if (!items.length) {
      container.innerHTML = '<div class="empty-state">当前没有已识别的降级或告警</div>';
      return;
    }
    container.innerHTML = items.map((item) => `<div class="stack-item">
      ${badge(item.kind === 'danger' ? '异常' : '降级', item.kind)}
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.detail)}</span>
    </div>`).join('');
  }

  function normalizeAudit(data) {
    if (Array.isArray(data)) return data;
    for (const key of ['items', 'audit', 'records', 'events']) {
      if (Array.isArray(data?.[key])) return data[key];
    }
    return [];
  }

  function renderAudit(data) {
    const items = normalizeAudit(data).slice(0, 6);
    const container = $('auditList');
    if (!items.length) {
      container.innerHTML = '<div class="empty-state">暂无可显示的配置变更</div>';
      return;
    }
    container.innerHTML = items.map((item) => `<div class="timeline-item">
      <strong>${escapeHtml(item.action || item.operation || item.kind || '配置操作')}</strong>
      <span>${escapeHtml(item.timestamp || item.created_at || item.time || '')} ${escapeHtml(item.target || item.path || item.message || '')}</span>
    </div>`).join('');
  }

  function normalizeLogs(data) {
    if (Array.isArray(data)) return data;
    for (const key of ['logs', 'files', 'items']) {
      if (Array.isArray(data?.[key])) return data[key];
    }
    return [];
  }

  function renderLogs(data) {
    const items = normalizeLogs(data).slice(0, 8);
    const container = $('logList');
    if (!items.length) {
      container.innerHTML = '<div class="empty-state">暂无日志文件摘要</div>';
      return;
    }
    container.innerHTML = items.map((item) => {
      const name = typeof item === 'string' ? item : item.name || item.path || item.file || '日志文件';
      const detail = typeof item === 'string' ? '' : item.updated_at || item.modified || item.size || item.status || '';
      return `<div class="log-item"><strong class="code">${escapeHtml(name)}</strong><span>${escapeHtml(detail)}</span></div>`;
    }).join('');
  }

  function renderGlobalStatus(mainHealthy, controlHealthy, degradedCount) {
    const good = mainHealthy && controlHealthy && degradedCount === 0;
    const dot = $('globalStatusDot');
    dot.className = `status-dot ${good ? 'status-dot-success' : 'status-dot-danger'}`;
    $('globalStatusText').textContent = good ? '生产状态正常' : '存在需要关注的状态';
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    const button = $('refreshButton');
    button.disabled = true;
    button.querySelector('span').textContent = '刷新中';

    const paths = [
      '/admin/overview',
      '/admin/query-console/lolban',
      '/admin/audit?limit=10',
      '/admin/logs',
      '/admin/service/status',
      '/build-info'
    ];
    const results = await Promise.allSettled(paths.map(api));
    const values = results.map((result) => result.status === 'fulfilled' ? result.value : null);
    const [overview, lolban, audit, logs, serviceStatus, buildInfo] = values;

    try {
      const mainHealthy = renderMainService(overview || {});
      const controlHealthy = renderControlService(overview || {}, serviceStatus || {});
      renderBuild(buildInfo || {});
      renderProviders(lolban || {});
      const degraded = collectDegraded(overview || {}, lolban || {}, serviceStatus || {});
      renderDegraded(degraded);
      renderAudit(audit || {});
      renderLogs(logs || {});
      renderGlobalStatus(mainHealthy, controlHealthy, degraded.length);

      const failed = results.filter((result) => result.status === 'rejected');
      if (failed.length) showToast(`有 ${failed.length} 项状态读取失败，页面已显示其余可用数据`, true);
    } finally {
      state.loading = false;
      button.disabled = false;
      button.querySelector('span').textContent = '刷新状态';
    }
  }

  function bindNavigation() {
    const toggle = $('sidebarToggle');
    const backdrop = $('sidebarBackdrop');
    const close = () => document.body.classList.remove('sidebar-open');
    toggle?.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
    backdrop?.addEventListener('click', close);
    document.querySelectorAll('.sidebar a').forEach((link) => link.addEventListener('click', close));
    window.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') close();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindNavigation();
    $('refreshButton')?.addEventListener('click', refresh);
    refresh().catch((error) => showToast(error.message || '状态读取失败', true));
  });
})();
