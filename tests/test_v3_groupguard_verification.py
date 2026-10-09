from __future__ import annotations

import base64
import io
from pathlib import Path
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-production-safe-deployment-v3.yml"
PATCHER = ROOT / "ops" / "Patch-V3-GroupGuardVerification.ps1"
SMOKE = ROOT / "ops" / "Test-V3-GroupGuardProbe.ps1"
CHUNKS = ROOT / ".deployment-package" / "full-bug-repair-20260801"


class V3GroupGuardVerificationTests(unittest.TestCase):
    def test_original_verifier_calls_both_live_features(self) -> None:
        encoded = "".join(f.read_text(encoding="ascii").strip() for f in sorted(CHUNKS.glob("chunk-*.txt")))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as bundle:
            source = bundle.read("ops/Verify-FullBugRepairProduction.ps1").decode("utf-8-sig")
        self.assertIn('foreach ($feature in @("shard", "aram"))', source)
        self.assertIn('Invoke-JsonRequest -Uri "$BaseUrl/api/v1/groupguard/query"', source)
        for marker in (
            'Assert-True ($result.Body.protocol -eq "groupguard-query-delivery.v1")',
            'Assert-True ($result.Body.ok -eq $true)',
            'Assert-True (@($result.Body.delivery.segments).Count -ge 1)',
        ):
            self.assertIn(marker, source)

    def test_artifact_patch_replaces_exactly_the_functional_request(self) -> None:
        text = PATCHER.read_text(encoding="utf-8")
        for marker in (
            'function Invoke-VerifiedGroupGuardRequest {',
            '-DisableKeepAlive',
            '[int]$MaxAttempts = 4',
            '[int]$TimeoutSeconds = 20',
            '"ConnectFailure", "ReceiveFailure", "KeepAliveFailure"',
            '"ConnectionClosed", "Timeout", "SendFailure"',
            '$statusCode -in @(429, 502, 503, 504)',
            'if (-not $transient -or $attempt -ge $MaxAttempts)',
            'listener_pid=',
            'GroupGuard production verification failed',
            'ConvertFrom-Json -InputObject $response.Content',
            '$json.ok -ne $true',
            '@($json.delivery.segments).Count -lt 1',
            'Assert-True ($result.Body.protocol -eq "groupguard-query-delivery.v1")',
            'Assert-True ($result.Body.ok -eq $true)',
            'Assert-True (@($result.Body.delivery.segments).Count -ge 1)',
            'groupguard_bounded_probe',
            'groupguard_fresh_connection',
            'groupguard_probe_diagnostics',
            'package_content_sha256',
            'zip_sha256',
        ):
            self.assertIn(marker, text)
        self.assertNotIn("skip post-switch verification", text.lower())
        self.assertNotIn("disable automatic rollback", text.lower())

    def test_patches_before_release_validation_and_attests_flags(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        stage = text.index("Patch V3 GroupGuard production verification")
        smoke = text.index("Exercise V3 GroupGuard verifier with Windows PowerShell 5.1")
        verify = text.index("Verify V3 package hashes and safety flags")
        self.assertLess(stage, smoke)
        self.assertLess(smoke, verify)
        self.assertIn("Patch-V3-GroupGuardVerification.ps1", text)
        self.assertIn("Test-V3-GroupGuardProbe.ps1", text)
        self.assertEqual(2, text.count('"groupguard_bounded_probe"'))
        self.assertEqual(2, text.count('"groupguard_fresh_connection"'))
        self.assertEqual(2, text.count('"groupguard_probe_diagnostics"'))
        self.assertIn("V3 verifier still uses the unsafe generic GroupGuard request", text)
        self.assertIn("Verify-FullBugRepairProduction.ps1", text)

    def test_smoke_suite_verifies_retry_and_fail_closed(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        for marker in (
            "FunctionDefinitionAst",
            "ConnectionClosed",
            "Invalid protocol or delivery",
            "Permanent error must not retry",
            "Disabled keep-alive",
            "Transient failure must retry",
            "GroupGuard verification smoke tests passed",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
