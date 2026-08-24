(() => {
  'use strict';

  if (document.body.dataset.consoleUi !== 'system') return;

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  let latestStatus = null;
  let updatePollTimer = 0;

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

  function progressLines(state) {
    const lines = [];
    if (!state || typeof state !== 'object' || !state.status) return lines;
    lines.push('', `升级状态: ${state.status}`);
    if (state.message) lines.push(`阶段: ${state.message}`);
    if (state.download_source) lines.push(`下载源: ${state.download_source}`);
    const total = Number(state.package_bytes || 0);
    const done = Number(state.downloaded_bytes || 0);
    if (total > 0 && done >= 0) {
      const percent = Number(state.progress_percent || (done * 100 / total));
      const speed = Number(state.speed_mbps || 0);
      lines.push(
        `进度: ${Number.isFinite(percent) ? percent.toFixed(1) : '0.0'}% · ${formatBytes(done)} / ${formatBytes(total)}${speed > 0 ? ` · ${speed.toFixed(2)} MB/s` : ''}`,
      );
    }
    const probes = Array.isArray(state.mirror_probes) ? state.mirror_probes : [];
    if (probes.length) {
      const summary = probes
        .slice()
        .sort((a, b) => Number(a.elapsed_ms || 999999) - Number(b.elapsed_ms || 999999))
        .map((item) => `${item.label}:${item.ok ? `${Math.round(Number(item.elapsed_ms || 0))}ms` : '失败'}`)
        .join('  ');
      lines.push(`测速: ${summary}`);
    }
    const errors = Array.isArray(state.download_errors) ? state.download_errors : [];
    if (errors.length) {
      const last = errors[errors.length - 1];
      lines.push(`自动切源: ${last.source || '-'} → ${last.error || '失败'}`);
    }
    if (state.target_commit) lines.push(`目标: ${shortSha(state.target_commit)}`);
    if (state.log) lines.push(`升级日志: ${state.log}`);
    if (state.error) lines.push(`错误: ${state.error}`);
    return lines;
  }

  function renderStatus(status) {
    latestStatus = status;
    setText('releaseCurrentCommit', shortSha(status?.current_commit));
    setText('releaseCurrentName', `build: ${status?.current_release || 'unknown'}`);
    setText('releaseLatestName', status?.latest_release || '不可用');
    setText(
      'releaseTargetCommit',
      status?.target_commit
        ? `目标 ${shortSha(status.target_commit)}`
        : (status?.error || '未取得目标提交'),
    );
    updateTokenStatus(status);

    const start = $('releaseUpdateStartButton');
    const supported = status?.platform_supported !== false;
    const available = Boolean(status?.available && status?.target_commit);
    const updating = status?.status === 'updating';
    if (start) start.disabled = updating || !(supported && available);

    if (status?.status === 'current') {
      setText('releaseUpdateState', '已是最新');
    } else if (status?.status === 'update_available') {
      setText('releaseUpdateState', '可升级');
    } else if (status?.status === 'updating') {
      setText('releaseUpdateState', '升级中');
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
    if (Array.isArray(status?.mirrors) && status.mirrors.length) {
      lines.push(`加速源: ${status.mirrors.join(' / ')} / GitHub`);
    }
    if (status?.error) lines.push(`说明: ${status.error}`);
    lines.push(...progressLines(state));
    setText('releaseUpdateResult', lines.join('\n'));
  }

  async function loadStatus(options = {}) {
    const silent = Boolean(options.silent);
    const button = $('releaseUpdateCheckButton');
    if (!silent && button) button.disabled = true;
    if (!silent) setText('releaseUpdateResult', '正在检查 GitHub Release 与 V3 metadata...');
    try {
      renderStatus(await request('/admin/update/status'));
    } catch (error) {
      if (!silent) {
        setText('releaseUpdateState', '检查失败');
        setText('releaseUpdateResult', `检查更新失败：${error.message}`);
        if ($('releaseUpdateStartButton')) $('releaseUpdateStartButton').disabled = true;
      }
    } finally {
      if (!silent && button) button.disabled = false;
    }
  }

  function startProgressPolling() {
    stopProgressPolling();
    updatePollTimer = window.setInterval(() => {
      loadStatus({ silent: true });
    }, 1200);
  }

  function stopProgressPolling() {
    if (updatePollTimer) {
      window.clearInterval(updatePollTimer);
      updatePollTimer = 0;
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
      setText(
        'releaseUpdateResult',
        token
          ? 'Release Token 已保存，正在重新检查更新...'
          : 'Release Token 已清除，正在重新检查更新...',
      );
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
      `将从 ${latestStatus.latest_release || '最新 Release'} 升级到 ${shortSha(latestStatus.target_commit)}。升级器会先并行测速多个镜像源并保持 SHA-256 校验。确认继续吗？`,
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
    setText(
      'releaseUpdateResult',
      '正在读取官方 metadata，并行测速 gh-proxy.com / ghproxy.net / ghfast.top / gh.ddlc.top / GitHub；慢源会自动切换，下载过程会显示实时进度...',
    );
    startProgressPolling();
    try {
      const result = await request('/admin/update/start', { method: 'POST', body: {} });
      stopProgressPolling();
      if (result?.scheduled) {
        const lines = [
          '一键升级已安全排队。',
          `目标提交: ${result.target_commit || '-'}`,
          `部署包: ${result.package || '-'}`,
          `下载源: ${result.download_source || '-'}`,
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
      stopProgressPolling();
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
