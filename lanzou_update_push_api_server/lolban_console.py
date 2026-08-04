from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from typing import Any, Mapping

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from . import management
from .parser_center_admin import _load_effective_config, _redact_config, save_parser_center


_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|cookie|api[_-]?key|access[_-]?key)",
    re.I,
)
_LOLBAN_ENV_FIELDS: list[dict[str, Any]] = [
    {"key": "LOL_BAN_UPSTREAM_URL", "label": "旧版封号上游 URL", "section": "封号查询", "type": "text"},
    {"key": "LOL_BAN_MAX_STALE_ENTRIES", "label": "最近成功结果最大条数", "section": "封号查询", "type": "int", "min": 1, "max": 100000},
    {"key": "LOL_BAN_SNAPSHOT_ENABLED", "label": "持久化快照启用", "section": "封号查询", "type": "bool"},
]
_LOLBAN_SETTING_KEYS = (
    "LOL_BAN_TIMEOUT",
    "LOL_BAN_NORMAL_CACHE_SECONDS",
    "LOL_BAN_BANNED_CACHE_SECONDS",
    "LOL_BAN_STALE_CACHE_SECONDS",
    "LOL_BAN_MAX_STALE_ENTRIES",
    "LOL_BAN_SNAPSHOT_ENABLED",
)
_LOLBAN_RELOAD_KEYS = (
    "LOL_BAN_PROVIDERS_JSON",
    "LOL_BAN_UPSTREAM_URL",
    *_LOLBAN_SETTING_KEYS,
)


def _ensure_fields() -> None:
    for spec in _LOLBAN_ENV_FIELDS:
        if spec["key"] in management._FIELD_BY_KEY:
            continue
        management.MAIN_CONFIG_FIELDS.append(spec)
        management._FIELD_BY_KEY[spec["key"]] = spec


def _file_env_values() -> dict[str, str]:
    source_text, _source = management._read_env_source()
    return management._parse_env_values(source_text)


def _effective_env_value(key: str, file_values: Mapping[str, str]) -> str:
    if key in file_values:
        return str(file_values.get(key) or "")
    return str(os.getenv(key) or "")


def _parse_provider_json(raw: str) -> tuple[list[dict[str, Any]], str]:
    text = str(raw or "").strip()
    if not text:
        return [], ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"LOL_BAN_PROVIDERS_JSON 不是有效 JSON：{exc.msg}"
    if not isinstance(value, list):
        return [], "LOL_BAN_PROVIDERS_JSON 必须是数组"
    return [copy.deepcopy(item) for item in value if isinstance(item, dict)], ""


def _redact(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str) and value.strip().startswith("$secret:"):
        return value
    if _SENSITIVE_KEY_RE.search(str(key or "")):
        return "***"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return copy.deepcopy(value)


def _merge_masked(value: Any, previous: Any) -> Any:
    if value == "***":
        return copy.deepcopy(previous)
    if isinstance(value, Mapping):
        old = previous if isinstance(previous, Mapping) else {}
        return {
            str(key): _merge_masked(item, old.get(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        old_list = previous if isinstance(previous, list) else []
        return [
            _merge_masked(item, old_list[index] if index < len(old_list) else None)
            for index, item in enumerate(value)
        ]
    return copy.deepcopy(value)


def _provider_key(provider: Mapping[str, Any], index: int) -> str:
    return str(provider.get("id") or provider.get("name") or f"provider-{index}").strip()


def _merge_provider_list(submitted: list[Any], previous: list[Any]) -> list[dict[str, Any]]:
    old_by_key = {
        _provider_key(item, index): item
        for index, item in enumerate(previous, start=1)
        if isinstance(item, Mapping)
    }
    result: list[dict[str, Any]] = []
    for index, item in enumerate(submitted, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Provider {index} 必须是对象")
        key = _provider_key(item, index)
        merged = _merge_masked(dict(item), old_by_key.get(key, {}))
        result.append(dict(merged))
    return result


def _provider_identity(provider: Mapping[str, Any], index: int) -> dict[str, Any]:
    request = provider.get("request") if isinstance(provider.get("request"), Mapping) else provider
    return {
        "order": index,
        "id": _provider_key(provider, index),
        "enabled": provider.get("enabled") is not False,
        "method": str(request.get("method") or "GET").upper(),
        "url": str(request.get("url") or provider.get("url") or "").strip(),
    }


def _provider_signature(providers: list[dict[str, Any]]) -> str:
    stable = json.dumps(providers, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _main_headers() -> dict[str, str]:
    token = str(os.getenv("GROUPGUARD_WRITE_TOKEN") or os.getenv("WEBUI_ADMIN_TOKEN") or "").strip()
    headers = {"accept": "application/json"}
    if token:
        headers["x-groupguard-token"] = token
    return headers


def _main_request(
    main_base_url: str,
    method: str,
    path: str,
    *,
    payload: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{main_base_url.rstrip('/')}{path}",
        headers={**_main_headers(), "content-type": "application/json"},
        json=dict(payload) if payload is not None else None,
        params=dict(params) if params is not None else None,
        timeout=(3.0, 30.0),
    )
    body = response.content
    if len(body) > 2_000_000:
        return {"ok": False, "status_code": response.status_code, "error": "response_too_large"}
    try:
        decoded = response.json()
    except ValueError:
        decoded = {"ok": False, "error": response.text[:4000]}
    if not isinstance(decoded, dict):
        decoded = {"ok": response.ok, "data": decoded}
    decoded.setdefault("ok", response.ok)
    decoded["status_code"] = response.status_code
    return decoded


def _disk_state() -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    config, target, using_default = _load_effective_config()
    features = config.get("features") if isinstance(config.get("features"), Mapping) else {}
    lolban = features.get("lolban") if isinstance(features.get("lolban"), Mapping) else {}
    parser_providers = lolban.get("providers") if isinstance(lolban.get("providers"), list) else []
    file_values = _file_env_values()
    legacy_raw = _effective_env_value("LOL_BAN_PROVIDERS_JSON", file_values)
    legacy_providers, legacy_error = _parse_provider_json(legacy_raw)
    legacy_url = _effective_env_value("LOL_BAN_UPSTREAM_URL", file_values)
    settings = {
        key: _effective_env_value(key, file_values)
        for key in _LOLBAN_SETTING_KEYS
    }
    active: list[dict[str, Any]] = []
    for index, provider in enumerate(parser_providers, start=1):
        if isinstance(provider, Mapping) and provider.get("enabled") is not False:
            active.append(_provider_identity(provider, len(active) + 1))
    for provider in legacy_providers:
        if provider.get("enabled") is not False:
            active.append(_provider_identity(provider, len(active) + 1))
    if legacy_url.strip():
        active.append(
            {
                "order": len(active) + 1,
                "id": "legacy-form",
                "enabled": True,
                "method": "POST",
                "url": legacy_url.strip(),
            }
        )
    public = {
        "parser_center": {
            "path": str(target),
            "using_default": using_default,
            "providers": _redact(parser_providers),
        },
        "legacy": {
            "path": str(management.APP_ENV_PATH),
            "providers": _redact(legacy_providers),
            "upstream_url": legacy_url,
            "error": legacy_error,
        },
        "settings": settings,
        "active_provider_identity": active,
        "provider_signature": _provider_signature(active),
    }
    raw = {
        "config": config,
        "parser_providers": parser_providers,
        "legacy_providers": legacy_providers,
        "legacy_raw": legacy_raw,
        "legacy_url": legacy_url,
    }
    return public, file_values, raw


def _runtime_identity(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    providers = runtime.get("providers") if isinstance(runtime.get("providers"), list) else []
    result: list[dict[str, Any]] = []
    for index, provider in enumerate(providers, start=1):
        if not isinstance(provider, Mapping):
            continue
        request = provider.get("request") if isinstance(provider.get("request"), Mapping) else {}
        result.append(
            {
                "order": index,
                "id": str(provider.get("id") or provider.get("name") or f"provider-{index}"),
                "enabled": True,
                "method": str(request.get("method") or "GET").upper(),
                "url": str(request.get("url") or "").strip(),
            }
        )
    return result


def read_lolban_console(main_base_url: str) -> dict[str, Any]:
    disk, _file_values, _raw = _disk_state()
    runtime = _main_request(main_base_url, "GET", "/admin/query/lolban/runtime")
    runtime_identity = _runtime_identity(runtime)
    disk_identity = disk.get("active_provider_identity") or []
    return {
        "ok": True,
        "disk": disk,
        "runtime": runtime,
        "runtime_provider_identity": runtime_identity,
        "runtime_matches_disk": runtime.get("ok") is True and runtime_identity == disk_identity,
    }


def save_lolban_console(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    parser_submitted = payload.get("parser_providers")
    legacy_submitted = payload.get("legacy_providers")
    settings = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else {}
    if not isinstance(parser_submitted, list) or not isinstance(legacy_submitted, list):
        raise ValueError("parser_providers 和 legacy_providers 必须是数组")

    _public, _file_values, raw = _disk_state()
    config = copy.deepcopy(raw["config"])
    features = config.setdefault("features", {})
    lolban = features.setdefault("lolban", {"operation": "query", "providers": []})
    lolban["operation"] = "query"
    parser_providers = _merge_provider_list(parser_submitted, raw["parser_providers"])
    lolban["providers"] = parser_providers
    parser_result = save_parser_center({"config": config})

    legacy_providers = _merge_provider_list(legacy_submitted, raw["legacy_providers"])
    legacy_url = str(payload.get("legacy_upstream_url") or "").strip()
    _ensure_fields()
    env_patch: dict[str, Any] = {
        "LOL_BAN_PROVIDERS_JSON": json.dumps(legacy_providers, ensure_ascii=False, separators=(",", ":")),
        "LOL_BAN_UPSTREAM_URL": legacy_url,
    }
    for key in _LOLBAN_SETTING_KEYS:
        if key in settings:
            env_patch[key] = settings[key]
    env_result = management.update_main_config(env_patch)

    final_values = _file_env_values()
    reload_environment = {
        key: str(final_values.get(key, os.getenv(key, "")) or "")
        for key in _LOLBAN_RELOAD_KEYS
    }
    reload_result = _main_request(
        main_base_url,
        "POST",
        "/admin/query/lolban/reload",
        payload={"environment": reload_environment},
    )
    return {
        "ok": reload_result.get("ok") is True,
        "message": (
            "封号查询配置已保存并热加载到 5001。"
            if reload_result.get("ok") is True
            else "配置已保存，但 5001 热加载失败；请查看 reload_result。"
        ),
        "parser_result": parser_result,
        "environment_result": env_result,
        "reload_result": reload_result,
        "state": read_lolban_console(main_base_url),
    }


def test_lolban_console(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    qq = str(payload.get("qq") or "").strip()
    provider_id = str(payload.get("provider_id") or "").strip()
    provider_result = _main_request(
        main_base_url,
        "POST",
        "/admin/query/lolban/provider-test",
        payload={"qq": qq, "provider_id": provider_id},
    )
    formal_result = _main_request(
        main_base_url,
        "GET",
        "/api/v2/lolban",
        params={"qq": qq, "output": "json"},
    )
    return {
        "ok": provider_result.get("ok") is True and formal_result.get("ok") is True,
        "provider_test": provider_result,
        "formal_chain": formal_result,
    }


def render_lolban_console_page() -> str:
    return r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>封号查询配置与诊断</title>
<style>
:root{--bg:#f2f5fa;--panel:#fff;--line:#d8e0eb;--text:#172033;--muted:#66758b;--blue:#2459d3;--green:#14865b;--red:#bd3e39;--dark:#111827}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1500px;margin:auto;padding:18px}.top,.head,.actions{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}.top h1{margin:0;font-size:25px}.hint{color:var(--muted);font-size:12px}.panel,.provider{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.two{grid-template-columns:repeat(2,minmax(0,1fr))}label span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:8px;padding:8px;background:#fff}textarea{min-height:86px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:8px 11px;font-weight:700;cursor:pointer}.primary{background:var(--blue);border-color:var(--blue);color:#fff}.danger{color:var(--red)}.status{padding:4px 8px;border-radius:999px;background:#eef2f7;font-size:12px;font-weight:800}.ok{color:var(--green)}.bad{color:var(--red)}pre{white-space:pre-wrap;word-break:break-word;background:var(--dark);color:#e5e7eb;border-radius:9px;padding:12px;max-height:520px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.provider .head h3{margin:0;font-size:15px}.switch{display:flex;gap:8px;align-items:center}.switch input{width:auto}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px}.card b{display:block;font-size:20px;margin-top:5px}@media(max-width:900px){.grid,.two,.cards{grid-template-columns:1fr}}
</style></head><body><main class="shell">
<header class="top"><div><h1>封号查询配置与实时诊断</h1><div class="hint">同时查看磁盘配置、5001 当前运行配置、Provider 直连结果和正式查询结果。</div></div><div class="actions"><button onclick="location.href='/'">返回总控台</button><input id="adminToken" type="password" placeholder="管理令牌（本机可留空）" style="width:230px"><button onclick="saveToken()">应用令牌</button><button onclick="loadAll()">刷新</button><button class="primary" onclick="saveAll()">保存并热加载</button></div></header>
<section class="cards"><div class="card">磁盘 Provider<b id="diskCount">-</b></div><div class="card">运行时 Provider<b id="runtimeCount">-</b></div><div class="card">配置一致性<b id="matchState">-</b></div><div class="card">最近运行状态<b id="healthState">-</b></div></section>
<section class="panel"><div class="head"><div><h2>缓存与降级设置</h2><div class="hint">保存后会写入 app_env.local.ps1，并传给 5001 热加载。</div></div></div><div class="grid">
<label><span>上游超时（秒）</span><input id="sTimeout" type="number"></label><label><span>正常缓存（秒）</span><input id="sNormal" type="number"></label><label><span>封禁缓存（秒）</span><input id="sBanned" type="number"></label><label><span>最近成功降级（秒）</span><input id="sStale" type="number"></label><label><span>最大降级条数</span><input id="sMax" type="number"></label><label class="switch"><input id="sSnapshot" type="checkbox"><span>启用持久化快照</span></label><label style="grid-column:span 2"><span>旧版单上游 URL（兼容项）</span><input id="legacyUrl"></label></div></section>
<section class="panel"><div class="head"><div><h2>解析中心 Provider</h2><div class="hint" id="parserPath"></div></div><button onclick="addProvider('parser')">新增 Provider</button></div><div id="parserProviders"></div></section>
<section class="panel"><div class="head"><div><h2>旧环境变量 Provider</h2><div class="hint" id="legacyPath"></div></div><button onclick="addProvider('legacy')">新增 Provider</button></div><div id="legacyError" class="bad"></div><div id="legacyProviders"></div></section>
<section class="panel"><div class="head"><div><h2>实时测试</h2><div class="hint">左侧直连当前已加载 Provider；右侧调用正式 /api/v2/lolban 链路。</div></div><button class="primary" onclick="runTest()">开始测试</button></div><div class="grid two"><label><span>测试 QQ</span><input id="testQQ" value="97077000"></label><label><span>运行时 Provider</span><select id="testProvider"></select></label></div><div class="grid two"><div><h3>Provider 直连</h3><pre id="providerResult">暂无</pre></div><div><h3>5001 正式链路</h3><pre id="formalResult">暂无</pre></div></div></section>
<section class="panel"><div class="head"><h2>运行时详情</h2></div><pre id="runtimeResult">暂无</pre></section>
</main><script>
const S={parser:[],legacy:[],runtime:{}};const $=id=>document.getElementById(id);function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function attr(v){return esc(v)}function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}function saveToken(){const v=$('adminToken').value.trim();if(v)sessionStorage.setItem('lolapisevers_admin_token',v);else sessionStorage.removeItem('lolapisevers_admin_token');loadAll()}
async function api(path,opt={}){const headers={'content-type':'application/json'};if(token())headers['x-admin-token']=token();const r=await fetch(path,{method:opt.method||'GET',headers,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const t=await r.text();let d;try{d=JSON.parse(t)}catch(e){d={ok:false,error:t}}if(!r.ok)throw new Error(d.detail||d.error||t||r.statusText);return d}
function obj(v,fallback={}){return v&&typeof v==='object'&&!Array.isArray(v)?v:fallback}function pretty(v){return JSON.stringify(v??{},null,2)}function parseJson(text,label,fallback){try{return JSON.parse(text||JSON.stringify(fallback))}catch(e){throw new Error(label+' JSON 无效：'+e.message)}}
function normalize(p,i){p=obj(p);const req=obj(p.request,p);return {id:p.id||p.name||`provider-${i+1}`,name:p.name||p.id||`Provider ${i+1}`,enabled:p.enabled!==false,request:{method:(req.method||'GET').toUpperCase(),url:req.url||p.url||'',timeout_seconds:req.timeout_seconds||p.timeout_seconds||10,headers:obj(req.headers),query:obj(req.query),form:obj(req.form),json:req.json??req.json_body??null},parser:obj(p.parser)}}
function card(kind,p,index){p=normalize(p,index);return `<div class="provider" data-kind="${kind}" data-index="${index}"><div class="head"><h3>${esc(p.name||p.id)}</h3><div class="actions"><label class="switch"><input data-f="enabled" type="checkbox" ${p.enabled?'checked':''}><span>启用</span></label><button class="danger" onclick="removeProvider('${kind}',${index})">删除</button></div></div><div class="grid"><label><span>ID</span><input data-f="id" value="${attr(p.id)}"></label><label><span>名称</span><input data-f="name" value="${attr(p.name)}"></label><label><span>方法</span><select data-f="method"><option ${p.request.method==='GET'?'selected':''}>GET</option><option ${p.request.method==='POST'?'selected':''}>POST</option></select></label><label><span>超时秒数</span><input data-f="timeout" type="number" value="${attr(p.request.timeout_seconds)}"></label></div><label><span>API URL</span><input data-f="url" value="${attr(p.request.url)}"></label><div class="grid two"><label><span>Query JSON</span><textarea data-f="query">${esc(pretty(p.request.query))}</textarea></label><label><span>Form JSON</span><textarea data-f="form">${esc(pretty(p.request.form))}</textarea></label><label><span>Headers JSON（敏感值显示 ***，原值会保留）</span><textarea data-f="headers">${esc(pretty(p.request.headers))}</textarea></label><label><span>JSON Body</span><textarea data-f="json">${esc(pretty(p.request.json))}</textarea></label></div><label><span>响应解析规则 JSON</span><textarea data-f="parser">${esc(pretty(p.parser))}</textarea></label></div>`}
function render(){ $('parserProviders').innerHTML=S.parser.map((p,i)=>card('parser',p,i)).join('')||'<div class="hint">暂无解析中心 Provider</div>'; $('legacyProviders').innerHTML=S.legacy.map((p,i)=>card('legacy',p,i)).join('')||'<div class="hint">暂无旧环境变量 Provider</div>' }
function addProvider(kind){S[kind].push({id:`lolban-${kind}-${Date.now()}`,name:'新封号 Provider',enabled:false,request:{method:'GET',url:'https://',timeout_seconds:10,headers:{},query:{qq:'$qq'},form:{},json:null},parser:{}});render()}function removeProvider(kind,index){S[kind].splice(index,1);render()}
function collect(kind){return [...document.querySelectorAll(`[data-kind="${kind}"]`)].map((el,i)=>({id:el.querySelector('[data-f="id"]').value.trim(),name:el.querySelector('[data-f="name"]').value.trim(),enabled:el.querySelector('[data-f="enabled"]').checked,request:{method:el.querySelector('[data-f="method"]').value,url:el.querySelector('[data-f="url"]').value.trim(),timeout_seconds:Number(el.querySelector('[data-f="timeout"]').value||10),headers:parseJson(el.querySelector('[data-f="headers"]').value,`Provider ${i+1} Headers`,{}),query:parseJson(el.querySelector('[data-f="query"]').value,`Provider ${i+1} Query`,{}),form:parseJson(el.querySelector('[data-f="form"]').value,`Provider ${i+1} Form`,{}),json:parseJson(el.querySelector('[data-f="json"]').value,`Provider ${i+1} JSON Body`,null)},parser:parseJson(el.querySelector('[data-f="parser"]').value,`Provider ${i+1} Parser`,{})}))}
function setState(d){const disk=d.disk||{},runtime=d.runtime||{};S.parser=(disk.parser_center&&disk.parser_center.providers)||[];S.legacy=(disk.legacy&&disk.legacy.providers)||[];S.runtime=runtime;$('parserPath').textContent=`配置文件：${disk.parser_center?.path||'-'}${disk.parser_center?.using_default?'（当前使用默认模板）':''}`;$('legacyPath').textContent=`配置文件：${disk.legacy?.path||'-'}`;$('legacyError').textContent=disk.legacy?.error||'';const st=disk.settings||{};$('sTimeout').value=st.LOL_BAN_TIMEOUT||10;$('sNormal').value=st.LOL_BAN_NORMAL_CACHE_SECONDS||60;$('sBanned').value=st.LOL_BAN_BANNED_CACHE_SECONDS||300;$('sStale').value=st.LOL_BAN_STALE_CACHE_SECONDS||86400;$('sMax').value=st.LOL_BAN_MAX_STALE_ENTRIES||1024;$('sSnapshot').checked=!['0','false','no','off',''].includes(String(st.LOL_BAN_SNAPSHOT_ENABLED??'1').toLowerCase());$('legacyUrl').value=disk.legacy?.upstream_url||'';$('diskCount').textContent=(disk.active_provider_identity||[]).length;$('runtimeCount').textContent=runtime.provider_count??'-';$('matchState').textContent=d.runtime_matches_disk?'一致':'不一致';$('matchState').className=d.runtime_matches_disk?'ok':'bad';const h=runtime.health||{};$('healthState').textContent=h.last_error_class?`失败：${h.last_error_class}`:(h.configured?'已配置':'未配置');$('healthState').className=h.last_error_class?'bad':'ok';$('runtimeResult').textContent=pretty(runtime);const providers=runtime.providers||[];$('testProvider').innerHTML=providers.map(p=>`<option value="${attr(p.id||p.name)}">${esc((p.order||'')+' · '+(p.name||p.id||''))}</option>`).join('');render()}
async function loadAll(){try{setState(await api('/admin/query-console/lolban'))}catch(e){alert(e.message)}}
async function saveAll(){try{const body={parser_providers:collect('parser'),legacy_providers:collect('legacy'),legacy_upstream_url:$('legacyUrl').value.trim(),settings:{LOL_BAN_TIMEOUT:Number($('sTimeout').value),LOL_BAN_NORMAL_CACHE_SECONDS:Number($('sNormal').value),LOL_BAN_BANNED_CACHE_SECONDS:Number($('sBanned').value),LOL_BAN_STALE_CACHE_SECONDS:Number($('sStale').value),LOL_BAN_MAX_STALE_ENTRIES:Number($('sMax').value),LOL_BAN_SNAPSHOT_ENABLED:$('sSnapshot').checked}};const r=await api('/admin/query-console/lolban/save',{method:'POST',body});alert(r.message||'保存完成');setState(r.state)}catch(e){alert(e.message)}}
async function runTest(){try{$('providerResult').textContent='测试中...';$('formalResult').textContent='测试中...';const r=await api('/admin/query-console/lolban/test',{method:'POST',body:{qq:$('testQQ').value.trim(),provider_id:$('testProvider').value}});$('providerResult').textContent=pretty(r.provider_test);$('formalResult').textContent=pretty(r.formal_chain)}catch(e){$('providerResult').textContent=e.message;$('formalResult').textContent=e.message}}
$('adminToken').value=token();loadAll();
</script></body></html>'''


def install_lolban_console_routes(app: FastAPI) -> None:
    @app.get("/query-console/lolban", response_class=HTMLResponse)
    async def lolban_console_page() -> str:
        return render_lolban_console_page()

    @app.get("/admin/query-console/lolban")
    async def admin_lolban_console() -> dict[str, Any]:
        return read_lolban_console(app.state.main_base_url)

    @app.post("/admin/query-console/lolban/save")
    async def admin_lolban_console_save(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return save_lolban_console(app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"封号查询配置写入失败：{exc}") from exc

    @app.post("/admin/query-console/lolban/test")
    async def admin_lolban_console_test(payload: dict[str, Any]) -> dict[str, Any]:
        return test_lolban_console(app.state.main_base_url, payload)
