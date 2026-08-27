from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "ops" / "Patch-V3-WinPS51ReleaseArtifact.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "build-production-safe-deployment-v3.yml"


class V3ReleaseArtifactWinPS51Tests(unittest.TestCase):
    def test_artifact_patcher_replaces_unsafe_native_commands(self) -> None:
        text = PATCHER.read_text(encoding="utf-8")
        for marker in (
            'Invoke-Git -WorkingDirectory $ProjectRoot -Arguments @("bundle", "verify", $bundlePath) | Out-Null',
            'Invoke-Git -WorkingDirectory $ProjectRoot -Arguments @("clone", "--no-checkout", $bundlePath, $candidateRepository) | Out-Null',
            "function Invoke-NativeProcess {",
            'Invoke-NativeProcess -FilePath $candidatePython -Arguments @(',
            '"-m", "unittest", "discover"',
            "Unsafe native bundle verify command remains after patch.",
            "Unsafe native clone command remains after patch.",
            "Unsafe direct native invocation remains after patch",
            "winps51_native_git_stderr_safe",
            "winps51_native_process_stderr_safe",
            "package_content_sha256",
        ):
            self.assertIn(marker, text)

    def test_workflow_patches_before_verifying_and_publishing(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        patch_step = text.index("Patch V3 WinPS5.1 native process stderr handling")
        verify_step = text.index("Verify V3 package hashes and safety flags")
        self.assertLess(patch_step, verify_step)
        self.assertIn("Patch-V3-WinPS51ReleaseArtifact.ps1", text)
        self.assertIn("winps51_native_git_stderr_safe", text)
        self.assertIn("winps51_native_process_stderr_safe", text)
        self.assertIn("V3 deployment still contains unsafe native bundle verify", text)
        self.assertIn("V3 deployment still contains unsafe native clone", text)
        self.assertIn("V3 deployment still contains unsafe direct native invocation", text)
        self.assertIn("function Invoke-NativeProcess {", text)


if __name__ == "__main__":
    unittest.main()
