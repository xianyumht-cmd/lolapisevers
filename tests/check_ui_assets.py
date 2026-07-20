from pathlib import Path
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lanzou_update_push_api_server.server import _control_page


try:
    html = _control_page()
except Exception:
    details = traceback.format_exc()
    Path("ui-generation-error.txt").write_text(details, encoding="utf-8")
    print(details, file=sys.stderr)
    raise

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
