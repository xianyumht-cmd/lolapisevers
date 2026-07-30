from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEANUP_SCRIPT = PROJECT_ROOT / "ops" / "remove-retired-video-provider-config.ps1"


class VideoRetirementDeploymentSafetyTests(unittest.TestCase):
    def test_cleanup_backup_is_outside_git_repository(self):
        text = CLEANUP_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn(
            'Join-Path $ProjectRoot ".video-provider-retirement-backups',
            text,
        )
        self.assertIn('$leaf.deploy-backups', text)
        self.assertIn(
            "Retirement backup root must be outside the Git repository",
            text,
        )

    def test_cleanup_preserves_non_video_configuration_and_waits_for_health(self):
        text = CLEANUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("QUERY_SCAMMER_PROVIDERS_JSON", text)
        self.assertIn("DYNAMIC_QUERY_PROVIDERS_PATH", text)
        self.assertIn('"video.info"', text)
        self.assertIn("Non-video dynamic command definitions changed unexpectedly", text)
        self.assertIn('Wait-Http200 -Uri "$BaseUrl/livez"', text)
        self.assertIn('Wait-Http200 -Uri "$BaseUrl/readyz"', text)
        self.assertIn('Wait-Http200 -Uri "$BaseUrl/health"', text)


if __name__ == "__main__":
    unittest.main()
