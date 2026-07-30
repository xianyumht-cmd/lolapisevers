from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from services.contact_risk_report_delivery import (
    list_report_retry_queue,
    remove_report_retry_item,
    retry_report_queue,
)


def _render_retry_queue_page() -> str:
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>举报待补交队列</title>
<style>
:root{color-scheme:light dark;--bg:#eef2f8;--panel:rgba(255,255,255,.82);--text:#172033;--muted:#66758b;--line:rgba(128,145,170,.28);--primary:#2563eb;--danger:#b42318;--code:#101827}
@media(prefers-color-scheme:dark){:root{--bg:#0d1421;--panel:rgba(25,36,54,.86);--text:#e7edf7;--muted:#a8b4c7;--line:rgba(170,190,220,.2);--primary:#6ea0ff;--danger:#ff8b82;--code:#060a11}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1400px;margin:auto;padding:20px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px;margin-bottom:14px;backdrop-filter:blur(22px)}h1{margin:0 0 6px;font-size:26px}.hint{font-size:12px;color:var(--muted);line-height:1.6}.top,.toolbar{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}button,a{border:1px solid var(--line);border-radius:11px;padding:9px 12px;background:var(--panel);color:var(--text);font:inherit;font-weight:720;text-decoration:none;cursor:pointer}button.primary{background:var(--primary);border-color:transparent;color:white}button.danger{color:var(--danger)}input,select{border:1px solid var(--line);border-radius:11px;padding:9px;background:var(--panel);color:var(--text)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:13px;max-height:680px}table{border-collapse:collapse;width:100%;min-width:1040px}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:12px}th{position:sticky;top:0;background:var(--panel)}pre{margin:0;white-space:pre-wrap;word-break:break-word;max-width:380px}.status{display:inline-flex;border-radius:999px;padding:3px 7px;background:rgba(100,120,160,.14);font-size:11px;font-weight:800}.result{white-space:pre-wrap;background:var(--code);color:#e5e7eb;border-radius:13px;padding:12px;min-height:70px;max-height:300px;overflow:auto;font:12px/1.55 ui-monospace,Consolas,monospace}.toast{display:none;position:fixed;right:18px;bottom:18px;padding:11px 14px;border-radius:12px;background:#111827;color:white;z-index:5}.toast.bad{background:#7f1d1d}@media(max-width:700px){.shell{padding:10px}.top{align-items:flex-start}.toolbar{justify-content:flex-start}}
</style>
</head>
<body>
<main class="shell">
<section class="panel top">
  <div><h1>举报待补交队列</h1><div class="hint">第三方举报暂时失败时，本地记录不会丢失。队列只保存 Provider ID 和提交参数，不保存第三方 URL、Headers 或 Secret。</div></div>
  <div class="toolbar"><input id="adminToken" type="password" placeholder="管理令牌（本机可留空）"><button onclick="saveToken()">应用令牌</button><a href="/parser-center">返回解析中心</a></div>
</section>
<section class="panel">
  <div class="top"><div class="toolbar"><select id="state"><option value="">全部状态</option><option value="pending">待补交</option><option value="failed">已达重试上限</option><option value="completed">已完成</option><option value="rejected">已拒绝</option></select><button onclick="loadQueue()">刷新</button><button class="primary" onclick="retryDue()">重试到期项目</button></div><div class="hint" id="summary">尚未读取</div></div>
  <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>ID</th><th>状态</th><th>功能</th><th>Provider ID</th><th>请求编号</th><th>尝试</th><th>下次时间</th><th>提交参数</th><th>操作</th></tr></thead><tbody id="rows"></tbody></table></div>
</section>
<section class="panel"><div class="top"><strong>操作结果</strong><span class="hint">不会显示第三方身份或密钥</span></div><pre id="result" class="result">暂无</pre></section>
</main>
<div id="toast" class="toast"></div>
<script>
const $=id=>document.getElementById(id);function token(){return sessionStorage.getItem('lolapisevers_admin_token')||''}function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function toast(m,b=false){const n=$('toast');n.textContent=m;n.className='toast'+(b?' bad':'');n.style.display='block';clearTimeout(window.__t);window.__t=setTimeout(()=>n.style.display='none',3500)}function saveToken(){const v=$('adminToken').value.trim();if(v)sessionStorage.setItem('lolapisevers_admin_token',v);else sessionStorage.removeItem('lolapisevers_admin_token');loadQueue()}async function api(path,opt={}){const h={'content-type':'application/json'};if(token())h['x-admin-token']=token();const r=await fetch(path,{method:opt.method||'GET',headers:h,body:opt.body===undefined?undefined:JSON.stringify(opt.body)});const t=await r.text();let d;try{d=JSON.parse(t)}catch(_){d={detail:t}}if(!r.ok)throw new Error(d.detail||d.error||t||r.statusText);return d}function when(ms){if(!ms)return '-';try{return new Date(Number(ms)).toLocaleString()}catch(_){return '-'}}async function loadQueue(){try{const state=$('state').value;const d=await api('/admin/parser-center/report-queue?state='+encodeURIComponent(state)+'&limit=200');$('summary').textContent=`${d.count||0} 项`;$('rows').innerHTML=(d.items||[]).map(item=>`<tr><td>${item.queue_id}</td><td><span class="status">${esc(item.state)}</span></td><td>${esc(item.feature)}</td><td>${esc(item.provider_id)}</td><td>${esc(item.request_id)}</td><td>${item.attempts}</td><td>${esc(when(item.next_attempt_at))}</td><td><pre>${esc(JSON.stringify(item.parameters,null,2))}</pre></td><td><div class="toolbar"><button onclick="retryOne(${item.queue_id})">重试</button><button class="danger" onclick="removeOne(${item.queue_id})">移除</button></div></td></tr>`).join('')||'<tr><td colspan="9" class="hint">队列为空</td></tr>';toast('队列已刷新')}catch(e){toast(e.message,true)}}async function retryDue(){try{const d=await api('/admin/parser-center/report-queue/retry',{method:'POST',body:{limit:50}});$('result').textContent=JSON.stringify(d,null,2);toast(`处理 ${d.processed||0} 项`);await loadQueue()}catch(e){toast(e.message,true)}}async function retryOne(id){try{const d=await api('/admin/parser-center/report-queue/retry',{method:'POST',body:{queue_id:id,limit:1}});$('result').textContent=JSON.stringify(d,null,2);await loadQueue()}catch(e){toast(e.message,true)}}async function removeOne(id){if(!confirm(`确认移除队列项目 ${id}？本地举报记录不会删除。`))return;try{const d=await api('/admin/parser-center/report-queue/remove',{method:'POST',body:{queue_id:id}});$('result').textContent=JSON.stringify(d,null,2);await loadQueue()}catch(e){toast(e.message,true)}}$('adminToken').value=token();$('state').onchange=loadQueue;loadQueue();
</script>
</body>
</html>'''


def install_parser_center_retry_routes(app: FastAPI) -> None:
    @app.get("/parser-center/report-queue", response_class=HTMLResponse)
    async def parser_center_report_queue_page() -> str:
        return _render_retry_queue_page()

    @app.get("/admin/parser-center/report-queue")
    async def admin_parser_center_report_queue(
        state: str = "",
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            list_report_retry_queue,
            state=str(state or "").strip(),
            limit=limit,
        )

    @app.post("/admin/parser-center/report-queue/retry")
    async def admin_parser_center_report_queue_retry(
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = payload or {}
        return await retry_report_queue(
            queue_id=max(0, int(body.get("queue_id") or 0)),
            limit=max(1, min(int(body.get("limit") or 20), 100)),
        )

    @app.post("/admin/parser-center/report-queue/remove")
    async def admin_parser_center_report_queue_remove(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        queue_id = int(payload.get("queue_id") or 0)
        if queue_id <= 0:
            return {"ok": False, "error": "queue_id is required"}
        return await asyncio.to_thread(remove_report_retry_item, queue_id)
