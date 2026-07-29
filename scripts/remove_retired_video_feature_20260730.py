from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def replace_exact(path: str, old: str, new: str) -> None:
    content = read(path)
    if old not in content:
        raise RuntimeError(f"expected block missing in {path}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def append_once(path: str, marker: str, section: str) -> None:
    content = read(path)
    if marker in content:
        return
    write(path, content.rstrip() + "\n\n" + section.strip() + "\n")


def remove_matching_lines(path: str, needles: tuple[str, ...]) -> None:
    content = read(path)
    lines = content.splitlines()
    filtered = [line for line in lines if not any(needle in line for needle in needles)]
    write(path, "\n".join(filtered).rstrip() + "\n")


# 1. Remove the formal video feature from the delivery router.
router = "routers/groupguard_delivery.py"
replace_exact(router, "from services.video_query_service import format_video_text, query_video, video_meta\n", "")
replace_exact(
    router,
    '    "video": "video",\n    "video_query": "video",\n    "我要看": "video",\n',
    "",
)
replace_exact(
    router,
    '    if feature == "video":\n        return video_meta(payload)\n',
    "",
)
replace_exact(
    router,
    '    if feature in {"shard", "aram", "battle", "hidden", "video", "scammer", "peer", "dynamic"} and ctx is None:\n',
    '    if feature in {"shard", "aram", "battle", "hidden", "scammer", "peer", "dynamic"} and ctx is None:\n',
)
replace_exact(
    router,
    '        elif feature == "video":\n            category = str(parameters.get("category") or "热门").strip() or "热门"\n            payload = await query_video(ctx, category)\n            text = format_video_text(payload)\n',
    "",
)

# 2. Remove the service implementation and its old positive tests.
for relative in ("services/video_query_service.py", "tests/test_video_query_service.py"):
    target = ROOT / relative
    if not target.is_file():
        raise RuntimeError(f"expected file missing: {relative}")
    target.unlink()

# 3. Remove the unused default dynamic video provider as part of the same product decision.
catalog_path = ROOT / "config/dynamic-query-providers.default.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
commands = catalog.get("commands")
if not isinstance(commands, list):
    raise RuntimeError("default dynamic provider catalog is invalid")
video_ids = [item.get("id") for item in commands if isinstance(item, dict) and item.get("id") == "video.info"]
if video_ids != ["video.info"]:
    raise RuntimeError(f"expected exactly one video.info provider, got {video_ids!r}")
catalog["commands"] = [
    item for item in commands if not (isinstance(item, dict) and item.get("id") == "video.info")
]
catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 4. Convert tests from positive video coverage into retirement gates.
dynamic_test = "tests/test_groupguard_dynamic_delivery.py"
replace_exact(
    dynamic_test,
    '            self.assertEqual(catalog.get("video.info").text_path, "list[0].url")\n',
    '            with self.assertRaises(HTTPException) as removed:\n'
    '                catalog.get("video.info")\n'
    '            self.assertEqual(removed.exception.status_code, 404)\n',
)
write(
    "tests/test_groupguard_video_removed.py",
    '''import json\nimport unittest\nfrom types import SimpleNamespace\n\nfrom routers.groupguard_delivery import groupguard_query\n\n\ndef decode(response):\n    return json.loads(bytes(response.body).decode("utf-8"))\n\n\nclass GroupGuardVideoRemovedTests(unittest.IsolatedAsyncioTestCase):\n    async def test_retired_video_aliases_are_not_supported(self):\n        request = SimpleNamespace(\n            app=SimpleNamespace(state=SimpleNamespace(ctx=object())),\n            headers={},\n        )\n        for feature in ("video", "video_query", "我要看"):\n            with self.subTest(feature=feature):\n                response = await groupguard_query(\n                    request,\n                    {\n                        "feature": feature,\n                        "parameters": {"category": "热门"},\n                        "preferred": "text",\n                    },\n                )\n                body = decode(response)\n                self.assertEqual(response.status_code, 400)\n                self.assertFalse(body["ok"])\n                self.assertEqual(body["feature"], "unknown")\n                self.assertEqual(body["error"]["code"], "invalid_query")\n                self.assertIn("不支持", body["error"]["user_message"])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
)

# 5. Update the machine plan to make the product decision explicit.
plan_path = ROOT / "docs/plans/ALL_QUERY_DELIVERY_HUB_20260729.json"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
plan["status"] = "video_retirement_code_verified_pending_windows_patch_deploy"
plan.setdefault("product_decisions", {})["video_query"] = {
    "decision": "retired",
    "decided_at_local": "2026-07-30T03:38:00+08:00",
    "reason": "User cancelled the entire 我要看 category video feature after all migrated providers failed diagnosis.",
    "legacy_dist_commit": "029118346adaa9232aeceeb283f5d243a407dc95",
    "legacy_dist_status": "revoked_do_not_deploy",
}
scope = plan.get("scope", {})
if isinstance(scope.get("business_queries"), list):
    scope["business_queries"] = [item for item in scope["business_queries"] if item != "video"]
plan["inventory"] = [
    item for item in plan.get("inventory", [])
    if not (isinstance(item, dict) and item.get("feature") == "video")
]
for step in plan.get("steps", []):
    if isinstance(step, dict) and step.get("id") == "AQ-VIDEO-001":
        step["status"] = "cancelled_by_product_decision"
        step["replacement"] = "AQ-VIDEO-RETIRE-001"
plan.setdefault("steps", []).append({
    "id": "AQ-VIDEO-RETIRE-001",
    "status": "code_verified_pending_windows_patch_deploy",
    "features_removed": ["video", "video.info"],
})
release = plan.setdefault("release_candidate", {})
release["previous_service_head_with_video"] = release.get("service_head")
release["previous_groupguard_head_with_video"] = release.get("groupguard_head")
release["service_head"] = "pending_video_retirement_release_commit"
release["groupguard_head"] = "pending_video_free_client_commit"
release["previous_groupguard_artifact_status"] = "revoked_do_not_deploy"
plan["next_action"] = {
    "repository": "xianyumht-cmd/lolapisevers",
    "step_id": "AQ-VIDEO-RETIRE-DEPLOY-001",
    "summary": "Package and deploy the video-free API patch, remove only QUERY_VIDEO_PROVIDERS_JSON with rollback protection, then run direct protocol acceptance before rebuilding GroupGuard.",
}
plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 6. Keep human documentation consistent. Historical handoff evidence is preserved;
# current plans and architecture no longer advertise video as supported scope.
for path in (
    "docs/plans/ALL_QUERY_DELIVERY_HUB_20260729.md",
    "docs/architecture/CHANNEL_NEUTRAL_ALL_QUERY_BOUNDARY.md",
    "docs/architecture/OFFICIAL_BOT_QUERY_CLIENT.md",
):
    remove_matching_lines(path, ("`video`", "我要看", "video.info"))

append_once(
    "docs/checkpoints/ALL_QUERY_RELEASE_VERIFICATION_20260730.md",
    "## 视频功能取消后的重新验证",
    '''## 视频功能取消后的重新验证\n\n- 用户已取消整个“我要看”分类视频功能；\n- `feature=video`、`video_query` 和“我要看”均不再是支持的查询别名；\n- 接口视频 Provider 服务文件与原正向测试已删除；\n- 默认动态 Provider `video.info` 已删除；\n- 新门禁明确验证上述别名返回“不支持的查询功能”；\n- 原封存 GroupGuard dist `029118346adaa9232aeceeb283f5d243a407dc95` 已作废，禁止部署。\n\n本检查点现在进入：API 无视频小版本打包与 Windows 安全部署，部署成功后再重新构建 GroupGuard。''',
)
append_once(
    "docs/checkpoints/ALL_QUERY_NEXT_CHAT_HANDOFF_20260730.md",
    "## 2026-07-30 API 视频移除代码阶段完成",
    '''## 2026-07-30 API 视频移除代码阶段完成\n\n已完成并由一次性工作流全量验证后提交：\n\n- 删除正式 `video/我要看` 路由别名；\n- 删除 `services/video_query_service.py`；\n- 删除默认动态 Provider `video.info`；\n- 将原视频正向测试替换为“视频功能必须不受支持”的退役门禁；\n- 新增 Windows 配置清理脚本，仅移除 `QUERY_VIDEO_PROVIDERS_JSON`，保留风险与自定义动态 Provider；\n- 旧含视频 dist 继续保持作废和禁止部署。\n\n下一步：生成固定提交的 API 无视频离线安全部署包，部署 Windows，运行 shard/scammer/custom dynamic/health 验收，再进入 GroupGuard 无视频最终 dist 构建。''',
)

write(
    "docs/NEXT_CHAT_PROMPT_20260730.txt",
    "继续 xianyumht-cmd/lolapisevers 与 xianyumht-cmd/groupguard-system 的全查询迁移任务。先读取两仓 ALL_QUERY_NEXT_CHAT_HANDOFF_20260730.md、机器计划和 Draft PR #19/#17。当前 API 代码已移除 video/我要看与默认 video.info，并通过一次性工作流全量测试；旧 GroupGuard dist 029118346adaa9232aeceeb283f5d243a407dc95 已作废。下一步严格执行：确认 API 最终提交与 Actions，生成固定提交的无视频离线安全部署包，Windows 部署并仅清理 QUERY_VIDEO_PROVIDERS_JSON，验收 health/shard/scammer/custom dynamic；随后完成 GroupGuard 删除我要看、重跑 CI、重新封存无视频 dist，最后替换 ARM 一次并做群内完整查询矩阵。不要合并 Draft PR，不要恢复公网 fallback，不要删除回滚备份。\n",
)

# 7. Add a rollback-safe Windows configuration cleanup script for the deployment phase.
write(
    "ops/remove-retired-video-provider-config.ps1",
    r'''param(
    [string]$ProjectRoot = "D:\project2\lolapisevers",
    [string]$ServiceName = "LOLDataSystem"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$envFile = Join-Path $ProjectRoot "ops\app_env.local.ps1"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing local environment file: $envFile"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $ProjectRoot ".video-provider-retirement-backups\$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupFile = Join-Path $backupDir "app_env.local.ps1"
Copy-Item -LiteralPath $envFile -Destination $backupFile -Force

$original = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
$riskBefore = [regex]::Match($original, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value
$dynamicBefore = [regex]::Match($original, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value
$updated = [regex]::Replace(
    $original,
    '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=.*(?:\r?\n)?',
    ''
)

if ($updated -eq $original) {
    Write-Host "QUERY_VIDEO_PROVIDERS_JSON is already absent. No file change required."
} else {
    [System.IO.File]::WriteAllText($envFile, $updated, (New-Object System.Text.UTF8Encoding($false)))
}

$after = Get-Content -LiteralPath $envFile -Raw -Encoding UTF8
if ($after -match '(?m)^\s*\$env:QUERY_VIDEO_PROVIDERS_JSON\s*=') {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Video provider setting still exists; configuration was rolled back."
}
if ($riskBefore -ne [regex]::Match($after, '(?m)^\s*\$env:QUERY_SCAMMER_PROVIDERS_JSON\s*=.*$').Value) {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Risk provider setting changed unexpectedly; configuration was rolled back."
}
if ($dynamicBefore -ne [regex]::Match($after, '(?m)^\s*\$env:DYNAMIC_QUERY_PROVIDERS_PATH\s*=.*$').Value) {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    throw "Dynamic provider path changed unexpectedly; configuration was rolled back."
}

try {
    Restart-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 3
    $live = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:5001/livez" -TimeoutSec 10
    $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:5001/health" -TimeoutSec 10
    if ($null -eq $live -or $null -eq $health) {
        throw "Health endpoints returned empty responses."
    }
} catch {
    Copy-Item -LiteralPath $backupFile -Destination $envFile -Force
    Restart-Service -Name $ServiceName -Force
    throw "Post-change validation failed and configuration was rolled back: $($_.Exception.Message)"
}

Write-Host "Retired video provider setting removed successfully."
Write-Host "Backup: $backupFile"
''',
)

print("retired video feature removal prepared successfully")
