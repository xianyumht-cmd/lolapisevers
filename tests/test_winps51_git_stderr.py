from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "ops" / "Launch-LapiQueryHardening.ps1"
DEPLOY = ROOT / "ops" / "Deploy-LapiQueryHardening.ps1"
ROLLBACK = ROOT / "ops" / "Rollback-LapiQueryHardening.ps1"


def _ps_quote(path: Path) -> str:
    return str(path).replace("'", "''")


@unittest.skipUnless(os.name == "nt", "Windows PowerShell 5.1 regression test")
class WindowsPowerShellGitStderrTests(unittest.TestCase):
    def test_process_wrapper_and_generic_manifest_are_winps51_safe(self):
        with tempfile.TemporaryDirectory() as temp_value:
            temp = Path(temp_value)
            deploy_copy = temp / "Deploy.ps1"
            rollback_copy = temp / "Rollback.ps1"
            shutil.copyfile(DEPLOY, deploy_copy)
            shutil.copyfile(ROLLBACK, rollback_copy)

            fake_git = temp / "fake-git.exe"
            test_script = temp / "test.ps1"
            test_script.write_text(
                textwrap.dedent(
                    f'''
                    $ErrorActionPreference = "Stop"
                    Set-StrictMode -Version 2.0

                    function Get-NamedFunctionText {{
                        param([string]$Path, [string]$Name)
                        $tokens = $null
                        $errors = $null
                        $ast = [System.Management.Automation.Language.Parser]::ParseFile(
                            $Path,
                            [ref]$tokens,
                            [ref]$errors
                        )
                        if ($errors -and $errors.Count -gt 0) {{
                            throw "parse failed: $Path"
                        }}
                        $functionAst = $ast.Find({{
                            param($node)
                            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                                $node.Name -eq $Name
                        }}, $true)
                        if ($null -eq $functionAst) {{
                            throw "function not found: $Name"
                        }}
                        return $functionAst.Extent.Text
                    }}

                    Invoke-Expression (Get-NamedFunctionText -Path '{_ps_quote(LAUNCHER)}' -Name 'Patch-WindowsPowerShellCompatibility')
                    Patch-WindowsPowerShellCompatibility -Path '{_ps_quote(deploy_copy)}' -Kind 'deploy'
                    Patch-WindowsPowerShellCompatibility -Path '{_ps_quote(rollback_copy)}' -Kind 'rollback'

                    $patchedDeploy = [System.IO.File]::ReadAllText('{_ps_quote(deploy_copy)}', [System.Text.Encoding]::ASCII)
                    if ($patchedDeploy.Contains('backup_items = @($backupItems)')) {{
                        throw 'generic list array subexpression was not removed'
                    }}
                    if (-not $patchedDeploy.Contains('backup_items = $backupItems.ToArray()')) {{
                        throw 'safe generic list conversion is missing'
                    }}

                    $source = @"
                    using System;
                    public static class FakeGit {{
                        public static int Main(string[] args) {{
                            Console.Out.WriteLine("simulated stdout");
                            Console.Error.WriteLine("simulated git progress");
                            foreach (string arg in args) {{
                                if (arg == "fail") return 7;
                            }}
                            return 0;
                        }}
                    }}
                    "@
                    Add-Type -TypeDefinition $source -Language CSharp -OutputAssembly '{_ps_quote(fake_git)}' -OutputType ConsoleApplication
                    $env:LAPI_GIT_EXE = '{_ps_quote(fake_git)}'
                    $ProjectRoot = '{_ps_quote(temp)}'

                    Invoke-Expression (Get-NamedFunctionText -Path '{_ps_quote(deploy_copy)}' -Name 'Resolve-GitExecutable')
                    Invoke-Expression (Get-NamedFunctionText -Path '{_ps_quote(deploy_copy)}' -Name 'Invoke-Git')
                    $success = Invoke-Git -Arguments @('fetch')
                    if ($success.ExitCode -ne 0) {{
                        throw 'successful command returned nonzero'
                    }}
                    if ($success.Output -notmatch 'simulated stdout') {{
                        throw 'stdout was not captured as text'
                    }}
                    if ($success.Error -notmatch 'simulated git progress') {{
                        throw 'stderr was not captured as text'
                    }}

                    $allowedFailure = Invoke-Git -Arguments @('fail') -AllowFailure
                    if ($allowedFailure.ExitCode -ne 7) {{
                        throw 'allowed failure exit code was not preserved'
                    }}

                    $didThrow = $false
                    try {{
                        Invoke-Git -Arguments @('fail') | Out-Null
                    }} catch {{
                        $didThrow = $true
                    }}
                    if (-not $didThrow) {{
                        throw 'nonzero Git command did not throw'
                    }}

                    Remove-Item Function:\Invoke-Git -Force
                    Remove-Item Function:\Resolve-GitExecutable -Force
                    Invoke-Expression (Get-NamedFunctionText -Path '{_ps_quote(rollback_copy)}' -Name 'Resolve-GitExecutable')
                    Invoke-Expression (Get-NamedFunctionText -Path '{_ps_quote(rollback_copy)}' -Name 'Invoke-Git')
                    $rollbackResult = Invoke-Git -Arguments @('checkout')
                    if ($rollbackResult.ExitCode -ne 0) {{
                        throw 'rollback wrapper returned nonzero'
                    }}
                    if ($rollbackResult.Error -notmatch 'simulated git progress') {{
                        throw 'rollback stderr was not captured'
                    }}

                    "winps51-process-wrapper-pass"
                    '''
                ),
                encoding="ascii",
                newline="\r\n",
            )

            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(test_script),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            self.assertIn("winps51-process-wrapper-pass", completed.stdout)


if __name__ == "__main__":
    unittest.main()
