from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "ops" / "Deploy-LapiQueryHardening.ps1"
TESTS = ROOT / "tests" / "test_lapi_deploy_scripts.py"
HANDOFF = ROOT / "docs" / "checkpoints" / "ALL_QUERY_NEXT_CHAT_HANDOFF_20260730.md"

old_block = '''function Invoke-ReleaseTests {
    param([string]$PythonExe)
    if ($SkipFullTests) {
        Write-Warning "Full unit tests were skipped by operator request."
        return
    }
    & $PythonExe -m unittest discover -s (Join-Path $ProjectRoot "tests") -p "test_*.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Full Python unit tests failed."
    }
}
'''
new_block = '''function Invoke-ReleaseTests {
    param([string]$PythonExe)
    if ($SkipFullTests) {
        Write-Warning "Full unit tests were skipped by operator request."
        return
    }

    Push-Location -LiteralPath $ProjectRoot
    try {
        & $PythonExe -m unittest discover -s "tests" -p "test_*.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Full Python unit tests failed."
        }
    } finally {
        Pop-Location
    }
}
'''

text = DEPLOY.read_text(encoding="utf-8")
if old_block not in text:
    raise SystemExit("expected old Invoke-ReleaseTests block was not found")
DEPLOY.write_text(text.replace(old_block, new_block, 1), encoding="utf-8", newline="\n")

test_text = TESTS.read_text(encoding="utf-8")
marker = "    def test_deploy_requires_backup_acl_tests_build_info_and_rollback(self):\n"
new_test = '''    def test_deploy_runs_unit_tests_from_project_root(self):
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertIn("Push-Location -LiteralPath $ProjectRoot", text)
        self.assertIn('& $PythonExe -m unittest discover -s "tests" -p "test_*.py"', text)
        self.assertIn("} finally {", text)
        self.assertIn("Pop-Location", text)
        self.assertNotIn('discover -s (Join-Path $ProjectRoot "tests")', text)

'''
if new_test.strip() in test_text:
    raise SystemExit("working-directory regression test already exists")
if marker not in test_text:
    raise SystemExit("test insertion marker was not found")
TESTS.write_text(test_text.replace(marker, new_test + marker, 1), encoding="utf-8", newline="\n")

section = '''
## 2026-07-30 Windows 首次无视频部署失败与安全回滚

首次运行无视频离线包时，业务代码尚未启动，部署前完整测试在临时解压目录执行。旧部署脚本把 `tests` 设为绝对路径，却没有把项目根目录设为 Python 当前目录，导致 `cache`、`routers`、`services` 等仓库模块无法导入。部署门禁正确阻止上线，并自动回滚到 `ba54d83d7dd8cdbbb213b7bf38264655d671f134`，`LOLDataSystem` 服务恢复运行。

修复要求：

- `Invoke-ReleaseTests` 必须先 `Push-Location -LiteralPath $ProjectRoot`；
- unittest 使用相对 `tests` 目录；
- `finally` 中始终 `Pop-Location`；
- 新回归测试禁止恢复旧的绝对 tests 路径写法；
- 旧部署 ZIP `864cb567...` 作废，禁止再次运行。
'''
if HANDOFF.exists():
    handoff_text = HANDOFF.read_text(encoding="utf-8")
    if "## 2026-07-30 Windows 首次无视频部署失败与安全回滚" not in handoff_text:
        HANDOFF.write_text(handoff_text.rstrip() + "\n" + section, encoding="utf-8", newline="\n")

print("deploy test working-directory fix prepared")
