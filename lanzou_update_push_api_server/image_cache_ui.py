from __future__ import annotations


def render_image_cache_page() -> str:
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LOL 图片资源缓存</title>
<style>
:root{--bg:#f3f6fb;--panel:#fff;--text:#172033;--muted:#66758b;--line:#d9e1ec;--primary:#2557d6;--green:#138a5b;--red:#c2413d;--amber:#b7791f;--dark:#101827}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1180px;margin:auto;padding:18px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px}.top h1{font-size:25px;margin:0 0 6px}.top p{margin:0;color:var(--muted);font-size:13px}.actions,.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button,a.button{border:1px solid var(--line);background:#fff;color:var(--text);border-radius:8px;padding:9px 12px;min-height:38px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}button.primary{background:var(--primary);border-color:var(--primary);color:#fff}button.warn{color:#875b07;border-color:#e8c16e;background:#fff8e7}button:disabled{opacity:.55;cursor:not-allowed}.cards{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-bottom:12px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}.card{padding:14px}.label{font-size:12px;color:var(--muted);margin-bottom:7px}.value{font-size:22px;font-weight:850}.sub{font-size:12px;color:var(--muted);margin-top:5px;word-break:break-all}.panel{padding:14px;margin-bottom:12px}.panel-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:12px}.panel h2{font-size:16px;margin:0}.hint{font-size:12px;color:var(--muted)}.status{display:inline-flex;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:800;background:#eef2f7}.status.ok{background:#e7f6ef;color:var(--green)}.status.bad{background:#fdeceb;color:var(--red)}.status.warn{background:#fff5db;color:var(--amber)}pre{white-space:pre-wrap;word-break:break-word;background:var(--dark);color:#e5e7eb;padding:12px;border-radius:8px;max-height:420px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.progress{height:16px;border-radius:999px;background:#e8edf5;overflow:hidden}.bar{height:100%;width:0;background:var(--primary);transition:width .25s}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.kv{display:grid;grid-template-columns:210px 1fr;gap:8px 12px;font-size:13px}.kv div:nth-child(odd){color:var(--muted)}input{border:1px solid var(--line);border-radius:8px;padding:9px;width:260px;max-width:100%}.toast{position:fixed;right:18px;bottom:18px;display:none;background:var(--dark);color:#fff;padding:11px 13px;border-radius:8px;max-width:560px;box-shadow:0 12px 30px rgba(0,0,0,.18)}.toast.err{background:#7f1d1d}@media(max-width:800px){.cards,.grid{grid-template-columns:1fr}.top{display:block}.actions{margin-top:10px}.kv{grid-template-columns:120px 1fr}.shell{padding:10px}}
</style>
</head>
<body>
<main class="shell">
  <header class="top">
    <div>
      <h1>LOL 图片资源缓存</h1>
      <p>英雄和装备支持全量预下载；玩家头像按战绩查询自动缓存。稳定文件名使用资源类型与数字 ID。</p>
    </div>
    <div class="actions">
      <a class="button" href="/">返回总控台</a>
      <input id="adminToken" type="password" placeholder="管理令牌（本机可留空）">
      <button onclick="saveToken()">应用令牌</button>
      <button class="primary" onclick="loadStatus()">刷新状态</button>
    </div>
  </header>

  <section class="cards">
    <div class="card"><div class="label">缓存状态</div><div class="value" id="enabled">-</div><div class="sub" id="ttl">-</div></div>
    <div class="card"><div class="label">英雄图标</div><div class="value" id="champions">0</div><div class="sub">champion/{ID}.png</div></div>
    <div class="card"><div class="label">装备图标</div><div class="value" id="items">0</div><div class="sub">item/{ID}.png</div></div>
    <div class="card"><div class="label">玩家头像</div><div class="value" id="profiles">0</div><div class="sub">profile/{ID}.png</div></div>
  </section>

  <div class="grid">
    <section class="panel">
      <div class="panel-head"><div><h2>缓存配置</h2><div class="hint">在总控台“主接口配置 → 图片资源缓存”修改，保存后重启 LOLDataSystem 生效。</div></div></div>
      <div class="kv" id="cacheKv"></div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><h2>批量操作</h2><div class="hint">更新采用临时文件校验后原子覆盖；下载失败会继续保留旧图。</div></div></div>
      <div class="toolbar">
        <button id="missingBtn" class="primary" onclick="startSync('missing')">下载缺失资源</button>
        <button id="updateBtn" class="warn" onclick="startSync('update')">检查并更新全部</button>
      </div>
      <p class="hint">“下载缺失资源”适合首次部署；“检查并更新全部”会重新下载英雄、装备及已缓存的玩家头像，并按内容哈希判断是否变化。</p>
    </section>
  </div>

  <section class="panel">
    <div class="panel-head"><h2>任务进度</h2><span id="jobBadge" class="status">空闲</span></div>
    <div class="progress"><div id="progressBar" class="bar"></div></div>
    <div class="kv" id="jobKv" style="margin-top:12px"></div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>详细状态</h2><span class="hint">最多显示 50 个失败项目</span></div>
    <pre id="rawStatus">尚未读取</pre>
  </section>
</main>
<div id="toast" class="toast"></div>
<script>
const $=id=>document.getElementById(id);
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg,err=false){const t=$('toast');t.textContent=msg;t.className='toast'+(err?' err':'');t.style.display='block';clearTimeout(t._timer);t._timer=setTimeout(()=>t.style.display='none',4500)}
function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
function saveToken(){const value=$('adminToken').value.trim();if(value)sessionStorage.setItem('lolapisevers_admin_token',value);else sessionStorage.removeItem('lolapisevers_admin_token');toast(value?'管理令牌已保存到当前会话':'已清除管理令牌');loadStatus()}
async function api(path,opt={}){const headers={'content-type':'application/json'};const value=token();if(value)headers['x-admin-token']=value;const response=await fetch(path,{method:opt.method||'GET',headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const text=await response.text();let data;try{data=JSON.parse(text)}catch{data={ok:false,error:text}}if(!response.ok)throw new Error(data.error||data.detail||text||response.statusText);return data}
function bytes(value){let n=Number(value)||0;const units=['B','KB','MB','GB'];let i=0;while(n>=1024&&i<units.length-1){n/=1024;i++}return `${n.toFixed(i?2:0)} ${units[i]}`}
function render(data){const cache=data.cache||{},job=data.job||{},counts=cache.counts||{};$('enabled').textContent=cache.enabled?'已启用':'已关闭';$('enabled').style.color=cache.enabled?'var(--green)':'var(--red)';$('ttl').textContent=`有效期：${cache.ttl_label||'-'}`;$('champions').textContent=counts.champion||0;$('items').textContent=counts.item||0;$('profiles').textContent=counts.profile||0;const cacheRows=[['缓存目录',cache.root||'-'],['有效期',cache.ttl_label||'-'],['总文件',cache.total_files||0],['占用空间',bytes(cache.total_bytes)],['已过期文件',cache.expired_files||0],['最后更新',cache.last_updated_at||'-']];$('cacheKv').innerHTML=cacheRows.map(r=>`<div>${esc(r[0])}</div><div>${esc(r[1])}</div>`).join('');const total=Number(job.total)||0,completed=Number(job.completed)||0,percent=total?Math.min(100,completed/total*100):(job.running?0:100);$('progressBar').style.width=`${percent}%`;const badge=$('jobBadge');badge.textContent=job.running?'运行中':job.error?'失败':'空闲';badge.className='status '+(job.running?'warn':job.error?'bad':'ok');const jobRows=[['模式',job.mode||'-'],['进度',`${completed} / ${total}`],['新下载',job.downloaded||0],['已更新',job.updated||0],['无变化',job.unchanged||0],['已存在',job.cached||0],['保留旧图',job.stale||0],['失败',job.failed||0],['开始时间',job.started_at||'-'],['完成时间',job.finished_at||'-'],['任务错误',job.error||'-']];$('jobKv').innerHTML=jobRows.map(r=>`<div>${esc(r[0])}</div><div>${esc(r[1])}</div>`).join('');$('rawStatus').textContent=JSON.stringify(data,null,2);$('missingBtn').disabled=!!job.running;$('updateBtn').disabled=!!job.running;if(job.running){clearTimeout(window._poll);window._poll=setTimeout(loadStatus,1500)}}
async function loadStatus(){try{render(await api('/admin/image-cache'))}catch(error){toast(error.message,true)}}
async function startSync(mode){const label=mode==='update'?'检查并更新全部图片':'下载全部缺失图片';if(!confirm(`${label}？任务会在接口端后台执行。`))return;try{const data=await api('/admin/image-cache/sync',{method:'POST',body:{mode}});render(data);toast('图片同步任务已启动')}catch(error){toast(error.message,true)}}
$('adminToken').value=token();loadStatus();
</script>
</body>
</html>"""
