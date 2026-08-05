(() => {
  'use strict';

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  const page = document.body.dataset.consoleUi || '';
  const state = {
    authPrompted: false,
    confirmAction: null,
    mainConfig: null,
    lanzou: null,
    environmentOverrides: {},
    overview: null,
    watchers: [],
    targets: [],
    routes: [],
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
    node.textContent = String(value ?? '-');
    node.classList.remove('skeleton-text', 'skeleton-title');
  }

  function badge(label, kind = 'neutral') {
    return `<span class="badge badge-${kind}">${escapeHtml(label)}</span>`;
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
    try { data = JSON.parse(raw); } catch (_error) { data = { ok: false, error: raw || response.statusText }; }
    if (!response.ok) {
      const error = new ApiError(data.detail || data.error || `HTTP ${response.status}`, response.status, path, data);
      if ((response.status === 401 || response.status === 403) && !state.authPrompted) {
        state.authPrompted = true;
        openTokenDialog('管理接口需要有效的 WEBUI_ADMIN_TOKEN。');
      }
      throw error;
    }
    return data;
  }

  async function safeApi(path, options = {}) {
    try { return { ok: true, data: await api(path, options) }; }
    catch (error) { return { ok: false, error }; }
  }

  function operationError(result, fallback) {
    if (!result.ok) return result.error?.message || fallback;
    if (result.data?.ok === false) return result.data.error || result.data.detail || fallback;
    return '';
  }

  function setResult(data) {
    const node = $('configurationResult');
    if (node) node.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
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
      storeAdminToken(''); state.authPrompted = false; setTokenUi(); closeTokenDialog();
      showToast('当前标签页的管理令牌已清除', 'success'); await reloadPage();
    });
    $('adminTokenForm')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const value = $('adminTokenInput')?.value.trim() || '';
      if (!storeAdminToken(value)) { showToast('浏览器无法保存管理令牌', 'error'); return; }
      state.authPrompted = false; setTokenUi(); closeTokenDialog();
      showToast(value ? '管理令牌已保存到当前标签页' : '管理令牌已清除', 'success');
      await reloadPage();
    });
  }

  function setupSidebar() {
    const sidebar = $('consoleSidebar');
    const backdrop = $('sidebarBackdrop');
    const close = () => { sidebar?.classList.remove('is-open'); backdrop?.classList.remove('is-visible'); };
    $('sidebarToggle')?.addEventListener('click', () => {
      sidebar?.classList.toggle('is-open'); backdrop?.classList.toggle('is-visible');
    });
    backdrop?.addEventListener('click', close);
    document.querySelectorAll('.nav-link').forEach((link) => link.addEventListener('click', close));
  }

  async function loadCommonStatus() {
    const result = await safeApi('/build-info');
    const dot = $('globalStatusDot');
    const text = $('globalStatusText');
    if (!dot || !text) return;
    dot.className = result.ok ? 'status-dot status-dot-success' : 'status-dot status-dot-danger';
    text.textContent = result.ok ? '6178 控制台响应正常' : '6178 状态读取失败';
  }

  function confirmOperation(options, action) {
    const dialog = $('configurationConfirmDialog');
    if (!dialog) return;
    state.confirmAction = action;
    setText('configurationConfirmTitle', options.title || '确认操作');
    setText('configurationConfirmMessage', options.message || '请确认是否继续。');
    setText('configurationConfirmWarning', options.warning || '保存前会自动备份当前配置。');
    setText('configurationConfirmSubmit', options.submitLabel || '确认执行');
    if (typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
  }

  function closeConfirmDialog() {
    state.confirmAction = null;
    const dialog = $('configurationConfirmDialog');
    if (dialog?.open) dialog.close();
  }

  function setupConfirmDialog() {
    $('configurationConfirmClose')?.addEventListener('click', closeConfirmDialog);
    $('configurationConfirmCancel')?.addEventListener('click', closeConfirmDialog);
    $('configurationConfirmForm')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const action = state.confirmAction;
      closeConfirmDialog();
      if (typeof action === 'function') await action();
    });
  }

  function parseJsonValue(raw, label, fallback = {}) {
    const text = String(raw || '').trim();
    if (!text) return fallback;
    try {
      const value = JSON.parse(text);
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('必须是 JSON 对象');
      return value;
    } catch (error) { throw new Error(`${label} JSON 格式错误：${error.message}`); }
  }

  function fieldInput(field) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(field.label || field.key);
    const inherited = field.inherited_from_example ? '<small class="is-warning">当前值继承自示例配置</small>' : '';
    if (field.type === 'bool') {
      return `<label class="switch-card"><span><strong>${label}</strong><small class="code">${key}</small>${inherited}</span><input data-main-key="${key}" data-main-type="bool" type="checkbox" ${field.value ? 'checked' : ''}></label>`;
    }
    const type = field.type === 'secret' ? 'password' : (field.type === 'int' ? 'number' : 'text');
    const value = field.type === 'secret' ? '' : escapeHtml(field.value ?? '');
    const configured = field.type === 'secret'
      ? `<small>${field.configured ? '已配置；留空保留原值' : '尚未配置'}</small>`
      : inherited;
    const limits = `${field.min !== undefined ? ` min="${escapeHtml(field.min)}"` : ''}${field.max !== undefined ? ` max="${escapeHtml(field.max)}"` : ''}`;
    return `<label class="field"><span>${label} · <span class="code">${key}</span></span><input data-main-key="${key}" data-main-type="${escapeHtml(field.type)}" type="${type}" value="${value}" autocomplete="${field.type === 'secret' ? 'new-password' : 'off'}" placeholder="${field.type === 'secret' ? (field.configured ? '已配置，留空不改' : '未配置') : ''}"${limits}>${configured}</label>`;
  }

  function renderMainConfig(data) {
    state.mainConfig = data;
    const fields = Array.isArray(data?.fields) ? data.fields : [];
    const groups = new Map();
    fields.forEach((field) => {
      const section = String(field.section || '其他');
      if (!groups.has(section)) groups.set(section, []);
      groups.get(section).push(field);
    });
    const form = $('mainConfigForm');
    if (form) {
      form.innerHTML = [...groups.entries()].map(([section, items]) => `<section class="configuration-section"><div class="configuration-section-header"><h3>${escapeHtml(section)}</h3><span>${items.length} 项</span></div><div class="configuration-grid configuration-grid-3">${items.map(fieldInput).join('')}</div></section>`).join('') || '<div class="empty-state">没有可管理的主接口配置字段</div>';
    }
    setText('mainConfigFieldCount', fields.length);
    setText('mainConfigSecretCount', fields.filter((field) => field.type === 'secret' && field.configured).length);
    setText('mainConfigPath', data?.path || data?.source || '配置来源未知');
  }

  async function loadMainConfig() {
    const result = await safeApi('/admin/main-config');
    if (!result.ok) { setResult(`读取失败：${result.error.message}`); showToast(`主接口配置读取失败：${result.error.message}`, 'error'); return; }
    renderMainConfig(result.data);
  }

  function collectMainConfig() {
    const patch = {};
    document.querySelectorAll('[data-main-key]').forEach((input) => {
      const key = input.dataset.mainKey;
      const type = input.dataset.mainType;
      if (type === 'bool') patch[key] = input.checked;
      else if (type === 'secret') { if (input.value.trim()) patch[key] = input.value; }
      else patch[key] = input.value;
    });
    return patch;
  }

  async function saveMainConfig() {
    const result = await safeApi('/admin/main-config', { method: 'POST', body: collectMainConfig() });
    const error = operationError(result, '主接口配置保存失败');
    if (error) { setResult(`保存失败：${error}`); showToast(`主接口配置保存失败：${error}`, 'error'); return; }
    setResult(result.data);
    renderMainConfig(result.data.config || {});
    showToast('主接口配置已保存，重启 LOLDataSystem 后生效', 'success');
  }

  function renderOverrides(overrides) {
    const container = $('lanzouOverrideList');
    if (!container) return;
    const items = Object.entries(overrides || {});
    container.innerHTML = items.map(([key, value]) => `<div class="stack-item">${badge('覆盖中', 'warning')}<strong class="code">${escapeHtml(key)}</strong><span class="code">${escapeHtml(value)}</span></div>`).join('') || '<div class="empty-state">当前没有已识别的环境变量覆盖</div>';
  }

  function fillLanzou(data, overrides = {}) {
    state.lanzou = data || {};
    state.environmentOverrides = overrides || {};
    const config = state.lanzou;
    if ($('lzHost')) $('lzHost').value = config.host || '127.0.0.1';
    if ($('lzPort')) $('lzPort').value = config.port || 6178;
    if ($('lzInterval')) $('lzInterval').value = config.scan_interval_seconds ?? 300;
    if ($('lzBatch')) $('lzBatch').value = config.scan_batch_size ?? 0;
    if ($('lzPause')) $('lzPause').value = config.scan_batch_pause_seconds ?? 0;
    if ($('lzProviders')) $('lzProviders').value = (config.provider_order || []).join(', ');
    if ($('lzStatePath')) $('lzStatePath').value = config.state_path || 'lanzou_update_push_api_server/state.json';
    if ($('lzScanStart')) $('lzScanStart').checked = config.scan_on_start !== false;
    if ($('lzWerEndpoint')) $('lzWerEndpoint').value = config.wer_api_endpoint || '';
    if ($('lzWerMethod')) $('lzWerMethod').value = config.wer_api_method || 'GET';
    if ($('lzWerUrlParam')) $('lzWerUrlParam').value = config.wer_api_url_param || 'url';
    if ($('lzWerPwdParam')) $('lzWerPwdParam').value = config.wer_api_password_param || 'pwd';
    if ($('lzWerKey')) $('lzWerKey').value = '';
    if ($('lzTemplate')) $('lzTemplate').value = config.notification_template || '';
    const status = $('werKeyStatus');
    if (status) {
      status.textContent = config.wer_api_key_configured ? 'API Key 已配置' : 'API Key 未配置';
      status.className = `badge ${config.wer_api_key_configured ? 'badge-success' : 'badge-neutral'}`;
    }
    renderOverrides(overrides);
  }

  async function loadLanzouConfig() {
    const result = await safeApi('/admin/lanzou-config');
    if (!result.ok) { setResult(`读取失败：${result.error.message}`); showToast(`蓝奏配置读取失败：${result.error.message}`, 'error'); return; }
    fillLanzou(result.data.config || {}, result.data.environment_overrides || {});
  }

  function collectLanzouConfig() {
    const patch = {
      host: $('lzHost').value,
      port: Number($('lzPort').value),
      scan_interval_seconds: Number($('lzInterval').value),
      scan_batch_size: Number($('lzBatch').value),
      scan_batch_pause_seconds: Number($('lzPause').value),
      scan_on_start: $('lzScanStart').checked,
      provider_order: $('lzProviders').value.split(',').map((item) => item.trim()).filter(Boolean),
      state_path: $('lzStatePath').value,
      wer_api_endpoint: $('lzWerEndpoint').value,
      wer_api_method: $('lzWerMethod').value,
      wer_api_url_param: $('lzWerUrlParam').value,
      wer_api_password_param: $('lzWerPwdParam').value,
      notification_template: $('lzTemplate').value,
    };
    const key = $('lzWerKey').value.trim();
    if (key) patch.wer_api_key = key;
    return patch;
  }

  async function saveLanzouConfig() {
    const result = await safeApi('/admin/lanzou-config', { method: 'POST', body: collectLanzouConfig() });
    const error = operationError(result, '蓝奏配置保存失败');
    if (error) { setResult(`保存失败：${error}`); showToast(`蓝奏配置保存失败：${error}`, 'error'); return; }
    setResult(result.data);
    fillLanzou(result.data.config || {}, result.data.environment_overrides || {});
    showToast(result.data.message || '蓝奏配置已保存并刷新运行态', 'success');
  }

  function watcherStatus(watcher) {
    const live = state.overview?.lanzou?.health?.last_scan?.[watcher.id] || {};
    if (!live.at) return { label: '暂无', kind: 'neutral', detail: '尚无扫描记录' };
    if (!live.ok) return { label: '失败', kind: 'danger', detail: live.error || '最近扫描失败' };
    if (live.notification_pending) return { label: '待推送', kind: 'warning', detail: '存在尚未完成的通知' };
    return { label: '成功', kind: 'success', detail: live.provider || live.at || '' };
  }

  function renderWatchers() {
    const body = $('watcherRows');
    if (!body) return;
    setText('watcherCount', state.watchers.length);
    setText('watcherEnabledCount', state.watchers.filter((item) => item.enabled !== false).length);
    const issueCount = state.watchers.filter((item) => ['danger', 'warning'].includes(watcherStatus(item).kind)).length;
    setText('watcherIssueCount', issueCount);
    body.innerHTML = state.watchers.map((watcher, index) => {
      const status = watcherStatus(watcher);
      return `<tr data-watcher-index="${index}">
        <td><input data-watcher-field="enabled" type="checkbox" ${watcher.enabled !== false ? 'checked' : ''}></td>
        <td><div class="cell-title"><input data-watcher-field="id" value="${escapeHtml(watcher.id || '')}" placeholder="唯一 ID"><input data-watcher-field="title" value="${escapeHtml(watcher.title || '')}" placeholder="显示名称"></div></td>
        <td class="cell-url"><input data-watcher-field="url" value="${escapeHtml(watcher.url || '')}" placeholder="https://..."></td>
        <td class="cell-secret"><input data-watcher-field="password" type="password" autocomplete="new-password" placeholder="${watcher.password_configured ? '已配置，留空不改' : '未配置'}"><label class="inline-check"><input data-watcher-field="clear_password" type="checkbox">清除已有密码</label></td>
        <td><input data-watcher-field="max_pages" type="number" min="1" max="100" value="${escapeHtml(watcher.max_pages || 20)}"></td>
        <td>${badge(status.label, status.kind)}<small class="table-subtext">${escapeHtml(status.detail)}</small></td>
        <td class="cell-actions"><div class="row-actions"><button class="button button-secondary button-small" data-watcher-action="scan" type="button">扫描</button><button class="button button-secondary button-small" data-watcher-action="test" type="button">推送</button><button class="button button-secondary button-small" data-watcher-action="files" type="button">文件</button><button class="button button-danger-ghost button-small" data-watcher-action="delete" type="button">删除</button></div></td>
      </tr>`;
    }).join('') || '<tr><td colspan="7"><div class="empty-state">暂无监控项目</div></td></tr>';
    body.querySelectorAll('[data-watcher-action]').forEach((button) => button.addEventListener('click', () => handleWatcherAction(button)));
  }

  function collectWatchers() {
    return [...document.querySelectorAll('[data-watcher-index]')].map((row) => {
      const get = (name) => row.querySelector(`[data-watcher-field="${name}"]`);
      const item = {
        enabled: get('enabled').checked,
        id: get('id').value.trim(),
        title: get('title').value.trim(),
        url: get('url').value.trim(),
        max_pages: Number(get('max_pages').value) || 20,
      };
      const password = get('password').value.trim();
      if (password) item.password = password;
      if (get('clear_password').checked) item.clear_password = true;
      return item;
    });
  }

  async function loadWatchers() {
    const [config, overview] = await Promise.all([safeApi('/admin/lanzou-config'), safeApi('/admin/overview')]);
    if (!config.ok) { setResult(`读取失败：${config.error.message}`); showToast(`监控项目读取失败：${config.error.message}`, 'error'); return; }
    state.watchers = Array.isArray(config.data.config?.watchers) ? config.data.config.watchers : [];
    state.overview = overview.ok ? overview.data : null;
    renderWatchers();
  }

  async function saveWatchers() {
    const result = await safeApi('/admin/lanzou-config', { method: 'POST', body: { watchers: collectWatchers() } });
    const error = operationError(result, '监控项目保存失败');
    if (error) { setResult(`保存失败：${error}`); showToast(`监控项目保存失败：${error}`, 'error'); return; }
    setResult(result.data);
    state.watchers = result.data.config?.watchers || [];
    renderWatchers();
    showToast('监控项目已保存并刷新运行态', 'success');
  }

  function addWatcher() {
    state.watchers.unshift({ id: `watcher-${Date.now()}`, title: '新监控', url: 'https://', password_configured: false, enabled: true, max_pages: 20 });
    renderWatchers();
    document.querySelector('[data-watcher-index="0"] [data-watcher-field="id"]')?.focus();
  }

  async function handleWatcherAction(button) {
    const row = button.closest('[data-watcher-index]');
    const index = Number(row?.dataset.watcherIndex || -1);
    const item = collectWatchers()[index];
    if (!item) return;
    const action = button.dataset.watcherAction;
    if (action === 'delete') {
      confirmOperation({ title: '删除监控项目', message: `确认删除 ${item.title || item.id}？`, warning: '保存监控项目后才会写入配置文件。', submitLabel: '确认删除' }, async () => {
        state.watchers.splice(index, 1); renderWatchers(); showToast('已从待保存列表移除', 'success');
      });
      return;
    }
    if (!item.id) { showToast('请先填写监控项目 ID', 'error'); return; }
    if (action === 'scan') {
      const result = await safeApi(`/scan?watcher_id=${encodeURIComponent(item.id)}&notify=false`, { method: 'POST' });
      const error = operationError(result, '扫描失败'); setResult(result.ok ? result.data : error);
      showToast(error ? `扫描失败：${error}` : '扫描完成', error ? 'error' : 'success');
      if (!error) await loadWatchers();
    } else if (action === 'test') {
      const result = await safeApi('/notify/test', { method: 'POST', body: { watcher_id: item.id } });
      const error = operationError(result, '测试推送失败'); setResult(result.ok ? result.data : error);
      showToast(error ? `测试推送失败：${error}` : '测试推送完成', error ? 'error' : 'success');
    } else if (action === 'files') {
      const result = await safeApi(`/files/${encodeURIComponent(item.id)}`);
      const error = operationError(result, '文件快照读取失败');
      if (error) { showToast(`文件快照读取失败：${error}`, 'error'); return; }
      setText('snapshotDialogTitle', `文件快照 · ${item.id}`);
      setText('snapshotDialogContent', JSON.stringify(result.data, null, 2));
      const dialog = $('snapshotDialog');
      if (typeof dialog?.showModal === 'function' && !dialog.open) dialog.showModal();
    }
  }

  function renderTargets() {
    const body = $('targetRows');
    if (!body) return;
    setText('targetCount', state.targets.length);
    setText('targetEnabledCount', state.targets.filter((item) => item.enabled !== false).length);
    body.innerHTML = state.targets.map((target, index) => `<tr data-target-index="${index}">
      <td><input data-target-field="enabled" type="checkbox" ${target.enabled !== false ? 'checked' : ''}></td>
      <td><input data-target-field="name" value="${escapeHtml(target.name || '')}" placeholder="唯一名称"></td>
      <td class="cell-url"><input data-target-field="url" value="${escapeHtml(target.url || '')}" placeholder="http://127.0.0.1:..."></td>
      <td><input data-target-field="timeout" type="number" min="0.1" max="120" step="0.1" value="${escapeHtml(target.timeout_seconds || 8)}"></td>
      <td><textarea data-target-field="headers">${escapeHtml(JSON.stringify(target.headers || {}, null, 2))}</textarea></td>
      <td><button class="button button-danger-ghost button-small" data-target-action="delete" type="button">删除</button></td>
    </tr>`).join('') || '<tr><td colspan="6"><div class="empty-state">暂无通知目标</div></td></tr>';
    body.querySelectorAll('[data-target-action="delete"]').forEach((button) => button.addEventListener('click', () => {
      const row = button.closest('[data-target-index]');
      const index = Number(row?.dataset.targetIndex || -1);
      const name = state.targets[index]?.name || `目标 ${index + 1}`;
      confirmOperation({ title: '删除通知目标', message: `确认删除 ${name}？`, warning: '保存通知目标后才会写入配置文件。', submitLabel: '确认删除' }, async () => {
        state.targets.splice(index, 1); renderTargets(); showToast('已从待保存列表移除', 'success');
      });
    }));
  }

  function collectTargets() {
    return [...document.querySelectorAll('[data-target-index]')].map((row, index) => {
      const get = (name) => row.querySelector(`[data-target-field="${name}"]`);
      return {
        enabled: get('enabled').checked,
        name: get('name').value.trim(),
        url: get('url').value.trim(),
        timeout_seconds: Number(get('timeout').value) || 8,
        headers: parseJsonValue(get('headers').value, `第 ${index + 1} 个通知目标 Headers`),
      };
    });
  }

  async function loadTargets() {
    const result = await safeApi('/admin/lanzou-config');
    if (!result.ok) { setResult(`读取失败：${result.error.message}`); showToast(`通知目标读取失败：${result.error.message}`, 'error'); return; }
    state.targets = Array.isArray(result.data.config?.notify_targets) ? result.data.config.notify_targets : [];
    renderTargets();
  }

  async function saveTargets() {
    let targets;
    try { targets = collectTargets(); } catch (error) { showToast(error.message, 'error'); return; }
    const result = await safeApi('/admin/lanzou-config', { method: 'POST', body: { notify_targets: targets } });
    const error = operationError(result, '通知目标保存失败');
    if (error) { setResult(`保存失败：${error}`); showToast(`通知目标保存失败：${error}`, 'error'); return; }
    setResult(result.data);
    state.targets = result.data.config?.notify_targets || [];
    renderTargets();
    showToast('通知目标已保存并刷新运行态', 'success');
  }

  function addTarget() {
    state.targets.unshift({ name: `target-${state.targets.length + 1}`, enabled: true, url: 'http://127.0.0.1:6108/', timeout_seconds: 8, headers: {} });
    renderTargets();
    document.querySelector('[data-target-index="0"] [data-target-field="name"]')?.focus();
  }

  async function testTargets() {
    const result = await safeApi('/notify/test', { method: 'POST', body: {} });
    const error = operationError(result, '测试推送失败');
    setResult(result.ok ? result.data : error);
    showToast(error ? `测试推送失败：${error}` : '测试推送完成', error ? 'error' : 'success');
  }

  function normalizeRoutes(payload, service) {
    if (payload?.ok === false) throw new Error(payload.error || `${service} OpenAPI 读取失败`);
    const schema = payload?.schema || {};
    const routes = [];
    Object.entries(schema.paths || {}).forEach(([path, operations]) => {
      Object.entries(operations || {}).forEach(([method, operation]) => {
        if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) return;
        routes.push({ service, path, method: method.toUpperCase(), summary: operation.summary || operation.operationId || '', parameters: operation.parameters || [], requestBody: operation.requestBody || null });
      });
    });
    return routes;
  }

  async function loadDebuggerRoutes() {
    const [main, lanzou] = await Promise.all([safeApi('/admin/openapi/main'), safeApi('/admin/openapi/lanzou')]);
    const failures = [];
    const routes = [];
    for (const [result, service] of [[main, 'main'], [lanzou, 'lanzou']]) {
      if (!result.ok) { failures.push(`${service}: ${result.error.message}`); continue; }
      try { routes.push(...normalizeRoutes(result.data, service)); } catch (error) { failures.push(`${service}: ${error.message}`); }
    }
    state.routes = routes.sort((a, b) => `${a.service}${a.path}${a.method}`.localeCompare(`${b.service}${b.path}${b.method}`));
    const select = $('debuggerRouteSelect');
    if (select) select.innerHTML = state.routes.map((route, index) => `<option value="${index}">[${escapeHtml(route.service)}] ${escapeHtml(route.method)} ${escapeHtml(route.path)} · ${escapeHtml(route.summary)}</option>`).join('') || '<option value="">没有可用接口</option>';
    setText('debuggerRouteCount', `${state.routes.length} 个接口${failures.length ? `；${failures.join('；')}` : ''}`);
    selectDebuggerRoute();
  }

  function selectDebuggerRoute() {
    const route = state.routes[Number($('debuggerRouteSelect')?.value || 0)];
    if (!route) { setText('debuggerRouteHint', '没有可用接口'); return; }
    const query = {};
    (route.parameters || []).filter((item) => ['query', 'path'].includes(item.in)).forEach((parameter) => {
      const schema = parameter.schema || {};
      query[parameter.name] = schema.default ?? (parameter.required ? `<${parameter.name}>` : '');
    });
    $('debuggerQuery').value = JSON.stringify(query, null, 2);
    $('debuggerBody').value = '{}';
    $('debuggerService').value = route.service;
    setText('debuggerRouteHint', `${route.method} ${route.path} · ${route.summary || '无摘要'}`);
  }

  async function sendDebuggerRequest() {
    const route = state.routes[Number($('debuggerRouteSelect')?.value || 0)];
    if (!route) { showToast('请选择接口', 'error'); return; }
    let query; let body;
    try {
      query = parseJsonValue($('debuggerQuery').value, 'Query 与 Path 参数');
      body = parseJsonValue($('debuggerBody').value, '请求体');
    } catch (error) { showToast(error.message, 'error'); return; }
    const payload = { service: route.service, method: route.method, path: route.path, query, timeout: Number($('debuggerTimeout').value) || 30 };
    if (route.method !== 'GET' && Object.keys(body).length) payload.json = body;
    setText('debuggerResponse', '正在发送请求...');
    const result = await safeApi('/admin/invoke', { method: 'POST', body: payload });
    if (!result.ok) { setText('debuggerResponse', `请求失败：${result.error.message}`); showToast(`请求失败：${result.error.message}`, 'error'); return; }
    const data = result.data || {};
    setText('debuggerResponseMeta', `HTTP ${data.status_code ?? '-'} · ${data.elapsed_ms ?? '-'} ms · ${data.content_type || '-'}`);
    const image = $('debuggerImage');
    if (image) image.innerHTML = '';
    if (data.base64 && image) {
      const safeType = String(data.content_type || 'image/png').split(';', 1)[0];
      image.innerHTML = `<img alt="接口返回图片" src="data:${escapeHtml(safeType)};base64,${data.base64}">`;
      const summary = { ...data, base64: `<${data.base64.length} chars>` };
      setText('debuggerResponse', JSON.stringify(summary, null, 2));
    } else setText('debuggerResponse', JSON.stringify(data, null, 2));
    showToast(data.ok === false ? '请求完成，上游返回非成功状态' : '请求完成', data.ok === false ? 'warning' : 'success');
  }

  function setupPageActions() {
    if (page === 'main-config') {
      $('mainConfigRefreshButton')?.addEventListener('click', loadMainConfig);
      $('mainConfigSaveButton')?.addEventListener('click', () => confirmOperation({ title: '保存主接口配置', message: '确认写入 ops/app_env.local.ps1？', warning: '系统会先备份当前文件。保存后需要重启 LOLDataSystem 才能完整生效。', submitLabel: '确认保存' }, saveMainConfig));
    } else if (page === 'lanzou-config') {
      $('lanzouConfigRefreshButton')?.addEventListener('click', loadLanzouConfig);
      $('lanzouConfigSaveButton')?.addEventListener('click', () => confirmOperation({ title: '保存蓝奏全局配置', message: '确认保存并刷新蓝奏监控运行态？', warning: '系统会先备份当前 JSON。监听地址、端口和状态路径变化后建议重启服务。', submitLabel: '确认保存' }, saveLanzouConfig));
    } else if (page === 'watchers') {
      $('watchersRefreshButton')?.addEventListener('click', loadWatchers);
      $('watcherAddButton')?.addEventListener('click', addWatcher);
      $('watchersSaveButton')?.addEventListener('click', () => confirmOperation({ title: '保存监控项目', message: '确认用当前列表覆盖监控项目配置？', warning: '系统会先备份配置。密码留空时保留已有值，勾选清除才会删除。', submitLabel: '确认保存' }, saveWatchers));
      const closeSnapshot = () => { const dialog = $('snapshotDialog'); if (dialog?.open) dialog.close(); };
      $('snapshotDialogClose')?.addEventListener('click', closeSnapshot);
      $('snapshotDialogDone')?.addEventListener('click', closeSnapshot);
    } else if (page === 'targets') {
      $('targetsRefreshButton')?.addEventListener('click', loadTargets);
      $('targetAddButton')?.addEventListener('click', addTarget);
      $('targetsTestButton')?.addEventListener('click', testTargets);
      $('targetsSaveButton')?.addEventListener('click', () => confirmOperation({ title: '保存通知目标', message: '确认用当前列表覆盖通知目标配置？', warning: '系统会先备份配置。Header 值为 *** 时保留原值。', submitLabel: '确认保存' }, saveTargets));
    } else if (page === 'api-debugger') {
      $('debuggerRefreshButton')?.addEventListener('click', loadDebuggerRoutes);
      $('debuggerRouteSelect')?.addEventListener('change', selectDebuggerRoute);
      $('debuggerSendButton')?.addEventListener('click', sendDebuggerRequest);
    }
  }

  async function reloadPage() {
    await loadCommonStatus();
    if (page === 'main-config') await loadMainConfig();
    else if (page === 'lanzou-config') await loadLanzouConfig();
    else if (page === 'watchers') await loadWatchers();
    else if (page === 'targets') await loadTargets();
    else if (page === 'api-debugger') await loadDebuggerRoutes();
  }

  async function init() {
    setupSidebar(); setupTokenDialog(); setupConfirmDialog(); setupPageActions(); setTokenUi();
    await reloadPage();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init().catch((error) => showToast(error.message, 'error')));
  else init().catch((error) => showToast(error.message, 'error'));
})();
