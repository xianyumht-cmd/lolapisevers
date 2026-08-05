from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_regex(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"regex anchor count={count} in {path}: {pattern[:120]!r}")
    path.write_text(next_text, encoding="utf-8")


def patch_lolban_console() -> None:
    path = ROOT / "lanzou_update_push_api_server" / "lolban_console.py"

    replace_once(
        path,
        '''_LOLBAN_RELOAD_KEYS = (
    "LOL_BAN_PROVIDERS_JSON",
    "LOL_BAN_UPSTREAM_URL",
    *_LOLBAN_SETTING_KEYS,
    "LOL_BAN_4PNG_TOKEN",
)
''',
        '''_LOLBAN_RELOAD_KEYS = (
    "LOL_BAN_PROVIDERS_JSON",
    "LOL_BAN_UPSTREAM_URL",
    *_LOLBAN_SETTING_KEYS,
    "LOLMAP_API_TOKEN",
    "LOL_BAN_4PNG_TOKEN",
)
_LOLBAN_PROVIDER_SECRET_SPECS: dict[str, dict[str, str]] = {
    "lolban-primary": {
        "name": "LOLMAP_API_TOKEN",
        "label": "主接口 Token",
    },
    "lolban-4png": {
        "name": "LOL_BAN_4PNG_TOKEN",
        "label": "4PNG Token",
    },
}
''',
    )

    replace_once(
        path,
        '''    disk_secret_value = str(_file_values.get("LOL_BAN_4PNG_TOKEN") or os.getenv("LOL_BAN_4PNG_TOKEN") or "").strip()
    disk_secret_configured = bool(disk_secret_value and disk_secret_value != "CHANGE_ME")
    runtime_secret_configured = False
    for secret in runtime.get("secrets") if isinstance(runtime.get("secrets"), list) else []:
        if isinstance(secret, Mapping) and secret.get("name") == "LOL_BAN_4PNG_TOKEN":
            runtime_secret_configured = bool(secret.get("configured"))
    return {
        "ok": True,
        "disk": disk,
        "runtime": runtime,
        "runtime_provider_identity": safe_runtime_identity,
        "runtime_matches_disk": runtime.get("ok") is True and safe_runtime_identity == disk_identity,
        "fourpng_secret": {
            "disk_configured": disk_secret_configured,
            "runtime_configured": runtime_secret_configured,
            "in_sync": disk_secret_configured == runtime_secret_configured,
        },
    }
''',
        '''    runtime_secret_states: dict[str, bool] = {}
    for secret in runtime.get("secrets") if isinstance(runtime.get("secrets"), list) else []:
        if not isinstance(secret, Mapping):
            continue
        name = str(secret.get("name") or "").strip()
        if name:
            runtime_secret_states[name] = bool(secret.get("configured"))

    provider_secrets: dict[str, dict[str, Any]] = {}
    for provider_id, spec in _LOLBAN_PROVIDER_SECRET_SPECS.items():
        name = spec["name"]
        disk_value = str(_file_values.get(name) or os.getenv(name) or "").strip()
        disk_configured = bool(disk_value and disk_value != "CHANGE_ME")
        runtime_configured = bool(runtime_secret_states.get(name))
        provider_secrets[provider_id] = {
            "label": spec["label"],
            "secret_name": name,
            "disk_configured": disk_configured,
            "runtime_configured": runtime_configured,
            "in_sync": disk_configured == runtime_configured,
        }

    return {
        "ok": True,
        "disk": disk,
        "runtime": runtime,
        "runtime_provider_identity": safe_runtime_identity,
        "runtime_matches_disk": runtime.get("ok") is True and safe_runtime_identity == disk_identity,
        "provider_secrets": provider_secrets,
        "fourpng_secret": provider_secrets["lolban-4png"],
    }
''',
    )

    replace_regex(
        path,
        r'''def save_fourpng_token\(main_base_url: str, payload: Mapping\[str, Any\]\) -> dict\[str, Any\]:\n.*?\n\n\ndef test_lolban_console''',
        '''def save_provider_secret(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = str(payload.get("provider_id") or "").strip()
    spec = _LOLBAN_PROVIDER_SECRET_SPECS.get(provider_id)
    if spec is None:
        raise ValueError("该 Provider 没有可配置的专用 Secret")
    value = str(payload.get("value") or "").strip()
    if not value:
        raise ValueError(f"{spec['label']} 不能为空")

    secret_name = spec["name"]
    saved = save_parser_secret({"name": secret_name, "value": value})
    reload_result = _main_request(
        main_base_url,
        "POST",
        "/admin/query/lolban/reload",
        payload={"environment": {secret_name: value}},
    )
    loaded = reload_result.get("ok") is True
    return {
        "ok": loaded,
        "provider_id": provider_id,
        "configured": True,
        "runtime_configured": loaded,
        "message": (
            f"{spec['label']} 已安全保存并热加载到 5001。"
            if loaded
            else f"{spec['label']} 已安全保存，但 5001 热加载失败；请重启 LOLDataSystem。"
        ),
        "save_result": _result_summary(saved),
        "reload_result": reload_result,
    }


def save_fourpng_token(main_base_url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return save_provider_secret(
        main_base_url,
        {"provider_id": "lolban-4png", "value": payload.get("value")},
    )


def test_lolban_console''',
    )

    replace_once(
        path,
        '''.provider .head h3{margin:0;font-size:15px}.switch{display:flex;gap:8px;align-items:center}.switch input{width:auto}.card{margin:0}.card b{display:block;font-size:20px;margin-top:5px}@media(max-width:900px){.grid,.two,.cards{grid-template-columns:1fr}}
''',
        '''.provider .head h3{margin:0;font-size:15px}.switch{display:flex;gap:8px;align-items:center}.switch input{width:auto}.provider-secret{display:grid;grid-template-columns:minmax(190px,1fr) minmax(230px,1.3fr) auto;gap:10px;align-items:end;margin:10px 0;padding:10px 12px;border:1px solid #dbe6f5;border-radius:9px;background:#f8fbff}.provider-secret-title{font-weight:800;font-size:13px}.provider-secret-meta{margin-top:3px;color:var(--muted);font:11px ui-monospace,SFMono-Regular,Consolas,monospace}.provider-secret-state{display:inline-block;margin-top:5px;font-size:12px;font-weight:700}.provider-secret button{white-space:nowrap}.card{margin:0}.card b{display:block;font-size:20px;margin-top:5px}@media(max-width:900px){.grid,.two,.cards{grid-template-columns:1fr}.provider-secret{grid-template-columns:1fr}}
''',
    )

    replace_once(
        path,
        '''const S={parser:[],legacy:[],runtime:{}};const $=id=>document.getElementById(id);
''',
        '''const S={parser:[],legacy:[],runtime:{},providerSecrets:{}};const $=id=>document.getElementById(id);
''',
    )

    replace_once(
        path,
        '''function normalize(p,i){p=obj(p);const req=obj(p.request,p);return {id:p.id||p.name||`provider-${i+1}`,name:p.name||p.id||`Provider ${i+1}`,enabled:p.enabled!==false,request:{method:(req.method||'GET').toUpperCase(),url:req.url||p.url||'',timeout_seconds:req.timeout_seconds||p.timeout_seconds||10,headers:obj(req.headers),query:obj(req.query),form:obj(req.form),json:req.json??req.json_body??null},parser:obj(p.parser)}}
function card(kind,p,index){p=normalize(p,index);return `<div class="provider" data-kind="${kind}" data-index="${index}"><div class="head"><h3>${esc(p.name||p.id)}</h3><div class="actions"><label class="switch"><input data-f="enabled" type="checkbox" ${p.enabled?'checked':''}><span>启用</span></label><button class="danger" onclick="removeProvider('${kind}',${index})">删除</button></div></div><div class="grid"><label><span>ID</span><input data-f="id" value="${attr(p.id)}"></label><label><span>名称</span><input data-f="name" value="${attr(p.name)}"></label><label><span>方法</span><select data-f="method"><option ${p.request.method==='GET'?'selected':''}>GET</option><option ${p.request.method==='POST'?'selected':''}>POST</option></select></label><label><span>超时秒数</span><input data-f="timeout" type="number" value="${attr(p.request.timeout_seconds)}"></label></div><label><span>API URL（敏感参数显示 ***）</span><input data-f="url" value="${attr(p.request.url)}"></label><div class="grid two"><label><span>Query JSON</span><textarea data-f="query">${esc(pretty(p.request.query))}</textarea></label><label><span>Form JSON</span><textarea data-f="form">${esc(pretty(p.request.form))}</textarea></label><label><span>Headers JSON（敏感值显示 ***）</span><textarea data-f="headers">${esc(pretty(p.request.headers))}</textarea></label><label><span>JSON Body</span><textarea data-f="json">${esc(pretty(p.request.json))}</textarea></label></div><label><span>响应解析规则 JSON</span><textarea data-f="parser">${esc(pretty(p.parser))}</textarea></label></div>`}
''',
        '''function normalize(p,i){p=obj(p);const req=obj(p.request,p);return {id:p.id||p.name||`provider-${i+1}`,name:p.name||p.id||`Provider ${i+1}`,enabled:p.enabled!==false,request:{method:(req.method||'GET').toUpperCase(),url:req.url||p.url||'',timeout_seconds:req.timeout_seconds||p.timeout_seconds||10,headers:obj(req.headers),query:obj(req.query),form:obj(req.form),json:req.json??req.json_body??null},parser:obj(p.parser)}}
function providerSecretControl(p){const state=S.providerSecrets[p.id];if(!state)return '';const ready=state.disk_configured&&state.runtime_configured;const partial=state.disk_configured&&!state.runtime_configured;const status=ready?'已配置并加载':(partial?'磁盘已配置，5001 未加载':'未配置');const statusClass=ready?'ok':'bad';return `<div class="provider-secret"><div><div class="provider-secret-title">${esc(state.label||'Provider Token')}</div><div class="provider-secret-meta">${esc(state.secret_name||'')}</div><span class="provider-secret-state ${statusClass}">${esc(status)}</span></div><label><span>输入新 Token（留空不修改）</span><input type="password" autocomplete="new-password" data-secret-provider="${attr(p.id)}" placeholder="仅安全写入本机 Secret"></label><button type="button" onclick="saveProviderSecret('${attr(p.id)}')">保存 Token</button></div>`}
function card(kind,p,index){p=normalize(p,index);return `<div class="provider" data-kind="${kind}" data-index="${index}"><div class="head"><h3>${esc(p.name||p.id)}</h3><div class="actions"><label class="switch"><input data-f="enabled" type="checkbox" ${p.enabled?'checked':''}><span>启用</span></label><button class="danger" onclick="removeProvider('${kind}',${index})">删除</button></div></div><div class="grid"><label><span>ID</span><input data-f="id" value="${attr(p.id)}"></label><label><span>名称</span><input data-f="name" value="${attr(p.name)}"></label><label><span>方法</span><select data-f="method"><option ${p.request.method==='GET'?'selected':''}>GET</option><option ${p.request.method==='POST'?'selected':''}>POST</option></select></label><label><span>超时秒数</span><input data-f="timeout" type="number" value="${attr(p.request.timeout_seconds)}"></label></div><label><span>API URL（敏感参数显示 ***）</span><input data-f="url" value="${attr(p.request.url)}"></label>${providerSecretControl(p)}<div class="grid two"><label><span>Query JSON</span><textarea data-f="query">${esc(pretty(p.request.query))}</textarea></label><label><span>Form JSON</span><textarea data-f="form">${esc(pretty(p.request.form))}</textarea></label><label><span>Headers JSON（敏感值显示 ***）</span><textarea data-f="headers">${esc(pretty(p.request.headers))}</textarea></label><label><span>JSON Body</span><textarea data-f="json">${esc(pretty(p.request.json))}</textarea></label></div><label><span>响应解析规则 JSON</span><textarea data-f="parser">${esc(pretty(p.parser))}</textarea></label></div>`}
''',
    )

    replace_once(
        path,
        '''function setState(d){const disk=d.disk||{},runtime=d.runtime||{};S.parser=disk.parser_center?.providers||[];S.legacy=disk.legacy?.providers||[];S.runtime=runtime;$('parserPath').textContent=`配置文件：${disk.parser_center?.path||'-'}${disk.parser_center?.using_default?'（当前使用默认模板）':''}`;
''',
        '''function setState(d){const disk=d.disk||{},runtime=d.runtime||{};S.parser=disk.parser_center?.providers||[];S.legacy=disk.legacy?.providers||[];S.runtime=runtime;S.providerSecrets=d.provider_secrets||{};$('parserPath').textContent=`配置文件：${disk.parser_center?.path||'-'}${disk.parser_center?.using_default?'（当前使用默认模板）':''}`;
''',
    )

    replace_once(
        path,
        '''async function saveAll(){try{const body={parser_providers:collect('parser'),legacy_providers:collect('legacy'),legacy_upstream_url:$('legacyUrl').value.trim(),settings:{LOL_BAN_TIMEOUT:Number($('sTimeout').value),LOL_BAN_NORMAL_CACHE_SECONDS:Number($('sNormal').value),LOL_BAN_BANNED_CACHE_SECONDS:Number($('sBanned').value),LOL_BAN_STALE_CACHE_SECONDS:Number($('sStale').value),LOL_BAN_MAX_STALE_ENTRIES:Number($('sMax').value),LOL_BAN_SNAPSHOT_ENABLED:$('sSnapshot').checked}};const r=await api('/admin/query-console/lolban/save',{method:'POST',body});alert(r.message||'保存完成');setState(r.state)}catch(e){alert(e.message)}}
''',
        '''async function saveAll(){try{const body={parser_providers:collect('parser'),legacy_providers:collect('legacy'),legacy_upstream_url:$('legacyUrl').value.trim(),settings:{LOL_BAN_TIMEOUT:Number($('sTimeout').value),LOL_BAN_NORMAL_CACHE_SECONDS:Number($('sNormal').value),LOL_BAN_BANNED_CACHE_SECONDS:Number($('sBanned').value),LOL_BAN_STALE_CACHE_SECONDS:Number($('sStale').value),LOL_BAN_MAX_STALE_ENTRIES:Number($('sMax').value),LOL_BAN_SNAPSHOT_ENABLED:$('sSnapshot').checked}};const r=await api('/admin/query-console/lolban/save',{method:'POST',body});alert(r.message||'保存完成');setState(r.state)}catch(e){alert(e.message)}}
async function saveProviderSecret(providerId){const input=Array.from(document.querySelectorAll('[data-secret-provider]')).find(item=>item.dataset.secretProvider===providerId);const value=input?input.value.trim():'';if(!value){alert('请输入新的 Token');return}try{const r=await api('/admin/query-console/lolban/provider-secret',{method:'POST',body:{provider_id:providerId,value}});input.value='';alert(r.message||'Token 已安全保存');await loadAll()}catch(e){alert(e.message)}}
''',
    )

    replace_once(
        path,
        '''    @app.post("/admin/query-console/lolban/4png-token")
    async def admin_lolban_fourpng_token(payload: dict[str, Any]) -> dict[str, Any]:
''',
        '''    @app.post("/admin/query-console/lolban/provider-secret")
    async def admin_lolban_provider_secret(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(save_provider_secret, app.state.main_base_url, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Provider Token 写入失败：{exc}") from exc

    @app.post("/admin/query-console/lolban/4png-token")
    async def admin_lolban_fourpng_token(payload: dict[str, Any]) -> dict[str, Any]:
''',
    )


def patch_query_admin() -> None:
    path = ROOT / "routers" / "query_admin.py"
    replace_once(
        path,
        '''    "LOL_BAN_SNAPSHOT_ENABLED",
    "LOL_BAN_4PNG_TOKEN",
}
''',
        '''    "LOL_BAN_SNAPSHOT_ENABLED",
    "LOLMAP_API_TOKEN",
    "LOL_BAN_4PNG_TOKEN",
}
''',
    )
    replace_once(
        path,
        '''        "secrets": [
            {"name": "LOL_BAN_4PNG_TOKEN", "configured": _secret_configured("LOL_BAN_4PNG_TOKEN")},
        ],
''',
        '''        "secrets": [
            {"name": "LOLMAP_API_TOKEN", "configured": _secret_configured("LOLMAP_API_TOKEN")},
            {"name": "LOL_BAN_4PNG_TOKEN", "configured": _secret_configured("LOL_BAN_4PNG_TOKEN")},
        ],
''',
    )


def patch_navigation() -> None:
    path = ROOT / "lanzou_update_push_api_server" / "control_navigation.py"
    replace_regex(
        path,
        r'''\n_LOLBAN_SECRET_PANEL = r'''.*?\n\ndef select_parser_center_section''',
        '''\n\ndef select_parser_center_section''',
    )
    replace_once(
        path,
        '''def apply_control_navigation(page: str, *, active: str) -> str:
    if active == "lolban":
        page = _inject_lolban_secret_controls(page)
    if 'id="control-navigation-style"' in page:
''',
        '''def apply_control_navigation(page: str, *, active: str) -> str:
    if 'id="control-navigation-style"' in page:
''',
    )


def patch_tests() -> None:
    path = ROOT / "tests" / "test_lolban_query_console.py"
    replace_once(
        path,
        '''    render_lolban_console_page,
    save_fourpng_token,
    test_lolban_console,
''',
        '''    render_lolban_console_page,
    save_fourpng_token,
    save_provider_secret,
    test_lolban_console,
''',
    )
    replace_once(
        path,
        '''                {"environment": {"LOL_BAN_TIMEOUT": "12", "LOL_BAN_SNAPSHOT_ENABLED": "1", "LOL_BAN_4PNG_TOKEN": "secret"}}
            )
            self.assertEqual(changed, ["LOL_BAN_TIMEOUT", "LOL_BAN_SNAPSHOT_ENABLED", "LOL_BAN_4PNG_TOKEN"])
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "12")
            self.assertEqual(os.environ["LOL_BAN_4PNG_TOKEN"], "secret")
''',
        '''                {"environment": {"LOL_BAN_TIMEOUT": "12", "LOL_BAN_SNAPSHOT_ENABLED": "1", "LOLMAP_API_TOKEN": "primary-secret", "LOL_BAN_4PNG_TOKEN": "backup-secret"}}
            )
            self.assertEqual(changed, ["LOL_BAN_TIMEOUT", "LOL_BAN_SNAPSHOT_ENABLED", "LOLMAP_API_TOKEN", "LOL_BAN_4PNG_TOKEN"])
            self.assertEqual(os.environ["LOL_BAN_TIMEOUT"], "12")
            self.assertEqual(os.environ["LOLMAP_API_TOKEN"], "primary-secret")
            self.assertEqual(os.environ["LOL_BAN_4PNG_TOKEN"], "backup-secret")
''',
    )
    replace_once(
        path,
        '''    def test_fourpng_token_save_hot_reloads_without_returning_value(self):
        with patch(
            "lanzou_update_push_api_server.lolban_console.save_parser_secret",
            return_value={"ok": True, "message": "saved", "backup_path": "backup"},
        ) as save_secret, patch(
            "lanzou_update_push_api_server.lolban_console._main_request",
            return_value={"ok": True, "changed_environment": ["LOL_BAN_4PNG_TOKEN"]},
        ) as main_request:
            result = save_fourpng_token("http://127.0.0.1:5001", {"value": "real-token"})
        save_secret.assert_called_once_with(
            {"name": "LOL_BAN_4PNG_TOKEN", "value": "real-token"}
        )
        self.assertEqual(
            main_request.call_args.kwargs["payload"],
            {"environment": {"LOL_BAN_4PNG_TOKEN": "real-token"}},
        )
        self.assertTrue(result["ok"])
        self.assertNotIn("real-token", str(result))
''',
        '''    def test_provider_tokens_save_hot_reload_without_returning_values(self):
        for provider_id, secret_name in (
            ("lolban-primary", "LOLMAP_API_TOKEN"),
            ("lolban-4png", "LOL_BAN_4PNG_TOKEN"),
        ):
            with self.subTest(provider_id=provider_id), patch(
                "lanzou_update_push_api_server.lolban_console.save_parser_secret",
                return_value={"ok": True, "message": "saved", "backup_path": "backup"},
            ) as save_secret, patch(
                "lanzou_update_push_api_server.lolban_console._main_request",
                return_value={"ok": True, "changed_environment": [secret_name]},
            ) as main_request:
                result = save_provider_secret(
                    "http://127.0.0.1:5001",
                    {"provider_id": provider_id, "value": "real-token"},
                )
            save_secret.assert_called_once_with(
                {"name": secret_name, "value": "real-token"}
            )
            self.assertEqual(
                main_request.call_args.kwargs["payload"],
                {"environment": {secret_name: "real-token"}},
            )
            self.assertTrue(result["ok"])
            self.assertNotIn("real-token", str(result))

    def test_fourpng_compatibility_endpoint_uses_provider_secret_path(self):
        with patch(
            "lanzou_update_push_api_server.lolban_console.save_provider_secret",
            return_value={"ok": True},
        ) as save_secret:
            result = save_fourpng_token("http://127.0.0.1:5001", {"value": "legacy-token"})
        self.assertTrue(result["ok"])
        save_secret.assert_called_once_with(
            "http://127.0.0.1:5001",
            {"provider_id": "lolban-4png", "value": "legacy-token"},
        )
''',
    )
    replace_once(
        path,
        '''        self.assertIn("测试正式链路", page)
''',
        '''        self.assertIn("测试正式链路", page)
        self.assertIn("LOLMAP_API_TOKEN", page)
        self.assertIn("LOL_BAN_4PNG_TOKEN", page)
        self.assertIn("/admin/query-console/lolban/provider-secret", page)
        self.assertIn("providerSecretControl", page)
''',
    )

    nav = ROOT / "tests" / "test_control_navigation.py"
    replace_once(
        nav,
        '''    def test_lolban_page_has_direct_secure_4png_secret_control(self):
        raw = render_lolban_console_page()
        page = _decorate_control_page("/query-console/lolban", raw)
        self.assertIn('4PNG Token', page)
        self.assertIn('LOL_BAN_4PNG_TOKEN', page)
        self.assertIn('/admin/query-console/lolban/4png-token', page)
        self.assertIn('安全保存 Token', page)
        self.assertIn('class="control-sidebar"', page)
''',
        '''    def test_lolban_page_keeps_provider_tokens_inside_provider_cards(self):
        raw = render_lolban_console_page()
        page = _decorate_control_page("/query-console/lolban", raw)
        self.assertIn('主接口 Token', page)
        self.assertIn('LOLMAP_API_TOKEN', page)
        self.assertIn('4PNG Token', page)
        self.assertIn('LOL_BAN_4PNG_TOKEN', page)
        self.assertIn('/admin/query-console/lolban/provider-secret', page)
        self.assertIn('providerSecretControl', page)
        self.assertNotIn('id="fourPngSecretPanel"', page)
        self.assertIn('class="control-sidebar"', page)
''',
    )


def main() -> None:
    patch_lolban_console()
    patch_query_admin()
    patch_navigation()
    patch_tests()


if __name__ == "__main__":
    main()
