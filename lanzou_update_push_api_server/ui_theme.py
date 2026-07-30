from __future__ import annotations


THEME_STORAGE_KEY = "LOLAPI_WEBUI_THEME"

_THEME_BOOTSTRAP = r'''<script id="ios-glass-theme-bootstrap">
(function(){
  var key='LOLAPI_WEBUI_THEME';
  var allowed={light:1,dark:1,system:1};
  var mode='system';
  try{var saved=localStorage.getItem(key);if(allowed[saved])mode=saved}catch(_error){}
  var dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.themeMode=mode;
  document.documentElement.dataset.theme=mode==='system'?(dark?'dark':'light'):mode;
})();
</script>'''

_THEME_STYLE = r'''<style id="ios-glass-theme-style">
:root{
  color-scheme:light;
  --bg:#eef3fb;
  --panel:rgba(255,255,255,.72);
  --panel-strong:rgba(255,255,255,.9);
  --text:#152238;
  --muted:#65748b;
  --line:rgba(93,116,151,.22);
  --primary:#0a84ff;
  --primary-strong:#006edc;
  --green:#159667;
  --red:#d0443f;
  --amber:#a66a08;
  --soft:rgba(246,249,255,.72);
  --dark:#111827;
  --glass-shadow:0 24px 70px rgba(44,65,96,.14),0 2px 8px rgba(44,65,96,.08);
  --glass-highlight:inset 0 1px 0 rgba(255,255,255,.78);
  --input-bg:rgba(255,255,255,.76);
  --table-head:rgba(245,248,253,.88);
  --terminal-bg:#111827;
  --terminal-text:#e8edf7;
  --focus:rgba(10,132,255,.25);
}
html[data-theme="dark"]{
  color-scheme:dark;
  --bg:#070b14;
  --panel:rgba(24,32,49,.68);
  --panel-strong:rgba(27,36,55,.9);
  --text:#edf3ff;
  --muted:#9aa9bf;
  --line:rgba(170,193,226,.16);
  --primary:#409cff;
  --primary-strong:#1684ef;
  --green:#45d39a;
  --red:#ff716a;
  --amber:#f0bd63;
  --soft:rgba(12,18,30,.66);
  --dark:#050811;
  --glass-shadow:0 28px 80px rgba(0,0,0,.42),0 2px 10px rgba(0,0,0,.28);
  --glass-highlight:inset 0 1px 0 rgba(255,255,255,.08);
  --input-bg:rgba(8,14,25,.64);
  --table-head:rgba(13,20,33,.9);
  --terminal-bg:#050811;
  --terminal-text:#e8edf7;
  --focus:rgba(64,156,255,.28);
}
html{min-height:100%;background:var(--bg)}
body{
  min-height:100vh;
  background:
    radial-gradient(circle at 8% 5%,rgba(73,157,255,.24),transparent 30rem),
    radial-gradient(circle at 90% 8%,rgba(169,105,255,.18),transparent 28rem),
    radial-gradient(circle at 52% 94%,rgba(74,213,180,.13),transparent 32rem),
    var(--bg)!important;
  color:var(--text)!important;
  transition:background-color .22s ease,color .22s ease;
}
body:before{
  content:"";
  position:fixed;
  inset:0;
  pointer-events:none;
  z-index:-1;
  background:linear-gradient(135deg,rgba(255,255,255,.14),transparent 38%,rgba(255,255,255,.04));
}
.shell{max-width:1640px!important;padding:22px!important}
.top{
  position:sticky;
  top:12px;
  z-index:8;
  padding:16px 18px;
  border:1px solid var(--line);
  border-radius:22px;
  background:var(--panel-strong);
  box-shadow:var(--glass-shadow),var(--glass-highlight);
  -webkit-backdrop-filter:blur(26px) saturate(150%);
  backdrop-filter:blur(26px) saturate(150%);
}
.top h1{letter-spacing:-.025em;font-weight:850}
.top p,.hint,.card .label,.card .sub,.field span{color:var(--muted)!important}
.actions,.toolbar{gap:9px!important}
.card,.panel,.route,.event{
  background:var(--panel)!important;
  border-color:var(--line)!important;
  border-radius:20px!important;
  box-shadow:var(--glass-shadow),var(--glass-highlight);
  -webkit-backdrop-filter:blur(24px) saturate(145%);
  backdrop-filter:blur(24px) saturate(145%);
}
.card{padding:16px!important}
.panel{padding:17px!important}
.card .value{letter-spacing:-.025em}
.tabs{
  position:sticky;
  top:114px;
  z-index:7;
  padding:9px;
  border:1px solid var(--line);
  border-radius:18px;
  background:var(--panel-strong);
  box-shadow:0 12px 34px rgba(35,53,82,.12),var(--glass-highlight);
  -webkit-backdrop-filter:blur(22px) saturate(150%);
  backdrop-filter:blur(22px) saturate(150%);
}
button,.tab{
  border-color:var(--line)!important;
  border-radius:12px!important;
  background:rgba(255,255,255,.42)!important;
  color:var(--text)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.34),0 3px 10px rgba(28,46,77,.07);
  transition:transform .16s ease,box-shadow .16s ease,background .16s ease;
}
html[data-theme="dark"] button,html[data-theme="dark"] .tab{background:rgba(31,43,65,.72)!important}
button:hover,.tab:hover{transform:translateY(-1px);box-shadow:0 7px 18px rgba(34,58,94,.16),inset 0 1px 0 rgba(255,255,255,.35)}
button:active,.tab:active{transform:translateY(0) scale(.98)}
button.primary,.tab.active{
  background:linear-gradient(180deg,var(--primary),var(--primary-strong))!important;
  border-color:transparent!important;
  color:#fff!important;
  box-shadow:0 9px 22px rgba(10,132,255,.28),inset 0 1px 0 rgba(255,255,255,.3);
}
button.danger{background:rgba(208,68,63,.1)!important;color:var(--red)!important;border-color:rgba(208,68,63,.26)!important}
button.warn{background:rgba(240,189,99,.12)!important;color:var(--amber)!important;border-color:rgba(240,189,99,.28)!important}
input,select,textarea,.field input,.field select,.field textarea{
  border-color:var(--line)!important;
  border-radius:12px!important;
  background:var(--input-bg)!important;
  color:var(--text)!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.22);
  outline:none;
  transition:border-color .16s ease,box-shadow .16s ease,background .16s ease;
}
input:focus,select:focus,textarea:focus{
  border-color:var(--primary)!important;
  box-shadow:0 0 0 4px var(--focus),inset 0 1px 0 rgba(255,255,255,.2)!important;
}
.switch{background:var(--soft)!important;border-color:var(--line)!important;border-radius:14px!important}
.table-wrap{border-color:var(--line)!important;border-radius:15px!important;background:rgba(255,255,255,.1)}
table{background:transparent!important}
th{background:var(--table-head)!important;color:var(--muted)!important}
th,td{border-color:var(--line)!important}
.status{background:rgba(118,137,163,.13)!important}
.status.ok{background:rgba(21,150,103,.14)!important}.status.bad{background:rgba(208,68,63,.13)!important}.status.warntext{background:rgba(166,106,8,.14)!important}
.result,pre.result{
  background:var(--terminal-bg)!important;
  color:var(--terminal-text)!important;
  border:1px solid rgba(145,168,202,.15)!important;
  border-radius:15px!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05);
}
.preview{background:var(--input-bg)!important;border-color:var(--line)!important;border-radius:15px!important}
.toast{border-radius:15px!important;box-shadow:0 18px 48px rgba(0,0,0,.25)!important;-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px)}
.ios-theme-control{
  display:inline-flex;
  align-items:center;
  gap:3px;
  padding:4px;
  border:1px solid var(--line);
  border-radius:14px;
  background:var(--soft);
  box-shadow:var(--glass-highlight);
}
.ios-theme-control button{
  min-height:30px!important;
  padding:5px 9px!important;
  border:0!important;
  border-radius:10px!important;
  background:transparent!important;
  box-shadow:none!important;
  color:var(--muted)!important;
  font-size:12px;
  white-space:nowrap;
}
.ios-theme-control button[aria-pressed="true"]{
  color:var(--text)!important;
  background:var(--panel-strong)!important;
  box-shadow:0 3px 10px rgba(35,55,87,.12),var(--glass-highlight)!important;
}
@supports not ((-webkit-backdrop-filter:blur(1px)) or (backdrop-filter:blur(1px))){.top,.tabs,.card,.panel{background:var(--panel-strong)!important}}
@media(max-width:700px){
  .shell{padding:10px!important}
  .top{position:relative;top:0;padding:14px!important;border-radius:18px}
  .tabs{position:relative;top:0;border-radius:16px;overflow-x:auto;flex-wrap:nowrap!important}
  .tab{white-space:nowrap}
  .ios-theme-control{width:100%;justify-content:space-between}
  .ios-theme-control button{flex:1}
}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
</style>'''

_THEME_CONTROLLER = r'''<script id="ios-glass-theme-controller">
(function(){
  var key='LOLAPI_WEBUI_THEME';
  var allowed={light:1,dark:1,system:1};
  var media=window.matchMedia?window.matchMedia('(prefers-color-scheme: dark)'):null;
  function getMode(){try{var mode=localStorage.getItem(key);return allowed[mode]?mode:'system'}catch(_error){return 'system'}}
  function resolved(mode){return mode==='system'?(media&&media.matches?'dark':'light'):mode}
  function syncButtons(mode){document.querySelectorAll('[data-ios-theme-mode]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.iosThemeMode===mode))})}
  function apply(mode,persist){if(!allowed[mode])mode='system';document.documentElement.dataset.themeMode=mode;document.documentElement.dataset.theme=resolved(mode);if(persist!==false){try{localStorage.setItem(key,mode)}catch(_error){}}syncButtons(mode);window.dispatchEvent(new CustomEvent('ios-theme-change',{detail:{mode:mode,resolved:resolved(mode)}}))}
  function mount(){
    if(document.querySelector('.ios-theme-control')){syncButtons(getMode());return}
    var control=document.createElement('div');
    control.className='ios-theme-control';
    control.setAttribute('role','group');
    control.setAttribute('aria-label','外观主题');
    [['light','☀ 日间'],['system','◐ 跟随'],['dark','☾ 夜间']].forEach(function(item){
      var button=document.createElement('button');button.type='button';button.dataset.iosThemeMode=item[0];button.textContent=item[1];button.title='切换到'+item[1]+'模式';button.addEventListener('click',function(){apply(item[0],true)});control.appendChild(button)
    });
    var host=document.querySelector('.actions')||document.querySelector('.top')||document.body;
    host.insertBefore(control,host.firstChild);
    apply(getMode(),false);
  }
  if(media){var onChange=function(){if(getMode()==='system')apply('system',false)};if(media.addEventListener)media.addEventListener('change',onChange);else if(media.addListener)media.addListener(onChange)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();
</script>'''


def apply_ios_glass_theme(page: str) -> str:
    """Inject the shared theme once into the final rendered dashboard HTML."""
    if 'id="ios-glass-theme-style"' in page:
        return page
    if "</head>" not in page or "</body>" not in page:
        raise ValueError("dashboard HTML is missing head/body closing tags")
    themed = page.replace("</head>", _THEME_BOOTSTRAP + _THEME_STYLE + "</head>", 1)
    return themed.replace("</body>", _THEME_CONTROLLER + "</body>", 1)
