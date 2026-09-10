from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-production-safe-deployment-v3.yml"


class V3RuntimeVenvAclWorkflowTests(unittest.TestCase):
    def test_canonical_v3_workflow_applies_runtime_acl_patchers_in_order(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        native = ".\\ops\\Patch-V3-WinPS51ReleaseArtifact.ps1 -DistRoot \"$pwd\\dist-v3\""
        bootstrap = ".\\ops\\Patch-V3-RuntimeBootstrapAcl.ps1 -DistRoot \"$pwd\\dist-v3\""
        lifecycle = ".\\ops\\Patch-V3-ProductionVenvAcl.ps1 -DistRoot \"$pwd\\dist-v3\""

        for marker in (native, bootstrap, lifecycle):
            self.assertIn(marker, text)

        self.assertLess(text.index(native), text.index(bootstrap))
        self.assertLess(text.index(bootstrap), text.index(lifecycle))

    def test_canonical_v3_workflow_verifies_runtime_acl_contract(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "runtime_bootstrap_acl_safe",
            "runtime_listener_bootstrap_discovery",
            "production_venv_acl_recovery",
            "installed_venv_acl_normalized",
            "venv_acl_well_known_sids",
            "Get-NetTCPConnection -State Listen -LocalPort $listenerPort",
            "Ensure-ManagedVenvAcl -Path $oldVenv",
            "Ensure-ManagedVenvAcl -Path $installedVenv",
            "if (Test-Path -LiteralPath $productionPython -PathType Leaf)",
            "if (Test-Path -LiteralPath $oldVenv -PathType Container)",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
