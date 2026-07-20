from __future__ import annotations


def render_control_dashboard() -> str:
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lolapisevers 全功能控制台</title>
<style>
:root{--bg:#f3f6fb;--panel:#fff;--text:#172033;--muted:#66758b;--line:#d9e1ec;--primary:#2557d6;--green:#138a5b;--red:#c2413d;--amber:#b7791f;--soft:#f8fafc;--dark:#101827}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1600px;margin:auto;padding:18px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px}.top h1{font-size:25px;margin:0 0 5px}.top p{margin:0;color:var(--muted);font-size:13px}.actions,.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button{border:1px solid var(--line);background:#fff;color:var(--text);border-radius:8px;padding:8px 11px;min-height:36px;font-weight:700;cursor:pointer}button.primary{background:var(--primary);border-color:var(--primary);color:#fff}button.danger{color:var(--red);border-color:#efb5b1;background:#fff7f6}button.warn{color:#875b07;border-color:#e8c16e;background:#fff8e7}button:disabled{opacity:.55;cursor:not-allowed}.cards{display:grid;grid-template-columns:repeat(6,minmax(145px,1fr));gap:10px;margin-bottom:12px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}.card{padding:13px}.card .label{font-size:12px;color:var(--muted);margin-bottom:7px}.card .value{font-size:20px;font-weight:850}.card .sub{font-size:12px;color:var(--muted);margin-top:5px;word-break:break-all}.ok{color:var(--green)}.bad{color:var(--red)}.warntext{color:var(--amber)}.tabs{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}.tab.active{background:var(--dark);color:#fff;border-color:var(--dark)}.hidden{display:none!important}.panel{padding:14px;margin-bottom:12px}.panel-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:12px}.panel h2{font-size:16px;margin:0}.hint{font-size:12px;color:var(--muted)}.grid{display:grid;gap:10px}.two{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:repeat(3,minmax(0,1fr))}.four{grid-template-columns:repeat(4,minmax(0,1fr))}.field span{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}.field input,.field select,.field textarea,input,select,textarea{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;padding:8px;font:inherit;color:var(--text)}textarea{min-height:86px;resize:vertical}.switch{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--line);border-radius:8px;padding:8px}.switch input{width:auto}.section-title{font-size:13px;font-weight:850;margin:13px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px;max-height:580px}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:12px}th{background:var(--soft);position:sticky;top:0;z-index:1;color:var(--muted)}td input,td textarea{min-width:110px;padding:6px}td textarea{min-height:58px}.status{display:inline-flex;padding:3px 7px;border-radius:999px;font-size:11px;font-weight:800;background:#eef2f7}.status.ok{background:#e7f6ef}.status.bad{background:#fdeceb}.status.warntext{background:#fff5db}.result{white-space:pre-wrap;word-break:break-word;background:var(--dark);color:#e5e7eb;padding:12px;border-radius:8px;max-height:500px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.route{border:1px solid var(--line);border-radius:8px;padding:9px;margin-bottom:7px}.event{border:1px solid var(--line);border-radius:8px;padding:9px;margin-bottom:7px}.event strong{display:block;margin-bottom:4px}.diag{display:grid;grid-template-columns:210px 90px 1fr;gap:8px;padding:8px;border-bottom:1px solid var(--line);font-size:12px}.preview{max-width:100%;max-height:520px;border:1px solid var(--line);border-radius:8px;background:#fff}.toast{position:fixed;right:18px;bottom:18px;display:none;background:var(--dark);color:#fff;padding:11px 13px;border-radius:8px;max-width:560px;box-shadow:0 12px 30px rgba(0,0,0,.18);z-index:10}.toast.err{background:#7f1d1d}@media(max-width:1100px){.cards{grid-template-columns:repeat(3,1fr)}.four,.three{grid-template-columns:repeat(2,1fr)}}@media(max-width:700px){.shell{padding:10px}.top{display:block}.actions{margin-top:10px}.cards,.two,.three,.four{grid-template-columns:1fr}.diag{grid-template-columns:1fr}.panel-head{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body>
<main class="shell">
  <header class="top">
    <div><h1>lolapisevers 全功能控制台</h1><p id="subtitle">正在读取主接口、蓝奏监控、插件、配置和日志...</p></div>
    <div class="actions"><button class="primary" onclick="loadAll()">刷新全部</button><button onclick="sendTestPush()">测试推送</button></div>
  </header>

  <section class="cards">
    <div class="card"><div class="label">主接口</div><div class="value" id="cMain">-</div><div class="sub" id="sMain">-</div></div>
    <div class="card"><div class="label">MySQL</div><div class="value" id="cMysql">-</div><div class="sub" id="sMysql">-</div></div>
    <div class="card"><div class="label">SO1 浏览器</div><div class="value" id="cSo1">-</div><div class="sub" id="sSo1">-</div></div>
    <div class="card"><div class="label">蓝奏监控</div><div class="value" id="cLanzou">-</div><div class="sub" id="sLanzou">-</div></div>
    <div class="card"><div class="label">插件连接</div><div class="value" id="cPlugin">-</div><div class="sub" id="sPlugin">-</div></div>
    <div class="card"><div class="label">状态文件</div><div class="value" id="cState">-</div><div class="sub" id="sState">-</div></div>
  </section>

  <nav class="tabs" id="tabs">
    <button class="tab active" data-tab="overview">总览</button>
    <button class="tab" data-tab="mainconfig">主接口配置</button>
    <button class="tab" data-tab="lanzouconfig">蓝奏配置</button>
    <button class="tab" data-tab="watchers">监控项</button>
    <button class="tab" data-tab="targets">通知目标</button>
    <button class="tab" data-tab="debugger">接口调试</button>
    <button class="tab" data-tab="logs">日志</button>
    <button class="tab" data-tab="diagnostics">诊断修复</button>
  </nav>

  <section id="tab-overview">
    <div class="grid two">
      <div class="panel"><div class="panel-head"><h2>连接与运行信息</h2><span class="hint">每 30 秒自动刷新</span></div><div id="overviewKv"></div></div>
      <div class="panel"><div class="panel-head"><h2>最近蓝奏事件</h2><span class="hint" id="eventCount">0 条</span></div><div id="events"></div></div>
    </div>
  </section>

  <section id="tab-mainconfig" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>主接口与运行环境配置</h2><div class="hint">保存到 ops/app_env.local.ps1；密码留空表示不修改；保存后需要重启 LOLDataSystem。</div></div><button class="primary" onclick="saveMainConfig()">保存主接口配置</button></div><div id="mainConfigForm"></div></div>
  </section>

  <section id="tab-lanzouconfig" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>蓝奏监控全局配置</h2><div class="hint">扫描策略可热更新；监听地址、端口和状态路径变化建议重启服务。</div></div><button class="primary" onclick="saveLanzouGlobal()">保存蓝奏配置</button></div>
      <div class="grid four">
        <label class="field"><span>监听地址</span><input id="lzHost"></label>
        <label class="field"><span>监听端口</span><input id="lzPort" type="number"></label>
        <label class="field"><span>完整扫描间隔（秒）</span><input id="lzInterval" type="number"></label>
        <label class="field"><span>每批扫描数量</span><input id="lzBatch" type="number"></label>
        <label class="field"><span>批次等待（秒）</span><input id="lzPause" type="number"></label>
        <label class="field"><span>解析器顺序（逗号分隔）</span><input id="lzProviders"></label>
        <label class="field"><span>状态文件路径</span><input id="lzStatePath"></label>
        <label class="switch"><span>启动后立即扫描</span><input id="lzScanStart" type="checkbox"></label>
        <label class="field"><span>WER API 地址</span><input id="lzWerEndpoint"></label>
        <label class="field"><span>WER 请求方法</span><select id="lzWerMethod"><option>GET</option><option>POST</option></select></label>
        <label class="field"><span>URL 参数名</span><input id="lzWerUrlParam"></label>
        <label class="field"><span>密码参数名</span><input id="lzWerPwdParam"></label>
        <label class="field"><span>WER API Key（留空不改）</span><input id="lzWerKey" type="password"></label>
      </div>
      <label class="field" style="display:block;margin-top:10px"><span>推送消息模板</span><textarea id="lzTemplate"></textarea></label>
    </div>
  </section>

  <section id="tab-watchers" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>蓝奏监控项完整管理</h2><div class="hint">支持新增、删除、修改 ID、URL、密码和页数。</div></div><div class="toolbar"><button onclick="addWatcher()">新增监控</button><button class="primary" onclick="saveWatchers()">保存监控项</button></div></div><div class="table-wrap"><table><thead><tr><th>启用</th><th>ID</th><th>名称</th><th>URL</th><th>密码</th><th>页数</th><th>状态</th><th>操作</th></tr></thead><tbody id="watcherRows"></tbody></table></div></div>
  </section>

  <section id="tab-targets" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>多个通知目标</h2><div class="hint">每个目标可单独启停、设置 URL、超时和请求 Headers。</div></div><div class="toolbar"><button onclick="addTarget()">新增目标</button><button class="primary" onclick="saveTargets()">保存通知目标</button></div></div><div class="table-wrap"><table><thead><tr><th>启用</th><th>名称</th><th>URL</th><th>超时</th><th>Headers JSON</th><th>操作</th></tr></thead><tbody id="targetRows"></tbody></table></div></div>
  </section>

  <section id="tab-debugger" class="hidden">
    <div class="grid two">
      <div class="panel"><div class="panel-head"><div><h2>OpenAPI 自动接口调试</h2><div class="hint">自动读取 5001 与 6178 的全部路由，不再手写接口清单。</div></div><button onclick="loadOpenApi()">刷新路由</button></div>
        <div class="grid two"><label class="field"><span>接口</span><select id="routeSelect" onchange="selectRoute()"></select></label><label class="field"><span>超时（秒）</span><input id="invokeTimeout" type="number" value="30"></label></div>
        <div class="grid two" style="margin-top:10px"><label class="field"><span>Query 参数 JSON</span><textarea id="invokeQuery">{}</textarea></label><label class="field"><span>请求体 JSON</span><textarea id="invokeBody">{}</textarea></label></div>
        <div class="toolbar" style="margin-top:10px"><button class="primary" onclick="invokeRoute()">发送请求</button><span class="hint" id="routeHint">请选择接口</span></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>响应</h2><span class="hint" id="responseMeta">-</span></div><pre class="result" id="invokeResult">暂无</pre><div id="imagePreview"></div></div>
    </div>
  </section>

  <section id="tab-logs" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>日志中心</h2><div class="hint">主接口、蓝奏监控、保活和启动日志统一查看。</div></div><div class="toolbar"><select id="logSelect"></select><input id="logLines" type="number" value="300" style="width:100px"><input id="logSearch" placeholder="关键词过滤" style="width:220px"><button class="primary" onclick="loadLog()">读取日志</button></div></div><div class="hint" id="logMeta"></div><pre class="result" id="logContent">暂无</pre></div>
  </section>

  <section id="tab-diagnostics" class="hidden">
    <div class="panel"><div class="panel-head"><div><h2>诊断与安全修复</h2><div class="hint">检查端口、Windows 服务、配置文件、state.json、虚拟环境和 Playwright。</div></div><div class="toolbar"><button class="primary" onclick="loadDiagnostics()">重新诊断</button><button class="warn" onclick="repairState()">修复 state.json</button></div></div><div id="diagnosticRows"></div></div>
    <div class="panel"><div class="panel-head"><h2>最后一次操作结果</h2><span class="hint" id="actionHint">等待操作</span></div><pre class="result" id="actionResult">暂无</pre></div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
const S={overview:null,mainConfig:null,lanzou:{},watchers:[],targets:[],events:[],logs:[],routes:[],diagnostics:[]};
const $=id=>document.getElementById(id);
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function attr(v){return esc(v)}
function toast(msg,err=false){const t=$('toast');t.textContent=msg;t.className='toast'+(err?' err':'');t.style.display='block';clearTimeout(t._timer);t._timer=setTimeout(()=>t.style.display='none',4500)}
async function api(path,opt={}){const r=await fetch(path,{method:opt.method||'GET',headers:{'content-type':'application/json'},body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const text=await r.text();let data;try{data=JSON.parse(text)}catch{data={ok:false,error:text}}if(!r.ok)throw new Error(data.error||text||r.statusText);return data}
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

function addWatcher(){S.watchers.push({id:`watcher-${Date.now()}`,title:'新监控',url:'https://',password:'',enabled:true,max_pages:20});renderWatchers()}
function collectWatchers(){return [...document.querySelectorAll('#watcherRows tr')].map(row=>({enabled:row.querySelector('[data-f="enabled"]').checked,id:row.querySelector('[data-f="id"]').value.trim(),title:row.querySelector('[data-f="title"]').value.trim(),url:row.querySelector('[data-f="url"]').value.trim(),password:row.querySelector('[data-f="password"]').value.trim(),max_pages:Number(row.querySelector('[data-f="max_pages"]').value)||20}))}
function renderWatchers(){$('watcherRows').innerHTML=S.watchers.map((w,i)=>{const live=(S.overview?.lanzou?.health?.last_scan||{})[w.id]||{},status=!live.at?'暂无':live.ok?(live.notification_pending?'待推送':'成功'):'失败';return `<tr><td><input data-f="enabled" type="checkbox" ${w.enabled!==false?'checked':''}></td><td><input data-f="id" value="${attr(w.id)}"></td><td><input data-f="title" value="${attr(w.title||'')}"></td><td><input data-f="url" value="${attr(w.url||'')}"></td><td><input data-f="password" value="${attr(w.password||'')}"></td><td><input data-f="max_pages" type="number" min="1" max="100" value="${attr(w.max_pages||20)}"></td><td><span class="status ${live.ok?(live.notification_pending?'warntext':'ok'):live.at?'bad':''}">${esc(status)}</span><div class="hint">${esc(live.error||live.provider||'')}</div></td><td><div class="toolbar"><button onclick="scanWatcher(${i})">扫描</button><button onclick="testWatcher(${i})">推送</button><button onclick="showFiles(${i})">文件</button><button class="danger" onclick="removeWatcher(${i})">删除</button></div></td></tr>`}).join('')||'<tr><td colspan="8" class="hint">暂无监控项</td></tr>'}
function removeWatcher(i){S.watchers.splice(i,1);renderWatchers()}
async function saveWatchers(){try{S.watchers=collectWatchers();const d=await api('/admin/lanzou-config',{method:'POST',body:{watchers:S.watchers}});await reloadLanzou();showAction('监控项已保存',d);toast('监控项已保存')}catch(e){toast(e.message,true)}}
async function scanWatcher(i){try{const id=collectWatchers()[i].id;const d=await api(`/scan?watcher_id=${encodeURIComponent(id)}&notify=false`,{method:'POST'});showAction(`扫描 ${id}`,d);toast('扫描完成');await loadAll()}catch(e){toast(e.message,true)}}
async function testWatcher(i){try{const id=collectWatchers()[i].id;const d=await api(`/notify/test?watcher_id=${encodeURIComponent(id)}`,{method:'POST'});showAction(`测试推送 ${id}`,d);toast('测试推送完成')}catch(e){toast(e.message,true)}}
async function showFiles(i){try{const id=collectWatchers()[i].id;const d=await api(`/files/${encodeURIComponent(id)}`);showAction(`文件快照 ${id}`,d);document.querySelector('[data-tab="diagnostics"]').click()}catch(e){toast(e.message,true)}}

function addTarget(){S.targets.push({name:`target-${S.targets.length+1}`,enabled:true,url:'http://127.0.0.1:6108/',timeout_seconds:8,headers:{}});renderTargets()}
function collectTargets(){return [...document.querySelectorAll('#targetRows tr')].map(row=>({enabled:row.querySelector('[data-f="enabled"]').checked,name:row.querySelector('[data-f="name"]').value.trim(),url:row.querySelector('[data-f="url"]').value.trim(),timeout_seconds:Number(row.querySelector('[data-f="timeout"]').value)||8,headers:JSON.parse(row.querySelector('[data-f="headers"]').value||'{}')}))}
function renderTargets(){$('targetRows').innerHTML=S.targets.map((t,i)=>`<tr><td><input data-f="enabled" type="checkbox" ${t.enabled!==false?'checked':''}></td><td><input data-f="name" value="${attr(t.name||'')}"></td><td><input data-f="url" value="${attr(t.url||'')}"></td><td><input data-f="timeout" type="number" min="0.1" max="120" step="0.1" value="${attr(t.timeout_seconds||8)}"></td><td><textarea data-f="headers">${esc(JSON.stringify(t.headers||{},null,2))}</textarea></td><td><button class="danger" onclick="removeTarget(${i})">删除</button></td></tr>`).join('')||'<tr><td colspan="6" class="hint">暂无通知目标</td></tr>'}
function removeTarget(i){S.targets.splice(i,1);renderTargets()}
async function saveTargets(){try{S.targets=collectTargets();const d=await api('/admin/lanzou-config',{method:'POST',body:{notify_targets:S.targets}});await reloadLanzou();showAction('通知目标已保存',d);toast('通知目标已保存')}catch(e){toast(e.message,true)}}
async function sendTestPush(){try{const d=await api('/notify/test',{method:'POST'});showAction('全局测试推送',d);toast('测试推送完成')}catch(e){toast(e.message,true)}}

async function loadOpenApi(notify=true){try{const [main,lz]=await Promise.all([api('/admin/openapi/main'),api('/admin/openapi/lanzou')]);const routes=[];[[main,'main'],[lz,'lanzou']].forEach(([d,service])=>{const paths=d.schema?.paths||{};Object.entries(paths).forEach(([path,ops])=>Object.entries(ops).forEach(([method,op])=>{if(!['get','post','put','patch','delete'].includes(method))return;routes.push({service,path,method:method.toUpperCase(),summary:op.summary||op.operationId||'',parameters:op.parameters||[],requestBody:op.requestBody||null})}))});S.routes=routes.sort((a,b)=>(a.service+a.path+a.method).localeCompare(b.service+b.path+b.method));$('routeSelect').innerHTML=S.routes.map((r,i)=>`<option value="${i}">[${r.service}] ${r.method} ${esc(r.path)} · ${esc(r.summary)}</option>`).join('');selectRoute();if(notify)toast(`已加载 ${S.routes.length} 个接口`)}catch(e){toast(e.message,true)}}
function selectRoute(){const r=S.routes[Number($('routeSelect').value)||0];if(!r){$('routeHint').textContent='没有可用接口';return}const q={};(r.parameters||[]).filter(p=>p.in==='query').forEach(p=>{const s=p.schema||{};q[p.name]=s.default??(p.required?`<${p.name}>`:'')});$('invokeQuery').value=JSON.stringify(q,null,2);$('invokeBody').value=r.requestBody?'{}':'{}';$('routeHint').textContent=`${r.service} · ${r.method} ${r.path} · ${r.summary||''}`}
async function invokeRoute(){try{const r=S.routes[Number($('routeSelect').value)||0];if(!r)throw new Error('请选择接口');const payload={service:r.service,method:r.method,path:r.path,query:parseJson('invokeQuery',{}),timeout:Number($('invokeTimeout').value)||30};const body=parseJson('invokeBody',{});if(r.method!=='GET'&&Object.keys(body).length)payload.json=body;const d=await api('/admin/invoke',{method:'POST',body:payload});$('responseMeta').textContent=`HTTP ${d.status_code??'-'} · ${d.elapsed_ms??'-'}ms · ${d.content_type||''}`;$('imagePreview').innerHTML='';if(d.base64){$('invokeResult').textContent=JSON.stringify({...d,base64:`<${d.base64.length} chars>`},null,2);$('imagePreview').innerHTML=`<img class="preview" src="data:${attr(d.content_type)};base64,${d.base64}">`}else $('invokeResult').textContent=JSON.stringify(d,null,2);toast('请求完成')}catch(e){toast(e.message,true)}}

function renderLogOptions(){$('logSelect').innerHTML=S.logs.map(x=>`<option value="${attr(x.name)}">${esc(x.name)} · ${x.exists?`${x.size_bytes} bytes`:'不存在'}</option>`).join('')}
async function loadLog(){try{const name=$('logSelect').value,lines=Number($('logLines').value)||300,search=$('logSearch').value;const d=await api(`/admin/logs/${encodeURIComponent(name)}?lines=${lines}&search=${encodeURIComponent(search)}`);$('logMeta').textContent=`${d.path||''} · ${d.exists?'存在':'不存在'}`;$('logContent').textContent=d.content||'暂无日志'}catch(e){toast(e.message,true)}}

function renderDiagnostics(){$('diagnosticRows').innerHTML=S.diagnostics.map(x=>`<div class="diag"><strong>${esc(x.name)}</strong><span class="status ${x.ok?'ok':'bad'}">${x.ok?'正常':'异常'}</span><span>${esc(x.detail||'')} ${x.path?`· ${esc(x.path)}`:''}</span></div>`).join('')||'<div class="hint">暂无诊断结果</div>'}
async function loadDiagnostics(){try{const d=await api('/admin/diagnostics');S.diagnostics=d.items||[];renderDiagnostics();showAction('诊断完成',d);toast(d.ok?'诊断通过':'发现异常',!d.ok)}catch(e){toast(e.message,true)}}
async function repairState(){if(!confirm('仅在 state.json 损坏时执行。程序会先备份损坏文件，再重建空状态。继续吗？'))return;try{const d=await api('/admin/repair/state',{method:'POST'});showAction('state.json 修复结果',d);toast(d.action==='recovered'?'已修复并备份':'状态文件无需修复');await loadAll()}catch(e){toast(e.message,true)}}

document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('[id^="tab-"]').forEach(x=>x.classList.add('hidden'));$(`tab-${btn.dataset.tab}`).classList.remove('hidden')}));
loadAll();setInterval(()=>loadAll(),30000);
</script>
</body>
</html>'''
