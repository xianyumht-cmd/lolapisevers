from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_FILES = tuple(sorted(ROOT.rglob("*.ps1")))
UTF8_BOM = b"\xef\xbb\xbf"


class AllPowerShellEncodingTests(unittest.TestCase):
    def test_non_ascii_scripts_have_utf8_bom_for_windows_powershell_51(self):
        self.assertTrue(POWERSHELL_FILES)
        for path in POWERSHELL_FILES:
            raw = path.read_bytes()
            has_non_ascii = any(byte > 0x7F for byte in raw)
            if has_non_ascii:
                self.assertTrue(
                    raw.startswith(UTF8_BOM),
                    f"non-ASCII PowerShell script must start with UTF-8 BOM: {path}",
                )

    def test_windows_powershell_51_parsefile_accepts_every_script(self):
        if os.name != "nt":
            self.skipTest("Windows PowerShell 5.1 is available only on Windows CI")

        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$env:POWERSHELL_SCRIPT_PATH,[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors -and $errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        for path in POWERSHELL_FILES:
            env = os.environ.copy()
            env["POWERSHELL_SCRIPT_PATH"] = str(path)
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"{path}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
