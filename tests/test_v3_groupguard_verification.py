from __future__ import annotations

import base64
import io
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / ".deployment-package" / "full-bug-repair-20260801"


class V3GroupGuardVerificationTests(unittest.TestCase):
    def test_inspect_original_verifier_shape(self) -> None:
        encoded = "".join(f.read_text(encoding="ascii").strip() for f in sorted(CHUNKS.glob("chunk-*.txt")))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as package:
            verifier = package.read("ops/Verify-FullBugRepairProduction.ps1").decode("utf-8-sig")
        lines = verifier.splitlines()
        for index, line in enumerate(lines):
            if "groupguard" in line.lower() or "function Invoke-JsonRequest" in line:
                lo, hi = max(0, index-18), min(len(lines), index+26)
                print("\nVERIFIER SOURCE CONTEXT",lo+1,hi,flush=True)
                for j in range(lo,hi):
                    print(f"{j+1:04d}: {lines[j]}",flush=True)
        self.assertIn("/api/v1/groupguard/query",verifier)
