from __future__ import annotations

import base64
import hashlib
import io
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "ops" / "Build-FullBugRepairPackageV3.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "build-production-safe-deployment-v3.yml"
CHUNK_ROOT = ROOT / ".deployment-package" / "full-bug-repair-20260801"
TOOLS_ZIP_SHA256 = "30266c26bc21b4600d7e2cf63a27978f486958fa7c1e65a11e19484587a54237"
READYZ_ANCHOR = (
    '$ready = Invoke-JsonRequest -Uri "$BaseUrl/readyz"\n'
    'Assert-True ($ready.StatusCode -eq 200) "readyz failed."\n'
    'Add-Check "readyz" "pass" "HTTP 200"'
)


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
            '$readyBlockAnchor.Replace("`r`n", "`n").TrimEnd()',
            '$readyBlockReplacement.Replace("`r`n", "`n").TrimEnd()',
            "$verifyText.IndexOf($readyBlockAnchorText, [System.StringComparison]::Ordinal)",
            "$verifyText.LastIndexOf($readyBlockAnchorText, [System.StringComparison]::Ordinal)",
            "$verifyText.Substring(0, $readyBlockFirstIndex)",
        ):
            self.assertIn(marker, text)
        self.assertIn(
            '$deployText.Replace($preflightStatusAnchor, $preSwitchBlock + $preflightStatusAnchor)',
            text,
        )
        self.assertNotIn(
            "[regex]::Matches($verifyText, [regex]::Escape($readyBlockAnchorText))",
            text,
        )

    def test_reconstructed_verifier_contains_one_literal_readyz_anchor(self) -> None:
        chunks = sorted(CHUNK_ROOT.glob("chunk-*.txt"))
        self.assertEqual(4, len(chunks))
        encoded = "".join(path.read_text(encoding="ascii").strip() for path in chunks)
        archive = base64.b64decode(encoded, validate=True)
        self.assertEqual(TOOLS_ZIP_SHA256, hashlib.sha256(archive).hexdigest())
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            raw = bundle.read("ops/Verify-FullBugRepairProduction.ps1")
        verifier = raw.decode("utf-8-sig").replace("\r\n", "\n")
        self.assertEqual(1, verifier.count(READYZ_ANCHOR))
        self.assertEqual(1, verifier.count('$BaseUrl/readyz'))

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
