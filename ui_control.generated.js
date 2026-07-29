
const S={overview:null,mainConfig:null,lanzou:{},watchers:[],targets:[],events:[],logs:[],routes:[],diagnostics:[]};
const $=id=>document.getElementById(id);
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function attr(v){return esc(v)}
function toast(msg,err=false){const t=$('toast');t.textContent=msg;t.className='toast'+(err?' err':'');t.style.display='block';clearTimeout(t._timer);t._timer=setTimeout(()=>t.style.display='none',4500)}
function currentAdminToken(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
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
}
function setState(id,ok,good,bad,sub=''){const e=$(id);e.textContent=ok?good:bad;e.className='value '+(ok?'ok':'bad');const s=$('s'+id.slice(1));if(s)s.textContent=sub}
function showAction(title,data){$('actionHint').textContent=title;$('actionResult').textContent=typeof data==='string'?data:JSON.stringify(data,null,2)}
function parseJson(id,fallback={}){const raw=$(id).value.trim();if(!raw)return fallback;try{return JSON.parse(raw)}catch(e){throw new Error(`${id} JSON 格式错误：${e.message}`)}}
function clone(v){return JSON.parse(JSON.stringify(v||null))}

async function loadAll(){try{const [overview,main,lanzou,watchers,events,logs,diag]=await Promise.all([api('/admin/overview'),api('/admin/main-config'),api('/admin/lanzou-config'),api('/watchers'),api('/events?limit=40'),api('/admin/logs'),api('/admin/diagnostics')]);S.overview=overview;S.mainConfig=main;S.lanzou=lanzou.config||{};S.watchers=clone(S.lanzou.watchers||watchers.watchers||[])||[];S.targets=clone(S.lanzou.notify_targets||[])||[];S.events=events.events||[];S.logs=logs.logs||[];S.diagnostics=diag.items||[];renderAll();await loadOpenApi(false);toast('全部状态已刷新')}catch(e){toast(e.message,true)}}
function renderAll(){renderCards();renderOverview();renderMainConfig();fillLanzou();renderWatchers();renderTargets();renderEvents();renderLogOptions();renderDiagnostics()}
function renderCards(){const o=S.overview||{},mh=o.mainApi?.health||{},lh=o.lanzou?.health||{},p=o.plugin||{},sr=lh.state_recovery||{};setState('cMain',mh.ready===true,'就绪','降级',o.mainApi?.baseUrl||'-');setState('cMysql',mh.mysql==='up','正常','异常',mh.mysql_error||'数据库连接');setState('cSo1',mh.so1_browser==='up','在线','离线',`并发 ${mh.so1_max_concurrent_pages||0}`);setState('cLanzou',lh.running===true,'运行中','未运行',`${lh.enabled_watcher_count||0}/${lh.watcher_count||0} 个启用`);setState('cPlugin',p.ok===true,'已连接','未连接',p.url||p.error||'-');const recovered=sr.action==='recovered',valid=['valid','missing'].includes(sr.action);const e=$('cState');e.textContent=recovered?'已恢复':valid?'正常':'未知';e.className='value '+(recovered?'warntext':valid?'ok':'bad');$('sState').textContent=recovered?(sr.backup_path||'已备份损坏文件'):(sr.path||'-');$('subtitle').textContent=`配置：${o.configPath||'-'} · 自动刷新 30 秒`}
function renderOverview(){const o=S.overview||{},c=o.lanzou?.config||{},p=o.plugin||{},rows=[['项目目录',o.projectRoot],['主接口',o.mainApi?.baseUrl],['蓝奏接口',o.lanzou?.baseUrl],['蓝奏配置',o.configPath],['状态文件',c.state_path],['插件状态地址',p.url],['插件账号',p.data?.botId||'-'],['通知目标',String((S.targets||[]).length)],['扫描策略',`每轮 ${c.scan_interval_seconds||0}s，每批 ${c.scan_batch_size||0}，等待 ${c.scan_batch_pause_seconds||0}s`]];$('overviewKv').innerHTML=rows.map(r=>`<div class="diag"><strong>${esc(r[0])}</strong><span></span><span>${esc(r[1]||'-')}</span></div>`).join('')}
function renderEvents(){$('eventCount').textContent=`${S.events.length} 条`;$('events').innerHTML=S.events.slice(0,20).map(ev=>`<div class="event"><strong>${esc(ev.title||ev.name||ev.watcher_id)}</strong><div class="hint">${esc(ev.created_at||'')} · ${esc(ev.provider||'')} · ${esc((ev.notify_results||[]).map(x=>`${x.target}:${x.ok?'ok':'failed'}`).join(' '))}</div><div>${esc(ev.message||'')}</div></div>`).join('')||'<div class="hint">暂无事件</div>'}

function renderMainConfig(){const fields=S.mainConfig?.fields||[],groups={};fields.forEach(f=>(groups[f.section]??=[]).push(f));let html='';Object.entries(groups).forEach(([section,list])=>{html+=`<div class="section-title">${esc(section)}</div><div class="grid three">`;list.forEach(f=>{const id=`mc_${f.key}`;if(f.type==='bool'){html+=`<label class="switch"><span>${esc(f.label)}<small class="hint"> ${esc(f.key)}</small></span><input id="${id}" data-key="${attr(f.key)}" data-type="bool" type="checkbox" ${f.value?'checked':''}></label>`}else{const type=f.type==='secret'?'password':f.type==='int'?'number':'text';const placeholder=f.type==='secret'?(f.configured?'已配置，留空不改':'未配置') : '';html+=`<label class="field"><span>${esc(f.label)} · ${esc(f.key)}</span><input id="${id}" data-key="${attr(f.key)}" data-type="${attr(f.type)}" type="${type}" value="${f.type==='secret'?'':attr(f.value)}" placeholder="${attr(placeholder)}" ${f.min!==undefined?`min="${f.min}"`:''} ${f.max!==undefined?`max="${f.max}"`:''}></label>`}});html+='</div>'});$('mainConfigForm').innerHTML=html}
async function saveMainConfig(){try{const patch={};document.querySelectorAll('#mainConfigForm [data-key]').forEach(el=>{const key=el.dataset.key,type=el.dataset.type;if(type==='bool')patch[key]=el.checked;else if(type==='secret'){if(el.value.trim())patch[key]=el.value}else patch[key]=el.value});const d=await api('/admin/main-config',{method:'POST',body:patch});S.mainConfig=d.config;renderMainConfig();showAction('主接口配置已保存',d);toast('已保存，重启 LOLDataSystem 后生效')}catch(e){toast(e.message,true)}}

function fillLanzou(){const c=S.lanzou||{};$('lzHost').value=c.host||'127.0.0.1';$('lzPort').value=c.port||6178;$('lzInterval').value=c.scan_interval_seconds??300;$('lzBatch').value=c.scan_batch_size??0;$('lzPause').value=c.scan_batch_pause_seconds??0;$('lzProviders').value=(c.provider_order||[]).join(', ');$('lzStatePath').value=c.state_path||'lanzou_update_push_api_server/state.json';$('lzScanStart').checked=c.scan_on_start!==false;$('lzWerEndpoint').value=c.wer_api_endpoint||'';$('lzWerMethod').value=c.wer_api_method||'GET';$('lzWerUrlParam').value=c.wer_api_url_param||'url';$('lzWerPwdParam').value=c.wer_api_password_param||'pwd';$('lzWerKey').value='';$('lzWerKey').placeholder=c.wer_api_key?'已配置，留空不改':'未配置';$('lzTemplate').value=c.notification_template||'hello，{title}网盘检测到更新'}
async function saveLanzouGlobal(){try{const patch={host:$('lzHost').value,port:Number($('lzPort').value),scan_interval_seconds:Number($('lzInterval').value),scan_batch_size:Number($('lzBatch').value),scan_batch_pause_seconds:Number($('lzPause').value),scan_on_start:$('lzScanStart').checked,provider_order:$('lzProviders').value.split(',').map(x=>x.trim()).filter(Boolean),state_path:$('lzStatePath').value,wer_api_endpoint:$('lzWerEndpoint').value,wer_api_method:$('lzWerMethod').value,wer_api_url_param:$('lzWerUrlParam').value,wer_api_password_param:$('lzWerPwdParam').value,notification_template:$('lzTemplate').value};if($('lzWerKey').value.trim())patch.wer_api_key=$('lzWerKey').value.trim();const d=await api('/admin/lanzou-config',{method:'POST',body:patch});await reloadLanzou();showAction('蓝奏全局配置已保存',d);toast(d.message||'已保存')}catch(e){toast(e.message,true)}}
async function reloadLanzou(){const d=await api('/admin/lanzou-config');S.lanzou=d.config||{};S.watchers=clone(S.lanzou.watchers||[])||[];S.targets=clone(S.lanzou.notify_targets||[])||[];fillLanzou();renderWatchers();renderTargets()}


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

function collectWatchers(){return [...document.querySelectorAll('#watcherRows tr')].map(row=>({enabled:row.querySelector('[data-f="enabled"]').checked,id:row.querySelector('[data-f="id"]').value.trim(),title:row.querySelector('[data-f="title"]').value.trim(),url:row.querySelector('[data-f="url"]').value.trim(),password:row.querySelector('[data-f="password"]').value.trim(),max_pages:Number(row.querySelector('[data-f="max_pages"]').value)||20}))}
function renderWatchers(){$('watcherRows').innerHTML=S.watchers.map((w,i)=>{const live=(S.overview?.lanzou?.health?.last_scan||{})[w.id]||{},status=!live.at?'暂无':live.ok?(live.notification_pending?'待推送':'成功'):'失败';return `<tr><td><input data-f="enabled" type="checkbox" ${w.enabled!==false?'checked':''}></td><td><input data-f="id" value="${attr(w.id)}"></td><td><input data-f="title" value="${attr(w.title||'')}"></td><td><input data-f="url" value="${attr(w.url||'')}"></td><td><input data-f="password" value="${attr(w.password||'')}"></td><td><input data-f="max_pages" type="number" min="1" max="100" value="${attr(w.max_pages||20)}"></td><td><span class="status ${live.ok?(live.notification_pending?'warntext':'ok'):live.at?'bad':''}">${esc(status)}</span><div class="hint">${esc(live.error||live.provider||'')}</div></td><td><div class="toolbar"><button onclick="scanWatcher(${i})">扫描</button><button onclick="testWatcher(${i})">推送</button><button onclick="showFiles(${i})">文件</button><button class="danger" onclick="removeWatcher(${i})">删除</button></div></td></tr>`}).join('')||'<tr><td colspan="8" class="hint">暂无监控项</td></tr>'}
function removeWatcher(i){S.watchers.splice(i,1);renderWatchers()}
async function saveWatchers(){try{S.watchers=collectWatchers();const d=await api('/admin/lanzou-config',{method:'POST',body:{watchers:S.watchers}});await reloadLanzou();showAction('监控项已保存',d);toast('监控项已保存')}catch(e){toast(e.message,true)}}
async function scanWatcher(i){try{const id=collectWatchers()[i].id;const d=await api(`/scan?watcher_id=${encodeURIComponent(id)}&notify=false`,{method:'POST'});showAction(`扫描 ${id}`,d);toast('扫描完成');await loadAll()}catch(e){toast(e.message,true)}}
async function testWatcher(i){try{const id=collectWatchers()[i].id;const d=await api(`/notify/test?watcher_id=${encodeURIComponent(id)}`,{method:'POST'});showAction(`测试推送 ${id}`,d);toast('测试推送完成')}catch(e){toast(e.message,true)}}
async function showFiles(i){try{const id=collectWatchers()[i].id;const d=await api(`/files/${encodeURIComponent(id)}`);showAction(`文件快照 ${id}`,d);document.querySelector('[data-tab="diagnostics"]').click()}catch(e){toast(e.message,true)}}


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

function collectTargets(){return [...document.querySelectorAll('#targetRows tr')].map(row=>({enabled:row.querySelector('[data-f="enabled"]').checked,name:row.querySelector('[data-f="name"]').value.trim(),url:row.querySelector('[data-f="url"]').value.trim(),timeout_seconds:Number(row.querySelector('[data-f="timeout"]').value)||8,headers:JSON.parse(row.querySelector('[data-f="headers"]').value||'{}')}))}
function renderTargets(){$('targetRows').innerHTML=S.targets.map((t,i)=>`<tr><td><input data-f="enabled" type="checkbox" ${t.enabled!==false?'checked':''}></td><td><input data-f="name" value="${attr(t.name||'')}"></td><td><input data-f="url" value="${attr(t.url||'')}"></td><td><input data-f="timeout" type="number" min="0.1" max="120" step="0.1" value="${attr(t.timeout_seconds||8)}"></td><td><textarea data-f="headers">${esc(JSON.stringify(t.headers||{},null,2))}</textarea></td><td><button class="danger" onclick="removeTarget(${i})">删除</button></td></tr>`).join('')||'<tr><td colspan="6" class="hint">暂无通知目标</td></tr>'}
function removeTarget(i){S.targets.splice(i,1);renderTargets()}
async function saveTargets(){try{S.targets=collectTargets();const d=await api('/admin/lanzou-config',{method:'POST',body:{notify_targets:S.targets}});await reloadLanzou();showAction('通知目标已保存',d);toast('通知目标已保存')}catch(e){toast(e.message,true)}}
async function sendTestPush(){try{const d=await api('/notify/test',{method:'POST'});showAction('全局测试推送',d);toast('测试推送完成')}catch(e){toast(e.message,true)}}

async function loadOpenApi(notify=true){
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
}
function selectRoute(){const r=S.routes[Number($('routeSelect').value)||0];if(!r){$('routeHint').textContent='没有可用接口';return}const q={};(r.parameters||[]).filter(p=>p.in==='query').forEach(p=>{const s=p.schema||{};q[p.name]=s.default??(p.required?`<${p.name}>`:'')});$('invokeQuery').value=JSON.stringify(q,null,2);$('invokeBody').value=r.requestBody?'{}':'{}';$('routeHint').textContent=`${r.service} · ${r.method} ${r.path} · ${r.summary||''}`}
async function invokeRoute(){try{const r=S.routes[Number($('routeSelect').value)||0];if(!r)throw new Error('请选择接口');const payload={service:r.service,method:r.method,path:r.path,query:parseJson('invokeQuery',{}),timeout:Number($('invokeTimeout').value)||30};const body=parseJson('invokeBody',{});if(r.method!=='GET'&&Object.keys(body).length)payload.json=body;const d=await api('/admin/invoke',{method:'POST',body:payload});$('responseMeta').textContent=`HTTP ${d.status_code??'-'} · ${d.elapsed_ms??'-'}ms · ${d.content_type||''}`;$('imagePreview').innerHTML='';if(d.base64){$('invokeResult').textContent=JSON.stringify({...d,base64:`<${d.base64.length} chars>`},null,2);$('imagePreview').innerHTML=`<img class="preview" src="data:${attr(d.content_type)};base64,${d.base64}">`}else $('invokeResult').textContent=JSON.stringify(d,null,2);toast('请求完成')}catch(e){toast(e.message,true)}}

function renderLogOptions(){$('logSelect').innerHTML=S.logs.map(x=>`<option value="${attr(x.name)}">${esc(x.name)} · ${x.exists?`${x.size_bytes} bytes`:'不存在'}</option>`).join('')}
async function loadLog(){try{const name=$('logSelect').value,lines=Number($('logLines').value)||300,search=$('logSearch').value;const d=await api(`/admin/logs/${encodeURIComponent(name)}?lines=${lines}&search=${encodeURIComponent(search)}`);$('logMeta').textContent=`${d.path||''} · ${d.exists?'存在':'不存在'}`;$('logContent').textContent=d.content||'暂无日志'}catch(e){toast(e.message,true)}}

function renderDiagnostics(){$('diagnosticRows').innerHTML=S.diagnostics.map(x=>`<div class="diag"><strong>${esc(x.name)}</strong><span class="status ${x.ok?'ok':'bad'}">${x.ok?'正常':'异常'}</span><span>${esc(x.detail||'')} ${x.path?`· ${esc(x.path)}`:''}</span></div>`).join('')||'<div class="hint">暂无诊断结果</div>'}
async function loadDiagnostics(){try{const d=await api('/admin/diagnostics');S.diagnostics=d.items||[];renderDiagnostics();showAction('诊断完成',d);toast(d.ok?'诊断通过':'发现异常',!d.ok)}catch(e){toast(e.message,true)}}
async function repairState(){if(!confirm('仅在 state.json 损坏时执行。程序会先备份损坏文件，再重建空状态。继续吗？'))return;try{const d=await api('/admin/repair/state',{method:'POST'});showAction('state.json 修复结果',d);toast(d.action==='recovered'?'已修复并备份':'状态文件无需修复');await loadAll()}catch(e){toast(e.message,true)}}

document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('[id^="tab-"]').forEach(x=>x.classList.add('hidden'));$(`tab-${btn.dataset.tab}`).classList.remove('hidden');if(btn.dataset.tab==='system')loadSystemPanel()}));

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

$('adminToken').value=currentAdminToken();
$('addWatcherButton').addEventListener('click',addWatcher);
$('addTargetButton').addEventListener('click',addTarget);
loadAll();setInterval(()=>{const active=document.querySelector('.tab.active');if(active&&active.dataset.tab==='overview')loadAll()},30000);
