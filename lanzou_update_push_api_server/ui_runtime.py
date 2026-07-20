from __future__ import annotations

import re

from .ui_control import render_control_dashboard


_OPENAPI_FUNCTION = r'''async function loadOpenApi(notify=true){
  try{
    const results=await Promise.all([
      api('/admin/openapi/main'),
      api('/admin/openapi/lanzou')
    ]);
    const routes=[];
    const sources=[
      {data:results[0],service:'main'},
      {data:results[1],service:'lanzou'}
    ];
    for(const source of sources){
      const paths=(source.data.schema&&source.data.schema.paths)||{};
      for(const pathEntry of Object.entries(paths)){
        const path=pathEntry[0];
        const operations=pathEntry[1]||{};
        for(const operationEntry of Object.entries(operations)){
          const method=operationEntry[0];
          const operation=operationEntry[1]||{};
          if(!['get','post','put','patch','delete'].includes(method))continue;
          routes.push({
            service:source.service,
            path:path,
            method:method.toUpperCase(),
            summary:operation.summary||operation.operationId||'',
            parameters:operation.parameters||[],
            requestBody:operation.requestBody||null
          });
        }
      }
    }
    S.routes=routes.sort((a,b)=>(a.service+a.path+a.method).localeCompare(b.service+b.path+b.method));
    $('routeSelect').innerHTML=S.routes.map((route,index)=>
      `<option value="${index}">[${route.service}] ${route.method} ${esc(route.path)} · ${esc(route.summary)}</option>`
    ).join('');
    selectRoute();
    if(notify)toast(`已加载 ${S.routes.length} 个接口`);
  }catch(error){
    toast(error.message,true);
  }
}'''

_API_FUNCTION = r'''function currentAdminToken(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
function saveAdminToken(){
  const value=$('adminToken').value.trim();
  if(value)sessionStorage.setItem('lolapisevers_admin_token',value);
  else sessionStorage.removeItem('lolapisevers_admin_token');
  toast(value?'管理令牌已保存到当前浏览器会话':'已清除管理令牌');
  loadAll();
}
async function api(path,opt={}){
  const headers={'content-type':'application/json'};
  const token=currentAdminToken();
  if(token)headers['x-admin-token']=token;
  const response=await fetch(path,{
    method:opt.method||'GET',
    headers:headers,
    body:opt.body===undefined?undefined:JSON.stringify(opt.body)
  });
  const text=await response.text();
  let data;
  try{data=JSON.parse(text)}catch(error){data={ok:false,error:text}}
  if(!response.ok){
    if(response.status===401||response.status===403){
      toast(data.error||'控制台需要管理令牌',true);
    }
    throw new Error(data.error||text||response.statusText);
  }
  return data;
}'''

_TOKEN_CONTROLS = r'''<input id="adminToken" type="password" placeholder="管理令牌（本机可留空）" style="width:240px;max-width:100%"><button type="button" onclick="saveAdminToken()">应用令牌</button>'''

_SYSTEM_TAB = r'''    <button class="tab" data-tab="system">系统与安全</button>
'''

_SYSTEM_HTML = r'''
  <section id="tab-system" class="hidden">
    <div class="grid two">
      <div class="panel">
        <div class="panel-head"><div><h2>控制台安全</h2><div class="hint">未配置令牌时仅允许本机访问；配置后所有控制接口都要求令牌。</div></div></div>
        <div id="securitySummary" class="result">尚未读取</div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><h2>Windows 服务</h2><div class="hint">重启会短暂中断 5001 和 6178，监管脚本会重新拉起两个进程。</div></div><button type="button" class="warn" onclick="restartManagedService()">重启 LOLDataSystem</button></div>
        <div id="serviceSummary" class="result">尚未读取</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><div><h2>配置备份与回滚</h2><div class="hint">每次保存配置都会自动备份；回滚前还会再备份当前版本。</div></div><button type="button" onclick="loadSystemPanel()">刷新</button></div>
      <div class="table-wrap"><table><thead><tr><th>类型</th><th>备份文件</th><th>时间</th><th>大小</th><th>操作</th></tr></thead><tbody id="backupRows"></tbody></table></div>
    </div>
    <div class="panel">
      <div class="panel-head"><div><h2>操作审计</h2><div class="hint">仅记录时间、客户端、路径和结果，不记录密码、Token 或请求正文。</div></div></div>
      <div class="table-wrap"><table><thead><tr><th>时间</th><th>操作</th><th>客户端</th><th>请求</th><th>结果</th></tr></thead><tbody id="auditRows"></tbody></table></div>
    </div>
  </section>
'''

_SYSTEM_SCRIPT = r'''
async function safeApi(path,opt={}){try{return await api(path,opt)}catch(error){return {ok:false,error:error.message}}}
async function loadSystemPanel(){
  const results=await Promise.all([
    safeApi('/security/status'),
    safeApi('/admin/service/status'),
    safeApi('/admin/backups'),
    safeApi('/admin/audit?limit=100')
  ]);
  const security=results[0];
  const service=results[1];
  const backups=results[2];
  const audit=results[3];
  $('securitySummary').textContent=JSON.stringify(security,null,2);
  $('serviceSummary').textContent=JSON.stringify(service,null,2);
  const backupItems=backups.backups||[];
  $('backupRows').innerHTML=backupItems.map(item=>
    `<tr><td>${esc(item.kind)}</td><td>${esc(item.name)}</td><td>${esc(item.modified_at||'')}</td><td>${esc(item.size_bytes||0)}</td><td><button type="button" data-rollback="1" data-kind="${attr(item.kind)}" data-name="${attr(item.name)}">回滚</button></td></tr>`
  ).join('')||'<tr><td colspan="5" class="hint">暂无配置备份</td></tr>';
  document.querySelectorAll('[data-rollback]').forEach(button=>button.onclick=()=>rollbackBackup(button.dataset.kind,button.dataset.name));
  const auditItems=audit.events||[];
  $('auditRows').innerHTML=auditItems.map(item=>
    `<tr><td>${esc(item.at||'')}</td><td>${esc(item.action||'')}</td><td>${esc(item.client||'')}</td><td>${esc((item.method||'')+' '+(item.path||''))}</td><td><span class="status ${item.ok?'ok':'bad'}">${item.ok?'成功':'失败'}</span></td></tr>`
  ).join('')||'<tr><td colspan="5" class="hint">暂无审计记录或当前未授权</td></tr>';
}
async function rollbackBackup(kind,name){
  if(!confirm(`确认把 ${kind} 配置回滚到 ${name}？`))return;
  const result=await safeApi(`/admin/rollback/${encodeURIComponent(kind)}`,{method:'POST',body:{backup_name:name}});
  showAction('配置回滚结果',result);
  toast(result.ok?'回滚完成':'回滚失败：'+(result.error||'未知错误'),!result.ok);
  await loadSystemPanel();
}
async function restartManagedService(){
  if(!confirm('确认重启 LOLDataSystem？控制台连接会短暂中断。'))return;
  const result=await safeApi('/admin/service/restart',{method:'POST',body:{delay_seconds:3}});
  showAction('服务重启结果',result);
  toast(result.ok?'已安排服务重启':'重启失败：'+(result.error||'未知错误'),!result.ok);
}
'''

_ROW_INTERACTION_SCRIPT = r'''
function revealNewTableRow(tbodyId,focusSelector){
  requestAnimationFrame(()=>{
    const body=$(tbodyId);
    const row=body&&body.querySelector('tr');
    if(!row)return;
    row.style.background='#fff8e7';
    row.scrollIntoView({behavior:'smooth',block:'nearest'});
    const field=row.querySelector(focusSelector);
    if(field){field.focus();field.select()}
  });
}
function addWatcher(){
  if(!Array.isArray(S.watchers))S.watchers=[];
  const sequence=S.watchers.length+1;
  S.watchers.unshift({
    id:`watcher-${Date.now()}`,
    title:`新监控 ${sequence}`,
    url:'https://',
    password:'',
    enabled:true,
    max_pages:20
  });
  renderWatchers();
  revealNewTableRow('watcherRows','[data-f="id"]');
  toast('已新增监控项，请填写后点击“保存监控项”');
}
function addTarget(){
  if(!Array.isArray(S.targets))S.targets=[];
  S.targets.unshift({
    name:`target-${S.targets.length+1}`,
    enabled:true,
    url:'http://127.0.0.1:6108/',
    timeout_seconds:8,
    headers:{}
  });
  renderTargets();
  revealNewTableRow('targetRows','[data-f="name"]');
  toast('已新增通知目标，请填写后点击“保存通知目标”');
}
'''


def _replace_once(page: str, old: str, new: str, label: str) -> str:
    if old not in page:
        raise RuntimeError(f"could not patch dashboard {label}")
    return page.replace(old, new, 1)


def render_runtime_dashboard() -> str:
    page = render_control_dashboard()
    page, replacement_count = re.subn(
        r"async function loadOpenApi\(notify=true\)\{.*?\}\nfunction selectRoute",
        lambda _match: _OPENAPI_FUNCTION + "\nfunction selectRoute",
        page,
        count=1,
        flags=re.DOTALL,
    )
    if replacement_count != 1:
        raise RuntimeError("could not patch dashboard OpenAPI loader")

    page, api_replacement_count = re.subn(
        r"async function api\(path,opt=\{\}\)\{.*?\}\nfunction setState",
        lambda _match: _API_FUNCTION + "\nfunction setState",
        page,
        count=1,
        flags=re.DOTALL,
    )
    if api_replacement_count != 1:
        raise RuntimeError("could not patch dashboard API client")

    page, watcher_replacement_count = re.subn(
        r"function addWatcher\(\)\{.*?\}\nfunction collectWatchers",
        lambda _match: _ROW_INTERACTION_SCRIPT + "\nfunction collectWatchers",
        page,
        count=1,
        flags=re.DOTALL,
    )
    if watcher_replacement_count != 1:
        raise RuntimeError("could not patch dashboard watcher interaction")

    page, target_replacement_count = re.subn(
        r"function addTarget\(\)\{.*?\}\nfunction collectTargets",
        lambda _match: "function collectTargets",
        page,
        count=1,
        flags=re.DOTALL,
    )
    if target_replacement_count != 1:
        raise RuntimeError("could not remove legacy target interaction")

    page = _replace_once(
        page,
        '<div class="actions"><button class="primary" onclick="loadAll()">刷新全部</button>',
        '<div class="actions">' + _TOKEN_CONTROLS + '<button type="button" class="primary" onclick="loadAll()">刷新全部</button>',
        "token controls",
    )
    page = _replace_once(
        page,
        '<button onclick="addWatcher()">新增监控</button>',
        '<button id="addWatcherButton" type="button">新增监控</button>',
        "watcher add button",
    )
    page = _replace_once(
        page,
        '<button onclick="addTarget()">新增目标</button>',
        '<button id="addTargetButton" type="button">新增目标</button>',
        "target add button",
    )
    page = _replace_once(page, "  </nav>", _SYSTEM_TAB + "  </nav>", "system tab")
    page = _replace_once(page, "</main>", _SYSTEM_HTML + "</main>", "system panel")
    page = _replace_once(
        page,
        "document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('[id^=\"tab-\"]').forEach(x=>x.classList.add('hidden'));$(`tab-${btn.dataset.tab}`).classList.remove('hidden')}));",
        "document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('[id^=\"tab-\"]').forEach(x=>x.classList.add('hidden'));$(`tab-${btn.dataset.tab}`).classList.remove('hidden');if(btn.dataset.tab==='system')loadSystemPanel()}));",
        "system tab handler",
    )
    page = _replace_once(
        page,
        "loadAll();setInterval(()=>loadAll(),30000);",
        _SYSTEM_SCRIPT
        + "\n$('adminToken').value=currentAdminToken();"
        + "\n$('addWatcherButton').addEventListener('click',addWatcher);"
        + "\n$('addTargetButton').addEventListener('click',addTarget);"
        + "\nloadAll();setInterval(()=>{const active=document.querySelector('.tab.active');if(active&&active.dataset.tab==='overview')loadAll()},30000);",
        "runtime startup",
    )
    page = page.replace(
        "<title>lolapisevers 全功能控制台</title>",
        "<title>lolapisevers 接口端总控台 · 全功能控制台</title>",
        1,
    )
    return page
