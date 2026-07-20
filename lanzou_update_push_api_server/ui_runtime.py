from __future__ import annotations

import re

from .ui_control import render_control_dashboard


_OPENAPI_FUNCTION = r'''async function loadOpenApi(notify=true){
  try{
    const results=await Promise.all([
      api('/admin/openapi/main'),
      api('/admin/openapi/lanzou')
    ]);
    const routes=[];
    const sources=[
      {data:results[0],service:'main'},
      {data:results[1],service:'lanzou'}
    ];
    for(const source of sources){
      const paths=(source.data.schema&&source.data.schema.paths)||{};
      for(const pathEntry of Object.entries(paths)){
        const path=pathEntry[0];
        const operations=pathEntry[1]||{};
        for(const operationEntry of Object.entries(operations)){
          const method=operationEntry[0];
          const operation=operationEntry[1]||{};
          if(!['get','post','put','patch','delete'].includes(method))continue;
          routes.push({
            service:source.service,
            path:path,
            method:method.toUpperCase(),
            summary:operation.summary||operation.operationId||'',
            parameters:operation.parameters||[],
            requestBody:operation.requestBody||null
          });
        }
      }
    }
    S.routes=routes.sort((a,b)=>(a.service+a.path+a.method).localeCompare(b.service+b.path+b.method));
    $('routeSelect').innerHTML=S.routes.map((route,index)=>
      `<option value="${index}">[${route.service}] ${route.method} ${esc(route.path)} · ${esc(route.summary)}</option>`
    ).join('');
    selectRoute();
    if(notify)toast(`已加载 ${S.routes.length} 个接口`);
  }catch(error){
    toast(error.message,true);
  }
}'''


def render_runtime_dashboard() -> str:
    page = render_control_dashboard()
    page, replacement_count = re.subn(
        r"async function loadOpenApi\(notify=true\)\{.*?\}\nfunction selectRoute",
        _OPENAPI_FUNCTION + "\nfunction selectRoute",
        page,
        count=1,
        flags=re.DOTALL,
    )
    if replacement_count != 1:
        raise RuntimeError("could not patch dashboard OpenAPI loader")

    page = page.replace(
        "<title>lolapisevers 全功能控制台</title>",
        "<title>lolapisevers 接口端总控台 · 全功能控制台</title>",
        1,
    )
    page = page.replace(
        "loadAll();setInterval(()=>loadAll(),30000);",
        "loadAll();setInterval(()=>{const active=document.querySelector('.tab.active');if(active&&active.dataset.tab==='overview')loadAll()},30000);",
        1,
    )
    return page
