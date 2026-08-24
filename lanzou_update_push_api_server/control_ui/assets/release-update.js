(() => {
  'use strict';

  if (document.body.dataset.consoleUi !== 'system') return;

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  let latestStatus = null;

  function adminToken() {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || '';
    } catch (_error) {
      return '';
    }
  }

  function setText(id, value) {
    const node = $(id);
    if (node) node.textContent = String(value ?? '-');
  }

  function shortSha(value) {
    const text = String(value || 'unknown');
    return /^[0-9a-f]{40}$/i.test(text) ? text.slice(0, 12) : text;
  }

  function formatBytes(value) {
    let size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index += 1;
    }
    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
  }

  async function request(path, options = {}) {
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
      data = { error: raw || response.statusText };
    }
    if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    if (data && data.ok === false) throw new Error(data.error || '操作失败');
    return data;
  }

  function updateTokenStatus(status) {
    const node = $('releaseTokenStatus');
    if (!node) return;
    const configured = Boolean(status?.token_configured);
    node.innerHTML = configured
      ? '<span class="status-dot status-dot-success"></span><span>已配置</span>'
      : '<span class="status-dot status-dot-neutral"></span><span>未配置</span>';
    setText(
      'releaseTokenHint',
      configured
        ? `Token 已配置（来源：${status?.token_source || 'unknown'}），真实值不会回显。`
        : '私有仓库首次使用需配置只读 Token；真实值不会回显。',
    );
  }

  function renderStatus(status) {
    latestStatus = status;
    setText('releaseCurrentCommit', shortSha(status?.current_commit));
    setText('releaseCurrentName', `build: ${status?.current_release || 'unknown'}`);
    setText('releaseLatestName', status?.latest_release || '不可用');
    setText('releaseTargetCommit', status?.target_commit ? `目标 ${shortSha(status.target_commit)}` : (status?.error || '未取得目标提交'));
    updateTokenStatus(status);

    const start = $('releaseUpdateStartButton');
    const supported = status?.platform_supported !== false;
    const available = Boolean(status?.available && status?.target_commit);
    if (start) start.disabled = !(supported && available);

    if (status?.status === 'current') {
      setText('releaseUpdateState', '已是最新');
    } else if (status?.status === 'update_available') {
      setText('releaseUpdateState', '可升级');
    } else {
      setText('releaseUpdateState', '暂不可用');
    }
    setText(
      'releasePackageInfo',
      status?.package_name
        ? `${formatBytes(status.package_bytes)} · V3`
        : (supported ? '等待 Release metadata' : '仅 Windows 支持一键升级'),
    );

    const state = status?.update_state || {};
    const lines = [
      `当前提交: ${status?.current_commit || 'unknown'}`,
      `最新 Release: ${status?.latest_release || '-'}`,
      `目标提交: ${status?.target_commit || '-'}`,
      `部署包: ${status?.package_name || '-'}`,
      `状态: ${status?.status || 'unknown'}`,
    ];
    if (status?.error) lines.push(`说明: ${status.error}`);
    if (state?.status) {
      lines.push('', `最近升级状态: ${state.status}`);
      if (state.target_commit) lines.push(`最近目标: ${state.target_commit}`);
      if (state.log) lines.push(`升级日志: ${state.log}`);
    }
    setText('releaseUpdateResult', lines.join('\n'));
  }

  async function loadStatus() {
    const button = $('releaseUpdateCheckButton');
    if (button) button.disabled = true;
    setText('releaseUpdateResult', '正在检查 GitHub Release 与 V3 metadata...');
    try {
      renderStatus(await request('/admin/update/status'));
    } catch (error) {
      setText('releaseUpdateState', '检查失败');
      setText('releaseUpdateResult', `检查更新失败：${error.message}`);
      if ($('releaseUpdateStartButton')) $('releaseUpdateStartButton').disabled = true;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function saveToken() {
    const input = $('releaseTokenInput');
    const token = input?.value.trim() || '';
    const button = $('releaseTokenSaveButton');
    if (button) button.disabled = true;
    try {
      await request('/admin/update/token', { method: 'POST', body: { token } });
      if (input) input.value = '';
      setText('releaseUpdateResult', token ? 'Release Token 已保存，正在重新检查更新...' : 'Release Token 已清除，正在重新检查更新...');
      await loadStatus();
    } catch (error) {
      setText('releaseUpdateResult', `Token 保存失败：${error.message}`);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function openUpdateConfirm() {
    if (!latestStatus?.available || !latestStatus?.target_commit) return;
    setText(
      'releaseUpdateConfirmMessage',
      `将从 ${latestStatus.latest_release || '最新 Release'} 升级到 ${shortSha(latestStatus.target_commit)}。确认继续吗？`,
    );
    const dialog = $('releaseUpdateConfirmDialog');
    if (dialog && typeof dialog.showModal === 'function' && !dialog.open) dialog.showModal();
  }

  function closeUpdateConfirm() {
    const dialog = $('releaseUpdateConfirmDialog');
    if (dialog?.open) dialog.close();
  }

  async function startUpdate() {
    const button = $('releaseUpdateStartButton');
    if (button) button.disabled = true;
    setText('releaseUpdateResult', '正在下载并校验 V3 Release 包。校验通过后将启动独立部署进程...');
    try {
      const result = await request('/admin/update/start', { method: 'POST', body: {} });
      if (result?.scheduled) {
        const lines = [
          '一键升级已安全排队。',
          `目标提交: ${result.target_commit || '-'}`,
          `部署包: ${result.package || '-'}`,
          `升级日志: ${result.log || '-'}`,
          '',
          '页面可能在数秒后断开。部署器会完成候选验证、生产备份、切换、健康检查与失败自动回滚。',
        ];
        setText('releaseUpdateResult', lines.join('\n'));
      } else {
        setText('releaseUpdateResult', result?.message || '当前无需升级');
        await loadStatus();
      }
    } catch (error) {
      setText('releaseUpdateResult', `一键升级未启动：${error.message}`);
      if (latestStatus?.available && button) button.disabled = false;
    }
  }

  function init() {
    $('releaseUpdateCheckButton')?.addEventListener('click', loadStatus);
    $('releaseTokenSaveButton')?.addEventListener('click', saveToken);
    $('releaseUpdateStartButton')?.addEventListener('click', openUpdateConfirm);
    $('releaseUpdateConfirmClose')?.addEventListener('click', closeUpdateConfirm);
    $('releaseUpdateConfirmCancel')?.addEventListener('click', closeUpdateConfirm);
    $('releaseUpdateConfirmForm')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      closeUpdateConfirm();
      await startUpdate();
    });
    loadStatus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
