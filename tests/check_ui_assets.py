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
    render_debugger_page,
    render_diagnostics_page,
    render_lanzou_config_page,
    render_logs_page,
    render_main_config_page,
    render_overview_page,
    render_system_page,
    render_target_file_watch_page,
    render_targets_page,
    render_watchers_page,
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
    configuration_script_path = ASSET_DIRECTORY / "configuration.js"
    configuration_script = configuration_script_path.read_text(encoding="utf-8")
    target_watch_script_path = ASSET_DIRECTORY / "target-file-watch.js"
    target_watch_script = target_watch_script_path.read_text(encoding="utf-8")
    lolban_script_path = ASSET_DIRECTORY / "lolban.js"
    lolban_script = lolban_script_path.read_text(encoding="utf-8")
    console_css = (ASSET_DIRECTORY / "console.css").read_text(encoding="utf-8")
    operations_css = (ASSET_DIRECTORY / "operations.css").read_text(encoding="utf-8")
    configuration_css = (ASSET_DIRECTORY / "configuration.css").read_text(encoding="utf-8")
    lolban_css = (ASSET_DIRECTORY / "lolban.css").read_text(encoding="utf-8")
    icon_sprite = (ASSET_DIRECTORY / "icons.svg").read_text(encoding="utf-8")
    logs_html = render_logs_page()
    diagnostics_html = render_diagnostics_page()
    system_html = render_system_page()
    main_config_html = render_main_config_page()
    lanzou_config_html = render_lanzou_config_page()
    watchers_html = render_watchers_page()
    targets_html = render_targets_page()
    target_watch_html = render_target_file_watch_page()
    debugger_html = render_debugger_page()
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
    'href="/target-file-watch"',
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

configuration_pages = {
    "main-config": (main_config_html, ["主接口配置", 'data-console-ui="main-config"', "mainConfigForm"]),
    "lanzou-config": (lanzou_config_html, ["蓝奏全局配置", 'data-console-ui="lanzou-config"', "lzWerEndpoint"]),
    "watchers": (watchers_html, ["监控项目", 'data-console-ui="watchers"', "watcherRows"]),
    "targets": (targets_html, ["通知目标", 'data-console-ui="targets"', "targetRows"]),
    "api-debugger": (debugger_html, ["接口调试器", 'data-console-ui="api-debugger"', "debuggerRouteSelect"]),
}
for name, (page_html, markers) in configuration_pages.items():
    missing = [marker for marker in markers if marker not in page_html]
    if missing:
        raise SystemExit(f"{name} page is missing required controls: {missing}")
    if "/control-assets/configuration.js" not in page_html or "/control-assets/configuration.css" not in page_html:
        raise SystemExit(f"{name} page is missing configuration assets")
    if "/control-assets/console.js" in page_html:
        raise SystemExit(f"{name} page incorrectly loads overview-only JavaScript")

required_target_watch_markers = [
    "定向文件监控",
    'data-console-ui="target-file-watch"',
    "/control-assets/target-file-watch.js",
    "配置源：GroupGuard 6108",
    "targetWatchBaselineRows",
    "targetWatchPendingList",
    "targetWatchRebaselineDialog",
]
target_watch_missing = [marker for marker in required_target_watch_markers if marker not in target_watch_html]
if target_watch_missing:
    raise SystemExit(f"target file watch page is missing required controls: {target_watch_missing}")
if "/control-assets/console.js" in target_watch_html or "/control-assets/configuration.js" in target_watch_html:
    raise SystemExit("target file watch page loads unrelated overview/configuration JavaScript")

required_target_watch_endpoints = [
    "/admin/target-file-watch",
    "/admin/target-file-watch/check",
    "/admin/target-file-watch/rebaseline",
]
target_watch_endpoint_missing = [marker for marker in required_target_watch_endpoints if marker not in target_watch_script]
if target_watch_endpoint_missing:
    raise SystemExit(f"target file watch JavaScript is missing endpoints: {target_watch_endpoint_missing}")

required_configuration_endpoints = [
    "/admin/main-config",
    "/admin/lanzou-config",
    "/admin/overview",
    "/scan?watcher_id=",
    "/notify/test",
    "/files/",
    "/admin/openapi/main",
    "/admin/openapi/lanzou",
    "/admin/invoke",
]
configuration_missing = [marker for marker in required_configuration_endpoints if marker not in configuration_script]
if configuration_missing:
    raise SystemExit(f"configuration JavaScript is missing endpoints: {configuration_missing}")

for marker in ("content_risk_status", "引流风险", "说明未知"):
    if marker not in configuration_script:
        raise SystemExit(f"configuration JavaScript is missing Lanzou risk marker: {marker}")

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
    if (
        forbidden in console_script
        or forbidden in operations_script
        or forbidden in configuration_script
        or forbidden in target_watch_script
    ):
        raise SystemExit(f"new control UI contains forbidden browser interaction: {forbidden}")
for forbidden in ("radial-gradient", "linear-gradient", "backdrop-filter"):
    if forbidden in console_css or forbidden in operations_css or forbidden in configuration_css:
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
    "icon-plus",
    "icon-save",
    "icon-send",
):
    if icon_marker not in icon_sprite:
        raise SystemExit(f"new control UI is missing SVG symbol: {icon_marker}")

lolban_html_markers = [
    "/control-assets/lolban.css",
    "/control-assets/lolban.js",
    "测试所选 Provider",
    "测试正式链路",
    "Provider 直连",
    "5001 正式链路",
    'id="providerResult"',
    'id="formalResult"',
]
lolban_html_missing = [marker for marker in lolban_html_markers if marker not in lolban_html]
if lolban_html_missing:
    raise SystemExit(f"lolban console HTML is missing required controls: {lolban_html_missing}")
if "<style>" in lolban_html or "const S=" in lolban_html:
    raise SystemExit("lolban console still contains embedded style or application JavaScript")

lolban_script_markers = [
    "/admin/query-console/lolban",
    "/admin/query-console/lolban/save",
    "/admin/query-console/lolban/test",
    "/admin/query-console/lolban/provider-secret",
    "parser_providers",
    "legacy_providers",
    "providerResult",
    "providerSecrets",
    "providerSecretControl",
    "data-secret-provider",
]
lolban_script_missing = [marker for marker in lolban_script_markers if marker not in lolban_script]
if lolban_script_missing:
    raise SystemExit(f"lolban console JavaScript is missing required behavior: {lolban_script_missing}")
if ".provider-secret" not in lolban_css or ".admin-token-input" not in lolban_css:
    raise SystemExit("lolban console stylesheet is missing required layout rules")

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
parser_path = Path("ui_parser_center.generated.js")
parser_path.write_text(parser_script, encoding="utf-8")
subprocess.run(["node", "--check", str(operations_script_path)], check=True)
subprocess.run(["node", "--check", str(configuration_script_path)], check=True)
subprocess.run(["node", "--check", str(target_watch_script_path)], check=True)
subprocess.run(["node", "--check", str(lolban_script_path)], check=True)
subprocess.run(["node", "--check", str(parser_path)], check=True)
print(
    "wrote "
    f"{len(console_script)} new-console JavaScript characters, validated "
    f"{len(operations_script)} operations, {len(configuration_script)} configuration, "
    f"{len(target_watch_script)} target-file-watch, and {len(lolban_script)} lolban-console "
    f"JavaScript characters, and wrote {len(parser_script)} parser-center JavaScript characters "
    "for syntax validation"
)
