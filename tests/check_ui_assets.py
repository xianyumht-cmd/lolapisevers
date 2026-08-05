from pathlib import Path
import re
import subprocess
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lanzou_update_push_api_server.control_ui import (
    ASSET_DIRECTORY,
    render_diagnostics_page,
    render_logs_page,
    render_overview_page,
    render_system_page,
)
from lanzou_update_push_api_server.lolban_console import render_lolban_console_page
from lanzou_update_push_api_server.parser_center_ui_guard import render_parser_center_page


def extract_scripts(html: str) -> list[str]:
    return re.findall(
        r"<script(?:\s[^>]*)?>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


try:
    html = render_overview_page()
    console_script = (ASSET_DIRECTORY / "console.js").read_text(encoding="utf-8")
    operations_script_path = ASSET_DIRECTORY / "operations.js"
    operations_script = operations_script_path.read_text(encoding="utf-8")
    console_css = (ASSET_DIRECTORY / "console.css").read_text(encoding="utf-8")
    operations_css = (ASSET_DIRECTORY / "operations.css").read_text(encoding="utf-8")
    icon_sprite = (ASSET_DIRECTORY / "icons.svg").read_text(encoding="utf-8")
    logs_html = render_logs_page()
    diagnostics_html = render_diagnostics_page()
    system_html = render_system_page()
    lolban_html = render_lolban_console_page()
    parser_center_html = render_parser_center_page()
except Exception:
    details = traceback.format_exc()
    Path("ui-generation-error.txt").write_text(details, encoding="utf-8")
    print(details, file=sys.stderr)
    raise

required_overview_markers = [
    'data-console-ui="p0"',
    "/control-assets/console.css",
    "/control-assets/console.js",
    "控制台总览",
    "封号 Provider",
    "最近配置变更",
    'href="/logs"',
    'href="/diagnostics"',
    'href="/system"',
]
overview_missing = [marker for marker in required_overview_markers if marker not in html]
if overview_missing:
    raise SystemExit(f"new overview is missing required controls: {overview_missing}")
if 'href="/legacy-ui"' in html or "旧版入口" in html or "旧版控制台" in html:
    raise SystemExit("new overview still advertises the legacy console")

required_console_endpoints = [
    "/admin/overview",
    "/admin/query-console/lolban",
    "/admin/audit?limit=10",
    "/admin/logs",
    "/admin/service/status",
    "/build-info",
]
console_missing = [marker for marker in required_console_endpoints if marker not in console_script]
if console_missing:
    raise SystemExit(f"new console JavaScript is missing endpoints: {console_missing}")

operations_pages = {
    "logs": (logs_html, ["运行日志", 'data-console-ui="logs"', "logRows", "logContent"]),
    "diagnostics": (diagnostics_html, ["诊断与修复", 'data-console-ui="diagnostics"', "diagnosticRows", "repairStateButton"]),
    "system": (system_html, ["安全与回滚", 'data-console-ui="system"', "backupRows", "auditRows", "restartServiceButton"]),
}
for name, (page_html, markers) in operations_pages.items():
    missing = [marker for marker in markers if marker not in page_html]
    if missing:
        raise SystemExit(f"{name} page is missing required controls: {missing}")
    if "/control-assets/operations.js" not in page_html or "/control-assets/operations.css" not in page_html:
        raise SystemExit(f"{name} page is missing operations assets")
    if "/control-assets/console.js" in page_html:
        raise SystemExit(f"{name} page incorrectly loads overview-only JavaScript")

required_operations_endpoints = [
    "/admin/logs",
    "/admin/diagnostics",
    "/admin/repair/state",
    "/security/status",
    "/admin/service/status",
    "/admin/service/restart",
    "/admin/backups",
    "/admin/rollback/",
    "/admin/audit?limit=100",
]
operations_missing = [marker for marker in required_operations_endpoints if marker not in operations_script]
if operations_missing:
    raise SystemExit(f"operations JavaScript is missing endpoints: {operations_missing}")

for forbidden in ("alert(", "confirm(", "prompt("):
    if forbidden in console_script or forbidden in operations_script:
        raise SystemExit(f"new control UI contains forbidden browser interaction: {forbidden}")
for forbidden in ("radial-gradient", "linear-gradient", "backdrop-filter"):
    if forbidden in console_css or forbidden in operations_css:
        raise SystemExit(f"new control UI contains forbidden legacy visual pattern: {forbidden}")

for font_marker in ('"Microsoft YaHei UI"', '"Microsoft YaHei"', '"Cascadia Mono"'):
    if font_marker not in console_css:
        raise SystemExit(f"new control UI is missing font marker: {font_marker}")

for icon_marker in (
    "icon-dashboard",
    "icon-shield",
    "icon-workflow",
    "icon-key",
    "icon-server",
    "icon-activity",
    "icon-refresh",
    "icon-check",
    "icon-tool",
    "icon-archive",
):
    if icon_marker not in icon_sprite:
        raise SystemExit(f"new control UI is missing SVG symbol: {icon_marker}")

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
    "测试所选 Provider",
    "测试正式链路",
    "parser_providers",
    "legacy_providers",
    "Provider 直连",
    "5001 正式链路",
]
lolban_missing = [marker for marker in lolban_markers if marker not in lolban_html]
if lolban_missing:
    raise SystemExit(f"lolban console is missing required controls: {lolban_missing}")

parser_scripts = extract_scripts(parser_center_html)
parser_script = next(
    (
        candidate
        for candidate in parser_scripts
        if "/admin/parser-center" in candidate
        and "renderResponseTree" in candidate
        and "switchTab" in candidate
    ),
    "",
)
if not parser_script:
    raise SystemExit("parser-center JavaScript block was not found")

parser_markers = [
    "/admin/parser-center",
    "/admin/parser-center/secret",
    "/admin/parser-center/backups",
    "/admin/parser-center/rollback",
    "renderResponseTree",
    "switchTab",
    "Secret 与备份",
]
parser_missing = [marker for marker in parser_markers if marker not in parser_center_html]
if parser_missing:
    raise SystemExit(f"parser center is missing required controls: {parser_missing}")

Path("ui_control.generated.js").write_text(console_script, encoding="utf-8")
lolban_path = Path("ui_lolban_console.generated.js")
lolban_path.write_text(lolban_script, encoding="utf-8")
parser_path = Path("ui_parser_center.generated.js")
parser_path.write_text(parser_script, encoding="utf-8")
subprocess.run(["node", "--check", str(operations_script_path)], check=True)
subprocess.run(["node", "--check", str(lolban_path)], check=True)
subprocess.run(["node", "--check", str(parser_path)], check=True)
print(
    "wrote "
    f"{len(console_script)} new-console JavaScript characters, validated "
    f"{len(operations_script)} operations JavaScript characters, and wrote "
    f"{len(lolban_script)} lolban-console and "
    f"{len(parser_script)} parser-center JavaScript characters for syntax validation"
)
