from __future__ import annotations


def render_parser_center_page() -> str:
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>接口与解析中心</title>
<style>
:root{color-scheme:light dark;--bg:#eef2f8;--panel:rgba(255,255,255,.78);--text:#172033;--muted:#66758b;--line:rgba(128,145,170,.28);--primary:#2563eb;--danger:#b42318;--code:#101827;--shadow:0 18px 55px rgba(31,45,70,.14)}
@media(prefers-color-scheme:dark){:root{--bg:#0d1421;--panel:rgba(25,36,54,.82);--text:#e7edf7;--muted:#a8b4c7;--line:rgba(170,190,220,.2);--primary:#6ea0ff;--code:#060a11;--shadow:0 18px 55px rgba(0,0,0,.32)}}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0%,rgba(90,140,255,.18),transparent 34%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1480px;margin:auto;padding:22px}.glass{background:var(--panel);backdrop-filter:blur(24px) saturate(135%);-webkit-backdrop-filter:blur(24px) saturate(135%);border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow)}header{padding:22px;margin-bottom:16px;display:flex;justify-content:space-between;gap:20px;align-items:flex-start}h1{font-size:27px;margin:0 0 7px}h2{font-size:17px;margin:0}.hint{color:var(--muted);font-size:13px;line-height:1.6}.toolbar{display:flex;gap:9px;flex-wrap:wrap;align-items:center}button,a.button{appearance:none;border:1px solid var(--line);background:rgba(255,255,255,.7);color:#172033;border-radius:12px;padding:10px 14px;font:inherit;font-weight:760;cursor:pointer;text-decoration:none}button.primary{background:var(--primary);border-color:transparent;color:white}button.danger{color:var(--danger)}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.72);color:#172033;padding:11px;font:inherit}textarea{min-height:180px;resize:vertical;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}@media(prefers-color-scheme:dark){button,a.button,input,textarea,select{background:rgba(8,14,24,.72);color:#e7edf7}}.grid{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(360px,.82fr);gap:16px}.panel{padding:18px}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}.field span{display:block;font-size:12px;color:var(--muted);margin-bottom:5px}.result{white-space:pre-wrap;word-break:break-word;background:var(--code);color:#e5e7eb;border-radius:14px;padding:14px;min-height:130px;max-height:540px;overflow:auto;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}.policy{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:12px}.policy div{border:1px solid var(--line);border-radius:14px;padding:11px;font-size:12px}.ok{color:#15803d}.bad{color:#dc2626}.toast{display:none;position:fixed;right:20px;bottom:20px;max-width:560px;padding:12px 15px;border-radius:13px;background:#111827;color:white;box-shadow:var(--shadow);z-index:20}.toast.bad{background:#7f1d1d;color:white}@media(max-width:900px){.shell{padding:12px}.grid,.fields,.policy{grid-template-columns:1fr}header{display:block}.toolbar{margin-top:13px}}
</style>
</head>
<body>
<main class="shell">
<header class="glass">
  <div><h1>接口与解析中心</h1><div class="hint">配置第三方请求、字段路径、命中条件和最终机器人文本。正式输出禁止出现第三方域名、Provider 名称、by 或接口来源。</div></div>
  <div class="toolbar"><input id="adminToken" type="password" placeholder="管理令牌（本机可留空）" style="width:230px"><button onclick="saveToken()">应用令牌</button><a class="button" href="/">返回控制台</a></div>
</header>
<section class="grid">
  <div class="glass panel">
    <div class="panel-head"><div><h2>解析配置 JSON</h2><div class="hint" id="configMeta">正在读取...</div></div><div class="toolbar"><button onclick="loadConfig()">重新读取</button><button onclick="validateConfig()">校验</button><button class="primary" onclick="saveConfig()">保存配置</button></div></div>
    <textarea id="configText" spellcheck="false"></textarea>
    <div class="policy">
      <div><strong>公开输出</strong><br><span class="ok">不显示第三方来源</span></div>
      <div><strong>敏感字段</strong><br><span class="ok">Secret 仅服务端解析</span></div>
      <div><strong>保存策略</strong><br><span class="ok">校验、备份、原子替换</span></div>
    </div>
  </div>
  <div class="glass panel">
    <div class="panel-head"><div><h2>测试请求</h2><div class="hint">先测试真实响应，再决定是否启用 Provider。</div></div><button class="primary" onclick="runTest()">请求并解析</button></div>
    <div class="fields">
      <label class="field"><span>功能</span><input id="testFeature" value="lolban"></label>
      <label class="field"><span>Provider ID</span><input id="testProvider" value="lolban-primary"></label>
    </div>
    <label class="field" style="display:block;margin-top:10px"><span>测试参数 JSON</span><textarea id="testParameters" style="min-height:100px">{"qq":"97077000"}</textarea></label>
    <div class="hint" id="secretState" style="margin-top:8px">Secret 状态尚未读取</div>
  </div>
</section>
<section class="grid" style="margin-top:16px">
  <div class="glass panel"><div class="panel-head"><h2>脱敏请求与原始响应</h2><span class="hint">仅管理员调试可见</span></div><pre class="result" id="rawResult">暂无</pre></div>
  <div class="glass panel"><div class="panel-head"><h2>机器人最终文本预览</h2><span class="hint">这里不得出现第三方来源</span></div><pre class="result" id="publicResult">暂无</pre></div>
</section>
</main>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);
function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}
function saveToken(){const value=$('adminToken').value.trim();if(value)sessionStorage.setItem('lolapisevers_admin_token',value);else sessionStorage.removeItem('lolapisevers_admin_token');toast(value?'管理令牌已保存到当前会话':'已清除管理令牌');loadConfig()}
function toast(message,bad=false){const node=$('toast');node.textContent=message;node.className='toast'+(bad?' bad':'');node.style.display='block';clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>node.style.display='none',4300)}
async function api(path,opt={}){const headers={'content-type':'application/json'};if(token())headers['x-admin-token']=token();const response=await fetch(path,{method:opt.method||'GET',headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const text=await response.text();let data;try{data=JSON.parse(text)}catch(_){data={detail:text}}if(!response.ok)throw new Error(data.detail||data.error||text||response.statusText);return data}
function parsedConfig(){try{return JSON.parse($('configText').value)}catch(error){throw new Error('配置 JSON 无效：'+error.message)}}
async function loadConfig(){try{const data=await api('/admin/parser-center');$('configText').value=JSON.stringify(data.config,null,2);$('configMeta').textContent=`${data.path} · ${data.exists?'正式配置':'默认模板，尚未落盘'}`;$('secretState').textContent=(data.secrets||[]).map(item=>`${item.name}：${item.configured?'已配置':'未配置'}`).join('；')||'当前配置没有 Secret 引用';toast('解析配置已读取')}catch(error){toast(error.message,true)}}
async function validateConfig(){try{const data=await api('/admin/parser-center/validate',{method:'POST',body:{config:parsedConfig()}});toast(data.message||'校验通过')}catch(error){toast(error.message,true)}}
async function saveConfig(){if(!confirm('确认保存解析配置？系统会先校验并备份现有文件。'))return;try{const data=await api('/admin/parser-center',{method:'POST',body:{config:parsedConfig()}});toast(data.message||'保存完成');await loadConfig()}catch(error){toast(error.message,true)}}
async function runTest(){try{const parameters=JSON.parse($('testParameters').value||'{}');const data=await api('/admin/parser-center/test',{method:'POST',body:{feature:$('testFeature').value.trim(),provider_id:$('testProvider').value.trim(),parameters}});$('rawResult').textContent=JSON.stringify({request:data.request,response:data.response,parsed:data.parsed},null,2);$('publicResult').textContent=data.public_text||'解析成功，但当前结果模板为空';toast('测试请求和解析完成')}catch(error){$('rawResult').textContent=error.message;toast(error.message,true)}}
$('adminToken').value=token();loadConfig();
</script>
</body>
</html>'''
