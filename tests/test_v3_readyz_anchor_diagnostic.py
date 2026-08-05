from __future__ import annotations

import base64
import hashlib
import io
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNK_ROOT = ROOT / ".deployment-package" / "full-bug-repair-20260801"
EXPECTED_SHA256 = "30266c26bc21b4600d7e2cf63a27978f486958fa7c1e65a11e19484587a54237"


class V3ReadyzAnchorDiagnostic(unittest.TestCase):
    def test_print_reconstructed_readyz_block(self) -> None:
        chunks = sorted(CHUNK_ROOT.glob("chunk-*.txt"))
        self.assertEqual(4, len(chunks))
        encoded = "".join(path.read_text(encoding="ascii").strip() for path in chunks)
        archive = base64.b64decode(encoded, validate=True)
        self.assertEqual(EXPECTED_SHA256, hashlib.sha256(archive).hexdigest())

        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            raw = bundle.read("ops/Verify-FullBugRepairProduction.ps1")
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        marker = '$BaseUrl/readyz'
        index = text.find(marker)
        self.assertGreaterEqual(index, 0)
        start = max(0, text.rfind("\n", 0, max(0, index - 240)))
        end = text.find("\n", min(len(text), index + 500))
        if end < 0:
            end = len(text)
        snippet = text[start:end]
        self.fail("RECONSTRUCTED_READYZ_SNIPPET=" + repr(snippet))


if __name__ == "__main__":
    unittest.main()
