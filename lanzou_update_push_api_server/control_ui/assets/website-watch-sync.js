(() => {
  'use strict';

  if (document.body?.dataset?.consoleUi !== 'watchers') return;

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const $ = (id) => document.getElementById(id);
  let preview = null;
  let busy = false;

  function toast(message, kind = 'info') {
    const region = $('toastRegion');
    if (!region) return;
    const node = document.createElement('div');
    node.className = 'toast toast-' + kind;
    node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(() => node.remove(), 5200);
  }

  async function api(path, options = {}) {
    const headers = { 'accept': 'application/json' };
    try {
      const token = sessionStorage.getItem(TOKEN_KEY);
      if (token) headers['x-admin-token'] = token;
    } catch (_error) {}
    if (options.body !== undefined) headers['content-type'] = 'application/json';
    const response = await fetch(path, {
      method: options.method || 'GET',
      headers,
      cache: 'no-store',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    let data;
    try { data = await response.json(); }
    catch (_error) { throw new Error('控制台返回了无效响应 (HTTP ' + response.status + ')'); }
    if (!response.ok || data?.ok === false) {
      throw new Error(typeof data?.detail === 'string'
        ? data.detail : (data?.error || 'HTTP ' + response.status));
    }
    return data;
  }

  function dialog() {
    if ($('websiteWatchSyncDialog')) return $('websiteWatchSyncDialog');
    const element = document.createElement('dialog');
    element.className = 'dialog dialog-wide';
    element.id = 'websiteWatchSyncDialog';
    element.innerHTML =
      '<div class="dialog-card">' +
      '<header class="dialog-header"><div><p class="eyebrow">WEBSITE · 私有仓库同步</p>' +
      '<h2>同步蓝奏监控目标</h2></div>' +
      '<button class="icon-button" type="button" id="websiteSyncClose" aria-label="关闭">×</button></header>' +
      '<div class="dialog-body">' +
      '<p class="dialog-description" id="websiteSyncSummary">准备检查…</p>' +
      '<div class="alert alert-warning">仅同步监控目标。扫描频率、Provider、通知目标保持不变。保存前自动备份。</div>' +
      '<div class="field" style="margin-top:12px"><label for="websiteSyncToken">GitHub 私有仓库只读 Token（可选：首次配置时填写）</label>' +
      '<input type="password" id="websiteSyncToken" autocomplete="off" placeholder="Fine-grained PAT · website 仓库 Contents: Read-only">' +
      '<button class="button button-secondary" type="button" id="websiteSyncSaveToken">保存访问凭据</button>' +
      '<p id="websiteSyncTokenStatus" class="hint">正在检查配置状态…</p></div>' +
      '<pre class="operations-result configuration-result" id="websiteSyncDiff">尚未检查</pre></div>' +
      '<footer class="dialog-footer"><span class="dialog-footer-spacer"></span>' +
      '<button class="button button-secondary" type="button" id="websiteSyncRefresh">重新检查</button>' +
      '<button class="button button-secondary" type="button" id="websiteSyncCancel">取消</button>' +
      '<button class="button button-primary" type="button" id="websiteSyncApply" disabled>确认同步</button>' +
      '</footer></div>';
    document.body.appendChild(element);
    const close = () => { if (!busy && element.open) element.close(); };
    $('websiteSyncClose').addEventListener('click', close);
    $('websiteSyncCancel').addEventListener('click', close);
    $('websiteSyncRefresh').addEventListener('click', () => void refresh());
    $('websiteSyncSaveToken').addEventListener('click', () => void saveToken());
    $('websiteSyncApply').addEventListener('click', () => void apply());
    return element;
  }

  function renderDiff(plan) {
    const change = plan.diff;
    const lines = [
      'website/source @ ' + plan.sha,
      '蓝奏监控目标：' + change.before + ' → ' + change.after,
      '新增 ' + change.added.length + ' / 删除 ' + change.removed.length + ' / 更新 ' + change.updated.length,
      '',
    ];
    for (const [label, items, prefix] of [
      ['新增', change.added, '+'], ['删除', change.removed, '-'], ['更新', change.updated, '~'],
    ]) {
      if (!items.length) continue;
      lines.push('【' + label + '】');
      for (const item of items) lines.push(prefix + ' ' + item.title + '  ' + item.url);
      lines.push('');
    }
    if (!change.added.length && !change.removed.length && !change.updated.length) {
      lines.push('本机监控目标与当前网站一致，无需同步。');
    }
    return lines.join('\n');
  }

  async function status() {
    try {
      const response = await api('/admin/website-watch-sync/status');
      $('websiteSyncTokenStatus').textContent = response.token_configured
        ? '已保存私有仓库访问凭据（不会回显）。'
        : '尚未配置。请创建仅授权 website 仓库 Contents 读取权限的 GitHub Fine-grained Token。';
      return response.token_configured;
    } catch (error) {
      $('websiteSyncTokenStatus').textContent = String(error.message || error);
      return false;
    }
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    preview = null;
    $('websiteSyncApply').disabled = true;
    $('websiteSyncSummary').textContent = '正在从 website/source 读取当前导航数据…';
    $('websiteSyncDiff').textContent = '检查中…';
    try {
      const plan = await api('/admin/website-watch-sync/preview');
      preview = plan;
      $('websiteSyncSummary').textContent = '已验证网站提交，共 ' + plan.count + ' 个蓝奏监控目标。';
      $('websiteSyncDiff').textContent = renderDiff(plan);
      $('websiteSyncApply').disabled = !(
        plan.diff.added.length || plan.diff.removed.length || plan.diff.updated.length
      );
    } catch (error) {
      $('websiteSyncSummary').textContent = '检查失败，未修改任何配置。';
      $('websiteSyncDiff').textContent = String(error.message || error);
      toast('同步检查失败：' + String(error.message || error), 'error');
    } finally { busy = false; }
  }

  async function saveToken() {
    if (busy) return;
    const input = $('websiteSyncToken');
    const token = input.value.trim();
    if (!token) { toast('请填写 GitHub Token', 'error'); return; }
    busy = true;
    $('websiteSyncSaveToken').disabled = true;
    try {
      await api('/admin/website-watch-sync/token', {
        method: 'POST', body: { token },
      });
      input.value = '';
      toast('私有仓库访问凭据已保存', 'success');
    } catch (error) {
      toast('保存凭据失败：' + String(error.message || error), 'error');
    } finally {
      input.value = '';
      $('websiteSyncSaveToken').disabled = false;
      busy = false;
      await status();
    }
    await refresh();
  }

  async function apply() {
    if (busy || !preview) return;
    const change = preview.diff;
    const largeRemoval = change.removed.length > Math.max(10, Math.floor(change.before * 0.4));
    if (largeRemoval && !window.confirm(
      '本次将删除 ' + change.removed.length + ' 项监控，请确认预览中的删除清单。是否继续？'
    )) return;
    busy = true;
    $('websiteSyncApply').disabled = true;
    $('websiteSyncApply').textContent = '同步中…';
    try {
      const result = await api('/admin/website-watch-sync/apply', {
        method: 'POST',
        body: { sha: preview.sha, revision: preview.revision, allow_large_removal: largeRemoval },
      });
      $('websiteSyncDiff').textContent += '\n\n' + result.message +
        '\n备份：' + (result.backup_path || '无变更') + '\n运行态：已热更新';
      toast('蓝奏监控目标同步成功', 'success');
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      preview = null;
      $('websiteSyncSummary').textContent = '同步未完成，请重新检查后再尝试。';
      $('websiteSyncDiff').textContent += '\n\n同步失败：' + String(error.message || error);
      toast('同步失败：' + String(error.message || error), 'error');
    } finally {
      busy = false;
      $('websiteSyncApply').textContent = '确认同步';
    }
  }

  function install() {
    const actions = document.querySelector('.page-header .page-actions');
    if (!actions || $('websiteWatchSyncButton')) return;
    const button = document.createElement('button');
    button.className = 'button button-secondary';
    button.id = 'websiteWatchSyncButton';
    button.type = 'button';
    button.textContent = '同步 website-main';
    const save = $('watchersSaveButton');
    if (save) actions.insertBefore(button, save);
    else actions.appendChild(button);
    button.addEventListener('click', async () => {
      const element = dialog();
      if (!element.open) element.showModal();
      if (await status()) await refresh();
      else {
        $('websiteSyncSummary').textContent = '请先保存 website 私有仓库的只读 GitHub Token。';
        $('websiteSyncDiff').textContent = '尚未修改任何配置。';
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
