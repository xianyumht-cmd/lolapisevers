from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "ops" / "Build-FullBugRepairPackageV3.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "build-production-safe-deployment-v3.yml"


class V3BaselineReadinessTests(unittest.TestCase):
    def test_builder_captures_pre_switch_health_before_production_stop(self) -> None:
        text = BUILDER.read_text(encoding="utf-8")
        for marker in (
            "Capture pre-switch production health baseline",
            "pre-switch-health.json",
            "Get-JsonEndpointSnapshot",
            "Pre-switch MySQL readiness is not up",
            "Pre-switch SO1 browser readiness is not up",
            "Production was not stopped or changed",
            "BaselineHealthPath",
            '$verifyCallAnchor.Replace("`r`n", "`n").TrimEnd()',
            '$verifyCallReplacement.Replace("`r`n", "`n").TrimEnd()',
        ):
            self.assertIn(marker, text)
        self.assertIn(
            '$deployText.Replace($preflightStatusAnchor, $preSwitchBlock + $preflightStatusAnchor)',
            text,
        )

    def test_verifier_allows_only_unchanged_inherited_so1_session_degradation(self) -> None:
        text = BUILDER.read_text(encoding="utf-8")
        for marker in (
            "Post-switch MySQL readiness regressed",
            "Post-switch SO1 browser readiness regressed",
            "does not match the pre-switch degradation baseline",
            "$baselineFingerprint -eq $postFingerprint",
            'status = $verificationStatus',
            'pass_with_warning',
            'inherited_so1_session_degradation',
            'readyz must remain HTTP 503',
        ):
            self.assertIn(marker, text)
        self.assertNotIn("ignore all readyz failures", text.lower())
        self.assertNotIn("skip post-switch verification", text.lower())

    def test_v3_workflow_requires_baseline_aware_artifact_markers(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "baseline_aware_readiness",
            "inherited_so1_session_degradation",
            "pass_with_warning",
            "Post-switch MySQL readiness regressed",
            "Post-switch SO1 browser readiness regressed",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
