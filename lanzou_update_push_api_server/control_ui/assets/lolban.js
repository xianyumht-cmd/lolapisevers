const S={parser:[],legacy:[],runtime:{},providerSecrets:{}};
const $=id=>document.getElementById(id);

function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function attr(v){return esc(v)}
function pretty(v){return JSON.stringify(v??{},null,2)}
function obj(v,f={}){return v&&typeof v==='object'&&!Array.isArray(v)?v:f}

function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
function saveToken(){const v=$('adminToken').value.trim();if(v)sessionStorage.setItem('lolapisevers_admin_token',v);else sessionStorage.removeItem('lolapisevers_admin_token');loadAll()}

async function api(path,opt={}){
  const headers={'content-type':'application/json'};
  if(token())headers['x-admin-token']=token();
  const r=await fetch(path,{method:opt.method||'GET',headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});
  const t=await r.text();
  let d;
  try{d=JSON.parse(t)}catch(_e){d={ok:false,error:t}}
  if(!r.ok)throw new Error(d.detail||d.error||t||r.statusText);
  return d;
}

function parseJson(text,label,fallback){try{return JSON.parse(text||JSON.stringify(fallback))}catch(e){throw new Error(label+' JSON 无效：'+e.message)}}
function normalize(p,i){p=obj(p);const req=obj(p.request,p);return {id:p.id||p.name||`provider-${i+1}`,name:p.name||p.id||`Provider ${i+1}`,enabled:p.enabled!==false,request:{method:(req.method||'GET').toUpperCase(),url:req.url||p.url||'',timeout_seconds:req.timeout_seconds||p.timeout_seconds||10,headers:obj(req.headers),query:obj(req.query),form:obj(req.form),json:req.json??req.json_body??null},parser:obj(p.parser)}}

function providerSecretControl(p){
  const state=S.providerSecrets[p.id];
  if(!state)return '';
  const ready=state.disk_configured&&state.runtime_configured;
  const partial=state.disk_configured&&!state.runtime_configured;
  const status=ready?'已配置并加载':(partial?'磁盘已配置，5001 未加载':'未配置');
  const statusClass=ready?'ok':'bad';
  return `<div class="provider-secret"><div><div class="provider-secret-title">${esc(state.label||'Provider Token')}</div><div class="provider-secret-meta">${esc(state.secret_name||'')}</div><span class="provider-secret-state ${statusClass}">${esc(status)}</span></div><label><span>输入新 Token（留空不修改）</span><input type="password" autocomplete="new-password" data-secret-provider="${attr(p.id)}" placeholder="仅安全写入本机 Secret"></label><button type="button" onclick="saveProviderSecret('${attr(p.id)}')">保存 Token</button></div>`;
}

function card(kind,p,index){
  p=normalize(p,index);
  return `<div class="provider" data-kind="${kind}" data-index="${index}"><div class="head"><h3>${esc(p.name||p.id)}</h3><div class="actions"><label class="switch"><input data-f="enabled" type="checkbox" ${p.enabled?'checked':''}><span>启用</span></label><button class="danger" onclick="removeProvider('${kind}',${index})">删除</button></div></div><div class="grid"><label><span>ID</span><input data-f="id" value="${attr(p.id)}"></label><label><span>名称</span><input data-f="name" value="${attr(p.name)}"></label><label><span>方法</span><select data-f="method"><option ${p.request.method==='GET'?'selected':''}>GET</option><option ${p.request.method==='POST'?'selected':''}>POST</option></select></label><label><span>超时秒数</span><input data-f="timeout" type="number" value="${attr(p.request.timeout_seconds)}"></label></div><label><span>API URL（敏感参数显示 ***）</span><input data-f="url" value="${attr(p.request.url)}"></label>${providerSecretControl(p)}<div class="grid two"><label><span>Query JSON</span><textarea data-f="query">${esc(pretty(p.request.query))}</textarea></label><label><span>Form JSON</span><textarea data-f="form">${esc(pretty(p.request.form))}</textarea></label><label><span>Headers JSON（敏感值显示 ***）</span><textarea data-f="headers">${esc(pretty(p.request.headers))}</textarea></label><label><span>JSON Body</span><textarea data-f="json">${esc(pretty(p.request.json))}</textarea></label></div><label><span>响应解析规则 JSON</span><textarea data-f="parser">${esc(pretty(p.parser))}</textarea></label></div>`;
}

function render(){
  $('parserProviders').innerHTML=S.parser.map((p,i)=>card('parser',p,i)).join('')||'<div class="hint">暂无解析中心 Provider</div>';
  $('legacyProviders').innerHTML=S.legacy.map((p,i)=>card('legacy',p,i)).join('')||'<div class="hint">暂无旧环境变量 Provider</div>';
}

function addProvider(kind){S[kind].push({id:`lolban-${kind}-${Date.now()}`,name:'新封号 Provider',enabled:false,request:{method:'GET',url:'https://',timeout_seconds:10,headers:{},query:{qq:'$qq'},form:{},json:null},parser:{}});render()}
function removeProvider(kind,index){S[kind].splice(index,1);render()}

function collect(kind){
  return [...document.querySelectorAll(`[data-kind="${kind}"]`)].map((el,i)=>({
    id:el.querySelector('[data-f="id"]').value.trim(),
    name:el.querySelector('[data-f="name"]').value.trim(),
    enabled:el.querySelector('[data-f="enabled"]').checked,
    request:{
      method:el.querySelector('[data-f="method"]').value,
      url:el.querySelector('[data-f="url"]').value.trim(),
      timeout_seconds:Number(el.querySelector('[data-f="timeout"]').value||10),
      headers:parseJson(el.querySelector('[data-f="headers"]').value,`Provider ${i+1} Headers`,{}),
      query:parseJson(el.querySelector('[data-f="query"]').value,`Provider ${i+1} Query`,{}),
      form:parseJson(el.querySelector('[data-f="form"]').value,`Provider ${i+1} Form`,{}),
      json:parseJson(el.querySelector('[data-f="json"]').value,`Provider ${i+1} JSON Body`,null)
    },
    parser:parseJson(el.querySelector('[data-f="parser"]').value,`Provider ${i+1} Parser`,{})
  }))
}

function setState(d){
  const disk=d.disk||{},runtime=d.runtime||{};
  S.parser=disk.parser_center?.providers||[];
  S.legacy=disk.legacy?.providers||[];
  S.runtime=runtime;
  S.providerSecrets=d.provider_secrets||{};
  $('parserPath').textContent=`配置文件：${disk.parser_center?.path||'-'}${disk.parser_center?.using_default?'（当前使用默认模板）':''}`;
  $('legacyPath').textContent=`配置文件：${disk.legacy?.path||'-'}`;
  $('legacyError').textContent=disk.legacy?.error||'';
  const st=disk.settings||{};
  $('sTimeout').value=st.LOL_BAN_TIMEOUT||10;
  $('sNormal').value=st.LOL_BAN_NORMAL_CACHE_SECONDS||60;
  $('sBanned').value=st.LOL_BAN_BANNED_CACHE_SECONDS||300;
  $('sStale').value=st.LOL_BAN_STALE_CACHE_SECONDS||86400;
  $('sMax').value=st.LOL_BAN_MAX_STALE_ENTRIES||1024;
  $('sSnapshot').checked=!['0','false','no','off',''].includes(String(st.LOL_BAN_SNAPSHOT_ENABLED??'1').toLowerCase());
  $('legacyUrl').value=disk.legacy?.upstream_url||'';
  $('diskCount').textContent=(disk.active_provider_identity||[]).length;
  $('runtimeCount').textContent=runtime.provider_count??'-';
  $('matchState').textContent=d.runtime_matches_disk?'一致':'不一致';
  $('matchState').className=d.runtime_matches_disk?'ok':'bad';
  const h=runtime.health||{};
  $('healthState').textContent=h.last_error_class?`失败：${h.last_error_class}`:(h.configured?'已配置':'未配置');
  $('healthState').className=h.last_error_class?'bad':'ok';
  $('runtimeResult').textContent=pretty(runtime);
  $('testProvider').innerHTML=(runtime.providers||[]).map(p=>`<option value="${attr(p.id||p.name)}">${esc((p.order||'')+' · '+(p.name||p.id||''))}</option>`).join('');
  render();
}

async function loadAll(){try{setState(await api('/admin/query-console/lolban'))}catch(e){alert(e.message)}}

async function saveAll(){
  try{
    const body={
      parser_providers:collect('parser'),
      legacy_providers:collect('legacy'),
      legacy_upstream_url:$('legacyUrl').value.trim(),
      settings:{
        LOL_BAN_TIMEOUT:Number($('sTimeout').value),
        LOL_BAN_NORMAL_CACHE_SECONDS:Number($('sNormal').value),
        LOL_BAN_BANNED_CACHE_SECONDS:Number($('sBanned').value),
        LOL_BAN_STALE_CACHE_SECONDS:Number($('sStale').value),
        LOL_BAN_MAX_STALE_ENTRIES:Number($('sMax').value),
        LOL_BAN_SNAPSHOT_ENABLED:$('sSnapshot').checked
      }
    };
    const r=await api('/admin/query-console/lolban/save',{method:'POST',body});
    alert(r.message||'保存完成');
    setState(r.state);
  }catch(e){alert(e.message)}
}

async function saveProviderSecret(providerId){
  const input=Array.from(document.querySelectorAll('[data-secret-provider]')).find(item=>item.dataset.secretProvider===providerId);
  const value=input?input.value.trim():'';
  if(!value){alert('请输入新的 Token');return}
  try{
    const r=await api('/admin/query-console/lolban/provider-secret',{method:'POST',body:{provider_id:providerId,value}});
    input.value='';
    alert(r.message||'Token 已安全保存');
    await loadAll();
  }catch(e){alert(e.message)}
}

async function runProviderTest(){
  try{
    $('providerResult').textContent='测试中...';
    const r=await api('/admin/query-console/lolban/test',{method:'POST',body:{mode:'provider',qq:$('testQQ').value.trim(),provider_id:$('testProvider').value}});
    $('providerResult').textContent=pretty(r.provider_test);
  }catch(e){$('providerResult').textContent=e.message}
}

async function runFormalTest(){
  try{
    $('formalResult').textContent='测试中...';
    const r=await api('/admin/query-console/lolban/test',{method:'POST',body:{mode:'formal',qq:$('testQQ').value.trim(),provider_id:$('testProvider').value}});
    $('formalResult').textContent=pretty(r.formal_chain);
  }catch(e){$('formalResult').textContent=e.message}
}

async function runTest(){await runProviderTest();await runFormalTest()}

$('adminToken').value=token();
loadAll();
