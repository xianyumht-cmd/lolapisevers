from __future__ import annotations


def render_parser_center_page() -> str:
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>接口与解析中心</title>
<style>
:root{color-scheme:light dark;--bg:#eef2f8;--panel:rgba(255,255,255,.8);--panel2:rgba(247,250,255,.76);--text:#172033;--muted:#66758b;--line:rgba(128,145,170,.28);--primary:#2563eb;--danger:#b42318;--green:#16845b;--amber:#a66b05;--code:#101827;--shadow:0 18px 55px rgba(31,45,70,.14)}
@media(prefers-color-scheme:dark){:root{--bg:#0d1421;--panel:rgba(25,36,54,.84);--panel2:rgba(14,23,38,.78);--text:#e7edf7;--muted:#a8b4c7;--line:rgba(170,190,220,.2);--primary:#6ea0ff;--danger:#ff8b82;--green:#55d49a;--amber:#f2be63;--code:#060a11;--shadow:0 18px 55px rgba(0,0,0,.32)}}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0%,rgba(90,140,255,.18),transparent 34%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1600px;margin:auto;padding:20px}.glass{background:var(--panel);backdrop-filter:blur(24px) saturate(135%);-webkit-backdrop-filter:blur(24px) saturate(135%);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}header{padding:20px;margin-bottom:14px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}h1{font-size:27px;margin:0 0 7px}h2{font-size:17px;margin:0}h3{font-size:14px;margin:0 0 9px}.hint{color:var(--muted);font-size:12px;line-height:1.6}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button,a.button{appearance:none;border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:12px;padding:9px 12px;font:inherit;font-weight:740;cursor:pointer;text-decoration:none}button:hover,a.button:hover{border-color:var(--primary)}button.primary{background:var(--primary);border-color:transparent;color:white}button.danger{color:var(--danger)}button.active{background:var(--primary);border-color:transparent;color:white}button:disabled{opacity:.5;cursor:not-allowed}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:12px;background:var(--panel2);color:var(--text);padding:9px;font:inherit}textarea{min-height:94px;resize:vertical;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.tabs{display:flex;gap:8px;margin:0 0 14px;flex-wrap:wrap}.tab-panel.hidden{display:none}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:14px}.side{padding:14px;align-self:start;position:sticky;top:12px}.panel{padding:16px}.section{border:1px solid var(--line);background:var(--panel2);border-radius:16px;padding:13px;margin-bottom:12px}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:11px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.fields.three{grid-template-columns:repeat(3,minmax(0,1fr))}.field span{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}.switch{display:flex;align-items:center;gap:8px;min-height:40px}.switch input{width:auto}.list{display:grid;gap:6px;max-height:290px;overflow:auto}.list button{text-align:left;width:100%;font-size:12px;word-break:break-all}.badge{display:inline-flex;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:800;background:rgba(90,120,170,.14);margin-left:5px}.badge.ok{color:var(--green)}.badge.warn{color:var(--amber)}.result{white-space:pre-wrap;word-break:break-word;background:var(--code);color:#e5e7eb;border-radius:14px;padding:13px;min-height:120px;max-height:500px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.result.light{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.tree{background:var(--code);color:#e5e7eb;border-radius:14px;padding:10px;max-height:500px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.tree-row{padding-left:14px;border-left:1px solid rgba(255,255,255,.14)}.path-button{border:0;background:transparent;color:#91b8ff;padding:2px 3px;font:inherit;font-weight:700}.path-button:hover{text-decoration:underline;border:0}.scalar{color:#c8e6c9}.null{color:#f5c2c7}.policy{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.policy div{border:1px solid var(--line);border-radius:13px;padding:9px;font-size:11px}.ok{color:var(--green)}.divider{height:1px;background:var(--line);margin:13px 0}.toast{display:none;position:fixed;right:18px;bottom:18px;max-width:600px;padding:12px 15px;border-radius:13px;background:#111827;color:white;box-shadow:var(--shadow);z-index:30}.toast.bad{background:#7f1d1d;color:white}.empty{padding:14px;text-align:center;color:var(--muted);font-size:12px;border:1px dashed var(--line);border-radius:13px}.advanced{min-height:580px}.small{font-size:11px}.capture{display:grid;grid-template-columns:1fr 1.4fr auto;gap:8px;align-items:end}@media(max-width:1050px){.layout{grid-template-columns:1fr}.side{position:static}.fields.three{grid-template-columns:1fr 1fr}}@media(max-width:760px){.shell{padding:10px}header{display:block}.toolbar{margin-top:10px}.fields,.fields.three,.two,.policy,.capture{grid-template-columns:1fr}.layout{display:block}.side{margin-bottom:12px}}
</style>
</head>
<body>
<main class="shell">
<header class="glass">
  <div><h1>接口与解析中心</h1><div class="hint">第三方请求、字段解析、命中判定和机器人输出统一在 Windows 接口完成。正式消息禁止出现第三方域名、Provider、by 或接口来源。</div></div>
  <div class="toolbar"><input id="adminToken" type="password" placeholder="管理令牌（本机可留空）" style="width:220px"><button type="button" onclick="saveToken()">应用令牌</button><button type="button" onclick="loadConfig()">刷新</button><a class="button" href="/">返回控制台</a></div>
</header>
<nav class="tabs">
  <button class="active" data-tab="visual">可视化配置</button>
  <button data-tab="advanced">高级 JSON</button>
  <button data-tab="backups">Secret 与备份</button>
</nav>
<section id="tab-visual" class="tab-panel">
  <div class="layout">
    <aside class="glass side">
      <div class="panel-head"><h2>功能列表</h2><button type="button" onclick="addFeature()">新增</button></div>
      <div id="featureList" class="list"></div>
      <div class="divider"></div>
      <div class="panel-head"><h2>Provider</h2><button type="button" onclick="addProvider()">新增</button></div>
      <div id="providerList" class="list"></div>
      <div class="toolbar" style="margin-top:10px"><button type="button" class="danger" onclick="deleteProvider()">删除 Provider</button><button type="button" class="danger" onclick="deleteFeature()">删除功能</button></div>
    </aside>
    <div>
      <section class="glass panel">
        <div class="panel-head"><div><h2>请求设置</h2><div class="hint" id="selectionHint">请选择功能和 Provider</div></div><div class="toolbar"><button type="button" onclick="applyVisual()">应用到配置</button><button type="button" onclick="validateVisual()">校验当前配置</button><button type="button" class="primary" onclick="saveVisual()">保存全部</button></div></div>
        <div id="editorEmpty" class="empty">当前功能还没有 Provider。点击左侧“新增”。</div>
        <div id="editor" class="hidden">
          <div class="section">
            <div class="fields three">
              <label class="field"><span>功能 ID</span><input id="featureId" readonly></label>
              <label class="field"><span>操作类型</span><select id="featureOperation"><option value="query">查询 query</option><option value="report">举报 report</option></select></label>
              <label class="field"><span>Provider ID</span><input id="providerId"></label>
              <label class="field"><span>管理员名称</span><input id="providerName" placeholder="只在管理后台显示"></label>
              <label class="field"><span>请求方法</span><select id="requestMethod"><option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option></select></label>
              <label class="field"><span>超时（秒）</span><input id="requestTimeout" type="number" min="1" max="60" value="10"></label>
            </div>
            <label class="field" style="display:block;margin-top:9px"><span>请求 URL</span><input id="requestUrl" placeholder="https://example.com/api"></label>
            <label class="switch"><input id="providerEnabled" type="checkbox"><span>启用此 Provider（未完成测试前不要启用）</span></label>
          </div>
          <div class="section">
            <h3>参数映射</h3>
            <div class="fields">
              <label class="field"><span>Query JSON</span><textarea id="requestQuery">{}</textarea></label>
              <label class="field"><span>Headers JSON</span><textarea id="requestHeaders">{}</textarea></label>
              <label class="field"><span>Form JSON</span><textarea id="requestForm">{}</textarea></label>
              <label class="field"><span>JSON Body</span><textarea id="requestJson">{}</textarea></label>
            </div>
            <div class="hint">参数使用 <code>$qq</code>、<code>$identifier</code>、<code>$content</code> 等；密钥必须使用 <code>$secret:环境变量名</code>。</div>
          </div>
          <div class="section">
            <h3>成功条件与结果判定</h3>
            <div class="fields three">
              <label class="field"><span>成功字段路径</span><input id="successPath" placeholder="code"></label>
              <label class="field"><span>操作符</span><select id="successOp"><option value="eq">等于</option><option value="ne">不等于</option><option value="in">包含于数组</option><option value="truthy">真值</option><option value="exists">存在</option></select></label>
              <label class="field"><span>目标值（JSON 标量）</span><input id="successValue" value="200"></label>
            </div>
            <label class="field" style="display:block;margin-top:9px"><span>结果规则 outcomes JSON</span><textarea id="parserOutcomes">[]</textarea></label>
          </div>
          <div class="section">
            <h3>字段与数组解析</h3>
            <div class="fields">
              <label class="field"><span>字段映射 fields JSON</span><textarea id="parserFields">{}</textarea></label>
              <label class="field"><span>数组记录 records JSON</span><textarea id="parserRecords">{}</textarea></label>
            </div>
            <div class="capture">
              <label class="field"><span>变量名称</span><input id="captureName" placeholder="ban_reason"></label>
              <label class="field"><span>从响应树点击得到的字段路径</span><input id="capturePath" placeholder="data.ban_reason"></label>
              <button type="button" onclick="addCapturedField()">加入字段映射</button>
            </div>
          </div>
          <div class="section">
            <h3>机器人输出模板</h3>
            <label class="field"><span>templates JSON（按 hit、clear、accepted、rejected 等结果分别配置）</span><textarea id="parserTemplates">{}</textarea></label>
          </div>
        </div>
      </section>
      <section class="glass panel" style="margin-top:14px">
        <div class="panel-head"><div><h2>请求测试与解析预览</h2><div class="hint">使用当前页面尚未保存的 Provider 配置测试，不会改变生产。</div></div><button type="button" class="primary" onclick="runVisualTest()">请求并解析</button></div>
        <label class="field"><span>测试参数 JSON</span><textarea id="testParameters" style="min-height:84px">{"qq":"97077000"}</textarea></label>
        <div class="two" style="margin-top:10px">
          <div><div class="panel-head"><h3>脱敏请求与响应</h3><span class="hint">点击响应字段可复制路径</span></div><div id="responseTree" class="tree">暂无</div><details style="margin-top:8px"><summary class="hint">查看完整脱敏 JSON</summary><pre id="rawResult" class="result">暂无</pre></details></div>
          <div><div class="panel-head"><h3>机器人最终文本</h3><span class="hint">不得出现第三方来源</span></div><pre id="publicResult" class="result light">暂无</pre></div>
        </div>
      </section>
    </div>
  </div>
</section>
<section id="tab-advanced" class="tab-panel hidden">
  <div class="glass panel">
    <div class="panel-head"><div><h2>高级 JSON</h2><div class="hint" id="configMeta">正在读取...</div></div><div class="toolbar"><button type="button" onclick="syncAdvancedFromVisual()">从可视化刷新</button><button type="button" onclick="applyAdvanced()">应用 JSON</button><button type="button" onclick="validateAdvanced()">校验</button><button type="button" class="primary" onclick="saveAdvanced()">保存</button></div></div>
    <textarea id="configText" class="advanced" spellcheck="false"></textarea>
    <div class="policy"><div><strong>公开输出</strong><br><span class="ok">不显示第三方来源</span></div><div><strong>敏感字段</strong><br><span class="ok">Secret 仅服务端解析</span></div><div><strong>保存策略</strong><br><span class="ok">校验、备份、原子替换</span></div></div>
  </div>
</section>
<section id="tab-backups" class="tab-panel hidden">
  <div class="two">
    <div class="glass panel">
      <div class="panel-head"><div><h2>Secret 配置</h2><div class="hint">值只写入本机环境文件，不回显、不写入普通配置。</div></div><button type="button" onclick="saveSecret()">保存 Secret</button></div>
      <div class="fields"><label class="field"><span>Secret 名称</span><select id="secretName"></select></label><label class="field"><span>新值（不会回显）</span><input id="secretValue" type="password" autocomplete="new-password"></label></div>
      <div id="secretState" class="hint" style="margin-top:9px">尚未读取</div>
    </div>
    <div class="glass panel">
      <div class="panel-head"><div><h2>配置备份与回滚</h2><div class="hint">保存和回滚前都会保留上一版本。</div></div><button type="button" onclick="loadBackups()">刷新</button></div>
      <select id="backupSelect"><option value="">暂无备份</option></select>
      <button type="button" class="danger" style="margin-top:10px" onclick="rollbackBackup()">回滚所选版本</button>
    </div>
  </div>
</section>
</main>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);
const S={config:{schema:'lapi-parser-center.v1',features:{}},feature:'',providerIndex:0,secrets:[]};
function esc(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
function saveToken(){const value=$('adminToken').value.trim();if(value)sessionStorage.setItem('lolapisevers_admin_token',value);else sessionStorage.removeItem('lolapisevers_admin_token');toast(value?'管理令牌已保存到当前会话':'已清除管理令牌');loadConfig()}
function toast(message,bad=false){const node=$('toast');node.textContent=message;node.className='toast'+(bad?' bad':'');node.style.display='block';clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>node.style.display='none',4300)}
async function api(path,opt={}){const headers={'content-type':'application/json'};if(token())headers['x-admin-token']=token();const response=await fetch(path,{method:opt.method||'GET',headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const text=await response.text();let data;try{data=JSON.parse(text)}catch(_){data={detail:text}}if(!response.ok)throw new Error(data.detail||data.error||text||response.statusText);return data}
function parseJsonText(id,fallback){const text=$(id).value.trim();if(!text)return structuredClone(fallback);try{return JSON.parse(text)}catch(error){throw new Error(`${id} JSON 无效：${error.message}`)}}
function parseScalar(text){const value=String(text??'').trim();if(!value)return '';try{return JSON.parse(value)}catch(_){return value}}
function featureConfig(){return S.config.features&&S.config.features[S.feature]||null}
function currentProvider(){const feature=featureConfig();return feature&&Array.isArray(feature.providers)?feature.providers[S.providerIndex]||null:null}
function ensureShape(){if(!S.config||typeof S.config!=='object')S.config={};S.config.schema='lapi-parser-center.v1';if(!S.config.features||typeof S.config.features!=='object'||Array.isArray(S.config.features))S.config.features={}}
function renderFeatures(){ensureShape();const names=Object.keys(S.config.features);if(!names.length){$('featureList').innerHTML='<div class="empty">暂无功能</div>';S.feature='';renderProviders();showEditor();return}if(!S.feature||!S.config.features[S.feature])S.feature=names[0];$('featureList').innerHTML=names.map(name=>{const f=S.config.features[name]||{};const count=Array.isArray(f.providers)?f.providers.length:0;return `<button type="button" class="${name===S.feature?'active':''}" data-feature="${esc(name)}">${esc(name)}<span class="badge">${esc(f.operation||'query')}</span><span class="badge ${count?'ok':'warn'}">${count}</span></button>`}).join('');document.querySelectorAll('[data-feature]').forEach(btn=>btn.onclick=()=>{applyVisualQuiet();S.feature=btn.dataset.feature;S.providerIndex=0;renderFeatures();renderProviders();showEditor()});renderProviders()}
function renderProviders(){const feature=featureConfig();const providers=feature&&Array.isArray(feature.providers)?feature.providers:[];if(S.providerIndex>=providers.length)S.providerIndex=Math.max(0,providers.length-1);$('providerList').innerHTML=providers.length?providers.map((p,index)=>`<button type="button" class="${index===S.providerIndex?'active':''}" data-provider-index="${index}">${esc(p.id||`provider-${index+1}`)}<span class="badge ${p.enabled?'ok':'warn'}">${p.enabled?'启用':'停用'}</span></button>`).join(''):'<div class="empty">暂无 Provider</div>';document.querySelectorAll('[data-provider-index]').forEach(btn=>btn.onclick=()=>{applyVisualQuiet();S.providerIndex=Number(btn.dataset.providerIndex);renderProviders();showEditor()});showEditor()}
function showEditor(){const feature=featureConfig();const provider=currentProvider();const visible=!!(feature&&provider);$('editor').classList.toggle('hidden',!visible);$('editorEmpty').classList.toggle('hidden',visible);if(!visible){$('selectionHint').textContent=S.feature?`${S.feature} 尚无 Provider`:'尚未选择功能';return}$('selectionHint').textContent=`${S.feature} / ${provider.id||'未命名'}`;$('featureId').value=S.feature;$('featureOperation').value=feature.operation||'query';$('providerId').value=provider.id||'';$('providerName').value=provider.name||'';$('providerEnabled').checked=provider.enabled===true;const request=provider.request&&typeof provider.request==='object'?provider.request:{};$('requestMethod').value=String(request.method||'GET').toUpperCase();$('requestUrl').value=request.url||'';$('requestTimeout').value=request.timeout_seconds||10;$('requestQuery').value=JSON.stringify(request.query||{},null,2);$('requestHeaders').value=JSON.stringify(request.headers||{},null,2);$('requestForm').value=JSON.stringify(request.form||{},null,2);$('requestJson').value=JSON.stringify(request.json??request.json_body??{},null,2);const parser=provider.parser&&typeof provider.parser==='object'?provider.parser:{};const success=parser.success&&typeof parser.success==='object'?parser.success:{};$('successPath').value=success.path||'';$('successOp').value=success.op||'eq';$('successValue').value=success.value===undefined?'':JSON.stringify(success.value);$('parserOutcomes').value=JSON.stringify(parser.outcomes||parser.outcome_rules||[],null,2);$('parserFields').value=JSON.stringify(parser.fields||{},null,2);$('parserRecords').value=JSON.stringify(parser.records||{},null,2);$('parserTemplates').value=JSON.stringify(parser.templates||{},null,2);refreshSecretOptions()}
function collectVisual(){const feature=featureConfig();const provider=currentProvider();if(!feature||!provider)return null;feature.operation=$('featureOperation').value;provider.id=$('providerId').value.trim();provider.name=$('providerName').value.trim();provider.enabled=$('providerEnabled').checked;provider.request={method:$('requestMethod').value,url:$('requestUrl').value.trim(),timeout_seconds:Number($('requestTimeout').value||10),query:parseJsonText('requestQuery',{}),headers:parseJsonText('requestHeaders',{}),form:parseJsonText('requestForm',{}),json:parseJsonText('requestJson',{})};const successPath=$('successPath').value.trim();const successOp=$('successOp').value;const success={};if(successPath)success.path=successPath;if(successOp)success.op=successOp;if(!['truthy','falsy','exists','not_exists'].includes(successOp))success.value=parseScalar($('successValue').value);provider.parser={success,outcomes:parseJsonText('parserOutcomes',[]),fields:parseJsonText('parserFields',{}),records:parseJsonText('parserRecords',{}),templates:parseJsonText('parserTemplates',{})};return provider}
function applyVisualQuiet(){try{collectVisual()}catch(_){}}
function applyVisual(){try{collectVisual();syncAdvancedFromVisual();renderFeatures();toast('当前表单已应用到配置草稿')}catch(error){toast(error.message,true)}}
function addFeature(){applyVisualQuiet();const name=prompt('输入功能 ID，例如 scammer、peer_report：');if(!name)return;const id=name.trim();if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$/.test(id)){toast('功能 ID 格式无效',true);return}ensureShape();if(S.config.features[id]){toast('功能已存在',true);return}S.config.features[id]={operation:id.endsWith('_report')?'report':'query',providers:[]};S.feature=id;S.providerIndex=0;renderFeatures();toast('功能已新增，请继续添加 Provider')}
function deleteFeature(){if(!S.feature)return;if(!confirm(`确认删除功能 ${S.feature}？`))return;delete S.config.features[S.feature];S.feature='';S.providerIndex=0;renderFeatures();refreshSecretOptions()}
function addProvider(){if(!S.feature){toast('请先新增或选择功能',true);return}applyVisualQuiet();const feature=featureConfig();if(!Array.isArray(feature.providers))feature.providers=[];const id=`${S.feature}-provider-${feature.providers.length+1}`;feature.providers.push({id,name:'',enabled:false,request:{method:'GET',url:'https://',query:{},headers:{},form:{},json:{},timeout_seconds:10},parser:{success:{path:'code',op:'eq',value:200},outcomes:[],fields:{},records:{},templates:{}}});S.providerIndex=feature.providers.length-1;renderProviders();showEditor();toast('Provider 已新增，完成测试前保持停用')}
function deleteProvider(){const feature=featureConfig();const provider=currentProvider();if(!feature||!provider)return;if(!confirm(`确认删除 Provider ${provider.id||''}？`))return;feature.providers.splice(S.providerIndex,1);S.providerIndex=Math.max(0,S.providerIndex-1);renderProviders();refreshSecretOptions()}
function allSecretNames(){applyVisualQuiet();const found=new Set();function walk(value){if(Array.isArray(value))value.forEach(walk);else if(value&&typeof value==='object')Object.values(value).forEach(walk);else if(typeof value==='string'){const m=value.trim().match(/^\$secret:([A-Za-z_][A-Za-z0-9_]*)$/);if(m)found.add(m[1])}}walk(S.config);return [...found].sort()}
function refreshSecretOptions(){const names=allSecretNames();const status=new Map((S.secrets||[]).map(item=>[item.name,item.configured]));$('secretName').innerHTML=names.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('');$('secretState').textContent=names.map(name=>`${name}：${status.get(name)?'已配置':'未配置'}`).join('；')||'当前配置没有 Secret 引用'}
async function loadConfig(){try{const data=await api('/admin/parser-center');S.config=structuredClone(data.config||{schema:'lapi-parser-center.v1',features:{}});S.secrets=data.secrets||[];ensureShape();S.feature=Object.keys(S.config.features)[0]||'';S.providerIndex=0;$('configMeta').textContent=`${data.path} · ${data.exists?'正式配置':'默认模板，尚未落盘'}`;renderFeatures();syncAdvancedFromVisual();refreshSecretOptions();await loadBackups(false);toast('解析配置已读取')}catch(error){toast(error.message,true)}}
function syncAdvancedFromVisual(){applyVisualQuiet();$('configText').value=JSON.stringify(S.config,null,2)}
function applyAdvanced(){try{const value=JSON.parse($('configText').value);S.config=value;ensureShape();S.feature=Object.keys(S.config.features)[0]||'';S.providerIndex=0;renderFeatures();refreshSecretOptions();toast('高级 JSON 已应用到可视化草稿')}catch(error){toast('配置 JSON 无效：'+error.message,true)}}
async function validateObject(config){return api('/admin/parser-center/validate',{method:'POST',body:{config}})}
async function validateVisual(){try{collectVisual();const data=await validateObject(S.config);toast(data.message||'校验通过')}catch(error){toast(error.message,true)}}
async function validateAdvanced(){try{const value=JSON.parse($('configText').value);const data=await validateObject(value);toast(data.message||'校验通过')}catch(error){toast(error.message,true)}}
async function persist(config){if(!confirm('确认保存解析配置？系统会先校验并备份当前版本。'))return;const data=await api('/admin/parser-center',{method:'POST',body:{config}});toast(data.message||'保存完成');await loadConfig()}
async function saveVisual(){try{collectVisual();await persist(S.config)}catch(error){toast(error.message,true)}}
async function saveAdvanced(){try{const value=JSON.parse($('configText').value);await persist(value)}catch(error){toast(error.message,true)}}
async function runVisualTest(){try{const provider=collectVisual();if(!provider)throw new Error('请先选择 Provider');const parameters=JSON.parse($('testParameters').value||'{}');const data=await api('/admin/parser-center/test',{method:'POST',body:{provider,parameters}});$('rawResult').textContent=JSON.stringify({request:data.request,response:data.response,parsed:data.parsed},null,2);$('publicResult').textContent=data.public_text||'解析成功，但当前结果模板为空';renderResponseTree(data.response&&data.response.payload);toast('测试请求和解析完成')}catch(error){$('rawResult').textContent=error.message;$('responseTree').textContent=error.message;toast(error.message,true)}}
function renderResponseTree(value){const root=$('responseTree');root.innerHTML='';if(value===undefined){root.textContent='响应中没有可展示的数据';return}function walk(node,path,parent){if(node&&typeof node==='object'){const entries=Array.isArray(node)?node.map((v,i)=>[i,v]):Object.entries(node);if(!entries.length){const span=document.createElement('span');span.textContent=Array.isArray(node)?'[]':'{}';parent.appendChild(span);return}for(const [key,val] of entries){const next=path?(Array.isArray(node)?`${path}[${key}]`:`${path}.${key}`):String(key);const row=document.createElement('div');row.className='tree-row';const button=document.createElement('button');button.type='button';button.className='path-button';button.textContent=String(key);button.title='点击复制路径 '+next;button.onclick=()=>pickPath(next);row.appendChild(button);if(val&&typeof val==='object'){walk(val,next,row)}else{const span=document.createElement('span');span.className=val===null?'null':'scalar';span.textContent=': '+JSON.stringify(val);row.appendChild(span)}parent.appendChild(row)}}walk(value,'',root)}
async function pickPath(path){$('capturePath').value=path;try{await navigator.clipboard.writeText(path);toast(`字段路径已复制：${path}`)}catch(_){toast(`字段路径已选择：${path}`)}}
function addCapturedField(){try{const name=$('captureName').value.trim();const path=$('capturePath').value.trim();if(!name||!path)throw new Error('请填写变量名称并从响应树选择路径');const fields=parseJsonText('parserFields',{});fields[name]={paths:[path],string:true};$('parserFields').value=JSON.stringify(fields,null,2);toast(`已添加字段 ${name} ← ${path}`)}catch(error){toast(error.message,true)}}
async function saveSecret(){const name=$('secretName').value;const value=$('secretValue').value;if(!name){toast('当前配置没有 Secret 引用',true);return}if(!value){toast('请输入新的 Secret 值',true);return}try{const data=await api('/admin/parser-center/secret',{method:'POST',body:{name,value}});$('secretValue').value='';toast(data.message||'Secret 已保存');S.secrets=(S.secrets||[]).filter(item=>item.name!==name).concat([{name,configured:true}]);refreshSecretOptions()}catch(error){toast(error.message,true)}}
async function loadBackups(notify=true){try{const data=await api('/admin/parser-center/backups');const items=data.backups||[];$('backupSelect').innerHTML=items.map(item=>`<option value="${esc(item.name)}">${esc(item.name)} · ${item.size_bytes} B</option>`).join('')||'<option value="">暂无备份</option>';if(notify)toast(`已读取 ${items.length} 个备份`)}catch(error){toast(error.message,true)}}
async function rollbackBackup(){const name=$('backupSelect').value;if(!name){toast('没有可回滚的备份',true);return}if(!confirm(`确认回滚到 ${name}？当前配置会先自动备份。`))return;try{const data=await api('/admin/parser-center/rollback',{method:'POST',body:{backup_name:name}});toast(data.message||'回滚完成');await loadConfig()}catch(error){toast(error.message,true)}}
function switchTab(name){document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('active',button.dataset.tab===name));document.querySelectorAll('.tab-panel').forEach(panel=>panel.classList.toggle('hidden',panel.id!==`tab-${name}`));if(name==='advanced')syncAdvancedFromVisual();if(name==='backups'){refreshSecretOptions();loadBackups(false)}}
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>switchTab(button.dataset.tab));$('adminToken').value=token();loadConfig();
</script>
</body>
</html>'''
