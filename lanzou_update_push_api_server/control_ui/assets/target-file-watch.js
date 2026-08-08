(() => {
  'use strict';

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  const state = { authPrompted: false, loading: false };

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
    try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (_error) { return ''; }
  }

  function storeAdminToken(value) {
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
      return true;
    } catch (_error) { return false; }
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function text(value, fallback = '-') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
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

  function setText(id, value) {
    const node = $(id);
    if (!node) return;
    node.textContent = text(value);
    node.classList.remove('skeleton-text', 'skeleton-title');
  }

  function setBadge(id, label, kind = 'neutral') {
    const node = $(id);
    if (!node) return;
    node.textContent = label;
    node.className = `badge badge-${kind}`;
  }

  async function api(path, options = {}) {
    const headers = { accept: 'application/json' };
    const token = adminToken();
    if (token) headers['x-admin-token'] = token;
    if (options.body !== undefined) headers['content-type'] = 'application/json';
    const response = await fetch(path, {
      method: options.method || 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
    });
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); }
    catch (_error) { data = { ok: false, error: raw || response.statusText }; }
    if (!response.ok) {
      const error = new ApiError(
        data.detail || data.error || `HTTP ${response.status}`,
        response.status,
        path,
        data,
      );
      if ((response.status === 401 || response.status === 403) && !state.authPrompted) {
        state.authPrompted = true;
        openTokenDialog('管理接口需要有效的 WEBUI_ADMIN_TOKEN。');
      }
      throw error;
    }
    return data;
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
    if (!dialog) return;
    const input = $('adminTokenInput');
    const hint = $('adminTokenHint');
    if (input) input.value = adminToken();
    if (hint) hint.textContent = reason || '未配置令牌时，本机回环访问可以直接使用管理功能。';
    setTokenUi();
    if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
    window.setTimeout(() => input?.focus(), 0);
  }

  function closeTokenDialog() {
    const dialog = $('adminTokenDialog');
    if (dialog?.open) dialog.close();
  }

  function setupTokenDialog() {
    $('adminTokenButton')?.addEventListener('click', () => openTokenDialog());
    $('adminTokenClose')?.addEventListener('click', closeTokenDialog);
    $('adminTokenCancel')?.addEventListener('click', closeTokenDialog);
    $('adminTokenClear')?.addEventListener('click', async () => {
      storeAdminToken('');
      state.authPrompted = false;
      setTokenUi();
      closeTokenDialog();
      showToast('当前标签页的管理令牌已清除', 'success');
      await loadPage();
    });
    $('adminTokenForm')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const value = $('adminTokenInput')?.value.trim() || '';
      if (!storeAdminToken(value)) {
        showToast('浏览器无法保存管理令牌', 'error');
        return;
      }
      state.authPrompted = false;
      setTokenUi();
      closeTokenDialog();
      showToast(value ? '管理令牌已保存到当前标签页' : '管理令牌已清除', 'success');
      await loadPage();
    });
  }

  function setupSidebar() {
    const sidebar = $('consoleSidebar');
    const backdrop = $('sidebarBackdrop');
    const close = () => {
      sidebar?.classList.remove('is-open');
      backdrop?.classList.remove('is-visible');
    };
    $('sidebarToggle')?.addEventListener('click', () => {
      sidebar?.classList.toggle('is-open');
      backdrop?.classList.toggle('is-visible');
    });
    backdrop?.addEventListener('click', close);
    document.querySelectorAll('.nav-link').forEach((link) => link.addEventListener('click', close));
  }

  async function loadCommonStatus() {
    try {
      await api('/build-info');
      $('globalStatusDot').className = 'status-dot status-dot-success';
      $('globalStatusText').textContent = '服务正常';
    } catch (_error) {
      $('globalStatusDot').className = 'status-dot status-dot-danger';
      $('globalStatusText').textContent = '状态读取失败';
    }
  }

  function formatTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '-';
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString('zh-CN', { hour12: false });
  }

  function baselineFiles(baseline) {
    if (!baseline || typeof baseline !== 'object') return [];
    if (Array.isArray(baseline.files)) return baseline.files;
    if (baseline.fingerprint || baseline.name) return [baseline];
    return [];
  }

  function pendingEvents(pending) {
    if (!pending || typeof pending !== 'object') return [];
    if (Array.isArray(pending.events)) return pending.events;
    return pending.event_id ? [pending] : [];
  }

  function renderBaseline(status) {
    const baseline = status?.baseline || null;
    const files = baselineFiles(baseline);
    const count = Number(baseline?.file_count ?? files.length ?? 0) || 0;
    const provider = text(baseline?.provider || files[0]?.provider, '-');
    setText('targetWatchBaselineCount', count);
    setText('targetWatchBaselineDetail', baseline ? '已建立目录快照' : '尚未建立 baseline');
    setText('targetWatchProvider', provider);
    setText('targetWatchProviderDetail', baseline?.signature ? '当前 baseline Provider' : '等待首次检查');

    const body = $('targetWatchBaselineRows');
    if (!body) return;
    if (!files.length) {
      body.innerHTML = '<tr><td colspan="4"><div class="empty-state">尚未建立 baseline，或当前没有可展示文件。</div></td></tr>';
      return;
    }
    body.innerHTML = files.map((item) => `<tr>
      <td><strong>${escapeHtml(item.name || item.file?.name || '-')}</strong></td>
      <td>${escapeHtml(item.size || item.file?.size || '-')}</td>
      <td>${escapeHtml(item.modified_time || item.modified_at || item.file?.modified_at || '-')}</td>
      <td><span class="code">${escapeHtml(item.stable_id || item.file?.stable_id || '-')}</span></td>
    </tr>`).join('');
  }

  function renderPending(status) {
    const pending = status?.pending || null;
    const events = pendingEvents(pending);
    const host = $('targetWatchPendingList');
    if (!host) return;
    if (!events.length) {
      host.innerHTML = '<div class="empty-state">当前没有待投递事件。</div>';
      return;
    }
    host.innerHTML = events.map((event, index) => {
      const file = event.file || {};
      return `<div class="stack-item"><strong>${escapeHtml(file.name || `事件 ${index + 1}`)}</strong><span>${escapeHtml(file.size || '-')} · ${escapeHtml(event.event_id || '-')}</span></div>`;
    }).join('');
  }

  function renderError(status) {
    const code = String(status?.last_error_code || '').trim();
    const at = String(status?.last_error_at || '').trim();
    const box = $('targetWatchErrorBox');
    if (!box) return;
    if (!code) {
      box.innerHTML = '<div class="empty-state">当前没有定向文件监控错误。</div>';
      return;
    }
    box.innerHTML = `<div class="empty-state empty-state-error"><strong>最近错误</strong><br>${escapeHtml(code)}<br><small>${escapeHtml(formatTime(at))}</small></div>`;
  }

  function renderOverview(payload) {
    const status = payload?.status || {};
    const config = status?.config || {};
    const enabled = config.enabled === true;
    const running = status.running === true;
    const healthy = status.state_healthy !== false;

    setText('targetWatchEnabled', enabled ? '已启用' : '已关闭');
    setText('targetWatchEnabledDetail', enabled ? '由 GroupGuard 同步开启' : '当前不会自动检查');
    setText('targetWatchRunning', running ? '运行中' : (healthy ? '未运行' : '已停用'));
    setText('targetWatchRunningDetail', healthy ? '独立后台循环状态' : '状态文件异常，已 fail-safe 停止');
    setText('targetWatchSourceUrl', config.source_url || '尚未配置');
    setBadge('targetWatchInterval', `${Number(config.check_interval_seconds || 300)} 秒`, 'neutral');
    setText('targetWatchCallbackUrl', config.callback_url || '尚未配置');
    setBadge(
      'targetWatchCallbackToken',
      config.callback_token_configured ? 'Token 已配置' : 'Token 未配置',
      config.callback_token_configured ? 'success' : 'warning',
    );
    setText('targetWatchLastCheck', formatTime(status.last_check_at));
    setText('targetWatchLastSuccess', formatTime(status.last_success_at));
    setText('targetWatchLastDelivery', formatTime(status.last_delivery_at));
    setText('targetWatchLastEvent', status.last_event_id || '-');
    renderBaseline(status);
    renderPending(status);
    renderError(status);
  }

  function setBusy(value) {
    state.loading = value;
    ['targetWatchRefreshButton', 'targetWatchCheckButton', 'targetWatchRebaselineButton']
      .forEach((id) => { if ($(id)) $(id).disabled = value; });
  }

  async function loadPage() {
    if (state.loading) return;
    setBusy(true);
    try {
      await loadCommonStatus();
      const payload = await api('/admin/target-file-watch');
      renderOverview(payload);
    } catch (error) {
      renderError({ last_error_code: error.message, last_error_at: new Date().toISOString() });
      showToast(`定向文件监控状态读取失败：${error.message}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function runAction(path, successMessage) {
    if (state.loading) return;
    setBusy(true);
    try {
      const payload = await api(path, { method: 'POST', body: {} });
      showToast(successMessage, 'success');
      await loadCommonStatus();
      const overview = await api('/admin/target-file-watch');
      renderOverview(overview);
      return payload;
    } catch (error) {
      showToast(`${successMessage}失败：${error.message}`, 'error');
      return null;
    } finally {
      setBusy(false);
    }
  }

  function setupRebaselineDialog() {
    const dialog = $('targetWatchRebaselineDialog');
    const close = () => { if (dialog?.open) dialog.close(); };
    $('targetWatchRebaselineButton')?.addEventListener('click', () => {
      if (typeof dialog?.showModal === 'function' && !dialog.open) dialog.showModal();
    });
    $('targetWatchRebaselineCancel')?.addEventListener('click', close);
    $('targetWatchRebaselineClose')?.addEventListener('click', close);
    $('targetWatchRebaselineConfirm')?.addEventListener('click', async () => {
      close();
      await runAction('/admin/target-file-watch/rebaseline', '重新建立基线请求已执行');
    });
  }

  function setupActions() {
    $('targetWatchRefreshButton')?.addEventListener('click', loadPage);
    $('targetWatchCheckButton')?.addEventListener('click', () => runAction('/admin/target-file-watch/check', '立即检查完成'));
    setupRebaselineDialog();
  }

  async function mount() {
    setupSidebar();
    setupTokenDialog();
    setupActions();
    setTokenUi();
    await loadPage();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
