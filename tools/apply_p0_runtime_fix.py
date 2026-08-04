from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


LOCAL_ENV_SOURCE = '''from __future__ import annotations

import os
import re
from pathlib import Path
from typing import MutableMapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_ENV_PATH = PROJECT_ROOT / "ops" / "app_env.local.ps1"
_ENV_LINE_RE = re.compile(
    r"^\\s*\\$env:(?P<key>[A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*(?P<value>.*?)\\s*$"
)


def _parse_powershell_literal(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        body = value[1:-1]
        output: list[str] = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "`" and index + 1 < len(body):
                output.append(body[index + 1])
                index += 2
                continue
            output.append(char)
            index += 1
        return "".join(output)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"[^\\s;|&(){}]+", value):
        return value
    return None


def read_local_powershell_env(path: Path = DEFAULT_LOCAL_ENV_PATH) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        parsed = _parse_powershell_literal(match.group("value"))
        if parsed is None:
            continue
        values[match.group("key")] = parsed
    return values


def load_local_powershell_env(
    path: Path = DEFAULT_LOCAL_ENV_PATH,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    target = os.environ if environ is None else environ
    loaded: list[str] = []
    for key, value in read_local_powershell_env(path).items():
        if str(target.get(key) or "").strip():
            continue
        target[key] = value
        loaded.append(key)
    return tuple(loaded)
'''


LOCAL_ENV_TEST_SOURCE = '''from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.local_env import load_local_powershell_env, read_local_powershell_env


class LocalEnvironmentLoaderTests(unittest.TestCase):
    def test_reads_literal_assignments_without_executing_powershell(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_env.local.ps1"
            path.write_text(
                "\\ufeff$env:LOL_BAN_4PNG_TOKEN = \\\"abc``123`$x`\\\\\\\"\\\"\\n"
                "$env:SINGLE = 'it''s-safe'\\n"
                "$env:NUMBER = 5001\\n"
                "$env:UNSAFE = (Get-Content secret.txt)\\n",
                encoding="utf-8",
            )
            values = read_local_powershell_env(path)

        self.assertEqual(values["LOL_BAN_4PNG_TOKEN"], 'abc`123$x"')
        self.assertEqual(values["SINGLE"], "it's-safe")
        self.assertEqual(values["NUMBER"], "5001")
        self.assertNotIn("UNSAFE", values)

    def test_loads_only_missing_environment_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_env.local.ps1"
            path.write_text(
                '$env:LOL_BAN_4PNG_TOKEN = "disk-token"\\n'
                '$env:APP_PORT = "5001"\\n',
                encoding="utf-8",
            )
            environ = {"APP_PORT": "6000"}
            loaded = load_local_powershell_env(path, environ=environ)

        self.assertEqual(environ["LOL_BAN_4PNG_TOKEN"], "disk-token")
        self.assertEqual(environ["APP_PORT"], "6000")
        self.assertEqual(loaded, ("LOL_BAN_4PNG_TOKEN",))

    def test_app_bootstrap_loads_local_environment_before_routers(self) -> None:
        app_text = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        self.assertLess(
            app_text.index("load_local_powershell_env()"),
            app_text.index("from routers.lolban"),
        )


if __name__ == "__main__":
    unittest.main()
'''


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"expected anchor missing: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    (ROOT / "core" / "local_env.py").write_text(LOCAL_ENV_SOURCE, encoding="utf-8")
    (ROOT / "tests" / "test_local_env_loader.py").write_text(
        LOCAL_ENV_TEST_SOURCE,
        encoding="utf-8",
    )

    replace_once(
        ROOT / "app.py",
        "import logging\n\nfrom fastapi import FastAPI\nimport uvicorn\n\nfrom core.build_info import load_build_info\n",
        "import logging\n\nfrom core.local_env import load_local_powershell_env\n\n\n"
        "# NSSM normally starts the service through ops/run_service.ps1, which dot-sources\n"
        "# app_env.local.ps1. Load missing literal assignments again inside Python so a\n"
        "# trailing or unreachable PowerShell line cannot leave provider Secrets absent.\n"
        "load_local_powershell_env()\n\n\n"
        "from fastapi import FastAPI\nimport uvicorn\n\nfrom core.build_info import load_build_info\n",
    )

    script = ROOT / "lanzou_update_push_api_server" / "control_ui" / "assets" / "console.js"
    replace_once(
        script,
        "  function renderControlService(overview, serviceStatus) {\n"
        "    const health = overview?.lanzou?.health || {};\n"
        "    const serviceRunning = serviceStatus?.running === true || String(serviceStatus?.status || '').toLowerCase() === 'running';\n"
        "    const healthy = isHealthy(health) || serviceRunning;\n"
        "    setText('controlServiceState', healthy ? '运行正常' : '需要关注');\n"
        "    setText('controlServiceDetail', healthy ? '6178 控制台可用' : healthMessage(health));\n"
        "    setText('controlServiceMessage', serviceRunning ? 'Windows 服务正在运行' : healthMessage(health));\n"
        "    setBadge('controlServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');\n"
        "    return healthy;\n"
        "  }\n",
        "  function windowsServiceRunning(serviceStatus) {\n"
        "    const stateValue = String(serviceStatus?.state || serviceStatus?.status || '').toLowerCase();\n"
        "    return serviceStatus?.running === true || stateValue === 'running';\n"
        "  }\n\n"
        "  function renderControlService(serviceStatus, buildInfo, buildFailure = null) {\n"
        "    const serviceRunning = windowsServiceRunning(serviceStatus);\n"
        "    const consoleReachable = !buildFailure && Boolean(buildInfo && typeof buildInfo === 'object');\n"
        "    const healthy = consoleReachable;\n"
        "    setText('controlServiceState', healthy ? '运行正常' : '需要关注');\n"
        "    setText('controlServiceDetail', healthy ? '6178 页面与状态接口可用' : '6178 构建信息读取失败');\n"
        "    setText(\n"
        "      'controlServiceMessage',\n"
        "      serviceRunning ? 'Windows 托管服务正在运行' : (healthy ? '控制台响应正常，服务状态未确认' : '控制台状态读取失败')\n"
        "    );\n"
        "    setBadge('controlServiceBadge', healthy ? '正常' : '异常', healthy ? 'success' : 'danger');\n"
        "    return healthy;\n"
        "  }\n",
    )
    replace_once(
        script,
        "    const lanzouHealth = overview?.lanzou?.health || {};\n"
        "    if (!isHealthy(mainHealth)) items.push({ title: '5001 主接口健康异常', detail: healthMessage(mainHealth), kind: 'danger' });\n"
        "    if (!isHealthy(lanzouHealth)) items.push({ title: '6178 监控状态异常', detail: healthMessage(lanzouHealth), kind: 'danger' });\n",
        "    const lanzouHealth = overview?.lanzou?.health || {};\n"
        "    if (!isHealthy(mainHealth)) items.push({ title: '5001 主接口健康异常', detail: healthMessage(mainHealth), kind: 'danger' });\n"
        "    if (lanzouHealth?.running === false) {\n"
        "      items.push({ title: '蓝奏监控后台循环未运行', detail: '6178 页面可访问，但后台扫描循环没有运行', kind: 'danger' });\n"
        "    } else if (lanzouHealth?.degraded === true || String(lanzouHealth?.status || '').toLowerCase() === 'degraded') {\n"
        "      const reasons = Array.isArray(lanzouHealth?.degraded_reasons)\n"
        "        ? lanzouHealth.degraded_reasons.join('、')\n"
        "        : healthMessage(lanzouHealth);\n"
        "      items.push({ title: '蓝奏监控任务存在降级', detail: reasons || '部分监控项需要处理', kind: 'warning' });\n"
        "    }\n",
    )
    replace_once(
        script,
        "    const serviceText = String(serviceStatus?.status || '').toLowerCase();\n"
        "    if (serviceStatus?.running === false || (serviceText && serviceText !== 'running')) {\n"
        "      items.push({ title: 'Windows 服务状态需要关注', detail: text(serviceStatus?.message || serviceStatus?.status), kind: 'warning' });\n"
        "    }\n",
        "    const serviceState = String(serviceStatus?.state || serviceStatus?.status || '').toLowerCase();\n"
        "    if (serviceStatus?.supported !== false && serviceState && serviceState !== 'running') {\n"
        "      items.push({ title: 'Windows 服务状态需要关注', detail: text(serviceStatus?.message || serviceStatus?.state || serviceStatus?.status), kind: 'warning' });\n"
        "    }\n",
    )
    replace_once(
        script,
        "  function renderGlobalStatus(mainHealthy, controlHealthy, degradedCount) {\n"
        "    const good = mainHealthy && controlHealthy && degradedCount === 0;\n"
        "    const dot = $('globalStatusDot');\n"
        "    dot.className = `status-dot ${good ? 'status-dot-success' : 'status-dot-danger'}`;\n"
        "    $('globalStatusText').textContent = good ? '生产状态正常' : '存在需要关注的状态';\n"
        "  }\n",
        "  function renderGlobalStatus(mainHealthy, controlHealthy, degradedCount) {\n"
        "    const servicesHealthy = mainHealthy && controlHealthy;\n"
        "    const good = servicesHealthy && degradedCount === 0;\n"
        "    const dot = $('globalStatusDot');\n"
        "    dot.className = `status-dot ${good ? 'status-dot-success' : (servicesHealthy ? '' : 'status-dot-danger')}`.trim();\n"
        "    $('globalStatusText').textContent = good\n"
        "      ? '生产状态正常'\n"
        "      : (servicesHealthy ? '服务正常，存在业务告警' : '存在服务异常');\n"
        "  }\n",
    )
    replace_once(
        script,
        "      const mainHealthy = renderMainService(overview || {});\n"
        "      const controlHealthy = renderControlService(overview || {}, serviceStatus || {});\n"
        "      renderBuild(buildInfo || {});\n",
        "      const mainHealthy = renderMainService(overview || {});\n"
        "      const controlHealthy = renderControlService(serviceStatus || {}, buildInfo || {}, endpointFailure(results, 5));\n"
        "      renderBuild(buildInfo || {});\n",
    )

    p0_test = ROOT / "tests" / "test_control_ui_p0.py"
    replace_once(
        p0_test,
        "        self.assertNotIn('alert(', script)\n"
        "        self.assertNotIn('confirm(', script)\n",
        "        self.assertNotIn('alert(', script)\n"
        "        self.assertNotIn('confirm(', script)\n"
        "        self.assertIn(\"6178 页面与状态接口可用\", script)\n"
        "        self.assertIn(\"蓝奏监控任务存在降级\", script)\n"
        "        self.assertIn(\"serviceStatus?.state\", script)\n"
        "        self.assertNotIn(\"6178 监控状态异常\", script)\n",
    )


if __name__ == "__main__":
    main()
