from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.local_env import load_local_powershell_env, read_local_powershell_env


class LocalEnvironmentLoaderTests(unittest.TestCase):
    def test_reads_literal_assignments_without_executing_powershell(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_env.local.ps1"
            path.write_text(
                "\ufeff$env:LOL_BAN_4PNG_TOKEN = \"abc``123`$x`\\\"\"\n"
                "$env:SINGLE = 'it''s-safe'\n"
                "$env:NUMBER = 5001\n"
                "$env:UNSAFE = (Get-Content secret.txt)\n",
                encoding="utf-8",
            )
            values = read_local_powershell_env(path)

        self.assertEqual(values["LOL_BAN_4PNG_TOKEN"], 'abc`123$x\\"')
        self.assertEqual(values["SINGLE"], "it's-safe")
        self.assertEqual(values["NUMBER"], "5001")
        self.assertNotIn("UNSAFE", values)

    def test_loads_only_missing_environment_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_env.local.ps1"
            path.write_text(
                '$env:LOL_BAN_4PNG_TOKEN = "disk-token"\n'
                '$env:APP_PORT = "5001"\n',
                encoding="utf-8",
            )
            environ = {"APP_PORT": "6000"}
            loaded = load_local_powershell_env(path, environ=environ)

        self.assertEqual(environ["LOL_BAN_4PNG_TOKEN"], "disk-token")
        self.assertEqual(environ["APP_PORT"], "6000")
        self.assertEqual(loaded, ("LOL_BAN_4PNG_TOKEN",))

    def test_app_bootstrap_loads_local_environment_before_routers(self) -> None:
        app_text = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        self.assertLess(
            app_text.index("load_local_powershell_env()"),
            app_text.index("from routers.lolban"),
        )


if __name__ == "__main__":
    unittest.main()
