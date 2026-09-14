from __future__ import annotations


def render_lolban_console_page() -> str:
    return '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>封号查询配置与诊断</title>
<link rel="stylesheet" href="/control-assets/lolban.css">
</head>
<body>
<main class="shell">
<header class="top">
  <div><h1>封号查询配置与实时诊断</h1><div class="hint">同时查看磁盘配置、5001 当前运行配置、Provider 直连结果和正式查询结果。</div></div>
  <div class="actions">
    <button onclick="location.href='/'">返回总控台</button>
    <input id="adminToken" class="admin-token-input" type="password" placeholder="管理令牌（本机可留空）">
    <button onclick="saveToken()">应用令牌</button>
    <button onclick="loadAll()">刷新</button>
    <button class="primary" onclick="saveAll()">保存并热加载</button>
  </div>
</header>
<section class="cards">
  <div class="card">磁盘 Provider<b id="diskCount">-</b></div>
  <div class="card">运行时 Provider<b id="runtimeCount">-</b></div>
  <div class="card">配置一致性<b id="matchState">-</b></div>
  <div class="card">最近运行状态<b id="healthState">-</b></div>
</section>
<section class="panel">
  <div class="head"><div><h2>缓存与降级设置</h2><div class="hint">保存后写入 app_env.local.ps1，并安全热加载到 5001。</div></div></div>
  <div class="grid">
    <label><span>上游超时（秒）</span><input id="sTimeout" type="number"></label>
    <label><span>正常缓存（秒）</span><input id="sNormal" type="number"></label>
    <label><span>封禁缓存（秒）</span><input id="sBanned" type="number"></label>
    <label><span>最近成功降级（秒）</span><input id="sStale" type="number"></label>
    <label><span>最大降级条数</span><input id="sMax" type="number"></label>
    <label class="switch"><input id="sSnapshot" type="checkbox"><span>启用持久化快照</span></label>
    <label class="span-two"><span>旧版单上游 URL（敏感参数显示 ***）</span><input id="legacyUrl"></label>
  </div>
</section>
<section class="panel">
  <div class="head"><div><h2>解析中心 Provider</h2><div class="hint" id="parserPath"></div></div><button onclick="addProvider('parser')">新增 Provider</button></div>
  <div id="parserProviders"></div>
</section>
<section class="panel">
  <div class="head"><div><h2>旧环境变量 Provider</h2><div class="hint" id="legacyPath"></div></div><button onclick="addProvider('legacy')">新增 Provider</button></div>
  <div id="legacyError" class="bad"></div>
  <div id="legacyProviders"></div>
</section>
<section class="panel">
  <div class="head"><div><h2>实时测试</h2><div class="hint">先单独测试所选 Provider，再测试正式降级链路；两项结果不再混在一次操作中。</div></div><div class="actions"><button class="primary" onclick="runProviderTest()">测试所选 Provider</button><button onclick="runFormalTest()">测试正式链路</button></div></div>
  <div class="grid two"><label><span>测试 QQ</span><input id="testQQ" value="97077000"></label><label><span>运行时 Provider</span><select id="testProvider"></select></label></div>
  <div class="grid two"><div><h3>Provider 直连</h3><pre id="providerResult">暂无</pre></div><div><h3>5001 正式链路</h3><pre id="formalResult">暂无</pre></div></div>
</section>
<section class="panel"><div class="head"><h2>运行时详情</h2></div><pre id="runtimeResult">暂无</pre></section>
</main>
<script src="/control-assets/lolban.js" defer></script>
</body>
</html>'''


__all__ = ["render_lolban_console_page"]
