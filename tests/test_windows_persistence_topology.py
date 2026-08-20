from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


class WindowsPersistenceTopologyTests(unittest.TestCase):
    def test_runtime_topology_helper_targets_only_project_legacy_entrypoints(self):
        script = read_text("ops/runtime_topology.ps1")

        self.assertIn("Get-LolDataLegacyStartupEntries", script)
        self.assertIn("Get-LolDataSupervisorProcesses", script)
        self.assertIn("Move-LolDataLegacyStartupEntries", script)
        self.assertIn("Restore-LolDataLegacyStartupEntries", script)
        self.assertIn("[Environment+SpecialFolder]::Startup", script)
        self.assertIn("[Environment+SpecialFolder]::CommonStartup", script)
        self.assertIn("Win32_UserProfile", script)
        self.assertIn("WScript.Shell", script)
        self.assertIn('Join-Path $root "start_hidden.vbs"', script)
        self.assertIn('Join-Path $root "run_server.bat"', script)
        self.assertIn('Join-Path $root "ops\\run_service.ps1"', script)
        self.assertIn("retired-startup", script)
        self.assertIn("manifest.json", script)

    def test_persistence_installer_validates_unique_supervisor_before_retiring_startup(self):
        script = read_text("ops/install_persistence.ps1")

        self.assertIn('. $runtimeTopologyScript', script)
        self.assertIn("Assert-NoNonServiceSupervisor", script)
        self.assertIn("Assert-SingleServiceSupervisor", script)
        self.assertIn("Move-LolDataLegacyStartupEntries", script)
        self.assertIn("Get-LolDataLegacyStartupEntries", script)

        service_index = script.index("Install-ServiceWithNssm -projectRoot")
        task_index = script.index("Install-KeepAliveTask -projectRoot")
        topology_index = script.index("Assert-SingleServiceSupervisor -projectRoot")
        retire_index = script.index("$retiredStartupEntries = @(Move-LolDataLegacyStartupEntries")
        self.assertLess(service_index, task_index)
        self.assertLess(task_index, topology_index)
        self.assertLess(topology_index, retire_index)

    def test_persistence_installer_queries_nssm_appexit_with_default_subparameter(self):
        script = read_text("ops/install_persistence.ps1")

        self.assertIn("& $nssmExe get $serviceName AppExit Default", script)
        self.assertIn("$saved['AppExitDefault']", script)
        self.assertIn("& $nssmExe set $serviceName AppExit Default $oldAppExitDefault", script)
        self.assertNotIn("& $nssmExe get $serviceName AppExit 2>$null", script)
        self.assertNotIn("'Start','AppExit','AppStdout'", script)

    def test_health_check_reports_runtime_topology_without_redefining_http_readiness(self):
        script = read_text("ops/health_check.ps1")

        self.assertIn('Show-Section "Runtime topology"', script)
        self.assertIn("Get-LolDataSupervisorProcesses", script)
        self.assertIn("Get-LolDataLegacyStartupEntries", script)
        self.assertIn("exactly one service-owned supervisor", script)
        self.assertIn("Topology warnings are reported separately", script)
        self.assertIn("if ($MainApiReady -and $LanzouHealthy)", script)

    def test_docs_make_windows_service_the_only_persistent_entrypoint(self):
        readme = read_text("README.md")
        runbook = read_text("SERVICE_RUNBOOK.md")

        self.assertIn("正式长期运行只保留 `LOLDataSystem` Windows 服务作为唯一入口", readme)
        self.assertIn("唯一入口规则", runbook)
        self.assertIn("logs/retired-startup/", readme)
        self.assertNotIn("推荐统一入口：\n\n```powershell\n.\\run_server.bat", readme)


if __name__ == "__main__":
    unittest.main()
