from __future__ import annotations

from html import escape


_NAVIGATION_GROUPS = (
    (
        "总览",
        (("overview", "/", "控制台总览", "dashboard"),),
    ),
    (
        "查询服务",
        (
            ("lolban", "/query-console/lolban", "封号查询", "shield"),
            ("parser-center", "/parser-center", "接口与解析中心", "workflow"),
            ("parser-secrets", "/parser-center/secrets", "Secret 与备份", "key"),
        ),
    ),
    (
        "蓝奏监控",
        (
            ("lanzou-config", "/?tab=lanzouconfig", "全局配置", "settings"),
            ("watchers", "/?tab=watchers", "监控项目", "radar"),
            ("targets", "/?tab=targets", "通知目标", "bell"),
        ),
    ),
    (
        "系统管理",
        (
            ("main-config", "/?tab=mainconfig", "主接口配置", "server"),
            ("logs", "/?tab=logs", "运行日志", "file-text"),
            ("diagnostics", "/?tab=diagnostics", "诊断与修复", "activity"),
            ("system", "/?tab=system", "安全与回滚", "lock"),
        ),
    ),
    (
        "开发与文档",
        (("docs", "/docs", "OpenAPI 文档", "book"),),
    ),
)


def icon(name: str) -> str:
    safe_name = escape(name, quote=True)
    return (
        '<svg class="ui-icon" aria-hidden="true">'
        f'<use href="/control-assets/icons.svg#icon-{safe_name}"></use>'
        "</svg>"
    )


def nav_link(key: str, path: str, label: str, icon_name: str, *, active: str) -> str:
    current = key == active
    classes = "nav-link is-active" if current else "nav-link"
    current_attr = ' aria-current="page"' if current else ""
    return (
        f'<a href="{escape(path, quote=True)}" class="{classes}"{current_attr}>'
        f'{icon(icon_name)}<span>{escape(label)}</span></a>'
    )


def render_sidebar(*, active: str) -> str:
    groups = []
    for title, links in _NAVIGATION_GROUPS:
        rendered_links = "".join(
            nav_link(key, path, label, icon_name, active=active)
            for key, path, label, icon_name in links
        )
        groups.append(
            '<section class="nav-group">'
            f'<h2>{escape(title)}</h2>{rendered_links}'
            "</section>"
        )
    return f'''<aside class="sidebar" id="consoleSidebar" aria-label="主导航">
  <div class="brand">
    <div class="brand-mark">LD</div>
    <div><strong>LOLDataSystem</strong><span>运维控制台 · 6178</span></div>
  </div>
  <nav class="nav-groups">{"".join(groups)}</nav>
  <div class="sidebar-footer">
    <span class="status-dot status-dot-neutral"></span>
    <span>生产操作会校验、备份并记录审计</span>
  </div>
</aside>'''


def render_topbar(*, title: str) -> str:
    safe_title = escape(title)
    return f'''<header class="topbar">
  <button class="icon-button mobile-only" id="sidebarToggle" type="button" aria-label="打开导航">{icon('menu')}</button>
  <div class="breadcrumb"><span>LOLDataSystem</span><b>/</b><strong>{safe_title}</strong></div>
  <div class="topbar-actions">
    <span class="environment-badge"><span class="status-dot" id="globalStatusDot"></span><span id="globalStatusText">正在读取状态</span></span>
    <button class="button button-secondary" id="adminTokenButton" type="button">{icon('key')}<span>管理令牌</span></button>
  </div>
</header>'''


def render_admin_token_dialog() -> str:
    return f'''<dialog class="dialog" id="adminTokenDialog" aria-labelledby="adminTokenTitle">
  <form class="dialog-card" id="adminTokenForm">
    <header class="dialog-header">
      <div>
        <p class="eyebrow">访问控制</p>
        <h2 id="adminTokenTitle">管理令牌</h2>
      </div>
      <button class="icon-button" id="adminTokenClose" type="button" aria-label="关闭对话框">{icon('x')}</button>
    </header>
    <div class="dialog-body">
      <p class="dialog-description">令牌仅保存在当前浏览器标签页的会话存储中，关闭标签页后自动清除，不会写入服务配置或页面源码。</p>
      <label class="field" for="adminTokenInput">
        <span>WEBUI_ADMIN_TOKEN</span>
        <input id="adminTokenInput" name="admin_token" type="password" autocomplete="off" spellcheck="false" placeholder="请输入管理令牌">
        <small id="adminTokenHint">未配置令牌时，本机回环访问可以直接使用管理功能。</small>
      </label>
      <div class="inline-status" id="adminTokenStatus"><span class="status-dot status-dot-neutral"></span><span>当前标签页尚未保存令牌</span></div>
    </div>
    <footer class="dialog-footer">
      <button class="button button-danger-ghost" id="adminTokenClear" type="button">清除令牌</button>
      <span class="dialog-footer-spacer"></span>
      <button class="button button-secondary" id="adminTokenCancel" type="button">取消</button>
      <button class="button button-primary" type="submit">保存并重新读取</button>
    </footer>
  </form>
</dialog>'''


def render_console_shell(
    *,
    active: str,
    title: str,
    content: str,
    body_marker: str,
) -> str:
    safe_title = escape(title)
    safe_marker = escape(body_marker, quote=True)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>LOLDataSystem · {safe_title}</title>
<link rel="stylesheet" href="/control-assets/console.css">
</head>
<body data-console-ui="{safe_marker}">
<div class="app-shell">
  {render_sidebar(active=active)}
  <div class="workspace">
    {render_topbar(title=title)}
    <main class="content">{content}</main>
  </div>
</div>
<div class="sidebar-backdrop" id="sidebarBackdrop"></div>
{render_admin_token_dialog()}
<div class="toast-region" id="toastRegion" aria-live="polite"></div>
<!-- legacy compatibility markers: lolapisevers 接口端总控台 watcherRows /notify/test -->
<script src="/control-assets/console.js" defer></script>
</body>
</html>'''


__all__ = [
    "icon",
    "nav_link",
    "render_admin_token_dialog",
    "render_console_shell",
    "render_sidebar",
    "render_topbar",
]
