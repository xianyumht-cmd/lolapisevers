(() => {
  'use strict';

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  const state = { loading: false, authPrompted: false };

  class ApiError extends Error {
    constructor(message, status, path, payload = {}) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.path = path;
      this.payload = payload;
    }
  }

  function adminToken() {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || '';
    } catch (_error) {
      return '';
    }
  }

  function storeAdminToken(value) {
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
      return true;
    } catch (_error) {
      return false;
    }
  }

  async function api(path) {
    const headers = { accept: 'application/json' };
    const token = adminToken();
    if (token) headers['x-admin-token'] = token;
    const response = await fetch(path, { headers, cache: 'no-store' });
    const raw = await response.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch (_error) {
      data = { ok: false, error: raw || response.statusText };
    }
    if (!response.ok) {
      throw new ApiError(
        data.detail || data.error || `HTTP ${response.status}`,
        response.status,
        path,
        data
      );
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

  function clearSkeleton(node) {
    node?.classList.remove('skeleton-text', 'skeleton-title');
  }

  function setText(id, value) {
    const node = $(id);
    if (!node) return;
    node.textContent = value;
    clearSkeleton(node);
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

  function showToast(message, kind = 'info') {
    const region = $('toastRegion');
    if (!region) return;
    const node = document.createElement('div');
    node.className = `toast toast-${kind}`;
    node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(() => node.remove(), 4200);
  }

  function renderMainService(overview) {
    const health = overview?.mainApi?.health || {};
    const healthy = isHealthy(health);
    setText('mainServiceState', healthy ? '运行正常' : '需要关注');
    setText('mainServiceDetail', healthy ? '5001 健康检查通过' : healthMessage(health));
    setText('mainServiceMessage', healthMessage(health));
    setBadge('mainServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');
    return healthy;
  }

  function renderControlService(overview, serviceStatus) {
    const health = overview?.lanzou?.health || {};
    const serviceRunning = serviceStatus?.running === true || String(serviceStatus?.status || '').toLowerCase() === 'running';
    const healthy = isHealthy(health) || serviceRunning;
    setText('controlServiceState', healthy ? '运行正常' : '需要关注');
    setText('controlServiceDetail', healthy ? '6178 控制台可用' : healthMessage(health));
    setText('controlServiceMessage', serviceRunning ? 'Windows 服务正在运行' : healthMessage(health));
    setBadge('controlServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');
    return healthy;
  }

  function renderBuild(buildInfo) {
    const release = text(buildInfo?.release || buildInfo?.version, '未知版本');
    const commit = text(buildInfo?.commit || buildInfo?.git_commit || buildInfo?.sha, '');
    setText('buildBadge', commit ? `${release} · ${commit.slice(0, 8)}` : release);
  }

  function providerRuntimeMap(lolban) {
    const map = new Map();
    const items = Array.isArray(lolban?.runtime_provider_identity) ? lolban.runtime_provider_identity : [];
    items.forEach((item) => map.set(String(item.id || item.name || ''), item));
    return map;
  }

  function renderProviders(lolban, failure = null) {
    const body = $('providerRows');
    const diskItems = Array.isArray(lolban?.disk?.active_provider_identity)
      ? lolban.disk.active_provider_identity
      : [];
    const runtimeMap = providerRuntimeMap(lolban);
    const runtimeCount = Array.isArray(lolban?.runtime?.providers) ? lolban.runtime.providers.length : runtimeMap.size;

    if (failure) {
      setText('providerMetric', '-');
      setText('providerMetricDetail', '运行态数据读取失败');
      body.innerHTML = `<tr><td colspan="5"><div class="empty-state empty-state-error">${escapeHtml(failure.message)}</div></td></tr>`;
      return { count: 0, mismatch: true };
    }

    setText('providerMetric', String(runtimeCount));
    setText('providerMetricDetail', lolban?.runtime_matches_disk ? '磁盘与运行态一致' : '磁盘与运行态需要核对');

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

  function collectDegraded(overview, lolban, serviceStatus, failures) {
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

    const authFailures = failures.filter((item) => item.error?.status === 401 || item.error?.status === 403);
    if (authFailures.length) {
      items.push({
        title: '管理令牌未通过验证',
        detail: adminToken() ? '当前标签页保存的令牌无效，请重新填写' : '管理接口需要 WEBUI_ADMIN_TOKEN',
        kind: 'warning'
      });
    }

    failures
      .filter((item) => item.error?.status !== 401 && item.error?.status !== 403)
      .slice(0, 4)
      .forEach((item) => items.push({
        title: `${item.label}读取失败`,
        detail: item.error?.message || '请求失败',
        kind: 'warning'
      }));
    return items;
  }

  function renderDegraded(items) {
    setText('degradedMetric', String(items.length));
    setText('degradedMetricDetail', items.length ? '存在需要处理的状态' : '当前没有已识别的降级项');
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

  function renderAudit(data, failure = null) {
    const container = $('auditList');
    if (failure) {
      container.innerHTML = `<div class="empty-state empty-state-error">${escapeHtml(failure.message)}</div>`;
      return;
    }
    const items = normalizeAudit(data).slice(0, 6);
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

  function renderLogs(data, failure = null) {
    const container = $('logList');
    if (failure) {
      container.innerHTML = `<div class="empty-state empty-state-error">${escapeHtml(failure.message)}</div>`;
      return;
    }
    const items = normalizeLogs(data).slice(0, 8);
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

  function endpointFailure(results, index) {
    const result = results[index];
    return result?.status === 'rejected' ? result.reason : null;
  }

  function setTokenUi() {
    const token = adminToken();
    const status = $('adminTokenStatus');
    const button = $('adminTokenButton');
    if (status) {
      status.innerHTML = token
        ? '<span class="status-dot status-dot-success"></span><span>当前标签页已保存管理令牌</span>'
        : '<span class="status-dot status-dot-neutral"></span><span>当前标签页尚未保存令牌</span>';
    }
    const label = button?.querySelector('span');
    if (label) label.textContent = token ? '令牌已保存' : '管理令牌';
    button?.classList.toggle('has-token', Boolean(token));
  }

  function openTokenDialog(reason = '') {
    const dialog = $('adminTokenDialog');
    const input = $('adminTokenInput');
    const hint = $('adminTokenHint');
    if (!dialog || !input) return;
    input.value = adminToken();
    if (hint) {
      hint.textContent = reason || '未配置令牌时，本机回环访问可以直接使用管理功能。';
      hint.classList.toggle('is-warning', Boolean(reason));
    }
    setTokenUi();
    if (!dialog.open) dialog.showModal();
    window.setTimeout(() => input.focus(), 0);
  }

  function closeTokenDialog() {
    const dialog = $('adminTokenDialog');
    if (dialog?.open) dialog.close();
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    const button = $('refreshButton');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.querySelector('span').textContent = '刷新中';

    const requests = [
      { label: '系统总览', path: '/admin/overview' },
      { label: '封号 Provider', path: '/admin/query-console/lolban' },
      { label: '审计记录', path: '/admin/audit?limit=10' },
      { label: '日志摘要', path: '/admin/logs' },
      { label: 'Windows 服务状态', path: '/admin/service/status' },
      { label: '构建信息', path: '/build-info' }
    ];
    const results = await Promise.allSettled(requests.map((item) => api(item.path)));
    const values = results.map((result) => result.status === 'fulfilled' ? result.value : null);
    const failures = results
      .map((result, index) => result.status === 'rejected' ? { ...requests[index], error: result.reason } : null)
      .filter(Boolean);
    const [overview, lolban, audit, logs, serviceStatus, buildInfo] = values;

    try {
      const mainHealthy = renderMainService(overview || {});
      const controlHealthy = renderControlService(overview || {}, serviceStatus || {});
      renderBuild(buildInfo || {});
      renderProviders(lolban || {}, endpointFailure(results, 1));
      const degraded = collectDegraded(overview || {}, lolban || {}, serviceStatus || {}, failures);
      renderDegraded(degraded);
      renderAudit(audit || {}, endpointFailure(results, 2));
      renderLogs(logs || {}, endpointFailure(results, 3));
      renderGlobalStatus(mainHealthy, controlHealthy, degraded.length);

      const authFailure = failures.find((item) => item.error?.status === 401 || item.error?.status === 403);
      if (authFailure && !state.authPrompted) {
        state.authPrompted = true;
        openTokenDialog(adminToken() ? '管理令牌验证失败，请检查后重新保存。' : '管理接口要求填写 WEBUI_ADMIN_TOKEN。');
      }
      if (failures.length) {
        showToast(`有 ${failures.length} 项状态读取失败，已在页面中标明原因`, 'error');
      } else {
        state.authPrompted = false;
      }
    } finally {
      state.loading = false;
      button.disabled = false;
      button.removeAttribute('aria-busy');
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

  function bindTokenDialog() {
    const dialog = $('adminTokenDialog');
    const form = $('adminTokenForm');
    const input = $('adminTokenInput');
    $('adminTokenButton')?.addEventListener('click', () => openTokenDialog());
    $('adminTokenClose')?.addEventListener('click', closeTokenDialog);
    $('adminTokenCancel')?.addEventListener('click', closeTokenDialog);
    $('adminTokenClear')?.addEventListener('click', () => {
      storeAdminToken('');
      if (input) input.value = '';
      state.authPrompted = false;
      setTokenUi();
      closeTokenDialog();
      showToast('当前标签页保存的管理令牌已清除', 'success');
      refresh().catch((error) => showToast(error.message || '状态读取失败', 'error'));
    });
    form?.addEventListener('submit', (event) => {
      event.preventDefault();
      const value = input?.value.trim() || '';
      if (!value) {
        showToast('请输入管理令牌，或使用“清除令牌”恢复本机回环访问', 'error');
        input?.focus();
        return;
      }
      if (!storeAdminToken(value)) {
        showToast('浏览器会话存储不可用，无法保存管理令牌', 'error');
        return;
      }
      state.authPrompted = false;
      setTokenUi();
      closeTokenDialog();
      showToast('管理令牌已保存到当前标签页', 'success');
      refresh().catch((error) => showToast(error.message || '状态读取失败', 'error'));
    });
    dialog?.addEventListener('click', (event) => {
      if (event.target === dialog) closeTokenDialog();
    });
    setTokenUi();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindNavigation();
    bindTokenDialog();
    $('refreshButton')?.addEventListener('click', () => {
      refresh().catch((error) => showToast(error.message || '状态读取失败', 'error'));
    });
    refresh().catch((error) => showToast(error.message || '状态读取失败', 'error'));
  });
})();
