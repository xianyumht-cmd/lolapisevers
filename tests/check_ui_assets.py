from pathlib import Path

from lanzou_update_push_api_server.server import _control_page


html = _control_page()
start_marker = "<script>"
end_marker = "</script>"
start = html.rfind(start_marker)
end = html.rfind(end_marker)
if start < 0 or end <= start:
    raise SystemExit("dashboard JavaScript block was not found")

script = html[start + len(start_marker) : end]
required_markers = [
    "/admin/main-config",
    "/admin/lanzou-config",
    "/admin/openapi/main",
    "/admin/logs",
    "/admin/diagnostics",
    "watcherRows",
    "targetRows",
]
missing = [marker for marker in required_markers if marker not in html]
if missing:
    raise SystemExit(f"dashboard is missing required controls: {missing}")

Path("ui_control.generated.js").write_text(script, encoding="utf-8")
print(f"wrote {len(script)} JavaScript characters for syntax validation")
