(() => {
  'use strict';

  if (document.body?.dataset?.consoleUi !== 'watchers') return;

  const TOKEN_KEY = 'lolapisevers_admin_token';
  const SOURCE_REPO = 'xianyumht-cmd/website';
  const SOURCE_BRANCH = 'source';
  const ENTRY_PATH = 'src/pages/nav/entry.js';
  const BASE_DATA_PATH = 'src/assets/data/nav-data.json';
  const NAV_DIR = 'src/pages/nav';
  const STRING_TOKEN = String.raw`(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')`;
  const MONITOR_HOST_ALIASES = new Set(['b-bu.cn']);

  const $ = (id) => document.getElementById(id);

  function toast(message, kind = 'info') {
    const region = $('toastRegion');
    if (!region) return;
    const node = document.createElement('div');
    node.className = `toast toast-${kind}`;
    node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(() => node.remove(), 5200);
  }

  function adminToken() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (_error) { return ''; }
  }

  async function localApi(path, options = {}) {
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
    try { data = JSON.parse(raw); } catch (_error) { data = { ok: false, detail: raw || response.statusText }; }
    if (!response.ok || data?.ok === false) {
      throw new Error(data?.detail || data?.error || `HTTP ${response.status}`);
    }
    return data;
  }

  async function fetchText(url) {
    const response = await fetch(url, {
      headers: { accept: 'text/plain,application/json;q=0.9,*/*;q=0.8' },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`读取 website-main 失败：HTTP ${response.status}`);
    return response.text();
  }

  async function fetchJson(url) {
    const text = await fetchText(url);
    try { return JSON.parse(text); }
    catch (_error) { throw new Error('website-main 返回了无效 JSON'); }
  }

  function decodeJsString(token) {
    const text = String(token || '').trim();
    if (text.length < 2) return text;
    const quote = text[0];
    let body = text.slice(1, -1);
    body = body.replace(/\\u([0-9a-fA-F]{4})/g, (_m, hex) => String.fromCharCode(parseInt(hex, 16)));
    body = body.replace(/\\x([0-9a-fA-F]{2})/g, (_m, hex) => String.fromCharCode(parseInt(hex, 16)));
    body = body.replace(/\\n/g, '\n').replace(/\\r/g, '\r').replace(/\\t/g, '\t');
    body = body.replace(/\\\\/g, '\\');
    if (quote === '"') body = body.replace(/\\"/g, '"');
    if (quote === "'") body = body.replace(/\\'/g, "'");
    return body;
  }

  function resolveImport(basePath, relativePath) {
    if (!relativePath.startsWith('.')) return '';
    const parts = basePath.split('/');
    parts.pop();
    for (const part of relativePath.split('/')) {
      if (!part || part === '.') continue;
      if (part === '..') parts.pop();
      else parts.push(part);
    }
    return parts.join('/');
  }

  function extractImports(entrySource) {
    const result = [];
    const re = /import\s+(?:[^'";]+?\s+from\s+)?['"]([^'"]+)['"];?/g;
    let match;
    while ((match = re.exec(entrySource)) !== null) {
      const path = resolveImport(ENTRY_PATH, match[1]);
      if (path.startsWith(`${NAV_DIR}/`) && path.endsWith('.js')) result.push(path);
    }
    return [...new Set(result)];
  }

  function matchingBracket(source, openIndex, openChar = '[', closeChar = ']') {
    let depth = 0;
    let quote = '';
    let escaped = false;
    for (let i = openIndex; i < source.length; i += 1) {
      const ch = source[i];
      if (quote) {
        if (escaped) escaped = false;
        else if (ch === '\\') escaped = true;
        else if (ch === quote) quote = '';
        continue;
      }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === openChar) depth += 1;
      else if (ch === closeChar) {
        depth -= 1;
        if (depth === 0) return i;
      }
    }
    return -1;
  }

  function parseMakeItems(source) {
    const re = new RegExp(`makeItem\\(\\s*(${STRING_TOKEN})\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*(${STRING_TOKEN})(?:\\s*,\\s*(${STRING_TOKEN}))?\\s*\\)`, 'gs');
    const result = [];
    let match;
    while ((match = re.exec(source)) !== null) {
      result.push({
        title: decodeJsString(match[1]),
        description: decodeJsString(match[2]),
        url: decodeJsString(match[3]),
        avatar: decodeJsString(match[4]),
        tooltip: match[5] ? decodeJsString(match[5]) : decodeJsString(match[1]),
      });
    }
    return result;
  }

  function parseObjectItems(source) {
    const items = [];
    const objectRe = /\{([^{}]*)\}/gs;
    let objectMatch;
    while ((objectMatch = objectRe.exec(source)) !== null) {
      const body = objectMatch[1];
      const read = (key) => {
        const re = new RegExp(`${key}\\s*:\\s*(${STRING_TOKEN})`, 's');
        const match = re.exec(body);
        return match ? decodeJsString(match[1]) : '';
      };
      const title = read('title');
      const url = read('url');
      if (!title || !url) continue;
      items.push({
        title,
        description: read('description'),
        url,
        avatar: read('avatar') || title.slice(0, 1),
        tooltip: read('tooltip') || title,
      });
    }
    return items;
  }

  function parseArrayByVariable(source, variableName) {
    const re = new RegExp(`(?:const|let|var)\\s+${variableName}\\s*=\\s*\\[`, 'm');
    const match = re.exec(source);
    if (!match) return [];
    const openIndex = source.indexOf('[', match.index);
    const closeIndex = matchingBracket(source, openIndex);
    if (closeIndex < 0) return [];
    const body = source.slice(openIndex + 1, closeIndex);
    const makeItems = parseMakeItems(body);
    return makeItems.length ? makeItems : parseObjectItems(body);
  }

  function sectionByName(sections, name) {
    return sections.find((section) => section && (section.id === name || section.title === name));
  }

  function upsertSection(sections, id, title, icon, items) {
    let section = sectionByName(sections, id) || sectionByName(sections, title);
    if (!section) {
      section = { id, title, icon, items: [] };
      sections.push(section);
    }
    section.id = id;
    section.title = title;
    section.icon = icon;
    section.items = items.map((item) => ({ ...item }));
  }

  function parseUpsertSections(source, sections) {
    const prefix = new RegExp(`upsertSection\\(\\s*sections\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*\\[`, 'gs');
    let match;
    while ((match = prefix.exec(source)) !== null) {
      const openIndex = source.indexOf('[', match.index);
      const closeIndex = matchingBracket(source, openIndex);
      if (closeIndex < 0) throw new Error('website-main upsertSection 数组无法解析');
      const items = parseMakeItems(source.slice(openIndex + 1, closeIndex));
      upsertSection(sections, decodeJsString(match[1]), decodeJsString(match[2]), decodeJsString(match[3]), items);
      prefix.lastIndex = closeIndex + 1;
    }

    const hidePrefix = new RegExp(`upsertHideAndSeekSection\\(\\s*sections\\s*,\\s*(${STRING_TOKEN})\\s*,\\s*\\[`, 'gs');
    while ((match = hidePrefix.exec(source)) !== null) {
      const openIndex = source.indexOf('[', match.index);
      const closeIndex = matchingBracket(source, openIndex);
      if (closeIndex < 0) throw new Error('website-main 躲猫猫专区数组无法解析');
      const items = parseMakeItems(source.slice(openIndex + 1, closeIndex));
      upsertSection(sections, '躲猫猫专区', decodeJsString(match[1]), 'fa fa-puzzle-piece', items);
      hidePrefix.lastIndex = closeIndex + 1;
    }
  }

  function applyGsPatch(source, sections) {
    if (!source.includes('gsSection')) return;
    const gs = sectionByName(sections, 'GS专区') || sectionByName(sections, 'GS Zone') || sectionByName(sections, '足本专区');
    if (!gs) return;
    const idMatch = new RegExp(`gsSection\\.id\\s*=\\s*(${STRING_TOKEN})`).exec(source);
    const titleMatch = new RegExp(`gsSection\\.title\\s*=\\s*(${STRING_TOKEN})`).exec(source);
    if (idMatch) gs.id = decodeJsString(idMatch[1]);
    if (titleMatch) gs.title = decodeJsString(titleMatch[1]);
    const pushIndex = source.indexOf('gsSection.items.push(makeItem(');
    if (pushIndex >= 0) {
      const end = source.indexOf('));', pushIndex);
      const items = parseMakeItems(source.slice(pushIndex, end > pushIndex ? end + 2 : source.length));
      for (const item of items) {
        if (!gs.items.some((current) => current.title === item.title)) gs.items.push(item);
      }
    }
  }

  function candidateSectionNames(source) {
    const result = [];
    const re = new RegExp(`(?:section|candidate)\\.(?:id|title)\\s*===\\s*(${STRING_TOKEN})`, 'g');
    let match;
    while ((match = re.exec(source)) !== null) {
      const value = decodeJsString(match[1]);
      if (/[\u3400-\u9fff]/.test(value) && !result.includes(value)) result.push(value);
    }
    return result;
  }

  function applyReplacementPatch(source, sections) {
    if (!source.includes('translations.zh') || !/\.items\s*=/.test(source)) return false;
    const sectionNames = candidateSectionNames(source);
    if (!sectionNames.length) return false;

    const variableNames = [];
    const declRe = /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[/g;
    let match;
    while ((match = declRe.exec(source)) !== null) variableNames.push(match[1]);
    const preferred = variableNames.sort((a, b) => {
      const score = (name) => (name === 'zhItems' ? 0 : name === 'weeklyItems' ? 1 : 2);
      return score(a) - score(b);
    });
    for (const name of preferred) {
      const items = parseArrayByVariable(source, name);
      if (!items.length) continue;
      const section = sectionNames.map((value) => sectionByName(sections, value)).find(Boolean);
      if (!section) return false;
      section.items = items.map((item) => ({ ...item }));
      return true;
    }
    return false;
  }

  function applyHePatch(source, sections) {
    if (!source.includes('isLegacyEzs') && !source.includes('replacementUrl')) return;
    const match = new RegExp(`replacementUrl\\s*=\\s*(${STRING_TOKEN})`).exec(source);
    if (!match) return;
    const replacementUrl = decodeJsString(match[1]);
    for (const section of sections) {
      for (const item of Array.isArray(section?.items) ? section.items : []) {
        const title = String(item.title || '').toLowerCase();
        const tooltip = String(item.tooltip || '').toLowerCase();
        if (title === 'ezs' || tooltip === 'ezs' || item.url === 'https://wwme.lanzouq.com/s/ezs6') {
          item.title = 'HE';
          item.avatar = 'HE';
          item.url = replacementUrl;
          item.tooltip = 'HE';
        }
      }
    }
  }

  function applyConfirmedFixes(source, sections) {
    if (!source.includes('markSpiritAsDisplayOnly')) return;
    for (const section of sections) {
      for (const item of Array.isArray(section?.items) ? section.items : []) {
        if (String(item.title || '').trim().toLowerCase() === 'spirit') {
          item.url = '';
          item.displayOnly = true;
        }
      }
    }
  }

  function monitorableUrl(value) {
    try {
      const url = new URL(String(value || '').trim());
      const host = url.hostname.toLowerCase();
      return url.protocol === 'http:' || url.protocol === 'https:'
        ? host.includes('lanzou') || host.endsWith('lanzn.com') || host.endsWith('lanwp.com') || MONITOR_HOST_ALIASES.has(host)
        : false;
    } catch (_error) { return false; }
  }

  function passwordFromDescription(value) {
    const match = /(?:密码|提取码)\s*[:：]?\s*([A-Za-z0-9._-]+)/i.exec(String(value || ''));
    return match ? match[1] : '';
  }

  function normalizedUrl(value) {
    const url = new URL(String(value || '').trim());
    const path = url.pathname.replace(/\/+$/, '') || '/';
    return `${url.protocol.toLowerCase()}//${url.host.toLowerCase()}${path}${url.search}`;
  }

  function finalTargets(baseData, orderedSources) {
    const sections = JSON.parse(JSON.stringify(baseData?.zh?.sections || []));
    if (!Array.isArray(sections) || !sections.length) throw new Error('website-main 中文导航数据为空');

    for (const { path, source } of orderedSources) {
      const file = path.split('/').pop();
      if (file === 'nav-patches.js') {
        applyGsPatch(source, sections);
        parseUpsertSections(source, sections);
      } else if (file === 'he-patch.js') {
        applyHePatch(source, sections);
      } else if (file === 'nav-confirmed-fixes.js') {
        applyConfirmedFixes(source, sections);
      } else {
        applyReplacementPatch(source, sections);
        parseUpsertSections(source, sections);
      }
    }

    const byUrl = new Map();
    for (const section of sections) {
      for (const item of Array.isArray(section?.items) ? section.items : []) {
        if (!monitorableUrl(item.url) || item.displayOnly) continue;
        const url = String(item.url).trim();
        byUrl.set(normalizedUrl(url), {
          title: String(item.title || '').trim() || '未命名监控',
          url,
          password: passwordFromDescription(item.description),
          section: String(section.title || section.id || '').trim(),
        });
      }
    }
    const targets = [...byUrl.values()];
    if (targets.length < 10) throw new Error(`website-main 解析结果异常：仅得到 ${targets.length} 个监控目标，已拒绝同步`);
    return targets;
  }

  async function loadWebsiteManifest() {
    const branch = await fetchJson(`https://api.github.com/repos/${SOURCE_REPO}/branches/${SOURCE_BRANCH}`);
    const sha = String(branch?.commit?.sha || '').trim();
    if (!/^[0-9a-f]{40}$/i.test(sha)) throw new Error('无法取得 website-main source 提交 SHA');
    const rawBase = `https://raw.githubusercontent.com/${SOURCE_REPO}/${sha}`;
    const [entrySource, baseData] = await Promise.all([
      fetchText(`${rawBase}/${ENTRY_PATH}`),
      fetchJson(`${rawBase}/${BASE_DATA_PATH}`),
    ]);
    const imports = extractImports(entrySource);
    if (!imports.length) throw new Error('website-main entry.js 没有发现导航补丁');
    const orderedSources = await Promise.all(imports.map(async (path) => ({ path, source: await fetchText(`${rawBase}/${path}`) })));
    const targets = finalTargets(baseData, orderedSources);
    return { sha, imports, targets };
  }

  function fnv1a(value) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16).padStart(8, '0');
  }

  function buildSync(current, manifest) {
    const old = Array.isArray(current) ? current : [];
    const byUrl = new Map(old.filter((item) => item?.url).map((item) => [normalizedUrl(item.url), item]));
    const usedIds = new Set(old.map((item) => String(item?.id || '').trim()).filter(Boolean));
    const next = [];
    const added = [];
    const updated = [];
    const targetUrls = new Set(manifest.targets.map((item) => normalizedUrl(item.url)));

    for (const target of manifest.targets) {
      const key = normalizedUrl(target.url);
      const previous = byUrl.get(key);
      let id;
      let enabled = true;
      let maxPages = 20;
      if (previous) {
        id = String(previous.id || '').trim();
        enabled = previous.enabled !== false;
        maxPages = Math.max(1, Math.min(100, Number(previous.max_pages || 20) || 20));
      } else {
        const base = `nav-${fnv1a(key)}`;
        id = base;
        let suffix = 2;
        while (usedIds.has(id)) id = `${base}-${suffix++}`;
        added.push(target);
      }
      usedIds.add(id);

      const item = {
        id,
        title: target.title,
        url: target.url,
        password: target.password || '',
        enabled,
        max_pages: maxPages,
      };
      if (previous && !target.password && previous.password_configured) item.clear_password = true;

      if (previous) {
        const changed = String(previous.title || '') !== target.title
          || Boolean(previous.password_configured) !== Boolean(target.password);
        if (changed) updated.push({ before: previous, after: target });
      }
      next.push(item);
    }

    const removed = old.filter((item) => item?.url && !targetUrls.has(normalizedUrl(item.url)));
    return { next, added, updated, removed, before: old.length, after: next.length };
  }

  function ensureDialog() {
    if ($('websiteWatchSyncDialog')) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'dialog dialog-wide';
    dialog.id = 'websiteWatchSyncDialog';
    dialog.innerHTML = `
      <div class="dialog-card">
        <header class="dialog-header">
          <div><p class="eyebrow">WEBSITE-MAIN · 实时同步</p><h2>同步蓝奏监控目标</h2></div>
          <button class="icon-button" id="websiteWatchSyncClose" type="button" aria-label="关闭">×</button>
        </header>
        <div class="dialog-body">
          <p class="dialog-description" id="websiteWatchSyncSummary">正在读取 website-main…</p>
          <div class="alert alert-warning" id="websiteWatchSyncWarning">只同步监控目标；扫描间隔、Provider、通知目标和 SnowLuma 回调均保持不变。应用前由后端自动备份 config.json。</div>
          <pre class="operations-result configuration-result" id="websiteWatchSyncDiff">等待检查</pre>
        </div>
        <footer class="dialog-footer">
          <span class="dialog-footer-spacer"></span>
          <button class="button button-secondary" id="websiteWatchSyncCancel" type="button">取消</button>
          <button class="button button-primary" id="websiteWatchSyncApply" type="button" disabled>确认同步</button>
        </footer>
      </div>`;
    document.body.appendChild(dialog);
    const close = () => { if (dialog.open) dialog.close(); };
    $('websiteWatchSyncClose')?.addEventListener('click', close);
    $('websiteWatchSyncCancel')?.addEventListener('click', close);
  }

  function formatDiff(manifest, diff) {
    const lines = [
      `website-main source: ${manifest.sha}`,
      `监控目标: ${diff.before} → ${diff.after}`,
      `新增: ${diff.added.length}  删除: ${diff.removed.length}  更新: ${diff.updated.length}`,
      '',
    ];
    if (diff.added.length) {
      lines.push('【新增】');
      diff.added.forEach((item) => lines.push(`+ ${item.title}  ${item.url}`));
      lines.push('');
    }
    if (diff.removed.length) {
      lines.push('【删除】');
      diff.removed.forEach((item) => lines.push(`- ${item.title || item.id}  ${item.url}`));
      lines.push('');
    }
    if (diff.updated.length) {
      lines.push('【更新】');
      diff.updated.forEach((item) => lines.push(`~ ${item.before.title || item.before.id} → ${item.after.title}`));
      lines.push('');
    }
    if (!diff.added.length && !diff.removed.length && !diff.updated.length) lines.push('当前监控目标已经与 website-main 一致。');
    return lines.join('\n');
  }

  let pending = null;

  async function previewSync() {
    ensureDialog();
    const dialog = $('websiteWatchSyncDialog');
    const summary = $('websiteWatchSyncSummary');
    const output = $('websiteWatchSyncDiff');
    const apply = $('websiteWatchSyncApply');
    pending = null;
    if (summary) summary.textContent = '正在读取 website-main/source 当前提交与最终导航补丁…';
    if (output) output.textContent = '读取中…';
    if (apply) apply.disabled = true;
    if (typeof dialog?.showModal === 'function' && !dialog.open) dialog.showModal();

    try {
      const [manifest, configPayload] = await Promise.all([
        loadWebsiteManifest(),
        localApi('/admin/lanzou-config'),
      ]);
      const current = configPayload?.config?.watchers || [];
      const diff = buildSync(current, manifest);
      pending = { manifest, diff };
      if (summary) summary.textContent = `已按 website-main/source @ ${manifest.sha.slice(0, 12)} 计算最终导航，共 ${manifest.targets.length} 个可监控目标。`;
      if (output) output.textContent = formatDiff(manifest, diff);
      if (apply) apply.disabled = !diff.added.length && !diff.removed.length && !diff.updated.length;
    } catch (error) {
      if (summary) summary.textContent = '检查失败，未修改任何配置。';
      if (output) output.textContent = String(error?.message || error);
      toast(`同步检查失败：${error?.message || error}`, 'error');
    }
  }

  async function applySync() {
    if (!pending) return;
    const button = $('websiteWatchSyncApply');
    const output = $('websiteWatchSyncDiff');
    if (button) { button.disabled = true; button.textContent = '同步中…'; }
    try {
      const result = await localApi('/admin/lanzou-config', {
        method: 'POST',
        body: { watchers: pending.diff.next },
      });
      if (output) output.textContent += `\n\n同步成功。\n备份：${result.backup_path || '已由后端处理'}\n运行态：已热更新`;
      toast('website-main 监控目标已同步并热更新', 'success');
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      if (output) output.textContent += `\n\n同步失败：${error?.message || error}`;
      toast(`同步失败：${error?.message || error}`, 'error');
      if (button) { button.disabled = false; button.textContent = '确认同步'; }
    }
  }

  function installButton() {
    const actions = document.querySelector('.page-header .page-actions');
    if (!actions || $('websiteWatchSyncButton')) return;
    const button = document.createElement('button');
    button.className = 'button button-secondary';
    button.id = 'websiteWatchSyncButton';
    button.type = 'button';
    button.innerHTML = '<span>同步 website-main</span>';
    const saveButton = $('watchersSaveButton');
    if (saveButton) actions.insertBefore(button, saveButton);
    else actions.appendChild(button);
    button.addEventListener('click', previewSync);
    ensureDialog();
    $('websiteWatchSyncApply')?.addEventListener('click', applySync);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installButton, { once: true });
  else installButton();
})();
