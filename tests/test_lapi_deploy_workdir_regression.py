from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "ops" / "Deploy-LapiQueryHardening.ps1"


class LapiDeployWorkingDirectoryRegressionTests(unittest.TestCase):
    def test_unittest_discovery_runs_from_project_root(self):
        text = DEPLOY.read_text(encoding="utf-8")
        self.assertIn("Push-Location -LiteralPath $ProjectRoot", text)
        self.assertIn('& $PythonExe -m unittest discover -s "tests" -p "test_*.py"', text)
        self.assertIn("} finally {", text)
        self.assertIn("Pop-Location", text)
        self.assertNotIn('discover -s (Join-Path $ProjectRoot "tests")', text)


if __name__ == "__main__":
    unittest.main()
