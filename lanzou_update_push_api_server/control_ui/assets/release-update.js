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

  function formatAge(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return '-';
    if (seconds < 60) return `${Math.round(seconds)} 秒前`;
    return `${(seconds / 60).toFixed(1)} 分钟前`;
  }

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
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

  function ensureControlButtons() {
    if ($('releaseUpdateControls')) return;
    const result = $('releaseUpdateResult');
    if (!result?.parentElement) return;
    const controls = document.createElement('div');
    controls.id = 'releaseUpdateControls';
    controls.className = 'page-actions';
    controls.style.margin = '12px 0';
    controls.innerHTML = `
      <button class="button button-secondary" id="releaseUpdatePauseButton" type="button" disabled>暂停下载</button>
      <button class="button button-secondary" id="releaseUpdateResumeButton" type="button" disabled>继续下载</button>
      <button class="button button-secondary" id="releaseUpdateReconnectButton" type="button" disabled>重新连接</button>
      <button class="button button-secondary" id="releaseUpdateResetButton" type="button" disabled>清空断点重下</button>
    `;
    result.parentElement.insertBefore(controls, result);
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

  function progressLines(state, status) {
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
    if (Number(state.resumed_bytes || 0) > 0) {
      lines.push(`断点: 已保留 ${formatBytes(state.resumed_bytes)}`);
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
      lines.push(`最近切源/重连: ${last.source || '-'} → ${last.error || '失败'}`);
    }
    if (status?.worker_alive !== undefined) {
      lines.push(`后台 worker: ${status.worker_alive ? '运行中' : '不存在'}`);
    }
    if (status?.heartbeat_age_seconds !== null && status?.heartbeat_age_seconds !== undefined) {
      lines.push(`最近心跳: ${formatAge(status.heartbeat_age_seconds)}`);
    }
    if (state.target_commit) lines.push(`目标: ${shortSha(state.target_commit)}`);
    if (state.log) lines.push(`升级日志: ${state.log}`);
    if (state.error) lines.push(`错误: ${state.error}`);
    return lines;
  }

  function statusLabel(status) {
    const stateStatus = String(status?.update_state?.status || '').toLowerCase();
    if (stateStatus === 'paused') return '已暂停';
    if (stateStatus === 'interrupted') return '已中断';
    if (stateStatus === 'stalled') return '下载停滞';
    if (stateStatus === 'failed') return '升级失败';
    if (stateStatus === 'scheduled') return '部署已启动';
    if (status?.status === 'current') return '已是最新';
    if (status?.status === 'update_available') return '可升级';
    if (status?.status === 'updating') return '升级中';
    return '暂不可用';
  }

  function renderControls(status) {
    ensureControlButtons();
    const controls = status?.controls || {};
    if ($('releaseUpdatePauseButton')) $('releaseUpdatePauseButton').disabled = !controls.can_pause;
    if ($('releaseUpdateResumeButton')) $('releaseUpdateResumeButton').disabled = !controls.can_resume;
    if ($('releaseUpdateReconnectButton')) $('releaseUpdateReconnectButton').disabled = !controls.can_reconnect;
    if ($('releaseUpdateResetButton')) $('releaseUpdateResetButton').disabled = !controls.can_reset;
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
    renderControls(status);

    const start = $('releaseUpdateStartButton');
    const supported = status?.platform_supported !== false;
    const available = Boolean(status?.available && status?.target_commit);
    const busy = Boolean(status?.worker_alive || status?.status === 'updating');
    if (start) start.disabled = busy || !(supported && available);

    setText('releaseUpdateState', statusLabel(status));
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
    lines.push(...progressLines(state, status));
    setText('releaseUpdateResult', lines.join('\n'));
  }

  async function loadStatus(options = {}) {
    const silent = Boolean(options.silent);
    const button = $('releaseUpdateCheckButton');
    if (!silent && button) button.disabled = true;
    if (!silent) setText('releaseUpdateResult', '正在检查 GitHub Release 与 V3 metadata...');
    try {
      const status = await request('/admin/update/status');
      renderStatus(status);
      return status;
    } catch (error) {
      if (!silent) {
        setText('releaseUpdateState', '检查失败');
        setText('releaseUpdateResult', `检查更新失败：${error.message}`);
        if ($('releaseUpdateStartButton')) $('releaseUpdateStartButton').disabled = true;
      }
      return null;
    } finally {
      if (!silent && button) button.disabled = false;
    }
  }

  function startProgressPolling() {
    stopProgressPolling();
    updatePollTimer = window.setInterval(async () => {
      const status = await loadStatus({ silent: true });
      const stateStatus = String(status?.update_state?.status || '').toLowerCase();
      if (['current', 'scheduled', 'complete', 'failed', 'interrupted'].includes(stateStatus)) {
        stopProgressPolling();
      }
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
      `将从 ${latestStatus.latest_release || '最新 Release'} 升级到 ${shortSha(latestStatus.target_commit)}。下载会在后台运行，可暂停、继续或断点重连。确认继续吗？`,
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
      '正在把升级任务交给后台 worker。之后页面只轮询本地状态，下载连接不再绑住当前 HTTP 请求...',
    );
    try {
      const result = await request('/admin/update/start', { method: 'POST', body: {} });
      setText('releaseUpdateResult', result?.message || '升级任务已启动');
      await loadStatus({ silent: true });
      startProgressPolling();
    } catch (error) {
      setText('releaseUpdateResult', `一键升级未启动：${error.message}`);
      if (latestStatus?.available && button) button.disabled = false;
    }
  }

  async function controlUpdate(action, buttonId, workingText) {
    const button = $(buttonId);
    if (button) button.disabled = true;
    setText('releaseUpdateResult', workingText);
    try {
      const result = await request(`/admin/update/${action}`, { method: 'POST', body: {} });
      setText('releaseUpdateResult', result?.message || '操作已提交');
      await loadStatus({ silent: true });
      if (action !== 'pause') startProgressPolling();
    } catch (error) {
      setText('releaseUpdateResult', `操作失败：${error.message}`);
      await loadStatus({ silent: true });
    }
  }

  function bindControls() {
    ensureControlButtons();
    $('releaseUpdatePauseButton')?.addEventListener('click', () => (
      controlUpdate('pause', 'releaseUpdatePauseButton', '正在请求暂停；当前网络读结束后会保留 .part 断点...')
    ));
    $('releaseUpdateResumeButton')?.addEventListener('click', () => (
      controlUpdate('resume', 'releaseUpdateResumeButton', '正在继续现有断点下载...')
    ));
    $('releaseUpdateReconnectButton')?.addEventListener('click', () => (
      controlUpdate('reconnect', 'releaseUpdateReconnectButton', '正在断开当前连接并从现有断点重新连接...')
    ));
    $('releaseUpdateResetButton')?.addEventListener('click', () => {
      if (!window.confirm('确认清空当前目标版本的下载断点并从 0 重新下载吗？已下载的部分会被删除。')) return;
      controlUpdate('reset', 'releaseUpdateResetButton', '正在清空当前断点并从 0 重新下载...');
    });
  }

  function renderVerifiedServiceStatus(status) {
    const pid = Number(status?.process_id || 0);
    const stateValue = String(status?.state || 'unknown').toLowerCase();
    setText('serviceState', stateValue === 'running' ? '运行中' : stateValue);
    setText('serviceDetail', `LOLDataSystem · ${stateValue}${pid > 0 ? ` · PID ${pid}` : ''}`);
    setText('serviceStatusContent', JSON.stringify(status || {}, null, 2));
  }

  async function pollRestartVerification(requestId, beforePid) {
    const deadline = Date.now() + 75000;
    let lastError = '';
    while (Date.now() < deadline) {
      try {
        const status = await request('/admin/service/status');
        renderVerifiedServiceStatus(status);
        const verification = status?.restart_verification || {};
        if (verification.request_id === requestId && verification.status === 'verified') {
          return verification;
        }
        if (
          verification.request_id === requestId
          && ['unverified', 'launch_failed'].includes(String(verification.status || '').toLowerCase())
        ) {
          throw new Error(verification.message || '服务 PID 未发生预期变化');
        }
      } catch (error) {
        lastError = error.message || String(error);
      }
      await sleep(1200);
    }
    throw new Error(lastError || `75 秒内未验证服务 PID 从 ${beforePid || '-'} 发生变化`);
  }

  async function verifiedRestartService() {
    if (!window.confirm('确认重启 LOLDataSystem？页面可能短暂断开；只有检测到服务 PID 更换后才会判定成功。')) return;
    const button = $('restartServiceButton');
    const original = button?.querySelector('span')?.textContent || '重启服务';
    if (button) button.disabled = true;
    const label = button?.querySelector('span');
    if (label) label.textContent = '等待重启验证';
    try {
      const scheduled = await request('/admin/service/restart', {
        method: 'POST',
        body: { delay_seconds: 3 },
      });
      setText(
        'serviceStatusContent',
        `重启已安排，等待 PID 变化验证...\n请求: ${scheduled.request_id || '-'}\n重启前 PID: ${scheduled.before_pid || '-'}`,
      );
      const verification = await pollRestartVerification(scheduled.request_id, scheduled.before_pid);
      setText('serviceStatusContent', JSON.stringify(verification, null, 2));
      setText('serviceDetail', verification.message || '服务重启已验证');
      if (label) label.textContent = '重启已验证';
      await sleep(1800);
    } catch (error) {
      setText('serviceStatusContent', `服务重启未验证：${error.message}`);
      setText('serviceDetail', '重启结果未验证，请查看 PID/服务状态');
      if (label) label.textContent = '重启未验证';
      await sleep(2500);
    } finally {
      if (button) button.disabled = false;
      if (label) label.textContent = original;
    }
  }

  function bindVerifiedRestart() {
    const button = $('restartServiceButton');
    if (!button || button.dataset.verifiedRestartBound === '1') return;
    button.dataset.verifiedRestartBound = '1';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      verifiedRestartService();
    }, true);
  }

  function init() {
    bindControls();
    bindVerifiedRestart();
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
    loadStatus().then((status) => {
      if (status?.worker_alive || status?.status === 'updating') startProgressPolling();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
