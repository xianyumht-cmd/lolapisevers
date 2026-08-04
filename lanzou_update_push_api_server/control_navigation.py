from __future__ import annotations


_CONTROL_STYLE = r'''<style id="control-navigation-style">
:root{--ctl-sidebar:#111827;--ctl-sidebar-soft:#1f2937;--ctl-sidebar-text:#e5e7eb;--ctl-sidebar-muted:#94a3b8;--ctl-accent:#2563eb;--ctl-border:rgba(148,163,184,.18)}
body.control-layout{min-height:100vh;padding-left:258px}
.control-sidebar{position:fixed;inset:0 auto 0 0;width:258px;background:linear-gradient(180deg,#0f172a,#111827 56%,#0b1220);color:var(--ctl-sidebar-text);z-index:1000;border-right:1px solid var(--ctl-border);display:flex;flex-direction:column;overflow:auto}
.control-brand{padding:20px 18px 16px;border-bottom:1px solid var(--ctl-border)}
.control-brand strong{display:block;font-size:18px;letter-spacing:.01em}.control-brand span{display:block;margin-top:5px;color:var(--ctl-sidebar-muted);font-size:12px}
.control-nav{padding:12px 10px 24px;display:grid;gap:7px}.control-nav details{border-radius:10px}.control-nav details[open]{background:rgba(255,255,255,.035)}
.control-nav summary{list-style:none;cursor:pointer;padding:9px 10px;color:var(--ctl-sidebar-muted);font-size:12px;font-weight:800;display:flex;justify-content:space-between;align-items:center}.control-nav summary::-webkit-details-marker{display:none}.control-nav summary:after{content:'›';font-size:18px;transition:transform .16s}.control-nav details[open] summary:after{transform:rotate(90deg)}
.control-nav a{display:flex;align-items:center;gap:9px;color:var(--ctl-sidebar-text);text-decoration:none;padding:9px 11px;border-radius:9px;font-size:13px;line-height:1.25;margin:2px 5px}.control-nav a:hover{background:rgba(255,255,255,.08)}.control-nav a.active{background:linear-gradient(135deg,var(--ctl-accent),#1d4ed8);color:#fff;box-shadow:0 8px 22px rgba(37,99,235,.28)}
.control-nav .nav-icon{width:24px;text-align:center;opacity:.92;font-size:12px;font-weight:850}.control-nav .nav-note{margin-left:auto;color:var(--ctl-sidebar-muted);font-size:10px}.control-nav a.active .nav-note{color:rgba(255,255,255,.72)}
.control-sidebar-footer{margin-top:auto;padding:14px 18px 18px;border-top:1px solid var(--ctl-border);color:var(--ctl-sidebar-muted);font-size:11px;line-height:1.6}
.control-mobile-bar{display:none;position:sticky;top:0;z-index:999;background:#111827;color:#fff;padding:10px 12px;align-items:center;gap:10px;border-bottom:1px solid var(--ctl-border)}.control-mobile-bar button{border:1px solid rgba(255,255,255,.2)!important;background:rgba(255,255,255,.08)!important;color:#fff!important;padding:7px 10px!important}.control-mobile-bar strong{font-size:14px}
body.control-layout>.shell,body.control-layout>main.shell{max-width:none!important;margin:0!important;padding:18px 22px 28px!important}
body.control-layout .tabs.control-original-tabs{display:none!important}
@media(max-width:900px){body.control-layout{padding-left:0}.control-sidebar{transform:translateX(-100%);transition:transform .18s ease;box-shadow:16px 0 40px rgba(0,0,0,.28)}body.control-nav-open .control-sidebar{transform:translateX(0)}.control-mobile-bar{display:flex}body.control-layout>.shell,body.control-layout>main.shell{padding:12px!important}}
</style>'''


def _nav_link(
    path: str,
    label: str,
    icon: str,
    *,
    active: bool = False,
    note: str = "",
    marker: str = "",
) -> str:
    class_name = ' class="active"' if active else ""
    marker_html = f" {marker}" if marker else ""
    note_html = f'<span class="nav-note">{note}</span>' if note else ""
    return (
        f'<a href="{path}"{class_name}{marker_html}>'
        f'<span class="nav-icon">{icon}</span><span>{label}</span>{note_html}</a>'
    )


def _sidebar(active: str) -> str:
    return f'''<aside class="control-sidebar" aria-label="LOLDataSystem 控制台导航">
  <div class="control-brand"><strong>LOLDataSystem</strong><span>接口端可视化控制台 · 6178</span></div>
  <nav class="control-nav">
    {_nav_link('/', '控制台总览', '首页', active=active == 'overview')}
    <details open>
      <summary>查询服务</summary>
      {_nav_link('/query-console/lolban', '封号查询', '封号', active=active == 'lolban', note='Provider', marker='data-query-console-lolban="1"')}
      {_nav_link('/parser-center?section=visual', '接口与解析中心', '解析', active=active == 'parser-center')}
      {_nav_link('/parser-center?section=backups', 'Secret 与备份', '密钥')}
      {_nav_link('/?tab=debugger', '接口调试器', '调试')}
    </details>
    <details>
      <summary>蓝奏监控</summary>
      {_nav_link('/?tab=lanzouconfig', '全局配置', '全局')}
      {_nav_link('/?tab=watchers', '监控项目', '监控')}
      {_nav_link('/?tab=targets', '通知目标', '通知')}
    </details>
    <details>
      <summary>系统管理</summary>
      {_nav_link('/?tab=mainconfig', '主接口配置', '配置')}
      {_nav_link('/?tab=logs', '运行日志', '日志')}
      {_nav_link('/?tab=diagnostics', '诊断与修复', '诊断')}
      {_nav_link('/?tab=system', '安全与回滚', '安全')}
    </details>
    <details>
      <summary>开发与文档</summary>
      {_nav_link('/docs', 'OpenAPI 文档', 'API')}
      {_nav_link('/legacy-ui', '旧版控制台', '旧版')}
    </details>
  </nav>
  <div class="control-sidebar-footer">生产配置写入前会校验并备份。第三方 Provider 默认停用，完成直连与正式链路测试后再启用。</div>
</aside>
<div class="control-mobile-bar"><button id="controlNavToggle" type="button">☰ 菜单</button><strong>LOLDataSystem 控制台</strong></div>'''


_LOLBAN_SECRET_PANEL = r'''<section class="panel" id="fourPngSecretPanel"><div class="head"><div><h2>4PNG Token</h2><div class="hint">真实 Token 只写入本机 Secret，不进入 Provider JSON、URL、日志或浏览器回显。</div></div><span id="fourPngSecretState" class="bad">正在读取...</span></div><div class="grid two"><label><span>LOL_BAN_4PNG_TOKEN 新值</span><input id="fourPngToken" type="password" autocomplete="new-password" placeholder="输入 4PNG 提供的真实 Token"></label><div class="actions" style="justify-content:flex-start;align-self:end"><button class="primary" type="button" onclick="save4PngToken()">安全保存 Token</button><button type="button" onclick="restartLolDataSystem()">重启 LOLDataSystem</button></div></div><div class="hint" style="margin-top:8px">保存后本页 Provider 测试可立即使用；5001 正式查询需要重启服务后读取新 Token。</div></section>'''

_LOLBAN_SECRET_SCRIPT = r'''<script id="lolban-secret-control-script">
(function(){
  function byId(id){return document.getElementById(id)}
  function adminToken(){try{return sessionStorage.getItem('lolapisevers_admin_token')||''}catch(_error){return ''}}
  async function requestJson(path,opt){
    opt=opt||{};
    var headers={'content-type':'application/json'};
    var token=adminToken();
    if(token)headers['x-admin-token']=token;
    var response=await fetch(path,{method:opt.method||'GET',headers:headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});
    var text=await response.text();
    var data;
    try{data=JSON.parse(text)}catch(_error){data={detail:text}}
    if(!response.ok)throw new Error(data.detail||data.error||text||response.statusText);
    return data;
  }
  function showState(configured){
    var node=byId('fourPngSecretState');
    if(!node)return;
    node.textContent=configured?'已配置':'未配置';
    node.className=configured?'ok':'bad';
  }
  async function refresh(){
    try{
      var data=await requestJson('/admin/parser-center');
      var item=(data.secrets||[]).find(function(value){return value.name==='LOL_BAN_4PNG_TOKEN'});
      showState(!!(item&&item.configured));
    }catch(error){
      var node=byId('fourPngSecretState');
      if(node){node.textContent='读取失败';node.className='bad'}
    }
  }
  window.save4PngToken=async function(){
    var input=byId('fourPngToken');
    var value=input?input.value.trim():'';
    if(!value){alert('请输入 4PNG Token');return}
    try{
      var data=await requestJson('/admin/parser-center/secret',{method:'POST',body:{name:'LOL_BAN_4PNG_TOKEN',value:value}});
      input.value='';
      showState(true);
      alert(data.message||'Token 已安全保存');
    }catch(error){alert(error.message)}
  };
  window.restartLolDataSystem=async function(){
    if(!confirm('确认重启 LOLDataSystem？5001 和 6178 会短暂断开。'))return;
    try{
      var data=await requestJson('/admin/service/restart',{method:'POST',body:{delay_seconds:3}});
      alert(data.message||'已安排服务重启');
    }catch(error){alert(error.message)}
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',refresh);else refresh();
})();
</script>'''


def _inject_lolban_secret_controls(page: str) -> str:
    if 'id="fourPngSecretPanel"' in page:
        return page
    marker = '<section class="panel"><div class="head"><div><h2>缓存与降级设置</h2>'
    if marker not in page:
        raise ValueError("lolban console cache panel marker is missing")
    page = page.replace(marker, _LOLBAN_SECRET_PANEL + marker, 1)
    return page.replace("</body>", _LOLBAN_SECRET_SCRIPT + "</body>", 1)


_NAV_SCRIPT = r'''<script id="control-navigation-script">
(function(){
  function markSidebar(href){
    document.querySelectorAll('.control-sidebar a.active').forEach(function(link){link.classList.remove('active')});
    var link=document.querySelector('.control-sidebar a[href="'+CSS.escape(href)+'"]');
    if(link){
      link.classList.add('active');
      var group=link.closest('details');
      if(group)group.open=true;
    }
  }
  function activateFromQuery(){
    var params=new URLSearchParams(location.search);
    var tab=params.get('tab');
    if(tab&&location.pathname==='/'){
      var target=document.querySelector('.tab[data-tab="'+CSS.escape(tab)+'"]');
      if(target)target.click();
      markSidebar('/?tab='+encodeURIComponent(tab));
    }
    var section=params.get('section');
    if(section&&location.pathname==='/parser-center'){
      var sectionButton=document.querySelector('[data-tab="'+CSS.escape(section)+'"]');
      if(sectionButton)sectionButton.click();
      markSidebar('/parser-center?section='+encodeURIComponent(section));
    }
  }
  function mount(){
    var toggle=document.getElementById('controlNavToggle');
    if(toggle)toggle.addEventListener('click',function(){document.body.classList.toggle('control-nav-open')});
    document.querySelectorAll('.control-sidebar a').forEach(function(link){link.addEventListener('click',function(){document.body.classList.remove('control-nav-open')})});
    var originalTabs=document.querySelector('main.shell > .tabs, main.shell > nav.tabs');
    if(originalTabs)originalTabs.classList.add('control-original-tabs');
    activateFromQuery();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();
</script>'''


def apply_control_navigation(page: str, *, active: str) -> str:
    if active == "lolban":
        page = _inject_lolban_secret_controls(page)
    if 'id="control-navigation-style"' in page:
        return page
    if "</head>" not in page or "</body>" not in page:
        raise ValueError("control page HTML is missing head/body closing tags")
    if "<body>" in page:
        page = page.replace("<body>", '<body class="control-layout">', 1)
    else:
        page = page.replace("<body ", '<body class="control-layout" ', 1)
    page = page.replace("</head>", _CONTROL_STYLE + "</head>", 1)
    body_marker = '<body class="control-layout">'
    page = page.replace(body_marker, body_marker + _sidebar(active), 1)
    return page.replace("</body>", _NAV_SCRIPT + "</body>", 1)
