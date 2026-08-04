from pathlib import Path
import re
import subprocess
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lanzou_update_push_api_server.lolban_console import render_lolban_console_page
from lanzou_update_push_api_server.server import _control_page


def extract_scripts(html: str) -> list[str]:
    return re.findall(
        r"<script(?:\s[^>]*)?>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


try:
    html = _control_page()
    lolban_html = render_lolban_console_page()
except Exception:
    details = traceback.format_exc()
    Path("ui-generation-error.txt").write_text(details, encoding="utf-8")
    print(details, file=sys.stderr)
    raise

scripts = extract_scripts(html)
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
    "/query-console/lolban",
    "data-query-console-lolban",
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

lolban_scripts = extract_scripts(lolban_html)
lolban_script = next(
    (
        candidate
        for candidate in lolban_scripts
        if "/admin/query-console/lolban/save" in candidate
        and "/admin/query-console/lolban/test" in candidate
        and "providerResult" in candidate
    ),
    "",
)
if not lolban_script:
    raise SystemExit("lolban console JavaScript block was not found")

lolban_markers = [
    "/admin/query-console/lolban",
    "/admin/query-console/lolban/save",
    "/admin/query-console/lolban/test",
    "parser_providers",
    "legacy_providers",
    "Provider 直连",
    "5001 正式链路",
]
lolban_missing = [marker for marker in lolban_markers if marker not in lolban_html]
if lolban_missing:
    raise SystemExit(f"lolban console is missing required controls: {lolban_missing}")

Path("ui_control.generated.js").write_text(script, encoding="utf-8")
lolban_path = Path("ui_lolban_console.generated.js")
lolban_path.write_text(lolban_script, encoding="utf-8")
subprocess.run(["node", "--check", str(lolban_path)], check=True)
print(
    "wrote "
    f"{len(script)} dashboard JavaScript characters and "
    f"{len(lolban_script)} lolban-console JavaScript characters for syntax validation"
)
