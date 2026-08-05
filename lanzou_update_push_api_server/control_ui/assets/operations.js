(() => {
  'use strict';

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  const page = document.body.dataset.consoleUi || '';
  const state = {
    logs: [],
    confirmAction: null,
    authPrompted: false,
  };

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

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index += 1;
    }
    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
  }

  function formatTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
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
    try {
      data = JSON.parse(raw);
    } catch (_error) {
      data = { ok: false, error: raw || response.statusText };
    }
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

  async function safeApi(path, options = {}) {
    try {
      return { ok: true, data: await api(path, options) };
    } catch (error) {
      return { ok: false, error };
    }
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
      await reloadPage();
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
      await reloadPage();
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
    const [build, service] = await Promise.all([
      safeApi('/build-info'),
      safeApi('/admin/service/status'),
    ]);
    const dot = $('globalStatusDot');
    const text = $('globalStatusText');
    if (!dot || !text) return;
    if (!build.ok) {
      dot.className = 'status-dot status-dot-danger';
      text.textContent = '6178 状态读取失败';
      return;
    }
    const serviceState = String(service.data?.state || '').toLowerCase();
    if (service.ok && (service.data?.supported === false || serviceState === 'running')) {
      dot.className = 'status-dot status-dot-success';
      text.textContent = service.data?.supported === false ? '控制台响应正常' : '生产服务运行正常';
      return;
    }
    dot.className = 'status-dot';
    text.textContent = '控制台正常，服务状态需确认';
  }

  function badge(label, kind = 'neutral') {
    return `<span class="badge badge-${kind}">${escapeHtml(label)}</span>`;
  }

  function clearSkeleton(id) {
    const node = $(id);
    node?.classList.remove('skeleton-text', 'skeleton-title');
  }

  function setText(id, value) {
    const node = $(id);
    if (!node) return;
    node.textContent = String(value ?? '-');
    clearSkeleton(id);
  }

  function confirmOperation(options, action) {
    const dialog = $('operationConfirmDialog');
    if (!dialog) return;
    state.confirmAction = action;
    setText('operationConfirmTitle', options.title || '确认操作');
    setText('operationConfirmMessage', options.message || '请确认是否继续。');
    setText('operationConfirmWarning', options.warning || '操作会被记录到管理审计。');
    setText('operationConfirmSubmit', options.submitLabel || '确认执行');
    const submit = $('operationConfirmSubmit');
    submit?.classList.toggle('button-danger', options.kind === 'danger');
    if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
  }

  function closeConfirmDialog() {
    state.confirmAction = null;
    const dialog = $('operationConfirmDialog');
    if (dialog?.open) dialog.close();
  }

  function setupConfirmDialog() {
    $('operationConfirmClose')?.addEventListener('click', closeConfirmDialog);
    $('operationConfirmCancel')?.addEventListener('click', closeConfirmDialog);
    $('operationConfirmForm')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const action = state.confirmAction;
      closeConfirmDialog();
      if (typeof action === 'function') await action();
    });
  }

  function renderLogCatalog(items) {
    state.logs = Array.isArray(items) ? items : [];
    const select = $('logSelect');
    const previous = select?.value || '';
    if (select) {
      select.innerHTML = state.logs.map((item) => (
        `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}${item.exists ? '' : '（不存在）'}</option>`
      )).join('') || '<option value="">没有日志文件</option>';
      if (state.logs.some((item) => item.name === previous)) select.value = previous;
    }
    setText('logFileCount', state.logs.length);
    setText('logExistingCount', state.logs.filter((item) => item.exists).length);
    const body = $('logRows');
    if (!body) return;
    body.innerHTML = state.logs.map((item) => `<tr>
      <td><strong class="code">${escapeHtml(item.name)}</strong></td>
      <td>${badge(item.exists ? '可读取' : '不存在', item.exists ? 'success' : 'neutral')}</td>
      <td>${escapeHtml(formatBytes(item.size_bytes))}</td>
      <td><button class="button button-secondary button-small" type="button" data-read-log="${escapeHtml(item.name)}" ${item.exists ? '' : 'disabled'}>读取</button></td>
    </tr>`).join('') || '<tr><td colspan="4"><div class="empty-state">没有登记日志文件</div></td></tr>';
    body.querySelectorAll('[data-read-log]').forEach((button) => {
      button.addEventListener('click', () => {
        if (select) select.value = button.dataset.readLog || '';
        loadSelectedLog();
      });
    });
    updateSelectedLogSummary();
  }

  function updateSelectedLogSummary() {
    const selected = state.logs.find((item) => item.name === $('logSelect')?.value);
    setText('logSelectedName', selected?.name || '未选择');
    setText('logSelectedSize', selected ? `${formatBytes(selected.size_bytes)} · ${selected.exists ? '可读取' : '不存在'}` : '请选择日志');
  }

  async function loadLogCatalog({ readSelected = false } = {}) {
    const result = await safeApi('/admin/logs');
    if (!result.ok) {
      showToast(`日志目录读取失败：${result.error.message}`, 'error');
      const body = $('logRows');
      if (body) body.innerHTML = `<tr><td colspan="4"><div class="empty-state empty-state-error">${escapeHtml(result.error.message)}</div></td></tr>`;
      return;
    }
    renderLogCatalog(result.data.logs || result.data.files || []);
    if (readSelected && $('logSelect')?.value) await loadSelectedLog();
  }

  async function loadSelectedLog() {
    const name = $('logSelect')?.value || '';
    if (!name) {
      showToast('请先选择日志文件', 'warning');
      return;
    }
    updateSelectedLogSummary();
    const lines = Math.max(1, Math.min(5000, Number($('logLines')?.value || 300)));
    const search = $('logSearch')?.value.trim() || '';
    setText('logContent', '正在读取日志...');
    setText('logViewerMeta', `${name} · 正在读取`);
    const path = `/admin/logs/${encodeURIComponent(name)}?lines=${encodeURIComponent(lines)}&search=${encodeURIComponent(search)}`;
    const result = await safeApi(path);
    if (!result.ok) {
      setText('logContent', `读取失败：${result.error.message}`);
      setText('logViewerMeta', `${name} · 读取失败`);
      showToast(`日志读取失败：${result.error.message}`, 'error');
      return;
    }
    setText('logContent', result.data.content || '当前筛选条件下没有日志内容');
    setText('logViewerMeta', `${name} · ${lines} 行${search ? ` · 关键词：${search}` : ''}`);
  }

  async function initLogs() {
    $('logsRefreshButton')?.addEventListener('click', () => loadLogCatalog());
    $('loadLogButton')?.addEventListener('click', loadSelectedLog);
    $('logSelect')?.addEventListener('change', updateSelectedLogSummary);
    $('logSearch')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') loadSelectedLog();
    });
    $('clearLogSearchButton')?.addEventListener('click', () => {
      if ($('logSearch')) $('logSearch').value = '';
      loadSelectedLog();
    });
    await loadLogCatalog({ readSelected: true });
  }

  function diagnosticLabel(name) {
    const labels = {
      main_api_port: '5001 主接口端口',
      lanzou_port: '6178 控制台端口',
      mysql_port: 'MySQL 端口',
      lanzou_config: '蓝奏配置文件',
      lanzou_state: '蓝奏状态文件',
      python_runtime: 'Python 运行环境',
      playwright_path: 'Playwright 浏览器目录',
      main_env: '主接口本地环境文件',
      windows_service: 'Windows 服务',
      app_port_config: '主接口端口配置',
      mysql_port_config: 'MySQL 端口配置',
      lanzou_monitor_port_config: '6178 端口配置',
    };
    return labels[name] || name;
  }

  async function loadDiagnostics() {
    setText('diagnosticSummary', '正在运行诊断');
    const result = await safeApi('/admin/diagnostics');
    const body = $('diagnosticRows');
    if (!result.ok) {
      if (body) body.innerHTML = `<tr><td colspan="3"><div class="empty-state empty-state-error">${escapeHtml(result.error.message)}</div></td></tr>`;
      setText('diagnosticSummary', '诊断接口读取失败');
      showToast(`诊断失败：${result.error.message}`, 'error');
      return;
    }
    const items = Array.isArray(result.data.items) ? result.data.items : [];
    const passed = items.filter((item) => item.ok).length;
    setText('diagnosticTotal', items.length);
    setText('diagnosticPassed', passed);
    setText('diagnosticFailed', items.length - passed);
    setText('diagnosticSummary', result.data.ok ? '全部检查通过' : `${items.length - passed} 项需要处理`);
    if (body) {
      body.innerHTML = items.map((item) => `<tr>
        <td><strong>${escapeHtml(diagnosticLabel(item.name))}</strong>${item.path ? `<small class="table-subtext code">${escapeHtml(item.path)}</small>` : ''}</td>
        <td>${badge(item.ok ? '通过' : '异常', item.ok ? 'success' : 'danger')}</td>
        <td class="cell-wrap code">${escapeHtml(item.detail || '-')}</td>
      </tr>`).join('') || '<tr><td colspan="3"><div class="empty-state">没有诊断结果</div></td></tr>';
    }
  }

  async function repairState() {
    const button = $('repairStateButton');
    if (button) button.disabled = true;
    setText('repairStateResult', '正在修复状态文件...');
    const result = await safeApi('/admin/repair/state', { method: 'POST', body: {} });
    if (button) button.disabled = false;
    const repairError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '修复接口返回失败') : '');
    if (repairError) {
      setText('repairStateResult', `修复失败：${repairError}`);
      showToast(`状态文件修复失败：${repairError}`, 'error');
      return;
    }
    setText('repairStateResult', JSON.stringify(result.data, null, 2));
    showToast('状态文件修复流程已完成', 'success');
    await loadDiagnostics();
  }

  async function initDiagnostics() {
    $('runDiagnosticsButton')?.addEventListener('click', loadDiagnostics);
    $('repairStateButton')?.addEventListener('click', () => confirmOperation({
      title: '修复蓝奏状态文件',
      message: '仅当状态 JSON 损坏、为空或无法读取时执行。确认继续吗？',
      warning: '系统会先备份异常文件，再重建可用状态。该操作会记录到审计日志。',
      submitLabel: '确认修复',
      kind: 'danger',
    }, repairState));
    await loadDiagnostics();
  }

  function renderServiceStatus(data) {
    const stateValue = String(data?.state || 'unknown').toLowerCase();
    const running = stateValue === 'running';
    setText('serviceState', data?.supported === false ? '不支持' : (running ? '运行中' : stateValue));
    setText('serviceDetail', data?.supported === false ? '当前平台不支持服务控制' : `LOLDataSystem · ${stateValue}`);
    setText('serviceStatusContent', JSON.stringify(data || {}, null, 2));
  }

  function renderSecurityStatus(data) {
    const required = Boolean(data?.token_configured || data?.token_required || data?.admin_token_required || data?.configured);
    setText('securityMode', required ? '令牌保护' : '仅本机访问');
    setText('securityDetail', required ? '管理操作需要 WEBUI_ADMIN_TOKEN' : '未配置令牌时仅允许回环地址');
    setText('securityStatusContent', JSON.stringify(data || {}, null, 2));
  }

  function renderBackups(data) {
    const items = Array.isArray(data?.backups) ? data.backups : [];
    setText('backupCount', items.length);
    const body = $('backupRows');
    if (!body) return;
    body.innerHTML = items.map((item) => `<tr>
      <td>${badge(item.kind === 'main' ? '主接口' : '蓝奏', item.kind === 'main' ? 'warning' : 'neutral')}</td>
      <td><strong class="code">${escapeHtml(item.name)}</strong></td>
      <td>${escapeHtml(formatTime(item.modified_at))}</td>
      <td>${escapeHtml(formatBytes(item.size_bytes))}</td>
      <td><button class="button button-secondary button-small" type="button" data-rollback-kind="${escapeHtml(item.kind)}" data-rollback-name="${escapeHtml(item.name)}">回滚</button></td>
    </tr>`).join('') || '<tr><td colspan="5"><div class="empty-state">暂无配置备份</div></td></tr>';
    body.querySelectorAll('[data-rollback-kind]').forEach((button) => {
      button.addEventListener('click', () => {
        const kind = button.dataset.rollbackKind || '';
        const name = button.dataset.rollbackName || '';
        confirmOperation({
          title: '回滚配置',
          message: `把 ${kind === 'main' ? '主接口' : '蓝奏'} 配置回滚到 ${name}？`,
          warning: '回滚前会再次备份当前配置。主接口配置回滚后需要重启服务生效。',
          submitLabel: '确认回滚',
          kind: 'danger',
        }, () => rollbackBackup(kind, name));
      });
    });
  }

  function renderAudit(data) {
    const items = Array.isArray(data?.events) ? data.events : [];
    setText('auditCount', items.length);
    const body = $('auditRows');
    if (!body) return;
    body.innerHTML = items.slice(0, 100).map((item) => `<tr>
      <td>${escapeHtml(formatTime(item.at))}</td>
      <td><strong>${escapeHtml(item.action || '-')}</strong><small class="table-subtext">${escapeHtml(`${item.method || ''} ${item.path || ''}`.trim())}</small></td>
      <td>${badge(item.ok ? '成功' : '失败', item.ok ? 'success' : 'danger')}</td>
    </tr>`).join('') || '<tr><td colspan="3"><div class="empty-state">暂无审计记录</div></td></tr>';
  }

  async function loadSystem() {
    const [security, service, backups, audit] = await Promise.all([
      safeApi('/security/status'),
      safeApi('/admin/service/status'),
      safeApi('/admin/backups'),
      safeApi('/admin/audit?limit=100'),
    ]);
    if (security.ok) renderSecurityStatus(security.data);
    else setText('securityStatusContent', `读取失败：${security.error.message}`);
    if (service.ok) renderServiceStatus(service.data);
    else setText('serviceStatusContent', `读取失败：${service.error.message}`);
    if (backups.ok) renderBackups(backups.data);
    else if ($('backupRows')) $('backupRows').innerHTML = `<tr><td colspan="5"><div class="empty-state empty-state-error">${escapeHtml(backups.error.message)}</div></td></tr>`;
    if (audit.ok) renderAudit(audit.data);
    else if ($('auditRows')) $('auditRows').innerHTML = `<tr><td colspan="3"><div class="empty-state empty-state-error">${escapeHtml(audit.error.message)}</div></td></tr>`;
  }

  async function rollbackBackup(kind, name) {
    const result = await safeApi(`/admin/rollback/${encodeURIComponent(kind)}`, {
      method: 'POST',
      body: { backup_name: name },
    });
    const rollbackError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '回滚接口返回失败') : '');
    if (rollbackError) {
      showToast(`配置回滚失败：${rollbackError}`, 'error');
      return;
    }
    showToast(kind === 'main' ? '主接口配置已回滚，重启服务后生效' : '蓝奏配置已回滚并刷新运行态', 'success');
    await loadSystem();
  }

  async function restartService() {
    const result = await safeApi('/admin/service/restart', {
      method: 'POST',
      body: { delay_seconds: 3 },
    });
    const restartError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '重启接口返回失败') : '');
    if (restartError) {
      showToast(`服务重启安排失败：${restartError}`, 'error');
      return;
    }
    showToast('已安排 LOLDataSystem 重启，页面连接会短暂中断', 'success');
    setText('serviceStatusContent', JSON.stringify(result.data, null, 2));
  }

  async function initSystem() {
    $('systemRefreshButton')?.addEventListener('click', loadSystem);
    $('restartServiceButton')?.addEventListener('click', () => confirmOperation({
      title: '重启 LOLDataSystem',
      message: '确认重启 Windows 托管服务吗？',
      warning: '5001 和 6178 会短暂中断，监管脚本随后会重新拉起两个进程。',
      submitLabel: '确认重启',
      kind: 'danger',
    }, restartService));
    await loadSystem();
  }

  async function reloadPage() {
    await loadCommonStatus();
    if (page === 'logs') await loadLogCatalog();
    if (page === 'diagnostics') await loadDiagnostics();
    if (page === 'system') await loadSystem();
  }

  async function init() {
    setupSidebar();
    setupTokenDialog();
    setupConfirmDialog();
    setTokenUi();
    await loadCommonStatus();
    if (page === 'logs') await initLogs();
    if (page === 'diagnostics') await initDiagnostics();
    if (page === 'system') await initSystem();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init().catch((error) => showToast(error.message, 'error')));
  } else {
    init().catch((error) => showToast(error.message, 'error'));
  }
})();
