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
    def test_successful_native_stderr_does_not_abort_release(self):
        with tempfile.TemporaryDirectory() as temp_value:
            temp = Path(temp_value)
            deploy_copy = temp / "Deploy.ps1"
            rollback_copy = temp / "Rollback.ps1"
            shutil.copyfile(DEPLOY, deploy_copy)
            shutil.copyfile(ROLLBACK, rollback_copy)

            fake_bin = temp / "bin"
            fake_bin.mkdir()
            (fake_bin / "git.cmd").write_text(
                textwrap.dedent(
                    r"""
                    @echo off
                    echo simulated git progress 1>&2
                    for %%A in (%*) do if "%%~A"=="fail" exit /b 7
                    exit /b 0
                    """
                ).lstrip(),
                encoding="ascii",
                newline="\r\n",
            )

            test_script = temp / "test.ps1"
            test_script.write_text(
                textwrap.dedent(
                    f"""
                    $ErrorActionPreference = "Stop"
                    Set-StrictMode -Version 2.0

                    function Import-NamedFunction {{
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
                        Invoke-Expression $functionAst.Extent.Text
                    }}

                    Import-NamedFunction -Path '{_ps_quote(LAUNCHER)}' -Name 'Patch-WindowsPowerShellGitStderr'
                    Patch-WindowsPowerShellGitStderr -Path '{_ps_quote(deploy_copy)}' -Kind 'deploy'
                    Patch-WindowsPowerShellGitStderr -Path '{_ps_quote(rollback_copy)}' -Kind 'rollback'

                    $env:PATH = '{_ps_quote(fake_bin)};' + $env:PATH
                    $ProjectRoot = '{_ps_quote(temp)}'

                    Import-NamedFunction -Path '{_ps_quote(deploy_copy)}' -Name 'Invoke-Git'
                    $success = Invoke-Git -Arguments @('fetch')
                    if ($success.ExitCode -ne 0) {{
                        throw 'successful stderr command returned nonzero'
                    }}
                    if (($success.Output -join "`n") -notmatch 'simulated git progress') {{
                        throw 'stderr progress was not captured'
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
                        throw 'nonzero git command did not throw'
                    }}

                    Import-NamedFunction -Path '{_ps_quote(rollback_copy)}' -Name 'Invoke-Git'
                    $rollbackOutput = Invoke-Git -Arguments @('checkout')
                    if (($rollbackOutput -join "`n") -notmatch 'simulated git progress') {{
                        throw 'rollback wrapper did not tolerate stderr progress'
                    }}
                    "winps51-native-stderr-pass"
                    """
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
            self.assertIn("winps51-native-stderr-pass", completed.stdout)


if __name__ == "__main__":
    unittest.main()
