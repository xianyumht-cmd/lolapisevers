from pathlib import Path
import re
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

scripts = re.findall(
    r"<script(?:\s[^>]*)?>(.*?)</script>",
    html,
    flags=re.IGNORECASE | re.DOTALL,
)
script = next(
    (
        candidate
        for candidate in scripts
        if "/admin/main-config" in candidate
        and "/admin/lanzou-config" in candidate
        and "adminToken" in candidate
    ),
    "",
)
if not script:
    raise SystemExit("dashboard main JavaScript block was not found")

required_markers = [
    "/admin/main-config",
    "/admin/lanzou-config",
    "/admin/openapi/main",
    "/admin/logs",
    "/admin/diagnostics",
    "/admin/backups",
    "/admin/audit",
    "/admin/service/restart",
    "/security/status",
    "adminToken",
    "watcherRows",
    "targetRows",
    "backupRows",
    "auditRows",
    "addWatcherButton",
    "addTargetButton",
    "S.watchers.unshift",
    "S.targets.unshift",
    "scrollIntoView",
    "addEventListener('click',addWatcher)",
    "addEventListener('click',addTarget)",
    "请填写后点击“保存监控项”",
]
missing = [marker for marker in required_markers if marker not in html]
if missing:
    raise SystemExit(f"dashboard is missing required controls: {missing}")

Path("ui_control.generated.js").write_text(script, encoding="utf-8")
print(
    f"wrote {len(script)} JavaScript characters from {len(scripts)} script blocks for syntax validation"
)
