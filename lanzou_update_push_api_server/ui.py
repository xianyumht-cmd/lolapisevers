from __future__ import annotations


def render_dashboard_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lolapisevers 接口端总控台</title>
<style>
:root{--bg:#f5f7fb;--panel:#fff;--ink:#172033;--muted:#66758b;--line:#d9e1ec;--blue:#2557d6;--green:#138a5b;--red:#c2413d;--amber:#b7791f;--soft:#f8fafc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}.shell{max-width:1480px;margin:0 auto;padding:20px}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.top h1{margin:0 0 6px;font-size:25px}.top p{margin:0;color:var(--muted);font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}button{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:8px;padding:9px 12px;min-height:38px;font-weight:700;cursor:pointer}button.primary{background:var(--blue);border-color:var(--blue);color:#fff}button.warn{background:#fff8e7;border-color:#e8c16e;color:#875b07}button:disabled{opacity:.58;cursor:not-allowed}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink);padding:9px;font:inherit}textarea{min-height:74px;resize:vertical}.grid{display:grid;gap:12px}.cards{grid-template-columns:repeat(5,minmax(150px,1fr));margin-bottom:12px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px}.card{padding:14px}.label{font-size:12px;color:var(--muted);margin-bottom:7px}.value{font-size:22px;font-weight:800}.sub{font-size:12px;color:var(--muted);margin-top:6px}.layout{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(380px,.75fr);gap:12px}.panel{padding:14px;min-width:0}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.panel h2{font-size:16px;margin:0}.hint{font-size:12px;color:var(--muted)}.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:999px;background:#eef2f7;color:#4d5c70;font-size:12px;font-weight:800}.pill.ok{background:#e7f6ef;color:var(--green)}.pill.err{background:#fdeceb;color:var(--red)}.pill.warn{background:#fff5db;color:var(--amber)}.dot{width:8px;height:8px;border-radius:999px;background:currentColor}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.tab{background:#fff}.tab.active{background:#172033;color:#fff;border-color:#172033}.hidden{display:none!important}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.form-grid label span,label.block span{display:block;font-size:12px;color:var(--muted);margin:0 0 5px}.switch{display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff}.switch input{width:auto}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.toolbar input{max-width:320px}.table-wrap{border:1px solid var(--line);border-radius:8px;overflow:auto;max-height:560px}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid var(--line);text-align:left;padding:9px 8px;font-size:13px;vertical-align:top}th{position:sticky;top:0;background:var(--soft);z-index:1;font-size:12px;color:var(--muted)}td .name{font-weight:800}.url{max-width:460px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:12px}.kv{display:grid;grid-template-columns:190px 1fr;gap:8px 10px;font-size:13px}.kv div:nth-child(odd){color:var(--muted)}.function-list{display:grid;gap:8px}.function{border:1px solid var(--line);border-radius:8px;padding:10px;background:#fff}.function .title{font-weight:800;margin-bottom:5px}.function .meta{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px}.events{display:grid;gap:9px;max-height:500px;overflow:auto}.event{border:1px solid var(--line);border-radius:8px;padding:10px}.event-title{font-weight:800}.event-meta{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:4px}.diff{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.diff span{font-size:12px;border-radius:999px;padding:3px 7px;background:#eef2f7}.diff .add{background:#e7f6ef;color:var(--green)}.diff .rem{background:#fdeceb;color:var(--red)}.diff .chg{background:#fff5db;color:var(--amber)}pre{white-space:pre-wrap;word-break:break-word;background:#101827;color:#e5e7eb;border-radius:8px;padding:12px;max-height:270px;overflow:auto}.toast{position:fixed;right:18px;bottom:18px;background:#172033;color:#fff;border-radius:8px;padding:11px 13px;box-shadow:0 12px 32px rgba(20,30,50,.2);display:none;max-width:560px;font-size:13px}.toast.err{background:#7f1d1d}@media(max-width:1060px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.layout,.form-grid{grid-template-columns:1fr}.top{display:block}.actions{justify-content:flex-start;margin-top:12px}}@media(max-width:620px){.shell{padding:12px}.cards{grid-template-columns:1fr}.kv{grid-template-columns:120px 1fr}.toolbar input{max-width:none}.table-wrap{max-height:none}th:nth-child(4),td:nth-child(4){display:none}}
</style>
</head>
<body>
<main class="shell">
  <div class="top">
    <div>
      <h1>lolapisevers 接口端总控台</h1>
      <p id="subtitle">正在读取主接口、蓝奏监控和插件端状态...</p>
    </div>
    <div class="actions">
      <button id="refreshBtn" class="primary">刷新状态</button>
      <button id="notifyBtn">发送蓝奏测试推送</button>
    </div>
  </div>

  <section class="grid cards">
    <div class="card"><div class="label">主接口</div><div class="value" id="mainStatus">-</div><div class="sub" id="mainSub">-</div></div>
    <div class="card"><div class="label">MySQL</div><div class="value" id="mysqlStatus">-</div><div class="sub" id="mysqlSub">-</div></div>
    <div class="card"><div class="label">SO1 浏览器</div><div class="value" id="so1Status">-</div><div class="sub" id="so1Sub">-</div></div>
    <div class="card"><div class="label">蓝奏监控</div><div class="value" id="lanzouStatus">-</div><div class="sub" id="lanzouSub">-</div></div>
    <div class="card"><div class="label">插件连接</div><div class="value" id="pluginStatus">-</div><div class="sub" id="pluginSub">-</div></div>
  </section>

  <div class="tabs">
    <button class="tab active" data-tab="overview">总览</button>
    <button class="tab" data-tab="config">配置</button>
    <button class="tab" data-tab="watchers">蓝奏监控</button>
    <button class="tab" data-tab="functions">接口功能</button>
    <button class="tab" data-tab="events">事件与日志</button>
  </div>

  <section id="tab-overview" class="layout">
    <div class="panel">
      <div class="panel-head"><h2>连接状态</h2><span class="hint" id="overviewHint">-</span></div>
      <div class="kv" id="connectionBox"></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>最近事件</h2><span class="hint" id="eventCount">-</span></div>
      <div id="eventListMini" class="events"></div>
    </div>
  </section>

  <section id="tab-config" class="grid hidden">
    <div class="panel">
      <div class="panel-head"><h2>主接口运行配置</h2><span class="hint">敏感项已隐藏，修改环境配置后通常需要重启服务</span></div>
      <div class="kv" id="mainConfigBox"></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>蓝奏监控配置</h2><button id="saveLanzouBtn" class="primary">保存蓝奏配置</button></div>
      <div class="form-grid">
        <label><span>完整扫描间隔（秒）</span><input id="scanInterval" type="number" min="5"></label>
        <label><span>每批扫描数量</span><input id="scanBatchSize" type="number" min="0"></label>
        <label><span>批次间隔（秒）</span><input id="scanBatchPause" type="number" min="0"></label>
        <label class="switch"><span>启动后立即扫描</span><input id="scanOnStart" type="checkbox"></label>
        <label><span>文件列表来源顺序</span><input id="providerOrder" placeholder="lanzou_web, wer_api"></label>
        <label><span>Wer API 状态</span><input id="werApiState" disabled></label>
      </div>
      <label class="block" style="margin-top:10px"><span>推送消息模板</span><textarea id="notificationTemplate"></textarea></label>
      <div class="form-grid" style="margin-top:10px">
        <label class="switch"><span>通知目标启用</span><input id="notifyEnabled" type="checkbox"></label>
        <label><span>通知目标名称</span><input id="notifyName"></label>
        <label><span>通知超时（秒）</span><input id="notifyTimeout" type="number" min="1"></label>
      </div>
      <label class="block" style="margin-top:10px"><span>通知目标 URL（SnowLuma 插件端）</span><input id="notifyUrl"></label>
      <p class="hint">当前部署建议：蓝奏接口端 `192.168.3.100:6178`，插件端回调 `192.168.3.89:6108`。</p>
    </div>
  </section>

  <section id="tab-watchers" class="panel hidden">
    <div class="panel-head">
      <h2>蓝奏监控项</h2>
      <div class="toolbar"><input id="watcherSearch" placeholder="搜索标题、ID、URL"><button id="saveWatchersBtn" class="primary">保存监控项修改</button></div>
    </div>
    <div class="table-wrap">
      <table><thead><tr><th>启用</th><th>名称</th><th>URL</th><th>文件/扫描</th><th>页数</th><th>操作</th></tr></thead><tbody id="watcherRows"></tbody></table>
    </div>
  </section>

  <section id="tab-functions" class="panel hidden">
    <div class="panel-head"><h2>接口端功能列表</h2><span class="hint">主接口与蓝奏接口合并展示</span></div>
    <div id="functionList" class="function-list"></div>
  </section>

  <section id="tab-events" class="layout hidden">
    <div class="panel">
      <div class="panel-head"><h2>蓝奏最近事件</h2><span class="hint" id="eventHint">-</span></div>
      <div id="eventList" class="events"></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>最后一次操作结果</h2><span class="hint" id="actionHint">等待操作</span></div>
      <pre id="actionResult">暂无</pre>
    </div>
  </section>
</main>
<div id="toast" class="toast"></div>
<script>
(function(){
var state={overview:null,lanzouConfig:null,watchers:[],events:[],watcherFilter:''};
function E(id){return document.getElementById(id)}
function esc(v){return String(v==null?'':v).replace(/[&<"]/g,function(c){return {'&':'&amp;','<':'&lt;','"':'&quot;'}[c]})}
function api(path,opt){opt=opt||{};var headers={'content-type':'application/json'};return fetch(path,{method:opt.method||'GET',headers:headers,body:opt.body}).then(function(r){return r.text().then(function(text){var data;try{data=JSON.parse(text)}catch(e){data={ok:false,error:text}}if(!r.ok)throw new Error(data.error||text||r.statusText);return data})})}
function badge(ok,text){return '<span class="pill '+(ok?'ok':'err')+'"><span class="dot"></span>'+esc(text)+'</span>'}
function toast(msg,err){var t=E('toast');t.textContent=msg;t.className='toast'+(err?' err':'');t.style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(function(){t.style.display='none'},4200)}
function fmtTime(v){if(!v)return '-';var d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleString()}
function diffCounts(diff){diff=diff||{};return {add:(diff.added||[]).length,rem:(diff.removed||[]).length,chg:(diff.changed||[]).length}}
function scanState(w){var last=(state.overview&&state.overview.lanzou&&state.overview.lanzou.health&&state.overview.lanzou.health.last_scan||{})[w.id];if(!last)return {kind:'none',text:'暂无扫描',file:'-',at:'-'};return {kind:last.ok?(last.notification_pending?'warn':'ok'):'err',text:last.ok?(last.notification_pending?'待推送':'成功'):'失败',file:last.file_count==null?'-':last.file_count,at:fmtTime(last.at),info:last.provider||last.error||''}}
function renderCards(){var o=state.overview||{},mh=o.mainApi&&o.mainApi.health||{},lh=o.lanzou&&o.lanzou.health||{},plugin=o.plugin||{};E('mainStatus').innerHTML=badge(mh.ready===true,mh.ready===true?'就绪':'降级');E('mainSub').textContent=o.mainApi&&o.mainApi.baseUrl||'-';E('mysqlStatus').innerHTML=badge(mh.mysql==='up',mh.mysql==='up'?'正常':'异常');E('mysqlSub').textContent=mh.mysql_error||'数据库连接';E('so1Status').innerHTML=badge(mh.so1_browser==='up',mh.so1_browser==='up'?'在线':'离线');E('so1Sub').textContent='并发页面 '+(mh.so1_max_concurrent_pages||0);E('lanzouStatus').innerHTML=badge(lh.running===true,'运行中');E('lanzouSub').textContent=(lh.enabled_watcher_count||0)+' / '+(lh.watcher_count||0)+' 个监控启用';E('pluginStatus').innerHTML=badge(plugin.ok===true,plugin.ok?'已连接':'未连接');E('pluginSub').textContent=plugin.url||plugin.error||'-';E('subtitle').textContent='配置文件：'+(o.configPath||'-')}
function renderConnections(){var o=state.overview||{},c=o.lanzou&&o.lanzou.config||{},p=o.plugin||{},pd=p.data||{};var rows=['项目根目录',o.projectRoot,'蓝奏配置文件',o.configPath,'主接口地址',o.mainApi&&o.mainApi.baseUrl,'蓝奏接口地址',o.lanzou&&o.lanzou.baseUrl,'插件状态地址',p.url,'插件账号',pd.botId||'-','插件配置文件',pd.configPath||'-','通知目标数量',(c.notify_targets||[]).length,'扫描策略','每轮 '+(c.scan_interval_seconds||0)+' 秒；每批 '+(c.scan_batch_size||0)+' 个；批次间隔 '+(c.scan_batch_pause_seconds||0)+' 秒'];var html='';for(var i=0;i<rows.length;i+=2)html+='<div>'+esc(rows[i])+'</div><div>'+esc(rows[i+1])+'</div>';E('connectionBox').innerHTML=html;E('overviewHint').textContent='自动每 30 秒刷新'}
function renderMainConfig(){var cfg=state.overview&&state.overview.mainApi&&state.overview.mainApi.config||{},v=cfg.values||{};var names={app_host:'主接口监听地址',app_port:'主接口端口',cache_seconds:'通用缓存秒数',shard_cache_seconds:'云顶合集缓存秒数',aram_augment_cache_seconds:'大乱斗缓存秒数',shard_data_url:'云顶数据 URL',shard_hero_url:'英雄列表 URL',mysql_host:'MySQL 地址',mysql_port:'MySQL 端口',mysql_user:'MySQL 用户',mysql_password:'MySQL 密码',mysql_database:'MySQL 数据库',so1_username:'SO1 用户',so1_password:'SO1 密码',so1_headless:'SO1 无头模式',so1_timeout_ms:'SO1 超时毫秒'};var html='';Object.keys(names).forEach(function(k){html+='<div>'+esc(names[k])+'<div class="hint">'+esc(k)+'</div></div><div>'+esc(v[k])+'</div>'});html+='<div>配置来源</div><div>'+esc(cfg.source||'-')+'</div>';html+='<div>生效方式</div><div>'+(cfg.restart_required?'修改后重启 LOLDataSystem 生效':'可热更新')+'</div>';E('mainConfigBox').innerHTML=html}
function renderLanzouEditor(){var cfg=state.lanzouConfig||{};E('scanInterval').value=cfg.scan_interval_seconds||300;E('scanBatchSize').value=cfg.scan_batch_size||0;E('scanBatchPause').value=cfg.scan_batch_pause_seconds||0;E('scanOnStart').checked=cfg.scan_on_start!==false;E('providerOrder').value=(cfg.provider_order||[]).join(', ');E('werApiState').value=cfg.wer_api_key?'已配置':'未配置';E('notificationTemplate').value=cfg.notification_template||'hello，{title}网盘检测到更新';var target=(cfg.notify_targets||[])[0]||{};E('notifyEnabled').checked=target.enabled!==false;E('notifyName').value=target.name||'snowluma';E('notifyTimeout').value=target.timeout_seconds||8;E('notifyUrl').value=target.url||''}
function renderWatchers(){var q=state.watcherFilter.toLowerCase();var cfg=state.lanzouConfig||{},raw=cfg.watchers||[];var byId={};state.watchers.forEach(function(w){byId[w.id]=w});var rows='';raw.filter(function(w){return !q||[w.id,w.title,w.url].join(' ').toLowerCase().indexOf(q)>=0}).forEach(function(w,i){var live=byId[w.id]||w,s=scanState(live);rows+='<tr data-i="'+i+'"><td><input data-field="enabled" type="checkbox" '+(w.enabled!==false?'checked':'')+'></td><td><input data-field="title" value="'+esc(w.title||w.id)+'"><div class="hint">'+esc(w.id)+'</div></td><td><div class="url">'+esc(w.url)+'</div><input data-field="password" placeholder="密码，可空" value="'+esc(w.password||'')+'"></td><td><span class="pill '+(s.kind==='ok'?'ok':s.kind==='err'?'err':'warn')+'"><span class="dot"></span>'+esc(s.text)+'</span><div class="hint">文件 '+esc(s.file)+' · '+esc(s.at)+' '+esc(s.info||'')+'</div></td><td><input data-field="max_pages" type="number" min="1" max="100" value="'+esc(w.max_pages||20)+'"></td><td><button class="smallbtn" data-scan="'+esc(w.id)+'">扫描</button> <button class="smallbtn warn" data-notify="'+esc(w.id)+'">测试推送</button></td></tr>'});E('watcherRows').innerHTML=rows||'<tr><td colspan="6" class="hint">没有匹配的监控项</td></tr>';document.querySelectorAll('[data-scan]').forEach(function(b){b.onclick=function(){scan(b.dataset.scan)}});document.querySelectorAll('[data-notify]').forEach(function(b){b.onclick=function(){notify(b.dataset.notify)}})}
function renderFunctions(){var funcs=(state.overview&&state.overview.mainApi&&state.overview.mainApi.functions)||[];E('functionList').innerHTML=funcs.map(function(f){return '<div class="function"><div class="title">'+esc(f.name)+'</div><div>'+esc(f.description)+'</div><div class="meta"><span>'+esc(f.method)+'</span><span>'+esc(f.service||'main')+'</span><span>'+esc(f.path)+'</span></div><div class="hint">'+esc(f.example||'')+'</div></div>'}).join('')}
function renderEvents(){var html=state.events.map(function(ev){var d=diffCounts(ev.diff),deliveries=(ev.notify_results||[]).map(function(x){return (x.target||'target')+': '+(x.ok?'ok':'failed')}).join(' · ');return '<article class="event"><div class="event-title">'+esc(ev.title||ev.name||ev.watcher_id)+'</div><div class="event-meta"><span>'+esc(ev.type||'event')+'</span><span>'+esc(fmtTime(ev.created_at))+'</span><span>'+esc(ev.provider||'')+'</span></div><div class="diff"><span class="add">新增 '+d.add+'</span><span class="rem">删除 '+d.rem+'</span><span class="chg">变化 '+d.chg+'</span></div><div class="hint">'+esc(deliveries||ev.message||'')+'</div></article>'}).join('')||'<p class="hint">暂无事件</p>';E('eventList').innerHTML=html;E('eventListMini').innerHTML=html;E('eventHint').textContent=state.events.length+' 条';E('eventCount').textContent=state.events.length+' 条'}
function render(){renderCards();renderConnections();renderMainConfig();renderLanzouEditor();renderWatchers();renderFunctions();renderEvents()}
function load(){E('refreshBtn').disabled=true;Promise.all([api('/admin/overview'),api('/admin/lanzou-config'),api('/watchers'),api('/events?limit=40')]).then(function(all){state.overview=all[0];state.lanzouConfig=all[1].config||{};state.watchers=all[2].watchers||[];state.events=all[3].events||[];render();toast('状态已刷新')}).catch(function(e){toast(e.message,true)}).finally(function(){E('refreshBtn').disabled=false})}
function currentWatcherPatch(){var cfg=JSON.parse(JSON.stringify(state.lanzouConfig||{}));var rows=document.querySelectorAll('#watcherRows tr[data-i]');rows.forEach(function(row){var i=Number(row.dataset.i),w=cfg.watchers[i];if(!w)return;row.querySelectorAll('[data-field]').forEach(function(input){var f=input.dataset.field;if(input.type==='checkbox')w[f]=input.checked;else if(input.type==='number')w[f]=Number(input.value)||20;else w[f]=input.value})});return cfg.watchers||[]}
function saveLanzou(includeWatchers){var target={name:E('notifyName').value||'snowluma',enabled:E('notifyEnabled').checked,url:E('notifyUrl').value,timeout_seconds:Number(E('notifyTimeout').value)||8,headers:((state.lanzouConfig.notify_targets||[])[0]||{}).headers||{}};var patch={scan_interval_seconds:Number(E('scanInterval').value)||300,scan_batch_size:Number(E('scanBatchSize').value)||0,scan_batch_pause_seconds:Number(E('scanBatchPause').value)||0,scan_on_start:E('scanOnStart').checked,provider_order:E('providerOrder').value.split(',').map(function(x){return x.trim()}).filter(Boolean),notification_template:E('notificationTemplate').value||'hello，{title}网盘检测到更新',notify_targets:[target]};if(includeWatchers)patch.watchers=currentWatcherPatch();E('actionHint').textContent='正在保存配置';api('/admin/lanzou-config',{method:'POST',body:JSON.stringify(patch)}).then(function(d){E('actionResult').textContent=JSON.stringify(d,null,2);toast('蓝奏配置已保存');return load()}).catch(function(e){E('actionResult').textContent=e.message;toast(e.message,true)})}
function scan(id){E('actionHint').textContent='检查更新 '+id;api('/scan?watcher_id='+encodeURIComponent(id)+'&notify=false',{method:'POST'}).then(function(d){E('actionResult').textContent=JSON.stringify(d,null,2);toast('检查完成；未推送的更新会由自动扫描继续发送');return load()}).catch(function(e){E('actionResult').textContent=e.message;toast(e.message,true)})}
function notify(id){E('actionHint').textContent='测试推送 '+(id||'默认监控');api('/notify/test'+(id?'?watcher_id='+encodeURIComponent(id):''),{method:'POST'}).then(function(d){E('actionResult').textContent=JSON.stringify(d,null,2);toast('测试推送已发送');return load()}).catch(function(e){E('actionResult').textContent=e.message;toast(e.message,true)})}
document.querySelectorAll('.tab').forEach(function(btn){btn.onclick=function(){document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('active')});btn.classList.add('active');document.querySelectorAll('[id^="tab-"]').forEach(function(s){s.classList.add('hidden')});E('tab-'+btn.dataset.tab).classList.remove('hidden')}});E('refreshBtn').onclick=load;E('notifyBtn').onclick=function(){notify('')};E('saveLanzouBtn').onclick=function(){saveLanzou(false)};E('saveWatchersBtn').onclick=function(){saveLanzou(true)};E('watcherSearch').oninput=function(){state.watcherFilter=this.value;renderWatchers()};load();setInterval(load,30000);
})();
</script>
</body>
</html>"""
